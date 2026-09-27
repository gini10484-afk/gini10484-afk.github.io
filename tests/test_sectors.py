"""运行：python -m unittest discover -s tests -p "test_*.py"
板块热度的计算（不联网，用造出来的行情）。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import update_sectors as U  # noqa: E402


def rows(n=100, start=100.0, step=0.0, vol=1000.0, hot_last5=1.0):
    """n 天行情：价格每天涨 step（比例），最后 5 天成交量乘 hot_last5。"""
    out, p = [], start
    for i in range(n):
        p *= 1 + step
        v = vol * (hot_last5 if i >= n - 5 else 1)
        out.append(("2026-%02d-%02d" % (1 + i // 28, 1 + i % 28), p, p, v))
    return out


class SectorsTest(unittest.TestCase):
    def test_returns_and_heat(self):
        data = {s: rows() for _, ss in U.THEMES for s in ss}
        data["MU"] = rows(step=0.01, hot_last5=3.0)  # 存储里一只票每天涨 1%，这周成交放大 3 倍
        out = U.build(data)
        mem = next(t for t in out["themes"] if t["name"] == "存储")
        mu = next(k for k in mem["stocks"] if k["s"] == "MU")
        self.assertAlmostEqual(mu["w"], (1.01 ** 5 - 1) * 100, places=1)
        self.assertGreater(mu["heat"], 2)
        # 等权平均：存储 4 只票里只有 MU 在涨
        self.assertAlmostEqual(mem["w"], mu["w"] / 4, places=1)
        # 存储整体热度高于其他没变化的细分
        other = next(t for t in out["themes"] if t["name"] == "软件")
        self.assertGreater(mem["heat"], other["heat"])

    def test_skips_missing_symbols(self):
        data = {s: rows() for _, ss in U.THEMES for s in ss}
        del data["SNDK"]
        out = U.build(data)
        mem = next(t for t in out["themes"] if t["name"] == "存储")
        self.assertEqual([k["s"] for k in mem["stocks"]], ["MU", "WDC", "STX"])
        self.assertEqual(out["sectors"], [])  # 没给行业 ETF 就是空的，不报错

    def test_too_few_symbols_fails(self):
        with self.assertRaises(RuntimeError):
            U.build({"NVDA": rows()})


if __name__ == "__main__":
    unittest.main()
