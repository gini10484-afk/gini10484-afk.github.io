"""运行：python -m unittest discover -s tests -p "test_*.py"
个股筛选的趋势判断和打分（不联网，用造出来的行情）。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import update_stocks as U  # noqa: E402


def series(prices, vol=1000.0):
    return [("2026-%02d-%02d" % (1 + i // 28, 1 + i % 28), p, p, vol) for i, p in enumerate(prices)]


class StocksTest(unittest.TestCase):
    def test_trend(self):
        up = [100 * 1.004 ** i for i in range(250)]
        down = [100 * 0.996 ** i for i in range(250)]
        flat = [100 + (5 if i % 2 else -5) for i in range(250)]
        self.assertEqual(U.trend_of(up)[0], "up")
        self.assertEqual(U.trend_of(down)[0], "down")
        self.assertEqual(U.trend_of(flat)[0], "flat")
        # 长期下跌后最近反弹到 50 日均线上方：还不算上涨趋势，是「震荡偏强」
        rebound = down[:230] + [down[229] * 1.03 ** k for k in range(1, 21)]
        t = U.trend_of(rebound)
        self.assertEqual((t[0], t[3]), ("flat", "strong"))

    def test_rank_and_score(self):
        data = {}
        for k in range(45):
            g = 1 + (k - 22) * 0.0002  # 每只票的日涨幅不同
            data["S%02d" % k] = ("Stock %d" % k, series([100 * g ** i for i in range(250)]))
        out = U.build(data, {})
        self.assertEqual(out["count"], 45)
        self.assertEqual(out["stocks"][0]["s"], "S44")  # 涨得最多的排第一
        self.assertEqual(out["stocks"][-1]["s"], "S00")
        self.assertEqual([x["rank"] for x in out["stocks"]], list(range(1, 46)))
        self.assertTrue(all(0 <= x["score"] <= 100 for x in out["stocks"]))
        self.assertEqual(sum(out["trendCounts"].values()), 45)

    def test_pool_has_ndx_and_themes(self):
        g = U.pool()
        self.assertEqual(g["MU"], "存储")
        self.assertEqual(g["COHR"], "光模块 / 光通信")
        self.assertEqual(g["TSLA"], "纳指100")
        self.assertNotIn("GOOG", g)


if __name__ == "__main__":
    unittest.main()
