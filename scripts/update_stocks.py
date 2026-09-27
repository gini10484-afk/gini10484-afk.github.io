#!/usr/bin/env python3
"""个股筛选：从「纳指100 成分股 + 科技细分代表股」里按强弱打分，挑出最强的 30 只，并标出每只的趋势。

趋势（看日线复权价的均线）：
  上涨趋势：收盘价 > 50 日均线 > 200 日均线，而且 50 日均线比 20 个交易日前高
  下跌趋势：收盘价 < 50 日均线 < 200 日均线，而且 50 日均线比 20 个交易日前低
  其他都算震荡；震荡里收盘价在 50 日均线上方算「偏强」，下方算「偏弱」
评分（0–100，在整个股票池里排百分位后加权）：
  近 3 个月涨幅 35% + 近 1 个月涨幅 25% + 高出 200 日均线多少 20% + 成交热度 20%
  成交热度 = 最近 5 天日均成交额 ÷ 之前 60 天日均，再除以整个股票池的同一个比值

输出 docs/stocks.json（整个股票池都在里面，网页默认只显示前 30）。每个美股交易日跟着行情一起更新。
纳指100 名单每年 12 月调整一次，调整后改下面的 NDX 就行。
"""

import json
import os
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from update_sectors import THEMES  # noqa: E402  科技细分和代表股，跟板块页用同一份

OUT = os.path.join(HERE, "..", "docs", "stocks.json")
UA = {"User-Agent": "Mozilla/5.0 (compatible; qqq-tqqq-dca/1.0; +https://github.com/)"}
CHART = "https://query{n}.finance.yahoo.com/v8/finance/chart/{sym}?range=1y&interval=1d"
TOP = 30

# 纳斯达克100 成分股（维基百科，2026-06-05 的名单；GOOG 和 GOOGL 只留一个）
NDX = """ADBE AMD ABNB ALNY GOOGL AMZN AEP AMGN ADI AAPL AMAT APP ARM ASML ALAB ADSK ADP AXON BKR BKNG AVGO
CDNS CTAS CSCO CCEP CMCSA CEG CPRT CRWV COST CRWD CSX DDOG DXCM FANG DASH EA EXC FAST FER FTNT GEHC GILD HON
IDXX INTC INTU ISRG KDP KLAC KHC LRCX LIN LITE MAR MRVL MELI META MCHP MU MSFT MSTR MDLZ MPWR MNST NBIS NFLX
NVDA NXPI ORLY ODFL PCAR PLTR PANW PAYX PYPL PDD PEP QCOM REGN RKLB ROP ROST SNDK STX SHOP SBUX SNPS TMUS TTWO
TER TSLA TXN TRI VRTX WMT WBD WDC WDAY XEL""".split()


def pool():
    group = {}
    for name, syms in THEMES:
        for s in syms:
            group.setdefault(s, name)
    for s in NDX:
        group.setdefault(s, "纳指100")
    return group


def fetch(symbol):
    """最近一年日线 + 公司简称：(简称, [(日期, 复权价, 收盘价, 成交量)])。"""
    last = None
    for n in (1, 2):
        try:
            req = urllib.request.Request(CHART.format(n=n, sym=symbol), headers=UA)
            with urllib.request.urlopen(req, timeout=30) as r:
                data = json.load(r)
            res = data["chart"]["result"][0]
            meta = res.get("meta") or {}
            q = res["indicators"]["quote"][0]
            adj = (res["indicators"].get("adjclose") or [{}])[0].get("adjclose") or q["close"]
            rows = []
            for i, t in enumerate(res.get("timestamp") or []):
                a, c, v = adj[i], q["close"][i], q["volume"][i]
                if a and c and v is not None and a > 0 and c > 0:
                    rows.append((time.strftime("%Y-%m-%d", time.gmtime(t)), float(a), float(c), float(v)))
            if len(rows) >= 70:
                return (meta.get("shortName") or meta.get("longName") or symbol).strip(" -"), rows
            last = RuntimeError("%s 只拿到 %d 行" % (symbol, len(rows)))
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(1.5)
    raise RuntimeError("拉 %s 失败：%s" % (symbol, last))


def mean(xs):
    return sum(xs) / len(xs)


def trend_of(adj):
    """上涨 / 下跌 / 震荡。数据不到 200 天就只用 50 日均线判断。"""
    n = len(adj)
    if n < 70:
        return "flat", None, None, None
    ma50 = mean(adj[-50:])
    ma50_prev = mean(adj[-70:-20])
    ma200 = mean(adj[-200:]) if n >= 200 else None
    px = adj[-1]
    rising, falling = ma50 > ma50_prev, ma50 < ma50_prev
    if ma200 is None:
        up = px > ma50 and rising
        down = px < ma50 and falling
    else:
        up = px > ma50 > ma200 and rising
        down = px < ma50 < ma200 and falling
    return ("up" if up else "down" if down else "flat"), ma50, ma200, ("strong" if px > ma50 else "weak")


def pct_rank(values):
    """每个值在整组里的百分位（0–1），None 算最低。"""
    idx = sorted(range(len(values)), key=lambda i: (values[i] is not None, values[i] if values[i] is not None else 0))
    out = [0.0] * len(values)
    for r, i in enumerate(idx):
        out[i] = r / (len(values) - 1) if len(values) > 1 else 1.0
    return out


def build(data, group):
    """data: {代码: (简称, [(日期, 复权价, 收盘价, 成交量)])} → 网页要的 JSON。"""
    items = []
    for s, (name, rows) in data.items():
        if len(rows) < 70:
            continue
        adj = [r[1] for r in rows]
        n = len(adj)

        def ret(k):
            return (adj[-1] / adj[-1 - k] - 1) * 100 if n > k else None

        dv = [r[2] * r[3] for r in rows]
        d5, d60 = mean(dv[-5:]), mean(dv[-65:-5]) if n >= 65 else mean(dv[:-5])
        tr, ma50, ma200, bias = trend_of(adj)
        items.append({
            "s": s, "name": name, "group": group.get(s, "纳指100"),
            "price": round(rows[-1][2], 2),
            "w": ret(5), "m": ret(21), "q": ret(63),
            "above200": (adj[-1] / ma200 - 1) * 100 if ma200 else None,
            "off52": (adj[-1] / max(adj[-252:]) - 1) * 100,
            "d5": d5, "d60": d60, "trend": tr, "bias": bias, "date": rows[-1][0],
        })
    if len(items) < 40:
        raise RuntimeError("能用的股票太少（%d 只）" % len(items))
    mkt = sum(x["d5"] for x in items) / sum(x["d60"] for x in items)
    for x in items:
        x["heat"] = x["d5"] / x["d60"] / mkt if x["d60"] > 0 else 1.0
    rq, rm = pct_rank([x["q"] for x in items]), pct_rank([x["m"] for x in items])
    ra, rh = pct_rank([x["above200"] for x in items]), pct_rank([x["heat"] for x in items])
    for i, x in enumerate(items):
        x["score"] = round((0.35 * rq[i] + 0.25 * rm[i] + 0.2 * ra[i] + 0.2 * rh[i]) * 100)
    items.sort(key=lambda x: (-x["score"], -(x["q"] or -999)))

    def rnd(v, k=1):
        return None if v is None else round(v, k)

    stocks = [{
        "rank": i + 1, "s": x["s"], "name": x["name"], "group": x["group"], "price": x["price"],
        "w": rnd(x["w"]), "m": rnd(x["m"]), "q": rnd(x["q"]), "above200": rnd(x["above200"]),
        "off52": rnd(x["off52"]), "heat": round(x["heat"], 2), "trend": x["trend"], "bias": x["bias"], "score": x["score"],
    } for i, x in enumerate(items)]
    counts = {k: sum(1 for x in stocks if x["trend"] == k) for k in ("up", "flat", "down")}
    return {
        "asOf": max(x["date"] for x in items),
        "updated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "source": "Yahoo Finance",
        "top": TOP, "count": len(stocks), "trendCounts": counts,
        "stocks": stocks,
    }


def main():
    group = pool()
    data, bad = {}, []
    for s in sorted(group):
        try:
            data[s] = fetch(s)
        except Exception as e:  # noqa: BLE001
            bad.append(s)
            print("跳过 %s：%s" % (s, e), file=sys.stderr)
        time.sleep(0.25)
    out = build(data, group)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    c = out["trendCounts"]
    print("写好了 %s：%d 只（上涨 %d / 震荡 %d / 下跌 %d），数据到 %s%s" % (
        OUT, out["count"], c["up"], c["flat"], c["down"], out["asOf"], "，跳过 " + ",".join(bad) if bad else ""))


if __name__ == "__main__":
    main()
