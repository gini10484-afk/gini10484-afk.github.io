"""运行：python -m unittest discover -s tests -p "test_*.py"
行情合并：纳指计划的格式不变；标普计划 VOO 成立前按 SPY 折算价格、UPRO 成立前模拟（不联网）。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import update_data as U  # noqa: E402


def days(n, start=0):
    out, d = [], 0
    y, m = 2000, 1
    for i in range(n + start):
        out.append("%04d-%02d-%02d" % (y + i // 336, 1 + (i // 28) % 12, 1 + i % 28))
    return out[start:]


class MergeTest(unittest.TestCase):
    def setUp(self):
        ds = days(1500)
        self.spy = [(d, 100 * 1.0003 ** i, 80 * 1.0003 ** i) for i, d in enumerate(ds)]
        self.voo = [(d, 92 * 1.0003 ** i, 75 * 1.0003 ** i) for i, d in enumerate(ds) if i >= 600]
        self.upro = [(d, 20 * 1.0009 ** i, 20 * 1.0009 ** i) for i, d in enumerate(ds) if i >= 400]

    def test_sp500(self):
        rows, info = U.merge("sp500", {"SPY": self.spy, "VOO": self.voo, "UPRO": self.upro})
        self.assertEqual(len(rows), 1500)
        self.assertEqual(info["firstReal"], self.upro[0][0])
        self.assertEqual(info["firstRealBase"], self.voo[0][0])
        # VOO 成立前：SPY 收盘价 × (VOO/SPY 在 VOO 第一天的比例)
        ratio = self.voo[0][1] / self.spy[600][1]
        self.assertAlmostEqual(rows[10][1], round(self.spy[10][1] * ratio, 4), places=3)
        self.assertAlmostEqual(rows[700][1], round(self.voo[100][1], 4), places=3)
        # 信号用 SPY 复权价；UPRO 前 400 天是模拟的，和真实段接得上
        self.assertAlmostEqual(rows[5][2], round(self.spy[5][2], 6))
        self.assertEqual([r[4] for r in rows[398:402]], [0, 0, 1, 1])
        self.assertAlmostEqual(rows[399][3], rows[400][3], places=4)

    def test_nasdaq_shape(self):
        qqq = [(d, c, a) for d, c, a in self.spy]
        rows, _ = U.merge("nasdaq", {"QQQ": qqq, "TQQQ": self.upro, "SPY": self.spy})
        self.assertEqual(len(rows[0]), 6)
        self.assertEqual(rows[50][1], round(qqq[50][1], 4))  # 纳指那份收盘价就是 QQQ 自己的
        p = U.payload_for("nasdaq", rows, {"firstReal": "x", "firstRealBase": "y"})
        self.assertEqual(p["cols"], ["date", "qqqClose", "qqqAdj", "tqqqAdj", "tqqqReal", "spyAdj"])
        self.assertEqual(p["names"]["lev"], "TQQQ")


if __name__ == "__main__":
    unittest.main()
