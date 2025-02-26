from ib_insync import IB, Option, Contract, ComboLeg, LimitOrder, Trade
import pyttsx3
import time

class OrderManager:
    def __init__(self, ib: IB, checkInterval: int = 5):
        """
        初始化 OrderManager。
        参数:
        - ib: IBInsync 提供的 IB 实例 (已连接到 TWS 或 IB Gateway)。
        - checkInterval: 检查成交的周期（秒）。
        """
        self.ib = ib
        self.checkInterval = checkInterval

        # 初始化语音引擎
        self.engine = pyttsx3.init()
        # 尝试选择中文语音（如果有的话）
        voices = self.engine.getProperty('voices')
        for voice in voices:
            if 'Chinese' in voice.name or 'zh' in voice.id:
                self.engine.setProperty('voice', voice.id)
                break

    def _voice_notify(self, text: str):
        """语音播报并打印日志。"""
        print(text)
        try:
            # 语音播报
            self.engine.say(text)
            self.engine.runAndWait()
        except Exception as e:
            print(f"[Voice Error] {e}")

    def track_order_status(self, trade: Trade, current_price: float, price_step: float, price_final: float):
        """
        持续追踪订单状态，直到完全成交。根据成交情况调整价格。
        参数:
        - trade: 下单后返回的交易对象 (IB-insync 的 Trade 对象)。
        - current_price: 当前委托价格。
        - price_step: 每次调整的价差步长。
        - price_final: 最终组合限价。
        """
        total_qty = trade.order.totalQuantity
        last_filled = 0  # 上次记录的已成交数量

        # 确定价格调整方向: True表示递增价格，False表示递减价格，None表示不调整
        if current_price < price_final:
            adjust_up = True   # 买单，从初始价逐步提高报价
        elif current_price > price_final:
            adjust_up = False  # 卖单，从初始价逐步降低报价
        else:
            adjust_up = None   # 已在底价，不做调整

        # 开始跟踪订单状态
        msg = f"开始跟踪订单，ID为{trade.order.orderId}，目标数量为{total_qty}。"
        # self._voice_notify(msg)
        print(msg)

        while True:
            filled_now = trade.orderStatus.filled      # 当前已成交数量
            remaining = trade.orderStatus.remaining    # 当前剩余数量

            # 如果全部成交，跳出循环
            if filled_now >= total_qty:
                break

            # 如果有新增成交（部分成交）
            if filled_now > last_filled:
                # 获取最近一笔成交价格
                last_fill_price = None
                if hasattr(trade.orderStatus, 'lastFillPrice'):
                    last_fill_price = trade.orderStatus.lastFillPrice
                if last_fill_price is None and trade.fills:
                    # 从成交明细中获取最后一笔成交价格
                    last_fill_price = trade.fills[-1].execution.price
                if last_fill_price is None:
                    last_fill_price = trade.orderStatus.avgFillPrice

                # 语音播报部分成交信息
                msg = f"部分成交 {filled_now} 张，剩余 {remaining} 张"
                if last_fill_price is not None:
                    msg += f"，成交价 {last_fill_price:.2f}"
                self._voice_notify(msg)

                last_filled = filled_now
                # 部分成交后，等待一个检查周期再继续判断

            # 等待下一个检查周期
            self.ib.sleep(self.checkInterval)

            # 检查等待期间是否有新增成交
            filled_after_wait = trade.orderStatus.filled
            if filled_after_wait < total_qty and filled_after_wait == last_filled:
                # 检查周期内没有新成交，尝试调整价格
                if adjust_up is True:
                    # 买单：提高报价
                    if current_price < price_final:
                        new_price = current_price + price_step
                        if new_price > price_final:
                            new_price = price_final
                        current_price = new_price
                        trade.order.lmtPrice = current_price
                        self.ib.placeOrder(trade.contract, trade.order)  # 修改订单价格
                        msg = f"调整买价至 {current_price:.2f}" + ("（底价）" if current_price == price_final else "")
                        self._voice_notify(msg)
                elif adjust_up is False:
                    # 卖单：降低报价
                    if current_price > price_final:
                        new_price = current_price - price_step
                        if new_price < price_final:
                            new_price = price_final
                        current_price = new_price
                        trade.order.lmtPrice = current_price
                        self.ib.placeOrder(trade.contract, trade.order)
                        msg = f"调整卖价至 {current_price:.2f}" + ("（底价）" if current_price == price_final else "")
                        self._voice_notify(msg)
                # adjust_up 为 None 时表示已在底价，不再调整，只等待成交

        # 订单完全成交，语音通知平均成交价
        avg_price = trade.orderStatus.avgFillPrice
        if (avg_price is None or avg_price == 0) and trade.fills:
            # 手动计算平均成交价（备用）
            total_cost = sum(fill.execution.price * fill.execution.shares for fill in trade.fills)
            total_filled = sum(fill.execution.shares for fill in trade.fills)
            avg_price = total_cost / total_filled if total_filled > 0 else 0.0

        msg_full = f"订单全部成交，平均成交价 {avg_price:.2f}"
        self._voice_notify(msg_full)
        return trade

    def place_single_option_order_incremental(self, contract: Contract, action: str, quantity: int,
                                              initial_price: float, price_step: float, price_final: float):
        """
        单腿期权递价下单。
        参数:
        - contract: 期权合约对象 (ib_insync.Option 或 IB Contract)。
        - action: 'BUY' 或 'SELL'。
        - quantity: 下单数量。
        - initial_price: 初始限价价格。
        - price_step: 每次调价的步长。
        - price_final: 最终组合限价。
        """
        # 确认合约细节（如 conId）确保可交易
        contract = self.ib.qualifyContracts(contract)[0]
        # 创建限价订单
        order = LimitOrder(action, quantity, initial_price)

        # 先做一次语音预报
        detail = f"{action} {quantity} 张 {contract.symbol} {contract.right} 行权价 {contract.strike}，初始限价 {initial_price:.2f}"
        # self._voice_notify(f"即将提交单腿期权订单: {detail}")
        print(f"即将提交单腿期权订单: {detail}")

        # 提交订单前再次确认
        confirm_input = input("请确认下单？输入 y 确认，其他键取消: ").strip().upper()
        if confirm_input != 'Y':
            self._voice_notify("下单已取消。")
            return None

        # 正式提交订单
        trade = self.ib.placeOrder(contract, order)
        self._voice_notify("单腿订单已提交")
        print(f"提交单腿期权{action}委托：{contract.symbol} × {quantity}张，初始价 {initial_price:.2f}")
        # 跟踪订单状态并根据情况递价调整
        return self.track_order_status(trade, initial_price, price_step, price_final)

    def place_vertical_spread_incremental(self, contract1: Contract, contract2: Contract,
                                          spread_action: str,
                                          action1: str, action2: str, quantity: int,
                                          initial_price: float, price_step: float, price_final: float):
        """
        双腿期权垂直价差（Vertical Spread）递价下单。
        参数:
        - contract1: 第一腿期权合约对象。
        - contract2: 第二腿期权合约对象。
        - spread_action: 组合操作 'BUY' 或 'SELL'。
        - action1: 第一腿操作 'BUY' 或 'SELL'。
        - action2: 第二腿操作 'BUY' 或 'SELL'。
        - quantity: 组合下单手数（几组期权对）。
        - initial_price: 初始组合限价（净价）。
        - price_step: 每次调价步长。
        - price_final: 最终组合限价。
        """
        # 确认两个合约细节
        c1, c2 = self.ib.qualifyContracts(contract1, contract2)
        # 构建组合合约 (BAG)
        combo_contract = Contract()
        combo_contract.symbol = c1.symbol        # 标的股票代码
        combo_contract.secType = 'BAG'
        combo_contract.currency = c1.currency
        combo_contract.exchange = 'SMART'

        # 定义组合腿
        leg1 = ComboLeg()
        leg1.conId = c1.conId
        leg1.ratio = 1
        leg1.action = action1
        leg1.exchange = c1.exchange

        leg2 = ComboLeg()
        leg2.conId = c2.conId
        leg2.ratio = 1
        leg2.action = action2
        leg2.exchange = c2.exchange

        combo_contract.comboLegs = [leg1, leg2]

        # 创建限价组合订单
        order = LimitOrder(spread_action, quantity, initial_price)

        # 语音播报双腿信息
        legs_detail = (f"{action1}腿: {c1.right} {c1.strike}, "
                       f"{action2}腿: {c2.right} {c2.strike}, "
                       f"数量: {quantity}, 初始净价: {initial_price:.2f}")
        # self._voice_notify(f"即将提交双腿期权订单: {legs_detail}")
        print(f"即将提交双腿期权订单: {legs_detail}")

        # ============ 在此处查询该 BAG 合约的市场行情 =============
        ticker = self.ib.reqMktData(combo_contract, "", snapshot=False)
        self.ib.sleep(2)
        print(">>> 当前多腿组合市场报价：Bid:", ticker.bid, "Ask:", ticker.ask, "Last:", ticker.last)


        # 提交订单前再次确认
        confirm_input = input("请确认提交双腿订单？输入 Y 确认，其他键取消: ").strip().upper()
        if confirm_input != 'Y':
            self._voice_notify("双腿订单下单已取消。")
            return None

        # 提交订单
        trade = self.ib.placeOrder(combo_contract, order)
        self._voice_notify("双腿订单已提交")
        print(f"提交垂直价差{spread_action}委托：{c1.symbol} {c1.lastTradeDateOrContractMonth or c1.localSymbol} "
              f"{c1.strike}{c1.right} {action1}, {c2.strike}{c2.right} {action2} × {quantity}组，"
              f"初始净价 {initial_price:.2f}")

        # 跟踪订单状态并递价调整
        return self.track_order_status(trade, initial_price, price_step, price_final)
    
    def place_combo_order_incremental(self, legs_info: list,
                                        combo_action: str,
                                        quantity: int,
                                        initial_price: float,
                                        price_step: float,
                                        price_final: float):
        """
        通用多腿期权递价下单。
        
        参数:            
        - legs_info: 每条腿的信息列表, 
            格式示例 [ 
            {'contract': Option(...), 'action': 'BUY', 'ratio': 3}, 
            {'contract': Option(...), 'action': 'SELL', 'ratio': 1}, 
            ... 
            ]
        - combo_action: 组合整体的交易方向, 'BUY' 或 'SELL',
                    这通常决定了组合净价是 debit 还是 credit, 
                    但在 IB 中具体要看每条腿的 action 设置。
        - quantity: 组合整体下单手数 (可以理解为 “几份组合”)
        - initial_price: 初始净价
        - price_step: 每次调价步长
        - price_final: 最终净价 (递价到这个位置就不再动了)

        返回:
        - 跟踪成交后的 Trade 对象
        """
        # 先对每条腿的合约做 qualify
        contracts = [leg['contract'] for leg in legs_info]
        qualified_contracts = self.ib.qualifyContracts(*contracts)
        
        # 构建 BAG 合约
        combo_contract = Contract()
        combo_contract.symbol = qualified_contracts[0].symbol      # 默认用第一腿的symbol
        combo_contract.secType = 'BAG'
        combo_contract.currency = qualified_contracts[0].currency
        combo_contract.exchange = 'SMART'
        
        combo_legs = []
        for i, leg_info in enumerate(legs_info):
            c = qualified_contracts[i]
            leg = ComboLeg()
            leg.conId = c.conId
            leg.ratio = leg_info.get('ratio', 1)
            leg.action = leg_info['action']
            leg.exchange = c.exchange
            combo_legs.append(leg)
            
        combo_contract.comboLegs = combo_legs

        # 创建限价组合订单
        order = LimitOrder(combo_action, quantity, initial_price)

        # 简单打印提示
        print("即将提交多腿期权组合订单，腿数:", len(combo_legs))
        for i, leg_info in enumerate(legs_info):
            c = qualified_contracts[i]
            print(f"  Leg{i+1}: {leg_info['action']} {leg_info.get('ratio',1)} 张 "
                f"{c.localSymbol} (strike={c.strike}, right={c.right})")
        print(f"组合下单方向: {combo_action}, 数量: {quantity}, 初始净价: {initial_price:.2f}")

        # ============ 在此处查询该 BAG 合约的市场行情 =============
        ticker = self.ib.reqMktData(combo_contract, "", snapshot=False)
        self.ib.sleep(2)
        print(">>> 当前多腿组合市场报价：Bid:", ticker.bid, "Ask:", ticker.ask, "Last:", ticker.last)


        # 提交订单前再次确认
        confirm_input = input("请确认提交多腿订单？输入 Y 确认，其他键取消: ").strip().upper()
        if confirm_input != 'Y':
            self._voice_notify("多腿订单下单已取消。")
            return None

        # 提交订单
        trade = self.ib.placeOrder(combo_contract, order)
        self._voice_notify("多腿订单已提交")
        print(f"提交多腿组合{combo_action}委托：{combo_contract.symbol} × {quantity}组，"
              f"初始净价 {initial_price:.2f}")

        # 跟踪订单状态并递价调整
        return self.track_order_status(trade, initial_price, price_step, price_final)

def main():
    # 连接到 IB TWS 或 IB Gateway（请确保 TWS/网关已运行）
    ib = IB()
    ib.connect('127.0.0.1', 7496, clientId=1)

    # 创建订单管理器实例，传入检查周期
    manager = OrderManager(ib, checkInterval=8)  # 8秒换一个价格

    # === 订单类型选择 ===
    engine = pyttsx3.init()
    # 语音播报提示
    try:
        # engine.say("请选择订单类型，单腿还是双腿")
        engine.runAndWait()
    except:
        pass

    order_type = input("请选择订单类型（1=单腿, 2=双腿, 3=3腿，4=4腿）: ").strip().upper()
    if order_type not in ["1", "2", "3", "4"]:  
        print("输入错误：订单类型只能为 '1' 或 '2' 或 '3' 或 '4'。程序退出。")
        return

    # === 单腿订单参数 ===
    # (用星号注释块，将来你或你的伙伴可在此修改参数)
    # ***********************************1
    single_symbol   = "UVXY"
    single_expiry   = "20250307"  # 格式可按 "YYYYMMDD"
    single_strike   = 17.5        # 行权价
    single_right    = "P"         # "C" or "P"
    single_action   = "SELL"      # "BUY" or "SELL"
    single_quantity = 1           # 下单数量
    single_init_price = 0.40      # 初始限价
    single_price_step = 0.01      # 每次调价步长
    single_price_final = 0.33     # 最终限价
    # ***********************************

    # === 双腿订单参数 ===
    # ***********************************
    spread_symbol = "UVXY"
    # 第一腿
    spread_expiry1 = "20250307"  # 格式可按 "YYYYMMDD"
    spread_strike1 = 17.5        # 行权价
    spread_right1  = "P"         # P 代表  put  C 代表 call 
    spread_action1 = "SELL"      # "BUY" or "SELL"
    # 第二腿
    spread_expiry2 = "20250307"  # 格式可按 "YYYYMMDD"
    spread_strike2 = 16.0        # 行权价
    spread_right2  = "P"         # P 代表  put  C 代表 call 
    spread_action2 = "BUY"       # "BUY" or "SELL"

    spread_action   = "BUY"      # "BUY" or "SELL"
    spread_quantity = 1           # 下单数量
    spread_init_price = -0.35    # 组合下单初始净价
    spread_price_step = 0.01 # 每次调价步长
    spread_price_final = -0.25 # 组合价格底限
    # ***********************************

    # 下单逻辑
    if order_type == "1":
        # 构造单腿合约
        contract_single = Option(
            symbol=single_symbol,
            lastTradeDateOrContractMonth=single_expiry,
            strike=single_strike,
            right=single_right,
            multiplier="100",   # 如果是美股期权，通常是100
            exchange="SMART",
            currency="USD"
        )
        # 执行单腿下单
        manager.place_single_option_order_incremental(
            contract_single,
            action=single_action,
            quantity=single_quantity,
            initial_price=single_init_price,
            price_step=single_price_step,  
            price_final=single_price_final
        )
    elif order_type == "2":
        # 构造双腿合约
        contract_leg1 = Option(
            symbol=spread_symbol,
            lastTradeDateOrContractMonth=spread_expiry1,
            strike=spread_strike1,
            right=spread_right1,
            multiplier="100",
            exchange="SMART",
            currency="USD"
        )
        contract_leg2 = Option(
            symbol=spread_symbol,
            lastTradeDateOrContractMonth=spread_expiry2,
            strike=spread_strike2,
            right=spread_right2,
            multiplier="100",
            exchange="SMART",
            currency="USD"
        )
        legs_info = [
            {'contract': contract_leg1, 'action': spread_action1, 'ratio': 1},
            {'contract': contract_leg2, 'action': spread_action2, 'ratio': 1},
        ]
        # 执行双腿下单
        manager.place_combo_order_incremental(
            legs_info,
            combo_action=spread_action,
            quantity=spread_quantity,
            initial_price=spread_init_price,
            price_step=spread_price_step,
            price_final=spread_price_final
        )
    elif order_type == "3":
        # 构造三腿合约
        leg1_contract = Option(
            symbol='FL', 
            lastTradeDateOrContractMonth='20250307', 
            strike=20, 
            right='C', 
            multiplier='100', 
            exchange='SMART',
            currency='USD'
        )
        leg2_contract = Option(
            symbol='FL', 
            lastTradeDateOrContractMonth='20250307', 
            strike=15, 
            right='C', 
            multiplier='100', 
            exchange='SMART',
            currency='USD'
        )
        leg3_contract = Option(
            symbol='FL', 
            lastTradeDateOrContractMonth='20250307', 
            strike=23.5, 
            right='C', 
            multiplier='100', 
            exchange='SMART',
            currency='USD'
        )
        legs_info_3legs = [
            {'contract': leg1_contract, 'action': 'BUY',  'ratio': 3},
            {'contract': leg2_contract, 'action': 'SELL', 'ratio': 1},
            {'contract': leg3_contract, 'action': 'SELL', 'ratio': 1},
        ]
        manager.place_combo_order_incremental(  
            legs_info_3legs,
            combo_action='BUY',
            quantity=1,
            initial_price=2.50,
            price_step=0.01,
            price_final=3.00
        )

    elif order_type == "4":
        # 构造四腿合约
        leg1_buy_call = Option(
            symbol='NVDA',
            lastTradeDateOrContractMonth='20250307',  # 3/7 到期（示例的年份自行改）
            strike=132,
            right='C',
            multiplier='100',
            exchange='SMART',
            currency='USD'
        )
        leg2_buy_put = Option(
            symbol='NVDA',
            lastTradeDateOrContractMonth='20250307',  # 3/7 到期
            strike=126,
            right='P',
            multiplier='100',
            exchange='SMART',
            currency='USD'
        )
        leg3_sell_call = Option(
            symbol='NVDA',
            lastTradeDateOrContractMonth='20250228',  # 2/28 到期
            strike=146,
            right='C',
            multiplier='100',
            exchange='SMART',
            currency='USD'
        )
        leg4_sell_put = Option(
            symbol='NVDA',
            lastTradeDateOrContractMonth='20250228',  # 2/28 到期
            strike=112,
            right='P',
            multiplier='100',
            exchange='SMART',
            currency='USD'
        )

        legs_info_4legs = [
            {'contract': leg1_buy_call, 'action': 'BUY',  'ratio': 1},
            {'contract': leg2_buy_put,  'action': 'BUY',  'ratio': 1},
            {'contract': leg3_sell_call,'action': 'SELL', 'ratio': 1},
            {'contract': leg4_sell_put, 'action': 'SELL', 'ratio': 1},
        ]
        manager.place_combo_order_incremental(
            legs_info_4legs,
            combo_action='BUY',
            quantity=1,
            initial_price=10.40,
            price_step=0.01,
            price_final=11.00
        ) 


    ib.disconnect()

if __name__ == "__main__":
    main()
