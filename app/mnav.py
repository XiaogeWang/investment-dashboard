"""Strategy (MSTR) 的 mNAV：股票市值相对所持 BTC 价值的溢价倍数。

两种口径：

- 市值口径：市值 / BTC 净值。2020-08 开始买币起每天都有，看长期走势用这个。
- EV 口径（Strategy 官方）：(市值 + 债务 + 优先股 − 现金储备) / BTC 净值。
  Strategy 从 2024-12-31 才开始公布，但它把债务和优先股算了进去，
  在 2025 年大量发行优先股之后，比市值口径更能反映真实溢价。

由 EV 口径还能反推出三条派生序列（决策页用）：

- 净负债 = EV 口径 × BTC 净值 − 市值，即债务 + 优先股 − 现金
- 净溢价 = 市值 / (BTC 净值 − 净负债)：普通股相对「扣掉排在前面的负债之后、归普通股的 BTC」的倍数
- 杠杆   = BTC 净值 / (BTC 净值 − 净负债)：BTC 涨跌 1%，归普通股的净资产涨跌多少。
  和接口里的 amplification（2026-06 起才有）口径一致，自己算是为了历史更长

账面口径另算一份：接口给了 (债务 + 优先股) / BTC 净值 和 优先股 / BTC 净值 两个百分比，
乘回 BTC 净值就是债务、优先股的面值（2026-10 核对过：债务 = 6 笔可转债本金之和，优先股 = 官网 KPI）。

- 斩杀线 = (债务 + 优先股 − 现金) / 持币量：BTC 跌到这个价，持币价值刚好等于排在普通股前面的负债。
  有现金储备数据（2025-12 起）时用账面口径，之前退回到 EV 反推的净负债

数据来自 Strategy 官网图表页用的公开接口（STRATEGY_TIMESERIES_URL），不是文档化的 API。
金额单位是「百万美元」，原样保存。
"""

import logging
from datetime import datetime, timezone

from . import db
from .config import STRATEGY_TIMESERIES_URL
from .macro import _get

log = logging.getLogger("mnav")


def fetch() -> list[dict]:
    resp = _get(STRATEGY_TIMESERIES_URL, {})
    series = next((x for x in resp.json() if x.get("ticker") == "MSTR"), None)
    if not series or not series.get("values"):
        raise RuntimeError("timeSeries 接口里没有 MSTR 的数据")

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    rows = []
    for r in series["values"]:
        mc, nav, btc = r.get("marketCap"), r.get("btcNav"), r.get("btcHoldings")
        if not mc or not nav or not btc:
            continue
        rows.append({
            "date": r["date"][:10], "price": r.get("price"),
            "market_cap": float(mc), "btc_nav": float(nav), "btc_holdings": float(btc),
            "mnav_ev": r.get("mNavEntVal"), "mnav": r.get("mNav"),
            # 以下几项 2025 年起才陆续有：每股 BTC（聪，官方按稀释后股数）、
            # 美元现金储备、年化优先股股息 + 利息、现金能覆盖几年股息和利息
            "sats_per_share": r.get("satsPerShare"), "usd_reserve": r.get("usdReserve"),
            "ann_dividends": r.get("annDividends"), "usd_duration_yrs": r.get("usdDurationYrs"),
            # (债务 + 优先股) / BTC 净值、优先股 / BTC 净值，单位是百分数
            "debt_pref_pct": r.get("debtPrefByBN"), "pref_pct": r.get("prefBtcNav"),
            "source": "strategy:timeSeries", "updated_at": now,
        })
    if not rows:
        raise RuntimeError("timeSeries 的 MSTR 数据里没有可用的市值 / BTC 净值")
    rows.sort(key=lambda x: x["date"])
    return rows


def _r(v, nd=4) -> float | None:
    return None if v is None else round(float(v), nd)


def _derived(r) -> tuple[float | None, float | None, float | None]:
    """(净负债, 净溢价, 杠杆)。没有 EV 口径，或负债已经吃掉全部 BTC 时为 None。"""
    if r["mnav_ev"] is None:
        return None, None, None
    liab = r["mnav_ev"] * r["btc_nav"] - r["market_cap"]
    net = r["btc_nav"] - liab
    if net <= 0:
        return liab, None, None
    return liab, r["market_cap"] / net, r["btc_nav"] / net


def _book(r) -> tuple[float | None, float | None]:
    """账面口径的 (债务, 优先股)，百万美元。"""
    if r["debt_pref_pct"] is None:
        return None, None
    both = r["debt_pref_pct"] / 100 * r["btc_nav"]
    pref = (r["pref_pct"] or 0) / 100 * r["btc_nav"]
    return both - pref, pref


def _kill_price(r, ev_liab) -> float | None:
    """斩杀线，美元/枚。"""
    debt, pref = _book(r)
    if debt is not None and r["usd_reserve"] is not None:
        liab = debt + pref - r["usd_reserve"]
    else:
        liab = ev_liab
    return None if liab is None else liab * 1e6 / r["btc_holdings"]


def build(conn) -> dict | None:
    rows = db.fetch_mstr_nav(conn)
    if not rows:
        return None
    derived = [_derived(r) for r in rows]
    book = [_book(r) for r in rows]
    return {
        "as_of": rows[-1]["date"],
        "unit": "USD million",
        "dates": [r["date"] for r in rows],
        "price": [_r(r["price"], 2) for r in rows],
        "mnav_mc": [_r(r["market_cap"] / r["btc_nav"]) for r in rows],
        "mnav_ev": [_r(r["mnav_ev"]) for r in rows],
        "mnav": [_r(r["mnav"]) for r in rows],
        "btc_holdings": [int(r["btc_holdings"]) for r in rows],
        "market_cap": [round(r["market_cap"]) for r in rows],
        "btc_nav": [round(r["btc_nav"]) for r in rows],
        "net_liab": [_r(d[0], 0) for d in derived],
        "prem_net": [_r(d[1]) for d in derived],
        "leverage": [_r(d[2]) for d in derived],
        "sats_per_share": [_r(r["sats_per_share"], 0) for r in rows],
        "usd_reserve": [_r(r["usd_reserve"], 0) for r in rows],
        "ann_dividends": [_r(r["ann_dividends"], 0) for r in rows],
        "usd_duration_yrs": [_r(r["usd_duration_yrs"], 2) for r in rows],
        "debt": [_r(b[0], 0) for b in book],
        "pref": [_r(b[1], 0) for b in book],
        "btc_price": [round(r["btc_nav"] * 1e6 / r["btc_holdings"]) for r in rows],
        "kill_price": [_r(_kill_price(r, d[0]), 0) for r, d in zip(rows, derived)],
    }
