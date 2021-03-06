from api.model.market import Market
from api.huobi.huobi_request import HuobiRequest
from api.huobi.huobi_request_swap import HuobiSwapRequest
from api.model.tasks import LoopRunTask
from api.huobi.sub.init_kline_sub import InitKlineSub
from api.huobi.sub.kline_sub import KlineSub
from api.huobi.sub.depth_sub import DepthSub
from api.huobi.sub.trade_sub import TradeSub
from api.huobi.sub.asset_sub import AssetSub
from api.huobi.sub.position_sub import PositonSub
from api.huobi.sub.order_sub import OrderSub
from api.huobi.sub.init_order_sub import InitOrderSub
from api.huobi.sub.init_asset_sub import InitAssetSub
from api.huobi.sub.init_position_sub import InitPositonSub
from api.huobi.sub.init_trade_sub import InitTradeSub
from api.huobi.sub.init_info_sub import InitInfoSub
from api.model.trade import Trade
from api.model.asset import Asset
from api.model.position import Position
import copy
from utils import tools
from utils.config import config
from utils import logger
from utils.tools import round_to
from api.model.error import Error
from api.model.order import TRADE_TYPE_BUY_CLOSE, TRADE_TYPE_BUY_OPEN, TRADE_TYPE_SELL_CLOSE, TRADE_TYPE_SELL_OPEN
from api.model.order import ORDER_STATUS_NONE, ORDER_STATUS_SUBMITTED, ORDER_STATUS_PARTIAL_FILLED
from api.model.order import ORDER_ACTION_SELL, ORDER_ACTION_BUY
from api.model.const import KILINE_PERIOD
from utils.recordutil import record
import talib
import numpy as np
from api.model.const import TradingCurb


class BaseStrategy:
    """
    基础策略类
    交割合约：
    "symbol": "eth",
    "mark_symbol": "ETH_CQ",
    "trade_symbol": "quarter",
    永久合约：
    "symbol": "ETH",
    "mark_symbol": "ETH_USD",
    "trade_symbol": "ETH_USD",
    2者的差别有：
    资产、下单、撤单中的symbol不一样
    """

    def __init__(self):
        self.host = config.accounts.get("host")
        self.mark_wss = config.accounts.get("mark_wss")
        self.wss = config.accounts.get("trade_wss")
        self.access_key = config.accounts.get("access_key")
        self.secret_key = config.accounts.get("secret_key")
        self.test = config.accounts.get("is_test", True)

        self.platform = config.markets.get("platform")
        self.symbol = config.markets.get("symbol")
        self.mark_symbol = config.markets.get("mark_symbol")
        self.trade_symbol = config.markets.get("trade_symbol")

        self.lever_rate = config.markets.get("lever_rate")
        self.price_tick = config.markets.get("price_tick")
        self.price_offset = config.markets.get("price_offset")
        self.loop_interval = config.markets.get("loop_interval")
        self.order_cancel_time = config.markets.get("order_cancel_time")
        self.auto_curb = config.markets.get("auto_curb")
        self.trading_curb = config.markets.get("trading_curb")
        self.long_position_weight_rate = config.markets.get("long_position_weight_rate")
        self.short_position_weight_rate = config.markets.get("short_position_weight_rate")
        self.long_fixed_position = config.markets.get("long_fixed_position", 0)
        self.short_fixed_position = config.markets.get("short_fixed_position", 0)

        e = None
        if not self.host:
            e = Error("host miss")
        if not self.mark_wss:
            e = Error("mark_wss miss")
        if not self.wss:
            e = Error("trade_wss miss")
        if not self.access_key:
            e = Error("access_key miss")
        if not self.secret_key:
            e = Error("secret_key miss")

        if not self.platform:
            e = Error("platform miss")
        if not self.symbol:
            e = Error("symbol miss")
        if not self.mark_symbol:
            e = Error("mark_symbol miss")
        if not self.trade_symbol:
            e = Error("trade_symbol miss")
        if not self.lever_rate:
            e = Error("lever_rate miss")
        if not self.price_tick:
            e = Error("price_tick miss")
        if not self.price_offset:
            e = Error("price_offset miss")
        if not self.loop_interval:
            e = Error("loop_interval miss")
        if not self.order_cancel_time:
            e = Error("order_cancel_time miss")
        if not self.trading_curb:
            e = Error("trading_curb miss")
        if not self.long_position_weight_rate:
            e = Error("long_position_weight_rate miss")
        if not self.short_position_weight_rate:
            e = Error("short_position_weight_rate miss")

        if e:
            logger.error(e, caller=self)
            return

        self.klines_max_size = 0
        self.depths_max_size = 0
        self.trades_max_size = 0
        self.period = "5min"
        self.step = "step2"

        # 市场数据
        self.klines = {}
        self.depths = {}
        self.trades = {}

        # 账号数据
        self.assets = Asset()
        self.orders = {}
        self.position = Position(self.symbol + '/' + self.trade_symbol)
        self.position.long_avg_open_price = 0
        self.position.long_quantity = 0
        self.position.long_avg_price = 0
        self.position.short_avg_open_price = 0
        self.position.short_quantity = 0
        self.position.short_avg_price = 0

        self.trade_money = 1  # 10USDT.  每次交易的金额, 修改成自己下单的金额.
        self.min_volume = 1  # 最小的交易数量(张).
        self.short_trade_size = 0
        self.long_trade_size = 0
        self.last_price = 0
        self.long_status = 0  # 0不处理  1做多 -1平多
        self.short_status = 0  # 0不处理  1做空 -1 平空
        self.last_order = {}  # 最近下单记录
        self.contract_size = 0  # 面值

        # 初始http链接
        if self.platform == "swap":
            self.request = HuobiSwapRequest(host=self.host, access_key=self.access_key, secret_key=self.secret_key)
        else:
            self.request = HuobiRequest(host=self.host, access_key=self.access_key, secret_key=self.secret_key)

        if len(config.mark_sub) > 0:
            self.market = self.init_market()
        self.trade = self.init_trade()
        # 运行周期
        LoopRunTask.register(self.on_ticker, self.loop_interval)

    def init_market(self):
        """
        初始和监听交易数据
        :return:
        """
        mark_sub_param = config.mark_sub
        market = Market(platform=self.platform, wss=self.mark_wss, request=self.request)
        market.add_sub(InitInfoSub(strategy=self))
        if "kline" in mark_sub_param:
            kline_config = mark_sub_param.get("kline")
            self.klines_max_size = kline_config["max_size"]
            self.period = kline_config["period"]
            market.add_sub(InitKlineSub(strategy=self, period=self.period))
            market.add_sub(KlineSub(strategy=self, period=self.period))
            if self.auto_curb:
                for period in KILINE_PERIOD:
                    if period == self.period:
                        continue
                    market.add_sub(InitKlineSub(strategy=self, period=period))
                    market.add_sub(KlineSub(strategy=self, period=period))
        if "depth" in mark_sub_param:
            depth_config = mark_sub_param.get("depth")
            self.depths_max_size = depth_config["max_size"]
            self.step = depth_config["step"]
            market.add_sub(DepthSub(strategy=self))
        if "trade" in mark_sub_param:
            trade_config = mark_sub_param.get("trade")
            self.trades_max_size = trade_config["max_size"]
            market.add_sub(InitTradeSub(strategy=self, period=trade_config["period"]))
            market.add_sub(TradeSub(strategy=self, period=trade_config["period"]))
        market.start()
        return market

    def init_trade(self):
        """
        初始和监听市场数据
        :return:
        """
        trade = Trade(platform=self.platform, wss=self.wss, access_key=self.access_key,
                      secret_key=self.secret_key, rest_api=self.request)
        trade.add_sub(InitPositonSub(strategy=self))
        trade.add_sub(PositonSub(strategy=self))
        trade.add_sub(InitOrderSub(strategy=self))
        trade.add_sub(OrderSub(strategy=self))
        trade.add_sub(InitAssetSub(strategy=self))
        trade.add_sub(AssetSub(strategy=self))
        trade.start()
        return trade

    async def on_ticker(self, *args, **kwargs):
        before_state = await self.before_strategy()
        if not before_state:  # 策略之前执行
            return
        self.strategy_handle()  # 策略计算
        await self.after_strategy()   # 策略之后执行

    async def before_strategy(self):
        # 撤单
        orders = copy.copy(self.orders)
        ut_time = tools.get_cur_timestamp_ms()
        if len(orders) > 0:
            for no in orders.values():
                if ut_time >= no.ctime + self.order_cancel_time:
                    if self.platform == "swap":
                        await self.trade.revoke_order(self.trade_symbol.upper(), self.trade_symbol, no.order_no)
                    else:
                        await self.trade.revoke_order(self.symbol.upper(), self.trade_symbol, no.order_no)

        # 检查k是否初始完了
        if self.auto_curb:
            if len(self.klines) != len(KILINE_PERIOD):  # k线数据没有
                return False
        else:
            if len(self.klines) != 1:  # k线数据没有
                return False
        if len(self.trades) == 0:  # 最近成交记录没有
            return False
        # if not self.position.init:
        #     return False

        # 设置计算参数
        self.long_status = 0
        self.short_status = 0
        self.long_trade_size = 0
        self.short_trade_size = 0
        self.last_price = 0
        trades = copy.copy(self.trades)
        last_trades = trades.get("market." + self.mark_symbol + ".trade.detail")
        if last_trades and len(last_trades) > 0:
            self.last_price = round_to(float(last_trades[-1].price), self.price_tick)
        if self.last_price <= 0:  # 最近一次的成交价格没有
            return False
        return True

    def strategy_handle(self):
        """
        策略重写
        :return:
        """
        pass

    async def after_strategy(self):
        """
        下单或者平仓
        :return:
        """
        # 判断装填和数量是否相等
        if self.long_status == 1 and self.long_trade_size < self.min_volume:
            self.long_status = 0
            self.long_trade_size = 0
        if self.short_status == 1 and self.short_trade_size < self.min_volume:
            self.short_status = 0
            self.short_trade_size = 0
        if self.long_status == 0 and self.short_status == 0:
            return
        self.long_trade_size = self.long_trade_size * self.long_position_weight_rate
        self.short_trade_size = self.short_trade_size * self.short_position_weight_rate
        position = copy.copy(self.position)
        if self.long_status == 1:  # 开多
            if self.long_trade_size > position.long_quantity:   # 开多加仓
                amount = self.long_trade_size - position.long_quantity
                if amount >= self.min_volume:
                    price = self.last_price * (1 + self.price_offset)
                    price = round_to(price, self.price_tick)
                    ret = await self.create_order(action=ORDER_ACTION_BUY,  price=price, quantity=amount)

            elif self.long_trade_size < position.long_quantity:  # 开多减仓
                amount = position.long_quantity - self.long_trade_size
                if abs(amount) >= self.min_volume:
                    price = self.last_price * (1 - self.price_offset)
                    price = round_to(price, self.price_tick)
                    ret = await self.create_order(action=ORDER_ACTION_SELL, price=price, quantity=amount)

        if self.short_status == 1:  # 开空
            if self.short_trade_size > position.short_quantity:  # 开空加仓
                amount = self.short_trade_size - position.short_quantity
                if amount >= self.min_volume:
                    price = self.last_price * (1 - self.price_offset)
                    price = round_to(price, self.price_tick)
                    ret = await self.create_order(action=ORDER_ACTION_SELL, price=price, quantity=-amount)

            elif self.short_trade_size < position.short_quantity:  # 开空减仓
                amount = position.short_quantity - self.short_trade_size
                if abs(amount) >= self.min_volume:
                    price = self.last_price * (1 + self.price_offset)
                    price = round_to(price, self.price_tick)
                    ret = await self.create_order(action=ORDER_ACTION_BUY, price=price, quantity=-amount)

        if self.long_status == -1:  # 平多
            if position.long_quantity > 0:
                price = self.last_price * (1 - self.price_offset)
                price = round_to(price, self.price_tick)
                ret = await self.create_order(action=ORDER_ACTION_SELL, price=price, quantity=position.long_quantity)

        if self.short_status == -1:  # 平空
            if position.short_quantity > 0:
                price = self.last_price * (1 + self.price_offset)
                price = round_to(price, self.price_tick)
                ret = await self.create_order(action=ORDER_ACTION_BUY, price=price, quantity=-position.short_quantity)

    async def create_order(self, action, price, quantity):
        if not self.test:
            if not self.limit_assert(action, quantity):
                return -1
            if not self.limit_curb(action, quantity):
                return -2
            if not self.limit_order(action, quantity):
                logger.info("开仓太快 action:", price, " quantity:", quantity, caller=self)
                return -3
            p = {"lever_rate": self.lever_rate}
            if self.platform == "swap":
                await self.trade.create_order(symbol=self.trade_symbol.upper(), contract_type=self.trade_symbol,
                                              action=action,
                                              price=price, quantity=quantity, **p)
            else:
                await self.trade.create_order(symbol=self.symbol.upper(), contract_type=self.trade_symbol,
                                              action=action,
                                              price=price, quantity=quantity, **p)
            logger.info("action", action, "price:", price, "num:", quantity, "r:", self.lever_rate, "ret", caller=self)
        else:
            if action == ORDER_ACTION_BUY:
                if quantity > 0:
                    self.position.long_quantity = self.position.long_quantity + quantity
                    logger.info("开多 price:", price, "amount:", self.position.long_quantity, "rate:", self.lever_rate,
                                caller=self)
                elif quantity < 0:
                    self.position.short_quantity = self.position.short_quantity + quantity
                    logger.info("平空 price:", price, "amount:", self.position.short_quantity, "rate:", self.lever_rate,
                                caller=self)
            if action == ORDER_ACTION_SELL:
                if quantity > 0:
                    self.position.long_quantity = self.position.long_quantity - quantity
                    logger.info("平多 price:", price, "amount:", self.position.long_quantity, "rate:", self.lever_rate,
                                caller=self)
                elif quantity < 0:
                    self.position.short_quantity = self.position.short_quantity - quantity
                    logger.info("开空 price:", price, "amount:", self.position.short_quantity, "rate:", self.lever_rate,
                                caller=self)
            return 0

    def limit_assert(self, action, quantity):
        """
        资产限制
        :param action:
        :param quantity:
        :return:
        """
        asserts = copy.copy(self.assets)
        if not asserts.assets:
            logger.error("asserts not init", caller=self)
            return False
        asset = asserts.assets.get(self.symbol)
        if not asset:
            logger.error(self.symbol, "no asset", caller=self)
            return False
        return True

    def limit_curb(self, action, quantity):
        """
        交易类型限制
        :param action:
        :param quantity:
        :return:
        """
        if self.trading_curb == TradingCurb.LOCK.value:  # 不能下单
            return False
        if self.trading_curb == TradingCurb.NONE.value:  # 都能下单
            return True

        if self.trading_curb == TradingCurb.LIMITLONGBUY.value:  #不能开多单
            if action == ORDER_ACTION_BUY and quantity > 0:
                return False
        if self.trading_curb == TradingCurb.LIMITSHORTBUY.value:  #不能开空单
            if action == ORDER_ACTION_SELL and quantity < 0:
                return False

        if self.trading_curb == TradingCurb.BUY.value:  # 只加仓
            if (action == ORDER_ACTION_BUY and quantity < 0) or (action == ORDER_ACTION_SELL and quantity > 0):
                return False
        if self.trading_curb == TradingCurb.SELL.value:  # 只减仓
            if (action == ORDER_ACTION_BUY and quantity > 0) or (action == ORDER_ACTION_SELL and quantity < 0):
                return False

        if self.trading_curb == TradingCurb.LONG.value and quantity < 0:  # 只做多
            return False
        if self.trading_curb == TradingCurb.SHORT.value and quantity > 0:  # 只做空
            return False
        return True

    def limit_order(self, action, quantity):
        """
        订单限制
        :param action:
        :param quantity:
        :return:
        """
        # 检查开多和开空的时间间隔是否太短 5s同一订单不下单
        ut_time = tools.get_cur_timestamp_ms()
        long_or_short_order = None
        if action == ORDER_ACTION_BUY and quantity > 0:  # 开多
            long_or_short_order = TradingCurb.LONG.value
        elif action == ORDER_ACTION_SELL and quantity < 0:  # 开空
            long_or_short_order = TradingCurb.SHORT.value
        last_order_info = self.last_order.get(long_or_short_order)
        if last_order_info:
            if last_order_info["action"] == action and last_order_info["quantity"] == quantity and \
                    ut_time < last_order_info["ts"] + 5000:
                return False
        if long_or_short_order:
            last__order_info = {
                "action": action,
                "quantity": quantity,
                "ts": ut_time
            }
            self.last_order[long_or_short_order] = last__order_info

        # 检查当前时候有该类型订单挂单了
        if action == ORDER_ACTION_BUY:
            if quantity > 0:
                trade_type = TRADE_TYPE_BUY_OPEN
            else:
                trade_type = TRADE_TYPE_BUY_CLOSE
        else:
            if quantity > 0:
                trade_type = TRADE_TYPE_SELL_CLOSE
            else:
                trade_type = TRADE_TYPE_SELL_OPEN
        orders = copy.copy(self.orders)
        for no in orders.values():
            if no.symbol == self.symbol + "/" + self.trade_symbol:
                if no.trade_type == trade_type and (no.status == ORDER_STATUS_NONE or no.status == ORDER_STATUS_SUBMITTED
                                                    or no.status == ORDER_STATUS_PARTIAL_FILLED):
                    logger.info("hand same order.", no.symbol, no.trade_type, no.status, caller=self)
                    return False
        return True

    def change_curb(self, klines, position):
        if not self.auto_curb:
            return
        last_ma = 0
        last_signal = 0
        ma = 0
        signal = 0
        log_data = {}
        close = None
        for index, period in enumerate(KILINE_PERIOD):
            df = klines.get("market.%s.kline.%s" % (self.mark_symbol, period))
            df["ma"], df["signal"], df["hist"] = talib.MACD(np.array(df["close"]), fastperiod=12,
                                                            slowperiod=26, signalperiod=9)
            curr_bar = df.iloc[-1]
            ma = ma + curr_bar["ma"]
            signal = signal + curr_bar["signal"]
            log_data[period + "_ma"] = curr_bar["ma"]
            log_data[period + "_signal"] = curr_bar["signal"]
            if not close:
                close = curr_bar["close"]
            last_bar = df.iloc[-2]
            last_ma = last_ma + last_bar["ma"]
            last_signal = last_signal + last_bar["signal"]
        new_curb = None
        if position.long_quantity - self.long_fixed_position == 0 and \
                position.short_quantity - self.short_fixed_position == 0:
            if last_ma <= last_signal and ma > signal:
                new_curb = TradingCurb.LIMITSHORTBUY.value
            elif last_ma >= last_signal and ma < signal:
                new_curb = TradingCurb.LIMITLONGBUY.value
        else:
            if ma == signal:
                new_curb = TradingCurb.LOCK.value
            if ma > signal:
                new_curb = TradingCurb.LIMITSHORTBUY.value
            if ma < signal:
                new_curb = TradingCurb.LIMITLONGBUY.value
        if new_curb and self.trading_curb != new_curb:
            self.trading_curb = new_curb
            self.save_file()
        log_data["ma"] = ma
        log_data["signal"] = signal
        log_data["trading_curb"] = self.trading_curb
        log_data["close"] = close
        logger.info("change_curb:", log_data)

    def save_file(self):
        pass

    def load_file(self):
        pass

    def e_g(self):
        curbs = []
        for curb in TradingCurb:
            curbs.append(curb.value)
        return "tc=" + str(curbs) + "\nlr=long_position_weight_rate\nsr=short_position_weight_rate\ndd=[0, 1]\n" \
                                    "ac=[true, false]\nlp=long_fixed_position\nsp=short_fixed_position"

    def show(self):
        return "trading_curb=%s\nauto_curb=%s\nlong_position_weight_rate=%s\nshort_position_weight_rate=%s\n" \
               "long_fixed_position=%s\nshort_fixed_position=%s\ndingding=%s\nstrategy=%s" % \
               (self.trading_curb, self.auto_curb, self.long_position_weight_rate, self.short_position_weight_rate,
                self.long_fixed_position, self.short_fixed_position,
                record.dingding, config.markets.get("strategy"))

    def set_param(self, key, value):
        msg = None
        if key == "tc":
            self.trading_curb = value
            msg = "trading_curb=%s" % self.trading_curb
            self.save_file()
        if key == "lr":
            self.long_position_weight_rate = int(value)
            msg = "long_position_weight_rate=%s" % self.long_position_weight_rate
            self.save_file()
        if key == "sr":
            self.short_position_weight_rate = int(value)
            msg = "short_position_weight_rate=%s" % self.short_position_weight_rate
            self.save_file()
        if key == "lp":
            self.long_fixed_position = int(value)
            msg = "long_fixed_position=%s" % self.long_fixed_position
            self.save_file()
        if key == "sp":
            self.short_fixed_position = int(value)
            msg = "short_fixed_position=%s" % self.short_fixed_position
            self.save_file()
        if key == "dd":
            if value == "0":
                record.dingding = False
            else:
                record.dingding = True
            msg = "dingding=%s" % record.dingding
        if key == "ac":
            if value == "false":
                self.auto_curb = False
            else:
                self.auto_curb = True
            msg = "auto_curb=%s" % self.auto_curb
        return msg




