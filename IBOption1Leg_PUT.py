import time
import sys
import threading
from ibapi.contract import Contract
from IBOptionToolOffical import IBApp, OrderManager

########################################################
# 单腿下单
interval = 8.0   # 每n秒递价一次(可自行调整)
spread_symbol = "UVXY"
leg1_right   = "P"
leg1_action  = "SELL"

leg1_expiry  = "20250417"
leg1_strike  = 30.0
leg1_ratio   = 1

# 起始与目标价格(组合净价)
combo_init_price  = 2.25
combo_price_final = 2.15
combo_price_step  = 0.01

########################################################


def main():
    # 连接到 IB TWS 或 IB Gateway（请确保 TWS/网关已运行）
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

    # 构造legs列表
    legs = [
        {
            "underlying": spread_symbol,
            "lastTradeDate": leg1_expiry,
            "strike": leg1_strike,
            "right": leg1_right,
            "action": leg1_action,
            "quantity": leg1_ratio
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

        print(f"Leg {idx}:"
              f"\n 期权={leg['right']}  方向={leg['action']}  数量={leg['quantity']}  到期日={leg['lastTradeDate']}  行权价={leg['strike']}"
              f"\n\n ask={ask:.2f}, bid={bid:.2f}, last={last:.2f}, mid~={mid:.2f}")

    print(f"\n下单金额参数: 起始价={combo_init_price:.2f}, 步长={combo_price_step:.2f}, 终止价={combo_price_final:.2f}")
    print("----------------------------------------------")
    print(f"--> Estimated combo total cost (for {leg['quantity']} leg) = {net_estimated_cost:.2f}")
    print("==============================================")

    # 5) 增加一个交互：是否确认下单
    user_input = input("是否确认下单？输入 Y 或 y 确认下单，其余任意键取消并退出: ")
    if user_input.lower() != 'y':
        print("用户取消下单，程序结束。")
        # 先主动断开，以防与TWS还连接着
        app.disconnect()
        sys.exit(0)

    # ========= 如果用户确认，才进行下单 =========
    order_id = manager.place_option_order(legs, order_type="LMT", limit_price=combo_init_price)
    if order_id:
        print(f"单腿下单完成, 订单ID={order_id}, 初始限价={combo_init_price:.2f}")
        # 继续自动追价到目标 combo_price_final
        # 注意这里：把返回的 chase_thread 存起来
        chase_thread = manager.chase_order_to_final(
            order_id    = order_id,
            step        = combo_price_step,
            final_price = combo_price_final,
            interval    = interval
        )

    # 等待追价线程执行完毕（即订单被填满/取消或到达final价）
    chase_thread.join()

    print("Disconnecting from IB...")
    app.disconnect()

if __name__ == "__main__":
    main()