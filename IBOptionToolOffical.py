#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
示例: 使用预先定义的多腿期权参数下单，并自动从初始限价逐步递价到目标限价。
"""

import sys
import threading
import time

from ibapi.client import EClient
from ibapi.wrapper import EWrapper
from ibapi.contract import Contract, ComboLeg
from ibapi.order import Order


class IBApp(EWrapper, EClient):
    """IB API App, 继承自 EWrapper 和 EClient, 处理 API 连接和回调."""
    def __init__(self):
        EClient.__init__(self, self)
        self.next_order_id = None
        # 存储合约详情查询结果: reqId -> list of Contract
        self._contract_details = {}
        # 存储行情数据: reqId -> dict of price/size
        self.market_data = {}

        # 存储订单状态: orderId -> dict(status, filled, remaining, avgFillPrice)
        self.order_statuses = {}
        # 标记已打印提示的订单 ID (避免重复输出)
        self._submitted_announced = set()
        self._partial_announced = set()

        # 事件字典: 用于同步等待请求结果
        self._req_events = {}
        # 错误信息存储(可选)
        self.last_error = None

    # EWrapper 回调方法重载:
    def nextValidId(self, orderId: int):
        """连接成功后返回下一个有效订单 ID"""
        super().nextValidId(orderId)
        self.next_order_id = orderId
        print(f"Connected: Next valid order ID is {orderId}")
        print("Connected to IB.")

    def error(self, reqId, errorCode, errorString, advancedOrderRejectJson=None):
        """错误回调"""
        err_msg = f"Info. Id: {reqId}, Code: {errorCode}, Msg: {errorString}"
        print(err_msg)
        self.last_error = (reqId, errorCode, errorString)

    def orderStatus(self, orderId, status, filled, remaining,
                    avgFillPrice, permId, parentId, lastFillPrice,
                    clientId, whyHeld, mktCapPrice):
        """订单状态更新回调"""
        self.order_statuses[orderId] = {
            "status": status,
            "filled": filled,
            "remaining": remaining,
            "avgFillPrice": avgFillPrice
        }
        print(f"OrderStatus - orderId: {orderId}, status: {status}, "
              f"filled: {filled}, remaining: {remaining}, avgFillPrice: {avgFillPrice}")

        if status == "Filled":
            print(f"Order {orderId} filled")
        elif status in ("Cancelled", "ApiCanceled"):
            print(f"Order {orderId} cancelled")
        elif filled > 0 and remaining > 0:
            if orderId not in self._partial_announced:
                print(f"Order {orderId} partially filled")
                self._partial_announced.add(orderId)
        elif status == "Submitted" and filled == 0:
            if orderId not in self._submitted_announced:
                print(f"Order {orderId} submitted")
                self._submitted_announced.add(orderId)

    def openOrder(self, orderId, contract, order, orderState):
        """打开订单回调"""
        price_info = ""
        if order.orderType.upper() == "LMT":
            price_info = f"{order.lmtPrice}"
        print(f"OpenOrder - orderId: {orderId}, {contract.symbol} {contract.secType}, "
              f"{order.action} {order.totalQuantity} @ {order.orderType} {price_info}, "
              f"Status: {orderState.status}")

        if orderId not in self.order_statuses:
            self.order_statuses[orderId] = {
                "status": orderState.status,
                "filled": 0,
                "remaining": order.totalQuantity,
                "avgFillPrice": 0.0
            }

    def execDetails(self, reqId, contract, execution):
        """成交明细回调"""
        print(f"ExecDetails - orderId: {execution.orderId}, execId: {execution.execId}, "
              f"shares: {execution.shares}, price: {execution.price}")

    def contractDetails(self, reqId: int, contractDetails):
        """合约详情回调"""
        cd = contractDetails
        if reqId not in self._contract_details:
            self._contract_details[reqId] = []
        self._contract_details[reqId].append(cd.contract)

    def contractDetailsEnd(self, reqId: int):
        """合约详情查询结束"""
        if reqId in self._req_events:
            ev = self._req_events[reqId]
            if isinstance(ev, threading.Event):
                ev.set()

    def tickPrice(self, reqId, tickType, price, attrib):
        """行情价格回调"""
        if reqId not in self.market_data:
            self.market_data[reqId] = {}
        price_fields = {
            1: "bid",
            2: "ask",
            4: "last",
            6: "high",
            7: "low",
            9: "close"
        }
        if tickType in price_fields:
            field = price_fields[tickType]
            self.market_data[reqId][field] = price
        self.market_data[reqId][f"tickPrice_{tickType}"] = price

    def tickSize(self, reqId, tickType, size):
        """行情数量回调"""
        if reqId not in self.market_data:
            self.market_data[reqId] = {}
        size_fields = {
            0: "bidSize",
            3: "askSize",
            5: "lastSize",
            8: "volume"
        }
        if tickType in size_fields:
            field = size_fields[tickType]
            self.market_data[reqId][field] = size
        self.market_data[reqId][f"tickSize_{tickType}"] = size

    def tickSnapshotEnd(self, reqId: int):
        """行情快照结束回调"""
        if reqId in self._req_events:
            ev = self._req_events[reqId]
            if isinstance(ev, threading.Event):
                ev.set()

    # 帮助方法
    def resolve_contract(self, contract: Contract, req_id: int = None, timeout: float = 5.0):
        """请求合约详情, 返回填充了 conId 的 Contract 对象."""
        if req_id is None:
            req_id = 1000000 + (0 if self.next_order_id is None else self.next_order_id)
        self._contract_details[req_id] = []
        ev = threading.Event()
        self._req_events[req_id] = ev
        self.reqContractDetails(req_id, contract)
        ev.wait(timeout)
        details_list = self._contract_details.get(req_id, [])
        if len(details_list) == 0:
            print(f"Contract details not found (reqId {req_id}).")
            return None
        if len(details_list) > 1:
            first = details_list[0]
            print(f"Warning: Multiple contract details returned (count={len(details_list)}). "
                  f"Using the first one: {first.symbol} {first.secType} {getattr(first, 'exchange', '')}.")
            return first
        return details_list[0]

    def get_market_snapshot(self, contract: Contract, req_id: int = None, timeout: float = 5.0):
        if req_id is None:
            req_id = 5000000 + (0 if self.next_order_id is None else self.next_order_id)

        self.market_data[req_id] = {}
        ev = threading.Event()
        self._req_events[req_id] = ev

        # snapshot=True，向IB请求一次性快照
        self.reqMktData(req_id, contract, "", True, False, [])

        # 等待tickSnapshotEnd 或超时
        ev.wait(timeout)

        data = self.market_data.get(req_id, {})
        
        # 对于快照，这里就不cancelMktData了
        return data


class OrderManager:
    """订单管理器, 提供高层交易功能封装"""
    def __init__(self, app: IBApp):
        self.app = app
        # 等待 app 连接就绪
        while self.app.next_order_id is None:
            time.sleep(0.1)
        self._order_id = self.app.next_order_id
        self._order_id_lock = threading.Lock()
        # 存储订单细节 (用于后续追价或修改)
        self._order_details = {}

    def _get_next_order_id(self):
        with self._order_id_lock:
            oid = self._order_id
            self._order_id += 1
            return oid

    def place_option_order(self, legs, order_type="LMT", limit_price=0.0):
        """
        下单:
        legs: 列表, 每个元素为一个腿(dict)，字段：
          - underlying: 标的股票代码
          - lastTradeDate: 到期日 (YYYYMMDD)
          - strike: 行权价 (float)
          - right: "C" 或 "P"
          - action: "BUY" 或 "SELL"
          - quantity: 数量(手)
          - 可选: secType, exchange, currency, multiplier
        order_type: "LMT" / "MKT"
        limit_price: 限价(多腿净价)
        返回订单ID
        """
        num_legs = len(legs)
        if num_legs == 0:
            print("No legs specified for order.")
            return None

        if num_legs == 1:
            # 单腿期权订单
            leg = legs[0]
            contract = Contract()
            contract.symbol = leg['underlying']
            contract.secType = leg.get('secType', "OPT")
            contract.exchange = leg.get('exchange', "SMART")
            contract.currency = leg.get('currency', "USD")
            contract.lastTradeDateOrContractMonth = leg['lastTradeDate']
            contract.strike = float(leg['strike'])
            contract.right = leg['right']
            contract.multiplier = leg.get('multiplier', "100")

            resolved_contract = self.app.resolve_contract(contract)
            if resolved_contract:
                contract = resolved_contract

            total_quantity = leg['quantity']
            order_action = leg['action'].upper()
            order = Order()
            order.action = order_action
            order.totalQuantity = total_quantity
            order.orderType = order_type.upper()
            if order.orderType == "LMT":
                order.lmtPrice = limit_price

            order_id = self._get_next_order_id()
            print(f"Placing single-leg order (ID {order_id}): {order.action} {total_quantity} "
                  f"{leg['underlying']} {leg['right']}{leg['strike']}@{leg['lastTradeDate']}, "
                  f"Price={'MKT' if order.orderType != 'LMT' else limit_price}")

            self.app.placeOrder(order_id, contract, order)
            self._order_details[order_id] = {
                "contract": contract,
                "action": order.action,
                "type": order.orderType,
                "limit_price": (order.lmtPrice if order.orderType == "LMT" else None),
                "quantity": order.totalQuantity
            }
            return order_id

        else:
            # 多腿组合单
            combo_legs = []
            underlying_symbol = None
            total_leg_quantities = []
            for idx, leg in enumerate(legs, start=1):
                if underlying_symbol is None:
                    underlying_symbol = leg['underlying']
                elif underlying_symbol != leg['underlying']:
                    print("Error: All legs must have the same underlying symbol for combo orders.")
                    return None

                contract = Contract()
                contract.symbol = leg['underlying']
                contract.secType = leg.get('secType', "OPT")
                contract.exchange = leg.get('exchange', "SMART")
                contract.currency = leg.get('currency', "USD")
                contract.lastTradeDateOrContractMonth = leg['lastTradeDate']
                contract.strike = float(leg['strike'])
                contract.right = leg['right']
                contract.multiplier = leg.get('multiplier', "100")

                resolved = self.app.resolve_contract(contract)
                if not resolved:
                    print(f"Leg {idx}: contract resolution failed, aborting combo order.")
                    return None

                combo_leg = ComboLeg()
                combo_leg.conId = resolved.conId
                combo_leg.ratio = int(leg['quantity'])
                combo_leg.action = leg['action'].upper()
                combo_leg.exchange = resolved.exchange if resolved.exchange else leg.get('exchange', "SMART")
                combo_legs.append(combo_leg)
                total_leg_quantities.append(int(leg['quantity']))

            # 计算各腿数量的最大公约数，以归一化比例
            from math import gcd
            from functools import reduce
            leg_gcd = reduce(gcd, total_leg_quantities)
            if leg_gcd == 0:
                leg_gcd = 1
            for combo_leg in combo_legs:
                combo_leg.ratio //= leg_gcd

            total_quantity = leg_gcd
            combo_contract = Contract()
            combo_contract.symbol = underlying_symbol
            combo_contract.secType = "BAG"
            combo_contract.currency = legs[0].get('currency', "USD")
            combo_contract.exchange = legs[0].get('exchange', "SMART")
            combo_contract.comboLegs = combo_legs

            # 组合单顶层 action: 以第一腿的 action 为基准
            order_action = "BUY" if legs[0]['action'].upper() == "BUY" else "SELL"
            order = Order()
            order.action = order_action
            order.totalQuantity = total_quantity
            order.orderType = order_type.upper()
            if order.orderType == "LMT":
                order.lmtPrice = limit_price

            order_id = self._get_next_order_id()
            print(f"Placing combo order (ID {order_id}): {order.action} {total_quantity}x Combo {underlying_symbol}, "
                  f"Price={'MKT' if order.orderType != 'LMT' else limit_price}")

            self.app.placeOrder(order_id, combo_contract, order)
            self._order_details[order_id] = {
                "contract": combo_contract,
                "action": order.action,
                "type": order.orderType,
                "limit_price": (order.lmtPrice if order.orderType == "LMT" else None),
                "quantity": order.totalQuantity
            }
            return order_id

    def chase_order_to_final(self, order_id: int,
                             step: float,
                             final_price: float,
                             interval: float = 5.0):
        """
        从当前订单限价开始，每隔 interval 秒自动加价或减价，直到达到 final_price 或订单成交/取消。
        BUY单： 若 final_price > current，则加价；若更低则减价
        SELL单： 若 final_price < current，则减价；若更高则加价
        """
        def _chase_logic(order_id, step, final_price, interval):
            while True:
                time.sleep(interval)
                status_info = self.app.order_statuses.get(order_id)
                if not status_info:
                    continue
                status = status_info.get("status")
                remaining = status_info.get("remaining", 0)
                if status in ("Filled", "Cancelled", "ApiCanceled") or remaining == 0:
                    print(f"Chase-to-final: Order {order_id} completed or cancelled, stop chasing.")
                    break

                details = self._order_details.get(order_id)
                if not details or details["type"] != "LMT":
                    print(f"Chase-to-final: Cannot chase order {order_id} (not limit or no details).")
                    break

                current_price = details["limit_price"]
                if current_price is None:
                    print(f"Chase-to-final: It's a market order, cannot chase.")
                    break

                order_action = details["action"].upper()

                # 根据 BUY/SELL 和 final_price 与 current_price 的大小关系计算 new_price
                new_price = current_price
                if order_action == "BUY":
                    direction = 1 if final_price > current_price else -1
                    candidate_price = current_price + direction * step
                    # 如果越过final_price，就设为final_price
                    if direction > 0 and candidate_price > final_price:
                        candidate_price = final_price
                    elif direction < 0 and candidate_price < final_price:
                        candidate_price = final_price
                    new_price = candidate_price
                else:
                    # SELL
                    direction = -1 if final_price < current_price else 1
                    candidate_price = current_price + direction * step
                    if direction > 0 and candidate_price > final_price:
                        candidate_price = final_price
                    elif direction < 0 and candidate_price < final_price:
                        candidate_price = final_price
                    new_price = candidate_price

                # 如果已经到达final_price，则停止
                if abs(new_price - current_price) < 1e-10:
                    print(f"Chase-to-final: Price already at final ({new_price}), stop chasing.")
                    break

                # 提交新价格
                details["limit_price"] = new_price
                self._order_details[order_id] = details

                print(f"Chase-to-final: Adjusting price from {current_price:.2f} to {new_price:.2f}")
                mod_order = Order()
                mod_order.action = order_action
                mod_order.orderType = "LMT"
                mod_order.totalQuantity = details["quantity"]
                mod_order.lmtPrice = new_price
                try:
                    self.app.placeOrder(order_id, details["contract"], mod_order)
                except Exception as e:
                    print(f"Chase-to-final: Order modify failed: {e}")
                    break

        chase_thread = threading.Thread(
            target=_chase_logic,
            args=(order_id, step, final_price, interval)
            # daemon=True 删掉，不要加！
        )
        chase_thread.start()

        # **这里新增：返回这个线程对象**
        return chase_thread


# ================ 主程序入口示例(无需交互) ================
if __name__ == "__main__":
    # 1) 连接 IB TWS/IB Gateway
    app = IBApp()
    print("Connecting to IB API...")
    try:
        # 真实账户常用7496，纸交易常用7497
        app.connect("127.0.0.1", 7496, clientId=1)
    except Exception as e:
        print("Could not connect to IB API:", e)
        sys.exit(1)

    api_thread = threading.Thread(target=app.run, daemon=True)
    api_thread.start()

    # 等待连接成功
    for _ in range(30):
        if app.next_order_id is not None:
            break
        time.sleep(0.1)
    if app.next_order_id is None:
        print("Warning: next valid order ID not received. Proceeding anyway.")

    # 2) 创建订单管理器
    manager = OrderManager(app)

    # 3) 示例: 四腿组合参数 (可以改成两腿/三腿/单腿)
    spread_symbol = "PDD"

    leg1_expiry  = "20250328"
    leg1_strike  = 122.0
    leg1_right   = "C"
    leg1_action  = "BUY"
    leg1_ratio   = 1

    leg2_expiry  = "20250328"
    leg2_strike  = 118.0
    leg2_right   = "P"
    leg2_action  = "BUY"
    leg2_ratio   = 1

    leg3_expiry  = "20250321"
    leg3_strike  = 140.0
    leg3_right   = "C"
    leg3_action  = "SELL"
    leg3_ratio   = 1

    leg4_expiry  = "20250321"
    leg4_strike  = 100.0
    leg4_right   = "P"
    leg4_action  = "SELL"
    leg4_ratio   = 1

    # 组合单总数量(即多少手)
    combo_quantity = 1

    # 起始与目标价格(组合净价)
    combo_init_price  = 10.00
    combo_price_final = 11.66
    combo_price_step  = 0.01

    # 构造legs列表
    legs = [
        {
            "underlying": spread_symbol,
            "lastTradeDate": leg1_expiry,
            "strike": leg1_strike,
            "right": leg1_right,
            "action": leg1_action,
            "quantity": leg1_ratio * combo_quantity
        },
        {
            "underlying": spread_symbol,
            "lastTradeDate": leg2_expiry,
            "strike": leg2_strike,
            "right": leg2_right,
            "action": leg2_action,
            "quantity": leg2_ratio * combo_quantity
        },
        {
            "underlying": spread_symbol,
            "lastTradeDate": leg3_expiry,
            "strike": leg3_strike,
            "right": leg3_right,
            "action": leg3_action,
            "quantity": leg3_ratio * combo_quantity
        },
        {
            "underlying": spread_symbol,
            "lastTradeDate": leg4_expiry,
            "strike": leg4_strike,
            "right": leg4_right,
            "action": leg4_action,
            "quantity": leg4_ratio * combo_quantity
        }
    ]

    # ========== 新增功能：在下单前打印每条腿信息、当前市场价格、组合价格，并询问确认 ==========

    # 4) 打印每条腿的市场行情 + 计算组合预估净价
    net_estimated_cost = 0.0  # 组合的预估净成本(正=花费，负=收到)
    print("\n======== Legs Market Data Preview ========")
    for idx, leg in enumerate(legs, start=1):
        # 为了获取准确行情，需要先构建并resolve_contract
        tmp_contract = Contract()
        tmp_contract.symbol = leg['underlying']
        tmp_contract.secType = leg.get('secType', "OPT")
        tmp_contract.exchange = leg.get('exchange', "SMART")
        tmp_contract.currency = leg.get('currency', "USD")
        tmp_contract.lastTradeDateOrContractMonth = leg['lastTradeDate']
        tmp_contract.strike = float(leg['strike'])
        tmp_contract.right = leg['right']
        tmp_contract.multiplier = leg.get('multiplier', "100")

        resolved_c = app.resolve_contract(tmp_contract)
        if resolved_c is None:
            print(f"Leg {idx} ({leg['action']} {leg['quantity']}): Resolve contract failed.")
            continue

        snapshot = app.get_market_snapshot(resolved_c)
        bid  = snapshot.get("bid", 0.0)
        ask  = snapshot.get("ask", 0.0)
        last = snapshot.get("last", 0.0)

        # 这里示例用简单的 mid = (bid+ask)/2 若都>0，否则用 last
        if (bid > 0.0) and (ask > 0.0):
            mid = (bid + ask) / 2.0
        else:
            mid = last

        # 1张合约 = 100股; 下单数量leg['quantity']是几张(手)
        # 若是 BUY, 则净成本为 +mid；若是 SELL, 则为 -mid
        sign = 1 if leg['action'].upper() == "BUY" else -1
        # leg['quantity']张合约, 每张 * 100 股
        leg_cost = mid * 100 * leg['quantity'] * sign
        net_estimated_cost += leg_cost

        print(f"Leg {idx}: Action={leg['action']} Qty={leg['quantity']}  "
              f"Exp={leg['lastTradeDate']} Strike={leg['strike']} {leg['right']}, "
              f"bid={bid:.2f}, ask={ask:.2f}, last={last:.2f}, mid~={mid:.2f}, "
              f"Leg est. cost={leg_cost:.2f}")

    print(f"--> Estimated combo total cost (for {combo_quantity} combo(s)) = {net_estimated_cost:.2f}")
    print("----------------------------------------------")
    print(f"下单金额参数: 起始={combo_init_price:.2f}, 步长={combo_price_step:.2f}, 终止={combo_price_final:.2f}")
    print("==============================================")

    # 5) 增加一个交互：是否确认下单
    user_input = input("是否确认下单？输入 Y 或 y 确认下单，其余任意键取消并退出: ")
    if user_input.lower() != 'y':
        print("用户取消下单，程序结束。")
        sys.exit(0)

    # ========= 如果用户确认，才进行下单 =========
    order_id = manager.place_option_order(legs, order_type="LMT", limit_price=combo_init_price)
    if order_id:
        print(f"四腿组合下单完成, 订单ID={order_id}, 初始限价={combo_init_price:.2f}")
        # 继续自动追价到目标 combo_price_final
        # 注意这里：把返回的 chase_thread 存起来
        chase_thread = manager.chase_order_to_final(
            order_id    = order_id,
            step        = combo_price_step,
            final_price = combo_price_final,
            interval    = 5.0   # 每5秒递价一次(可自行调整)
        )

    # 等待追价线程执行完毕（即订单被填满/取消或到达final价）
    chase_thread.join()

    print("Disconnecting from IB...")
    app.disconnect()