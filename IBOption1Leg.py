from ib_insync import IB, Option
import pyttsx3

from IBOptionTool import OrderManager


def main():
    # 连接到 IB TWS 或 IB Gateway（请确保 TWS/网关已运行）
    ib = IB()
    ib.connect('127.0.0.1', 7496, clientId=1)

    # 创建订单管理器实例，传入检查周期
    manager = OrderManager(ib, checkInterval=8)  # 8秒换一个价格

    # === 订单类型选择 ===
    engine = pyttsx3.init()



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


    ib.disconnect()

if __name__ == "__main__":
    main()
