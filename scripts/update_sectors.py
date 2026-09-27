#!/usr/bin/env python3
"""板块热度：美股 11 个行业 + 科技里的细分（存储、光模块、AI 芯片……）最近往哪儿走。

真实的「资金流向」数据要付费，这里用两样公开数据估算：
  - 涨跌：近 1 周 / 1 个月 / 3 个月（复权价）
  - 成交热度：最近 5 个交易日的日均成交额 ÷ 之前 60 个交易日的日均成交额，
    再除以同一组（科技细分 / 11 个行业）合起来的同一个比值，扣掉整个市场这周成交多 / 少的影响。
    大于 1 = 这周比同组平均更受关注，钱在往里挤；小于 1 = 被冷落。
细分板块用等权平均（每只股票算一票），成交热度用合计成交额算。

输出 docs/sectors.json，网页「板块」页读它。每个美股交易日跟着行情一起更新。
"""

import json
import os
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "docs", "sectors.json")
UA = {"User-Agent": "Mozilla/5.0 (compatible; qqq-tqqq-dca/1.0; +https://github.com/)"}
CHART = "https://query{n}.finance.yahoo.com/v8/finance/chart/{sym}?range=6mo&interval=1d"

# 科技细分：名字 → 代表股票（都是美股上市、成交活跃的）
THEMES = [
    ("AI 芯片", ["NVDA", "AMD", "AVGO", "MRVL"]),
    ("存储", ["MU", "WDC", "STX", "SNDK"]),
    ("光模块 / 光通信", ["COHR", "LITE", "FN", "AAOI", "CIEN"]),
    ("网络 / 高速互联", ["ANET", "CSCO", "CRDO", "ALAB"]),
    ("半导体设备", ["AMAT", "LRCX", "KLAC", "ASML"]),
    ("晶圆代工", ["TSM", "INTC", "GFS"]),
    ("AI 服务器", ["SMCI", "DELL", "HPE"]),
    ("数据中心电力", ["VRT", "ETN", "GEV", "CEG"]),
    ("软件", ["MSFT", "ORCL", "CRM", "NOW", "ADBE"]),
    ("网络安全", ["CRWD", "PANW", "ZS", "FTNT"]),
    ("互联网巨头", ["GOOGL", "META", "AMZN"]),
    ("消费电子", ["AAPL"]),
]

# 11 个行业（标普的 Select Sector SPDR ETF）
SECTORS = [
    ("XLK", "科技"), ("XLC", "通信"), ("XLY", "可选消费"), ("XLF", "金融"),
    ("XLI", "工业"), ("XLV", "医疗"), ("XLE", "能源"), ("XLB", "材料"),
    ("XLP", "必需消费"), ("XLU", "公用事业"), ("XLRE", "房地产"),
]
BENCH = ["SPY", "QQQ"]


def fetch(symbol):
    """最近半年的日线：[(日期, 复权价, 收盘价, 成交量)]。query1 不行换 query2，再不行用 yfinance。"""
    last = None
    for n in (1, 2):
        try:
            req = urllib.request.Request(CHART.format(n=n, sym=symbol), headers=UA)
            with urllib.request.urlopen(req, timeout=30) as r:
                data = json.load(r)
            res = data["chart"]["result"][0]
            q = res["indicators"]["quote"][0]
            adj = (res["indicators"].get("adjclose") or [{}])[0].get("adjclose") or q["close"]
            rows = []
            for i, t in enumerate(res.get("timestamp") or []):
                a, c, v = adj[i], q["close"][i], q["volume"][i]
                if a and c and v is not None and a > 0 and c > 0:
                    rows.append((time.strftime("%Y-%m-%d", time.gmtime(t)), float(a), float(c), float(v)))
            if len(rows) >= 70:
                return rows
            last = RuntimeError("%s 只拿到 %d 行" % (symbol, len(rows)))
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(1.5)
    try:
        import yfinance

        df = yfinance.Ticker(symbol).history(period="6mo", auto_adjust=False)
        rows = [(i.strftime("%Y-%m-%d"), float(r["Adj Close"]), float(r["Close"]), float(r["Volume"]))
                for i, r in df.iterrows() if r["Close"] > 0]
        if len(rows) >= 70:
            return rows
    except Exception as e:  # noqa: BLE001
        last = e
    raise RuntimeError("拉 %s 失败：%s" % (symbol, last))


def stats(rows):
    """一只票的涨跌和成交额。"""
    n = len(rows)
    last = rows[-1][1]

    def ret(k):
        return (last / rows[n - 1 - k][1] - 1) * 100 if n > k else None

    dv = [r[2] * r[3] for r in rows]  # 成交额 = 收盘价 × 成交量
    d5 = sum(dv[-5:]) / 5
    base = dv[-65:-5]
    d60 = sum(base) / len(base) if base else d5
    return {"w": ret(5), "m": ret(21), "q": ret(63), "d5": d5, "d60": d60, "date": rows[-1][0]}


def avg(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def rnd(x, k=1):
    return None if x is None else round(x, k)


def build(rows_by_symbol):
    """rows_by_symbol: {代码: [(日期, 复权价, 收盘价, 成交量), ...]} → 网页要的 JSON。拉不到的票直接跳过。"""
    st = {s: stats(r) for s, r in rows_by_symbol.items() if r and len(r) >= 70}
    stock_syms = [s for _, syms in THEMES for s in syms if s in st]
    if len(stock_syms) < 20:
        raise RuntimeError("能用的股票太少（%d 只）" % len(stock_syms))
    # 这一组这周整体比平常热多少：用所有细分股票合起来算，下面每个细分都跟它比
    mkt = sum(st[s]["d5"] for s in stock_syms) / sum(st[s]["d60"] for s in stock_syms)

    themes = []
    for name, syms in THEMES:
        ok = [s for s in syms if s in st]
        if not ok:
            continue
        heat = sum(st[s]["d5"] for s in ok) / sum(st[s]["d60"] for s in ok)
        themes.append({
            "name": name,
            "w": rnd(avg(st[s]["w"] for s in ok)),
            "m": rnd(avg(st[s]["m"] for s in ok)),
            "q": rnd(avg(st[s]["q"] for s in ok)),
            "heat": round(heat / mkt, 2),
            "dv": round(sum(st[s]["d5"] for s in ok) / 1e9, 2),  # 最近 5 天日均成交额（十亿美元）
            "stocks": [{
                "s": s, "w": rnd(st[s]["w"]), "m": rnd(st[s]["m"]), "q": rnd(st[s]["q"]),
                "heat": round(st[s]["d5"] / st[s]["d60"] / mkt, 2),
            } for s in ok],
        })

    etf_syms = [s for s, _ in SECTORS if s in st]
    etf_mkt = (sum(st[s]["d5"] for s in etf_syms) / sum(st[s]["d60"] for s in etf_syms)) if etf_syms else 1
    sectors = [{
        "s": s, "name": nm, "w": rnd(st[s]["w"]), "m": rnd(st[s]["m"]), "q": rnd(st[s]["q"]),
        "heat": round(st[s]["d5"] / st[s]["d60"] / etf_mkt, 2),
    } for s, nm in SECTORS if s in st]
    bench = [{"s": s, "w": rnd(st[s]["w"]), "m": rnd(st[s]["m"]), "q": rnd(st[s]["q"])} for s in BENCH if s in st]

    as_of = max(st[s]["date"] for s in stock_syms)
    return {
        "asOf": as_of,
        "updated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "source": "Yahoo Finance",
        "note": "涨跌用复权价；热度 = 最近 5 天日均成交额 ÷ 之前 60 天日均，再除以同组合计的同一个比值",
        "themes": themes,
        "sectors": sectors,
        "bench": bench,
    }


def main():
    syms = sorted({s for _, ss in THEMES for s in ss} | {s for s, _ in SECTORS} | set(BENCH))
    got, bad = {}, []
    for s in syms:
        try:
            got[s] = fetch(s)
        except Exception as e:  # noqa: BLE001
            bad.append(s)
            print("跳过 %s：%s" % (s, e), file=sys.stderr)
        time.sleep(0.3)
    out = build(got)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    print("写好了 %s：%d 个细分、%d 个行业，数据到 %s%s" % (
        OUT, len(out["themes"]), len(out["sectors"]), out["asOf"], "，跳过 " + ",".join(bad) if bad else ""))


if __name__ == "__main__":
    main()
