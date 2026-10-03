#!/usr/bin/env python3
"""拉两套定投计划的历史行情，检查一遍，写进 docs/。

纳指100 计划 → docs/data.json：QQQ（平时买）+ TQQQ（大跌才买，3 倍）+ SPY（对照）
标普500 计划 → docs/data-sp500.json：VOO（平时买）+ UPRO（大跌才买，3 倍）
    信号和回测用 SPY 的复权价（1993 年就有，比 VOO 早 17 年；两者跟踪同一个指数），
    页面上显示和记账用 VOO 的真实收盘价（VOO 2010-09 才有，之前按 SPY 等比折算）。

杠杆 ETF 成立前的部分用「指数 ETF 日涨跌 ×3 + 漂移」模拟：
    漂移（%/年）= A + B × 当年联邦基金利率(%)
A、B 用成立以后的真实数据拟合（每年「杠杆 ETF 实际涨跌 − 3×指数涨跌」对当年利率加权回归，剔除 2020 年）。
    TQQQ（2010-02 起）：A = −1.814，B = −2.258，16 年半复利误差约 4.5%
    UPRO（2009-06 起）：A = −1.636，B = −2.281，17 年复利误差约 0.1%
模拟出来的那段标成 real=0，网页会提示。

每一行是：[日期, 平时买的那只的收盘价, 指数复权价, 杠杆复权价, 杠杆是否真实(1/0), SPY 复权价]
纳指计划没变；标普计划第 2、3、6 列分别是 VOO 收盘价、SPY 复权价、SPY 复权价。
"""

import json
import os
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
DOCS = os.path.join(HERE, "..", "docs")
OUT = os.path.join(DOCS, "data.json")
OUT_SP = os.path.join(DOCS, "data-sp500.json")

UA = {"User-Agent": "Mozilla/5.0 (compatible; qqq-tqqq-dca/1.0; +https://github.com/)"}
CHART = "https://query{n}.finance.yahoo.com/v8/finance/chart/{sym}?period1=0&period2=9999999999&interval=1d&events=div%2Csplit"

# 美国联邦基金利率年平均值（%）。模拟杠杆 ETF 的成本要用。以后补新年份不影响已有数据。
FED_FUNDS = {
    1993: 3.02, 1994: 4.20, 1995: 5.84, 1996: 5.30, 1997: 5.46, 1998: 5.35,
    1999: 4.97, 2000: 6.24, 2001: 3.89, 2002: 1.67, 2003: 1.13, 2004: 1.35,
    2005: 3.22, 2006: 4.97, 2007: 5.02, 2008: 1.92, 2009: 0.16, 2010: 0.18,
}
# 纳指计划的 TQQQ 漂移系数（名字保持不变，data.json 里也照旧写这两个）
DRIFT_A = -1.814
DRIFT_B = -2.258
# 标普计划的 UPRO 漂移系数
UPRO_DRIFT_A = -1.636
UPRO_DRIFT_B = -2.281
TRADING_DAYS = 252

PLANS = {
    "nasdaq": {
        "out": OUT, "index": "QQQ", "base": "QQQ", "lev": "TQQQ",
        "drift": (DRIFT_A, DRIFT_B),
        "names": {"base": "QQQ", "lev": "TQQQ", "index": "纳指100", "short": "纳指"},
    },
    "sp500": {
        "out": OUT_SP, "index": "SPY", "base": "VOO", "lev": "UPRO",
        "drift": (UPRO_DRIFT_A, UPRO_DRIFT_B),
        "names": {"base": "VOO", "lev": "UPRO", "index": "标普500", "short": "标普"},
    },
}


def fetch_yfinance(symbol):
    """备用接口：Yahoo 的直连被挡时用 yfinance（它会自己处理 cookie）。"""
    import yfinance  # 只有走到这一步才需要这个包

    df = yfinance.Ticker(symbol).history(period="max", auto_adjust=False)
    if df is None or df.empty:
        raise RuntimeError("yfinance 没拿到 %s 的数据" % symbol)
    out = []
    for idx, row in df.iterrows():
        c, a = row.get("Close"), row.get("Adj Close", row.get("Close"))
        if c is None or a is None or not (c > 0) or not (a > 0):
            continue
        out.append((idx.strftime("%Y-%m-%d"), float(c), float(a)))
    return out


def parse_chart(data):
    """Yahoo chart 接口的返回 → [(日期, 收盘价, 复权价)]。"""
    res = (data.get("chart") or {}).get("result") or []
    if not res:
        raise RuntimeError("Yahoo 没返回数据：%s" % str(data)[:200])
    res = res[0]
    ts = res.get("timestamp") or []
    quote = (res.get("indicators") or {}).get("quote") or [{}]
    adjs = (res.get("indicators") or {}).get("adjclose") or [{}]
    close = quote[0].get("close") or []
    adj = adjs[0].get("adjclose") or close
    out = []
    for i, t in enumerate(ts):
        c = close[i] if i < len(close) else None
        a = adj[i] if i < len(adj) else None
        if c is None or a is None or not (c > 0) or not (a > 0):
            continue
        out.append((time.strftime("%Y-%m-%d", time.gmtime(t)), float(c), float(a)))
    return out


def fetch(symbol):
    """从 Yahoo 拉一只票的完整历史；query1 不行就换 query2，都不行再用 yfinance。"""
    last = None
    for n in (1, 2):
        url = CHART.format(n=n, sym=symbol)
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=45) as r:
                data = json.load(r)
            out = parse_chart(data)
        except (urllib.error.URLError, TimeoutError, ValueError, RuntimeError) as e:
            last = e
            time.sleep(2)
            continue
        if len(out) > 100:
            return out
        last = RuntimeError("%s 只拿到 %d 行" % (symbol, len(out)))
    try:
        rows = fetch_yfinance(symbol)
        if len(rows) > 100:
            print("直连失败（%s），改用 yfinance 拿到 %s 的 %d 行" % (last, symbol, len(rows)))
            return rows
    except Exception as e:  # noqa: BLE001
        last = e
    raise RuntimeError("拉 %s 失败：%s" % (symbol, last))


def sanity(rows, name, levered=False):
    """基本检查：日期递增、没有重复、单日涨跌不离谱。"""
    if len(rows) < 100:
        raise RuntimeError("%s 行数太少：%d" % (name, len(rows)))
    limit = 0.75 if levered or name == "TQQQ" else 0.25  # 3 倍杠杆单日波动更大
    for i in range(1, len(rows)):
        if rows[i][0] <= rows[i - 1][0]:
            raise RuntimeError("%s 日期没有递增：%s 之后是 %s" % (name, rows[i - 1][0], rows[i][0]))
        prev, cur = rows[i - 1][2], rows[i][2]
        if prev > 0:
            chg = abs(cur / prev - 1)
            if chg > limit:
                raise RuntimeError("%s %s 单日变动 %.1f%%，看起来不对" % (name, rows[i][0], chg * 100))
    return True


def simulate_lev(index_rows, real_by_date, first_real_date, drift_a, drift_b):
    """杠杆 ETF 成立以前，用 3×指数日涨跌 + 漂移模拟出来。"""
    out = []
    level = 1.0
    prev_adj = None
    last_ff = FED_FUNDS[max(FED_FUNDS)]
    for day, _close, adj in index_rows:
        if day >= first_real_date:
            break
        if prev_adj is None:
            out.append((day, level, 0))
            prev_adj = adj
            continue
        ff = FED_FUNDS.get(int(day[:4]), last_ff)
        drift = (drift_a + drift_b * ff) / 100.0
        level *= 1 + 3 * (adj / prev_adj - 1) + drift / TRADING_DAYS
        prev_adj = adj
        out.append((day, level, 0))
    # 让模拟段和真实段接得上：整段等比缩放，使模拟段最后一天等于真实价格的第一天
    if out and first_real_date in real_by_date and out[-1][1] > 0:
        scale = real_by_date[first_real_date] / out[-1][1]
        out = [(d, v * scale, 0) for d, v, _ in out]
    return out


def simulate_tqqq(qqq_rows, real_by_date, first_real_date):
    """老名字，保留给以前的调用方。"""
    return simulate_lev(qqq_rows, real_by_date, first_real_date, DRIFT_A, DRIFT_B)


def merge(plan, got):
    """got: {代码: [(日期, 收盘价, 复权价)]} → (rows, 额外信息)。不联网，方便测试。"""
    p = PLANS[plan]
    index, lev = got[p["index"]], got[p["lev"]]
    spy = got.get("SPY") or index
    base = got.get(p["base"]) or index
    l_by_date = {d: a for d, _c, a in lev}
    s_by_date = {d: a for d, _c, a in spy}
    b_close = {d: c for d, c, _a in base}
    first_real = lev[0][0]
    sim = {d: v for d, v, _ in simulate_lev(index, l_by_date, first_real, *p["drift"])}

    # 平时买的那只（VOO）成立前没有收盘价，用指数 ETF（SPY）的收盘价等比折算，只影响显示
    first_base = base[0][0]
    i_close = {d: c for d, c, _a in index}
    ratio = (b_close[first_base] / i_close[first_base]) if first_base in i_close and i_close[first_base] > 0 else 1.0

    rows, missing_spy = [], 0
    for day, close, adj in index:
        if day in l_by_date:
            t, real = l_by_date[day], 1
        elif day in sim:
            t, real = sim[day], 0
        else:
            continue  # 两边都没有的日子（极少）直接跳过，保证几条线对齐
        sp = s_by_date.get(day)
        if sp is None:
            missing_spy += 1
            continue
        c = b_close.get(day)
        if c is None:
            if day >= first_base:
                continue  # VOO 已经成立但这天缺数据：跳过，别用折算价混进去
            c = close * ratio
        rows.append([day, round(c, 4), round(adj, 6), round(t, 6), real, round(sp, 6)])
    if len(rows) < 1000:
        raise RuntimeError("%s 合并后只剩 %d 行，放弃这次更新" % (plan, len(rows)))
    if missing_spy > 5:
        raise RuntimeError("%s 有 %d 个交易日拿不到 SPY，放弃这次更新" % (plan, missing_spy))
    return rows, {"firstReal": first_real, "firstRealBase": first_base}


def payload_for(plan, rows, info):
    p = PLANS[plan]
    a, b = p["drift"]
    out = {
        "plan": plan,
        "names": p["names"],
        "symbol": "%s+%s+SPY" % (p["base"], p["lev"]) if plan == "nasdaq" else "VOO+UPRO（信号用 SPY）",
        "source": "Yahoo Finance",
        "updated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "firstRealTqqq": info["firstReal"],  # 字段名沿用：杠杆 ETF 真实数据开始的那天
        "fedFunds": FED_FUNDS,
        "drift": {"a": a, "b": b},
        "cols": ["date", "qqqClose", "qqqAdj", "tqqqAdj", "tqqqReal", "spyAdj"] if plan == "nasdaq"
        else ["date", "vooClose", "spyAdj", "uproAdj", "uproReal", "spyAdj"],
        "rows": rows,
    }
    if plan != "nasdaq":
        out["firstRealBase"] = info["firstRealBase"]
    return out


def write(path, payload):
    # 和旧数据比一比，行数骤减就不覆盖
    rows = payload["rows"]
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                old = json.load(f)
            if len(old.get("rows", [])) > len(rows) + 5:
                raise RuntimeError("新数据 %d 行比旧数据 %d 行少太多" % (len(rows), len(old["rows"])))
        except (ValueError, OSError):
            pass
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, separators=(",", ":"), ensure_ascii=False)


def build(plan="nasdaq", fetcher=fetch):
    p = PLANS[plan]
    got = {}
    for sym in dict.fromkeys([p["index"], p["lev"], p["base"], "SPY"]):
        got[sym] = fetcher(sym)
        sanity(got[sym], sym, levered=(sym == p["lev"]))
    rows, info = merge(plan, got)
    payload = payload_for(plan, rows, info)
    write(p["out"], payload)
    print("写好了 %s：%d 行，%s → %s，真实 %s 从 %s 开始"
          % (p["out"], len(rows), rows[0][0], rows[-1][0], p["lev"], info["firstReal"]))
    return payload


def main():
    try:
        build("nasdaq")
    except Exception as e:  # noqa: BLE001 —— 失败就退出，工作流会保留旧数据
        print("更新失败：%s" % e, file=sys.stderr)
        sys.exit(1)
    try:
        build("sp500")
    except Exception as e:  # noqa: BLE001 —— 标普这份失败不影响纳指那份
        print("::warning::标普500 数据这次没更新成功：%s" % e)


if __name__ == "__main__":
    main()
