import json, config
from flask import Flask, request
from api.binance_spot import BinanceSpotHttpClient
from api.binance_future import BinanceFutureHttpClient, OrderSide, OrderType
from event import EventEngine, Event, EVENT_TIMER, EVENT_SIGNAL
from decimal import Decimal

app = Flask(__name__)


@app.route('/', methods=['GET'])
def welcome():
    return "Hello Flask, This is for testing. If you receive this message, it means your configuration is correct."


@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        data = json.loads(request.data)
        print(data)
        if data.get('passphrase', None) != config.WEBHOOK_PASSPHRASE:
            return "failure: passphrase is incorrect."

        event = Event(EVENT_SIGNAL, data=data)
        event_engine.put(event)

        return "success"
    except Exception as error:
        print(f"error: {error}")
        return "failure"


def future_trade(data: dict):

    symbol = data.get('symbol', 'BTCUSDT')
    action = data.get('action', 'BUY').upper()

    leverage = 20
    usdt_amount = 15

    # Получаем цену BTC
    try:
        response = requests.get(f"https://fapi.binance.com/fapi/v1/ticker/price?symbol={symbol}")
        price = float(response.json()["price"])
    except Exception as e:
        print(f"Ошибка при получении цены: {e}")
        return

    quantity = round((usdt_amount * leverage) / price, 3)
    current_pos = 0
    trading_volume = quantity

    print(f"Открытие позиции: {action}, Символ: {symbol}, Цена: {price}, Объём: {quantity}")

    if action == 'EXIT':

        if current_pos > 0:

            vol1 = str(current_pos)

            order_id = binance_future_client.get_client_order_id()

            # the order support: LIMIT, MARKET, MAKER order
            # if you want to place a maker order, set the order_type=OrderType.MAKER
            # 支持限价单，市价单，做市单，如果你想下做市单，设置参数 order_type=OrderType.MAKER
            status, order = binance_future_client.place_order(
                symbol=symbol,
                order_side=OrderSide.SELL,
                order_type=OrderType.MARKET,
                quantity=Decimal(vol1),
                price=Decimal(price),
                client_order_id=order_id
            )

            print("exit long: ", status, order)

            if status == 200:
                future_strategy_order_dict[strategy_name] = order_id

        elif current_pos < 0:

            vol1 = str(abs(current_pos))

            order_id = binance_future_client.get_client_order_id()
            status, order = binance_future_client.place_order(
                symbol=symbol,
                order_side=OrderSide.BUY,
                order_type=OrderType.MARKET,
                quantity=Decimal(vol1),
                price=Decimal(price),
                client_order_id=order_id
            )
            print("exit short: ", status, order)
            if status == 200:
                future_strategy_order_dict[strategy_name] = order_id

    elif action == 'LONG':

        if current_pos < 0:

            vol1 = str(abs(current_pos) + trading_volume)
            order_id = binance_future_client.get_client_order_id()
            status, order = binance_future_client.place_order(
                symbol=symbol,
                order_side=OrderSide.BUY,
                order_type=OrderType.MARKET,
                quantity=Decimal(vol1),
                price=Decimal(price),
                client_order_id=order_id
            )
            print("exit short & long: ", status, order)
            if status == 200:
                future_strategy_order_dict[strategy_name] = order_id

        if current_pos == 0:
            # config your trading volume in config.py

            vol1 = str(trading_volume)
            order_id = binance_future_client.get_client_order_id()
            status, order = binance_future_client.place_order(
                symbol=symbol,
                order_side=OrderSide.BUY,
                order_type=OrderType.MARKET,
                quantity=Decimal(vol1),
                price=Decimal(price),
                client_order_id=order_id
            )
            print("long: ", status, order)
            if status == 200:
                future_strategy_order_dict[strategy_name] = order_id

    elif action == 'SHORT':

        if current_pos > 0:

            vol1 = str(abs(current_pos) + trading_volume)
            order_id = binance_future_client.get_client_order_id()
            status, order = binance_future_client.place_order(
                symbol=symbol,
                order_side=OrderSide.SELL,
                order_type=OrderType.MARKET,
                quantity=Decimal(vol1),
                price=Decimal(price),
                client_order_id=order_id
            )
            print("exit long & short: ", status, order)
            if status == 200:
                future_strategy_order_dict[strategy_name] = order_id

        if current_pos == 0:
            vol1 = str(trading_volume)
            order_id = binance_future_client.get_client_order_id()
            status, order = binance_future_client.place_order(
                symbol=symbol,
                order_side=OrderSide.SELL,
                order_type=OrderType.MARKET,
                quantity=Decimal(str(vol1)),
                price=Decimal(price),
                client_order_id=order_id
            )
            print("short: ", status, order)
            if status == 200:
                future_strategy_order_dict[strategy_name] = order_id


def timer_event(event: Event):
    global cancel_orders_timer
    global query_orders_timer

    cancel_orders_timer += 1
    query_orders_timer += 1

    if cancel_orders_timer > config.CANCEL_ORDERS_IN_SECONDS:  # for cancel order.
        cancel_orders_timer = 0 # reset the timer
        # will cancel the order repeatedly. the default value is CANCEL_ORDER_IN_SECONDS = 60
        for strategy_name in future_strategy_order_dict.keys():
            order_id = future_strategy_order_dict[strategy_name]
            if not order_id:
                continue

            symbol = config.strategies.get(strategy_name, {}).get('symbol', "")
            binance_future_client.cancel_order(symbol, client_order_id=order_id)

    if query_orders_timer > config.QUERY_ORDERS_STATUS_IN_SECONDS: # for updating order.
        query_orders_timer = 0 #  reset the query order timer.

        for strategy_name in future_strategy_order_dict.keys():
            order_id = future_strategy_order_dict[strategy_name]
            if not order_id:
                continue

            symbol = config.strategies.get(strategy_name, {}).get('symbol', "")

            status_code, order = binance_future_client.get_order(symbol, client_order_id=order_id)
            if status_code == 200 and order:
                if order.get('status') == 'CANCELED' or order.get('status') == 'FILLED':
                    side = order.get('side')
                    strategy_config = config.strategies.get(strategy_name, {})
                    executed_qty = Decimal(order.get('executedQty', "0"))

                    if side == "BUY":  # BUY
                        strategy_config['pos'] = strategy_config['pos'] + executed_qty

                    elif side == "SELL":  # SELL
                        strategy_config['pos'] = strategy_config['pos'] - executed_qty

                    # print(strategy_config)
                    config.strategies[strategy_name] = strategy_config  # update the data.
                    future_strategy_order_dict[strategy_name] = None
            elif status_code == 400 and order.get('code') == -2013:  # Order does not exist.
                future_strategy_order_dict[strategy_name] = None

    for strategy_name in future_signal_dict.keys():

        orderid = future_strategy_order_dict.get(strategy_name, None)
        if not orderid:
            data = future_signal_dict.get(strategy_name, None)
            if data:
                future_trade(data)

    for key in spot_signal_dict.keys():
        """
        check your spot signal here, whether your buy/sell order filled.
        
        please refer to the future signal and code your logic below.
        """
        pass


def signal_event(event: Event):
    """
    :param event: the event that contains the signal data
    the signal data like below.
    {'action': 'long',
    'symbol': 'ETHUSDT', 'exchange': 'binance_future',
    'price': '3054.66', 'close': '3054.66',
    'passphrase': 'btc_secret_999'}

    :return: None
    """

    data = event.data
    strategy_name = data.get('strategy_name', None)
    if not strategy_name:
        print("config from tradingview does not have strategy_name key.")
        return None

    if data.get('exchange', None) == 'binance_future':
        future_signal_dict[strategy_name] = data  # strategy_name -> data
        future_trade(data)

    elif data.get('exchange', None) == 'binance_spot':

        future_signal_dict[strategy_name] = data  # strategy_name -> data
        # write your logic code here.


if __name__ == '__main__':
    future_signal_dict = {}
    spot_signal_dict = {}

    future_strategy_order_dict = {}

    cancel_orders_timer = 0  # 撤单的timer.
    query_orders_timer = 0 # 查询订单的tismer.

    binance_spot_client = BinanceSpotHttpClient(api_key=config.API_KEY, secret=config.API_SECRET)
    binance_future_client = BinanceFutureHttpClient(api_key=config.API_KEY, secret=config.API_SECRET)

    event_engine = EventEngine(interval=1)  # you can update the loop interval.
    event_engine.start()
    event_engine.register(EVENT_TIMER, timer_event)
    event_engine.register(EVENT_SIGNAL, signal_event)

    import os
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
