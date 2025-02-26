from ib_insync import IB, Option
import pyttsx3

from IBOptionTool import OrderManager


def main():
    # 连接到 IB TWS 或 IB Gateway（请确保 TWS/网关已运行）
    ib = IB()
    ib.connect('127.0.0.1', 7496, clientId=2)

    # 创建订单管理器实例，传入检查周期
    manager = OrderManager(ib, checkInterval=8)  # 8秒换一个价格

    # === 订单类型选择 ===
    engine = pyttsx3.init()

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

   

    ib.disconnect()

if __name__ == "__main__":
    main()
