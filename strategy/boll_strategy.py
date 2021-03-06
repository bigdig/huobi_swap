import talib
from utils.tools import round_to
from strategy.base_strategy import BaseStrategy
import copy
from utils import logger


class BollStrategy(BaseStrategy):
    """
    布林策略
    """
    def __init__(self):
        self.time_period = 40
        self.nbdev_up = 2.5
        self.nbdev_dn = 2.5
        self.long = False
        self.short = False
        super(BollStrategy, self).__init__()

    def strategy_handle(self):
        klines = copy.copy(self.klines)
        df = klines.get("market."+self.mark_symbol+".kline." + self.period)
        print("calculate_signal")
        df['boll_up'], df['boll_mid'], df['boll_dn'] = talib.BBANDS(df['close'],
                                                                    timeperiod=self.time_period,
                                                                    nbdevup=self.nbdev_up,
                                                                    nbdevdn=self.nbdev_dn)
        current_bar = df.iloc[-1]  # 最新的K线 Bar.
        boll_up = round_to(float(current_bar['boll_up']), self.price_tick)
        boll_dn = round_to(float(current_bar['boll_dn']), self.price_tick)
        boll_mid = round_to(float(current_bar['boll_mid']), self.price_tick)
        if current_bar["close"] < boll_dn:
            self.short_status = 1
            self.short_trade_size = self.min_volume
            if not self.short:
                self.short = True
                logger.info("开空信号 ", current_bar["close"], caller=self)

        elif current_bar["close"] > boll_up:
            self.long_status = 1
            self.long_trade_size = self.min_volume
            if not self.long:
                self.long = True
                logger.info("开多信号 ", current_bar["close"], caller=self)
        elif current_bar["close"] > boll_mid:
            self.short_status = -1
            if self.short:
                self.short = False
                logger.info("平空信号 ", current_bar["close"], caller=self)
        elif current_bar["close"] < boll_mid:
            self.long_status = -1
            if self.long:
                self.long = False
                logger.info("平多信号 ", current_bar["close"], caller=self)







