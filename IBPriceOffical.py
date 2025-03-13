#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import threading
import time
import bisect
import numpy as np

from ibapi.client import EClient
from ibapi.wrapper import EWrapper
from ibapi.utils import iswrapper
from ibapi.contract import Contract
from ibapi.contract import ContractDetails
from ibapi.contract import ComboLeg

# ---- 自定义的应用类，继承 EWrapper + EClient ----
class IBOptionDataApp(EWrapper, EClient):
    def __init__(self):
        EClient.__init__(self, self)

        # 连接成功后会有 nextValidId 回调
        self.next_order_id = None

        # 存放标的行情
        self._underlying_price = None
        self._underlying_price_received = threading.Event()

        # 存放期权链数据
        self._sec_def_params = []  # 这里会存储 (exchange, underlyingConId, tradingClass, multiplier, expirations, strikes)
        self._sec_def_params_received = threading.Event()

        # 存放每个合约详情查询结果 (reqId -> list of ContractDetails)
        self._contract_details_map = {}
        self._contract_details_end_events = {}

        # 存放市场行情 (reqId -> { 'bid': x, 'ask': y })
        self._market_data_map = {}
        self._market_data_end_events = {}

        # 全局锁，防止多线程竞争访问数据
        self._lock = threading.Lock()

        # 给请求分配一个自增的 request ID
        self._req_id = 1000
        self._req_id_lock = threading.Lock()

    def get_new_req_id(self) -> int:
        with self._req_id_lock:
            val = self._req_id
            self._req_id += 1
            return val

    # ---- EWrapper 回调实现 ----
    @iswrapper
    def nextValidId(self, orderId: int):
        """当客户端和 TWS 连接握手成功后，会返回一个可用的订单ID。"""
        super().nextValidId(orderId)
        self.next_order_id = orderId
        print(f"[nextValidId] Connection established. Next Order ID: {orderId}")

    @iswrapper
    def error(self, reqId, errorCode, errorString, advancedOrderRejectJson=None):
        """处理错误、警告或提示信息。"""
        msg = f"[error] reqId={reqId}, code={errorCode}, msg={errorString}"
        # 2104,2106,2158 等是常见的“数据农场连接”提示，不是致命错误
        print(msg)

    @iswrapper
    def tickPrice(self, reqId, tickType, price, attrib):
        """
        行情价格回调 (bid=1, ask=2, last=4, etc.)
        这里只用来获取 bid/ask/last
        """
        if reqId not in self._market_data_map:
            self._market_data_map[reqId] = {}

        with self._lock:
            if tickType == 1:  # bid
                self._market_data_map[reqId]['bid'] = price
            elif tickType == 2:  # ask
                self._market_data_map[reqId]['ask'] = price
            elif tickType == 4:  # last
                self._market_data_map[reqId]['last'] = price

    @iswrapper
    def tickSize(self, reqId, tickType, size):
        # 如果需要量，可在这里处理
        pass

    @iswrapper
    def tickSnapshotEnd(self, reqId: int):
        """快照行情结束标志"""
        print(f"[tickSnapshotEnd] reqId={reqId}")
        if reqId in self._market_data_end_events:
            ev = self._market_data_end_events[reqId]
            ev.set()

    # ---- 获取期权链 ----
    @iswrapper
    def securityDefinitionOptionParameter(self, reqId: int, exchange: str, underlyingConId: int,
                                         tradingClass: str, multiplier: str, expirations, strikes):
        """
        回调：返回 reqSecDefOptParams 请求的期权合约信息
        expirations: set[str]
        strikes: set[float]
        """
        with self._lock:
            self._sec_def_params.append((exchange, underlyingConId, tradingClass, multiplier, expirations, strikes))

    @iswrapper
    def securityDefinitionOptionParameterEnd(self, reqId: int):
        """
        所有 securityDefinitionOptionParameter 回调结束
        """
        print(f"[securityDefinitionOptionParameterEnd] reqId={reqId}")
        self._sec_def_params_received.set()

    # ---- 获取合约详情 ----
    @iswrapper
    def contractDetails(self, reqId: int, details: ContractDetails):
        with self._lock:
            if reqId not in self._contract_details_map:
                self._contract_details_map[reqId] = []
            self._contract_details_map[reqId].append(details)

    @iswrapper
    def contractDetailsEnd(self, reqId: int):
        print(f"[contractDetailsEnd] reqId={reqId}")
        if reqId in self._contract_details_end_events:
            self._contract_details_end_events[reqId].set()

    # ---- 帮助方法：等待市场数据，获取“标的价格” ----
    def request_underlying_price(self, symbol: str = "UVXY", exchange: str = "SMART", currency: str = "USD"):
        """
        订阅标的的快照行情，拿到 last price/bid/ask 中可用的价格。
        """
        req_id = self.get_new_req_id()
        contract = Contract()
        contract.symbol = symbol
        contract.secType = "STK"
        contract.exchange = exchange
        contract.currency = currency

        self._market_data_map[req_id] = {}
        ev = threading.Event()
        self._market_data_end_events[req_id] = ev

        # 请求快照行情
        print(f"请求标的 {symbol} 的快照行情 (reqId={req_id})...")
        self.reqMktData(req_id, contract, "", True, False, [])

        # 等待最多 3 秒
        ev.wait(timeout=3.0)

        # 尝试取消行情请求（对于snapshot模式，一般回调完自动结束，但这里保险起见）
        try:
            self.cancelMktData(req_id)
        except:
            pass

        # 取到的数据
        data = self._market_data_map.get(req_id, {})
        last = data.get('last')
        bid = data.get('bid')
        ask = data.get('ask')

        # 优先用 last，没有再用 bid/ask 的中间
        price = None
        if last and last > 0:
            price = last
        elif bid and ask and bid > 0 and ask > 0:
            price = (bid + ask) / 2

        if price:
            self._underlying_price = price
            print(f"标的 {symbol} 行情获取完毕，价格={price:.2f}")
        else:
            print(f"未能获取到 {symbol} 的有效价格。")

    # ---- 帮助方法：请求期权链 ----
    def request_sec_def_opt_params(self, underlying_symbol: str, underlying_sec_type: str, underlying_conId: int):
        """
        发送 reqSecDefOptParams 获取期权链数据
        """
        req_id = self.get_new_req_id()
        self._sec_def_params.clear()
        self._sec_def_params_received.clear()

        # 期权所在的 exchange 一般可传空字符串 (官方示例如此)
        # 参考: reqSecDefOptParams(reqId, underlyingSymbol, futFopExchange, underlyingSecType, underlyingConId)
        self.reqSecDefOptParams(req_id, underlying_symbol, "", underlying_sec_type, underlying_conId)

        print(f"请求期权链信息 (reqId={req_id})...")
        # 等待最多 5 秒
        self._sec_def_params_received.wait(timeout=5.0)

        if not self._sec_def_params:
            print("未获取到期权链信息。")

    # ---- 帮助方法：请求合约详情、获取 conId ----
    def resolve_option_contract(self, contract: Contract, timeout=3.0):
        """
        通过 reqContractDetails 查询并返回第一个匹配的合约详情，以便拿到 conId 等信息。
        """
        req_id = self.get_new_req_id()
        self._contract_details_map[req_id] = []
        ev = threading.Event()
        self._contract_details_end_events[req_id] = ev

        self.reqContractDetails(req_id, contract)
        ev.wait(timeout)

        details_list = self._contract_details_map.get(req_id, [])
        if not details_list:
            print(f"resolve_option_contract: 没有合约详情返回 (reqId={req_id})。")
            return None

        # 只取第一条
        return details_list[0]

    # ---- 帮助方法：请求单个期权合约的快照行情 (bid/ask) ----
    def request_option_market_snapshot(self, contract: Contract, timeout=3.0):
        req_id = self.get_new_req_id()
        self._market_data_map[req_id] = {}
        ev = threading.Event()
        self._market_data_end_events[req_id] = ev

        self.reqMktData(req_id, contract, "", True, False, [])
        ev.wait(timeout)

        try:
            self.cancelMktData(req_id)
        except:
            pass

        data = self._market_data_map.get(req_id, {})
        bid = data.get('bid')
        ask = data.get('ask')
        return bid, ask


def get_option_data(expiry_date='20250314'):
    """
    使用官方 ibapi 方式获取指定到期日的 UVXY 期权数据，
    并打印 (PUT/ CALL) 行权价上下各 5档的中间价。
    """
    app = IBOptionDataApp()

    # 1) 连接
    print("尝试连接 TWS/网关...")
    app.connect("127.0.0.1", 7496, clientId=1)

    # 启动网络线程
    api_thread = threading.Thread(target=app.run, daemon=True)
    api_thread.start()

    # 等待连接就绪 (nextValidId)
    t0 = time.time()
    while app.next_order_id is None and (time.time() - t0 < 5):
        time.sleep(0.1)

    if app.next_order_id is None:
        print("警告: 未能收到 nextValidId，可能未连接成功。")

    try:
        print(f"开始获取 {expiry_date} 到期期权数据...")

        # 2) 请求标的UVXY的市场行情（snapshot），拿到当前价格
        app.request_underlying_price(symbol='UVXY')
        time.sleep(1.0)  # 稍作等待，保证行情已回调

        current_price = app._underlying_price
        if not current_price:
            print("无法获取UVXY价格，后续无法计算期权行权价范围。")
            return

        print(f"UVXY当前价格: {current_price:.2f}")

        # 3) 请求期权链参数
        #    首先要有标的合约 conId -> 先 resolve 一个 STK 合约
        stock_contract = Contract()
        stock_contract.symbol = "UVXY"
        stock_contract.secType = "STK"
        stock_contract.exchange = "SMART"
        stock_contract.currency = "USD"

        # resolve股的合约，获取 conId
        detail = app.resolve_option_contract(stock_contract)
        if not detail:
            print("无法获取UVXY股票合约详情，退出。")
            return
        underlying_conId = detail.contract.conId

        # 请求期权链
        app.request_sec_def_opt_params(
            underlying_symbol="UVXY",
            underlying_sec_type="STK",
            underlying_conId=underlying_conId
        )
        time.sleep(1.0)

        # 4) 从期权链中找与我们想要的 expiry_date、tradingClass='UVXY' 相匹配的 strikes
        #    这里可能返回了多个 exchange / multiplier，但UVXY一般 multiplier=100, exchange=???
        #    原 ib_insync 的写法: chain = next(c for c in chains if ...)
        #    我们此处手动去匹配
        matched_strikes = []
        for (exchange, uConId, tClass, multiplier, expirations, strikes) in app._sec_def_params:
            if (tClass == 'UVXY' or tClass == 'UVXY?') and (expiry_date in expirations):
                # 只要 multiplier == '100' 也可以检查
                matched_strikes.extend(strikes)

        if not matched_strikes:
            print(f"期权链中未找到到期日={expiry_date} 或 tradingClass=UVXY 的记录。")
            return

        # 过滤 strikes
        valid_strikes = sorted([s for s in matched_strikes if 5 < s < current_price * 3])

        # 找到当前价附近的索引
        index = bisect.bisect_left(valid_strikes, current_price)
        # put 取 index 前 5个，call 取 index 后 5个
        # 这里原代码 put 是从高到低 (max->index->reverse)；call 是从低到高
        put_strikes = valid_strikes[max(0, index - 5):index][::-1]
        call_strikes = valid_strikes[index:index + 5]

        print(f"目标 PUT 行权价: {put_strikes[:5]}")
        print(f"目标 CALL 行权价: {call_strikes[:5]}")

        # 5) 为这 5+5 个行权价创建 Option 合约，并各自查询合约详情
        #    这样才能拿到 conId，后面 reqMktData 才能订阅
        put_contracts = []
        for strike in put_strikes[:5]:
            c = Contract()
            c.symbol = "UVXY"
            c.secType = "OPT"
            c.exchange = "SMART"
            c.currency = "USD"
            c.lastTradeDateOrContractMonth = expiry_date
            c.strike = float(strike)
            c.right = "P"
            c.multiplier = "100"
            detail = app.resolve_option_contract(c)
            if detail:
                # 用 detail 里带 conId 的合约
                resolved_c = detail.contract
                put_contracts.append(resolved_c)
            else:
                print(f"警告: 未能解析 PUT strike={strike} 的合约。")

        call_contracts = []
        for strike in call_strikes[:5]:
            c = Contract()
            c.symbol = "UVXY"
            c.secType = "OPT"
            c.exchange = "SMART"
            c.currency = "USD"
            c.lastTradeDateOrContractMonth = expiry_date
            c.strike = float(strike)
            c.right = "C"
            c.multiplier = "100"
            detail = app.resolve_option_contract(c)
            if detail:
                resolved_c = detail.contract
                call_contracts.append(resolved_c)
            else:
                print(f"警告: 未能解析 CALL strike={strike} 的合约。")

        # 6) 逐个请求快照行情，并计算中间价
        #    原 ib_insync 代码是一次性 reqTickers(*qualified)，这里就循环请求 snapshot
        option_data = {}  # key: (strike, 'P'/'C'), value: mid-price
        # PUT
        for c in put_contracts:
            bid, ask = app.request_option_market_snapshot(c, timeout=3)
            if bid and ask and bid > 0 and ask > 0:
                mid = (bid + ask) / 2
                option_data[(c.strike, c.right)] = f"{mid:.2f}"
            else:
                option_data[(c.strike, c.right)] = "无报价"

        # CALL
        for c in call_contracts:
            bid, ask = app.request_option_market_snapshot(c, timeout=3)
            if bid and ask and bid > 0 and ask > 0:
                mid = (bid + ask) / 2
                option_data[(c.strike, c.right)] = f"{mid:.2f}"
            else:
                option_data[(c.strike, c.right)] = "无报价"

        # 7) 输出
        print("\n【最终结果】")
        print(f"到期日: {expiry_date} | 标的价: {current_price:.2f}")

        print("\nPUT期权（行权价从高到低）:")
        for strike in put_strikes[:5]:
            price = option_data.get((strike, 'P'), "无数据")
            print(f"PUT {strike:>5} | 中间价: {price}")

        print("\nCALL期权（行权价从低到高）:")
        for strike in call_strikes[:5]:
            price = option_data.get((strike, 'C'), "无数据")
            print(f"CALL {strike:>5} | 中间价: {price}")

    except Exception as e:
        print(f"发生错误: {str(e)}")
    finally:
        print("断开连接...")
        app.disconnect()
        api_thread.join(timeout=3)
        print("程序结束。")


if __name__ == "__main__":
    # 默认测试
    get_option_data('20250314')
