from api.huobi.sub.base_sub import BaseSub
from utils import logger
from utils import tools
from api.model.tasks import SingleTask
from api.model.error import Error
from api.model.order import Order
from api.model.order import ORDER_ACTION_SELL, ORDER_ACTION_BUY
from api.model.order import TRADE_TYPE_BUY_CLOSE, TRADE_TYPE_BUY_OPEN, TRADE_TYPE_SELL_CLOSE, TRADE_TYPE_SELL_OPEN
from api.model.order import ORDER_STATUS_CANCELED, ORDER_STATUS_SUBMITTED, ORDER_STATUS_FAILED, ORDER_STATUS_FILLED, \
    ORDER_STATUS_PARTIAL_FILLED


class InitOrderSub(BaseSub):
    """
    初始订单数据
    """

    def __init__(self, strategy):
        """
        symbol:交割合约btc、bch
        contract_type当周:"this_week", 次周:"next_week", 季度:"quarter"
        symbol:永续合约BTC
        contract_type续合约:"BTC-USD"
        """
        self._strategy = strategy
        self._platform = self._strategy.platform
        self._symbol = self._strategy.symbol
        self._contract_type = self._strategy.trade_symbol
        self._ch = "orders.{symbol}".format(symbol=self._symbol)
        SingleTask.run(self._init)

    async def _init(self):
        if self._platform == "swap":
            success, error = await self._strategy.request.get_open_orders(self._contract_type)
        else:
            success, error = await self._strategy.request.get_open_orders(self._symbol)
        print(success)
        if error:
            e = Error("get open orders failed!")
        if success:
            for order_info in success["data"]["orders"]:
                await self.call_back(self._ch, order_info)

    def ch(self):
        return "get_open_orders"

    def symbol(self):
        return self._symbol

    def sub_data(self):
        return None

    async def call_back(self, channel, order_info):
        if order_info["symbol"] != self._symbol.upper():
            return
        if self._platform == "swap":
            if order_info["contract_code"] != self._contract_type:
                return
        else:
            if order_info["contract_type"] != self._contract_type:
                return
        order_no = str(order_info["order_id"])
        status = order_info["status"]

        order = self._strategy.orders.get(order_no)
        if not order:
            if order_info["direction"] == "buy":
                if order_info["offset"] == "open":
                    trade_type = TRADE_TYPE_BUY_OPEN
                else:
                    trade_type = TRADE_TYPE_BUY_CLOSE
            else:
                if order_info["offset"] == "close":
                    trade_type = TRADE_TYPE_SELL_CLOSE
                else:
                    trade_type = TRADE_TYPE_SELL_OPEN

            info = {
                "order_no": order_no,
                "action": ORDER_ACTION_BUY if order_info["direction"] == "buy" else ORDER_ACTION_SELL,
                "symbol": self._symbol + '/' + self._contract_type,
                "price": order_info["price"],
                "quantity": order_info["volume"],
                "trade_type": trade_type
            }
            order = Order(**info)
            self._strategy.orders[order_no] = order

        if status in [1, 2, 3]:
            order.status = ORDER_STATUS_SUBMITTED
        elif status == 4:
            order.status = ORDER_STATUS_PARTIAL_FILLED
            order.remain = int(order.quantity) - int(order_info["trade_volume"])
        elif status == 6:
            order.status = ORDER_STATUS_FILLED
            order.remain = 0
        elif status in [5, 7]:
            order.status = ORDER_STATUS_CANCELED
            order.remain = int(order.quantity) - int(order_info["trade_volume"])
        else:
            return

        order.avg_price = order_info["trade_avg_price"]
        order.ctime = order_info["created_at"]
        # Delete order that already completed.
        if order.status in [ORDER_STATUS_FAILED, ORDER_STATUS_CANCELED, ORDER_STATUS_FILLED]:
            self._strategy.orders.pop(order_no)

        # publish order
        logger.info("symbol:", order.symbol, "order:", order, caller=self)

