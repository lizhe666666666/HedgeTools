from ib_insync import IB, Option
import pyttsx3

from IBOptionTool import OrderManager

def main():
    # 连接到 IB TWS 或 IB Gateway（请确保 TWS/网关已运行）
    ib = IB()
    ib.connect('127.0.0.1', 7496, clientId=3)

    # 创建订单管理器实例，传入检查周期
    manager = OrderManager(ib, checkInterval=8)  # 每 8 秒调价一次

    # === 合成语音引擎（可选） ===
    engine = pyttsx3.init()

    # === 三腿订单参数 ===
    # ***********************************
    spread_symbol = "NVDA"

    # 第1腿：Buy to open 1 NVDA Mar.7 132 call
    leg1_expiry  = "20250307"    # 合约到期日 (示例)
    leg1_strike  = 132.0         # 行权价
    leg1_right   = "C"           # "C" = call, "P" = put
    leg1_action  = "BUY"         # "BUY" 或 "SELL"
    leg1_ratio   = 1

    # 第2腿：Buy to open 1 NVDA Mar.7 126 put
    leg2_expiry  = "20250307"
    leg2_strike  = 126.0
    leg2_right   = "P"
    leg2_action  = "BUY"
    leg2_ratio   = 1

    # 第3腿：Sell to open 1 NVDA Feb.28 146 call
    leg3_expiry  = "20250228"
    leg3_strike  = 146.0
    leg3_right   = "C"
    leg3_action  = "SELL"
    leg3_ratio   = 1

    # 整体组合下单方向：由于我们是净付出 (debit)，一般组合方向选择 "BUY"
    combo_action = "BUY"
    combo_quantity = 1           # 下单张数

    # 初始价格和调价步长、终止价格
    # 本例中：从 10.40 起，到 11.00 止，每次 +0.01
    combo_init_price = 10.40
    combo_price_step = 0.01
    combo_price_final = 11.00
    # ***********************************

    # 构造三腿合约
    contract_leg1 = Option(
        symbol=spread_symbol,
        lastTradeDateOrContractMonth=leg1_expiry,
        strike=leg1_strike,
        right=leg1_right,
        multiplier="100",
        exchange="SMART",
        currency="USD"
    )

    contract_leg2 = Option(
        symbol=spread_symbol,
        lastTradeDateOrContractMonth=leg2_expiry,
        strike=leg2_strike,
        right=leg2_right,
        multiplier="100",
        exchange="SMART",
        currency="USD"
    )

    contract_leg3 = Option(
        symbol=spread_symbol,
        lastTradeDateOrContractMonth=leg3_expiry,
        strike=leg3_strike,
        right=leg3_right,
        multiplier="100",
        exchange="SMART",
        currency="USD"
    )

    legs_info = [
        {'contract': contract_leg1, 'action': leg1_action, 'ratio': leg1_ratio},
        {'contract': contract_leg2, 'action': leg2_action, 'ratio': leg2_ratio},
        {'contract': contract_leg3, 'action': leg3_action, 'ratio': leg3_ratio},
    ]

    # 执行三腿下单 (组合订单)
    manager.place_combo_order_incremental(
        legs_info,
        combo_action=combo_action,
        quantity=combo_quantity,
        initial_price=combo_init_price,
        price_step=combo_price_step,
        price_final=combo_price_final
    )

    ib.disconnect()

if __name__ == "__main__":
    main()
