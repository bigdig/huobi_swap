from api.huobi.sub.base_sub import BaseSub
from utils import logger


class InitAssetSub(BaseSub):
    """
    初始化资产
    """

    def __init__(self, strategy):
        """
        交割合约symbol:btc、bch
        永久合约合约symbol:BTC-USD
        """
        self._strategy = strategy
        self._platform = self._strategy.platform
        if self._platform == "swap":
            self._symbol = self._strategy.trade_symbol
        else:
            self._symbol = self._strategy.symbol

    def ch(self):
        return "accounts"

    def symbol(self):
        return self._symbol

    def sub_data(self):
        return None

    async def call_back(self, op, data):
        assets = {}
        event = data["event"]
        for item in data["data"]:
            symbol = item["symbol"].upper()
            total = float(item["margin_balance"])
            free = float(item["margin_available"])
            locked = float(item["margin_frozen"])
            risk = item["risk_rate"]
            rate = item["lever_rate"]
            factor = item["adjust_factor"]
            liquidation = item["liquidation_price"]
            if total > 0:
                assets[symbol] = {
                    "total": "%.8f" % total,
                    "free": "%.8f" % free,
                    "locked": "%.8f" % locked,
                    "risk": risk,
                    "rate": rate,
                    "liquidation": liquidation,
                    "factor": factor
                }
            else:
                assets[symbol] = {
                    "total": 0,
                    "free": 0,
                    "locked": 0,
                    "risk": risk,
                    "rate": rate,
                    "liquidation": liquidation,
                    "factor": factor
                }
        if assets == self._strategy.assets.assets:
            update = False
        else:
            update = True
        self._strategy.assets.update = update
        self._strategy.assets.assets = assets
        self._strategy.assets.timestamp = data["ts"]
        if event == "init":
            logger.info("init assets:", self._strategy.assets.__str__(), caller=self)

