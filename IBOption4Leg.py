from ib_insync import IB, Option
import pyttsx3

from IBOptionTool import OrderManager

def main():
    # 连接到 IB TWS 或 IB Gateway（请确保 TWS/网关已运行）
    ib = IB()
    ib.connect('127.0.0.1', 7496, clientId=4)

    # 创建订单管理器实例，传入检查周期
    manager = OrderManager(ib, checkInterval=8)  # 每 8 秒调价一次

    # === 合成语音引擎（可选） ===
    engine = pyttsx3.init()

    # === 四腿订单参数 ===
    # ***********************************
    spread_symbol = "NKE" 
    leg1_expiry = "20250328" 
    leg1_strike = 84.0 
    leg1_right = "C" 
    leg1_action = "BUY" 
    leg1_ratio = 1

    leg2_expiry = "20250328" 
    leg2_strike = 80.0 
    leg2_right = "P" 
    leg2_action = "BUY" 
    leg2_ratio = 1

    leg3_expiry = "20250321" 
    leg3_strike = 90.0 
    leg3_right = "C" 
    leg3_action = "SELL" 
    leg3_ratio = 1

    leg4_expiry = "20250321" 
    leg4_strike = 74.0 
    leg4_right = "P" 
    leg4_action = "SELL" 
    leg4_ratio = 1

    combo_action = "BUY" 
    combo_quantity = 3 
    combo_init_price = 4.10
    combo_price_step = 0.01
    combo_price_final = 4.15
    # ***********************************

    # 构造四腿合约
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

    contract_leg4 = Option(
        symbol=spread_symbol,
        lastTradeDateOrContractMonth=leg4_expiry,
        strike=leg4_strike,
        right=leg4_right,
        multiplier="100",
        exchange="SMART",
        currency="USD"
    )

    legs_info = [
        {'contract': contract_leg1, 'action': leg1_action, 'ratio': leg1_ratio},
        {'contract': contract_leg2, 'action': leg2_action, 'ratio': leg2_ratio},
        {'contract': contract_leg3, 'action': leg3_action, 'ratio': leg3_ratio},
        {'contract': contract_leg4, 'action': leg4_action, 'ratio': leg4_ratio},
    ]

    # 执行四腿下单 (组合订单)
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
