import pandas as pd
from utils import fileutil
import json
from api.model.const import KILINE_PERIOD
import matplotlib as mpl
from matplotlib import pyplot as plt
# 图形参数控制
import pylab as pl
from datetime import datetime
from sklearn import svm
mpl.use('TkAgg')
pd.set_option('expand_frame_repr', False)  # 当列太多时不换行
pd.set_option('display.max_rows', 1000)  # 最多显示行数.
pd.set_option('display.float_format', lambda x:'%.2f' % x)  # 设置不用科学计数法，保留两位小数.


class NodePoint:
    def __init__(self, x, y, d):
        self.x = x
        self.y = y
        self.d = d
        self.l = 0


class MatPlot:

    @classmethod
    def get_data(cls, profit, profit_period, size=500):
        pd_data = []
        lines = fileutil.load_file("../../logs/eth-config.out1")
        columns_title = {"Date": 0, "close": 1, "cur_lead_dir": 2, "cur_price_dir": 3, "price_base": 4, "cur_cb_dir": 5,
                         "cb_dir": 6, "cur_delay_dir": 7}
        for line in lines:
            if "IchimokuStrategy:" in line:
                strs = line.split("IchimokuStrategy:")
                date_str = strs[0].split("I [")[1].split(",")[0].rstrip().lstrip()
                json_str = strs[1].rstrip().lstrip().replace("'", "\"")
                append_data = {"Date": date_str}
                data = json.loads(json_str)
                append_data["close"] = data["close"]
                append_data["cur_lead_dir"] = data["cur_lead_dir"]
                append_data["cur_price_dir"] = data["cur_price_dir"]
                append_data["price_base"] = data["price_base"]
                append_data["cur_cb_dir"] = data["cur_cb_dir"]
                append_data["cb_dir"] = data["cb_dir"]
                append_data["cur_delay_dir"] = data["cur_delay_dir"]
                pd_data.append(append_data)
        df = pd.DataFrame(pd_data, columns=columns_title)
        df.set_index(["Date"], inplace=True)
        cls.handle_data(df, profit, profit_period, size)

    @classmethod
    def handle_data(cls, df, profit, profit_period, size):
        points = []
        for i in range(1, size - 1):
            if df.iloc[i - 1]["close"] < df.iloc[i]["close"] and df.iloc[i]["close"] >= df.iloc[i + 1]["close"]:
                points.append(NodePoint(i, df.iloc[i]["close"], 1))
            if df.iloc[i - 1]["close"] > df.iloc[i]["close"] and df.iloc[i]["close"] <= df.iloc[i + 1]["close"]:
                points.append(NodePoint(i, df.iloc[i]["close"], -1))

        long_new_points = cls.calculate_points(points, profit, profit_period, 1)
        short_new_points = cls.calculate_points(points, profit, profit_period, -1)
        svm_model = cls.svn_train(df, long_new_points, size)
        cls.svn_predict(svm_model, df, long_new_points, size)
        buy_x, buy_y, sell_x, sell_y = cls.get_points(long_new_points)
        cls.show(df, buy_x, buy_y, sell_x, sell_y)

    @classmethod
    def svn_train(cls, df, long_new_points, size):
        x_train = []  # 特征
        y_train = []  # 标记
        p_index = 0
        p1 = long_new_points[p_index]
        p2 = long_new_points[p_index + 1]
        for i in range(0, size):
            features = []
            cur_bar = df.iloc[i]
            features.append(cur_bar["cur_lead_dir"])
            features.append(cur_bar["cur_price_dir"])
            features.append(cur_bar["price_base"])
            features.append(cur_bar["cur_cb_dir"])
            features.append(cur_bar["cb_dir"])
            features.append(cur_bar["cur_delay_dir"])
            if i > p2.x and p_index + 2 < len(long_new_points):
                p_index = p_index + 2
                p1 = long_new_points[p_index]
                p2 = long_new_points[p_index + 1]
            if p_index + 2 > len(long_new_points):
                break
            label = False
            if p1.x <= i < p2.x:
                label = True
            x_train.append(features)
            y_train.append(label)
        svm_module = svm.SVC()
        print(y_train)
        svm_module.fit(x_train, y_train)
        return svm_module

    @classmethod
    def svn_train(cls, df, long_new_points, size):
        x_train = []  # 特征
        y_train = []  # 标记
        p_index = 0
        p1 = long_new_points[p_index]
        for i in range(0, size):
            features = []
            cur_bar = df.iloc[i]
            features.append(cur_bar["cur_lead_dir"])
            features.append(cur_bar["cur_price_dir"])
            features.append(cur_bar["price_base"])
            features.append(cur_bar["cur_cb_dir"])
            features.append(cur_bar["cb_dir"])
            features.append(cur_bar["cur_delay_dir"])
            label = False
            is_break = False
            if p1.x == i:
                label = True
                p_index = p_index + 1
                if p_index >= len(long_new_points):
                    is_break = True
                else:
                    p1 = long_new_points[p_index]
            x_train.append(features)
            y_train.append(label)
            if is_break:
                break

        svm_module = svm.SVC()
        print(y_train)
        svm_module.fit(x_train, y_train)
        return svm_module

    @classmethod
    def svn_predict(cls, svm_module, df, long_new_points, size):
        last_flag = None
        for i in range(size, len(df)):
            x = []  # 特征
            features = []
            cur_bar = df.iloc[i]
            features.append(cur_bar["cur_lead_dir"])
            features.append(cur_bar["cur_price_dir"])
            features.append(cur_bar["price_base"])
            features.append(cur_bar["cur_cb_dir"])
            features.append(cur_bar["cb_dir"])
            features.append(cur_bar["cur_delay_dir"])
            x.append(features)
            flag = svm_module.predict(x)
            if bool(flag):
                if last_flag is None:
                    last_flag = True
                else:
                    if last_flag is False and long_new_points[-1].d == -1:
                        long_new_points.append(NodePoint(i, cur_bar["close"], 1))
                    last_flag = True
            elif bool(flag) is False:
                if last_flag is None:
                    last_flag = False
                else:
                    if last_flag is True and long_new_points[-1].d == 1:
                        long_new_points.append(NodePoint(i, cur_bar["close"], -1))
                    last_flag = False
            else:
                last_flag = None

    @classmethod
    def calculate_points(cls, points, profit, profit_period, dir):
        new_points = []
        i = 0
        l = len(points)
        while i < l:
            p1 = points[i]
            add_point = False
            tmp_p1 = p1
            for j in range(1, profit_period):
                if i + j > l - 1:
                    break
                p2 = points[i + j]
                if p1.d == p2.d:
                    if dir == 1 and p1.d == -1 and p1.y > p2.y:
                        tmp_p1 = p2
                    if dir == -1 and p1.d == 1 and p1.y < p2.y:
                        tmp_p1 = p2
                else:
                    if dir == 1 and p1.d == -1 and (p2.y - tmp_p1.y)/tmp_p1.y >= profit:
                        new_points.append(tmp_p1)
                        new_points.append(p2)
                        add_point = True
                        i = i + j
                        break
                    if dir == -1 and p1.d == 1 and (tmp_p1.y - p2.y)/tmp_p1.y >= profit:
                        new_points.append(tmp_p1)
                        new_points.append(p2)
                        add_point = True
                        i = i + j
                        break

            if not add_point:
                i = i + 1
        return new_points

    @classmethod
    def get_points(cls, points):
        buy_x = []
        buy_y = []
        sell_x = []
        sell_y = []
        for i in range(0, len(points)):
            p = points[i]
            if p.d == 1:
                sell_x.append(p.x)
                sell_y.append(p.y)
            if p.d == -1:
                buy_x.append(p.x)
                buy_y.append(p.y)
        return buy_x, buy_y, sell_x, sell_y

    @classmethod
    def show(cls, df, buy_x, buy_y, sell_x, sell_y):
        price_values = df["close"]

        fig, ax = plt.subplots(1, 1)
        plt.rcParams['font.sans-serif'] = ['SimHei']
        plt.rcParams['axes.unicode_minus'] = False
        # 调整子图的间距，hspace表示高(height)方向的间距
        plt.subplots_adjust(hspace=.1)
        # 设置第一子图的y轴信息及标题
        ax.set_ylabel('Close price in ￥')
        ax.set_title('A_Stock %s factor Indicator' % ("test"))
        price_values.plot(ax=ax, color='g', lw=1., legend=True, use_index=False)

        plt.scatter(buy_x, buy_y, s=50, color='r', marker='^', alpha=0.5)
        plt.scatter(sell_x, sell_y, s=50, color='b', marker='^', alpha=0.5)

        # 设置间隔，以便图形横坐标可以正常显示（否则数据多了x轴会重叠）
        scale = 100
        interval = scale // 20
        # 设置x轴参数，应用间隔设置
        # 时间序列转换，(否则日期默认会显示时分秒数据00:00:00)
        # x轴标签旋转便于显示
        pl.xticks([i for i in range(1, scale + 1, interval)],
                  [datetime.strftime(i, format='%Y-%m-%d') for i in
                   pd.date_range(df.index[0], df.index[-1], freq='%dd' % (interval))],
                  rotation=45)
        plt.show()


if __name__ == "__main__":
    c = 1000
    profit = 0.001
    profit_period = 10
    MatPlot.get_data(profit, profit_period, c)
