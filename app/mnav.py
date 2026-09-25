"""Strategy (MSTR) 的 mNAV：股票市值相对所持 BTC 价值的溢价倍数。

两种口径：

- 市值口径：市值 / BTC 净值。2020-08 开始买币起每天都有，看长期走势用这个。
- EV 口径（Strategy 官方）：(市值 + 债务 + 优先股 − 现金储备) / BTC 净值。
  Strategy 从 2024-12-31 才开始公布，但它把债务和优先股算了进去，
  在 2025 年大量发行优先股之后，比市值口径更能反映真实溢价。

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
            "source": "strategy:timeSeries", "updated_at": now,
        })
    if not rows:
        raise RuntimeError("timeSeries 的 MSTR 数据里没有可用的市值 / BTC 净值")
    rows.sort(key=lambda x: x["date"])
    return rows


def _r4(v) -> float | None:
    return None if v is None else round(float(v), 4)


def build(conn) -> dict | None:
    rows = db.fetch_mstr_nav(conn)
    if not rows:
        return None
    return {
        "as_of": rows[-1]["date"],
        "unit": "USD million",
        "dates": [r["date"] for r in rows],
        "mnav_mc": [_r4(r["market_cap"] / r["btc_nav"]) for r in rows],
        "mnav_ev": [_r4(r["mnav_ev"]) for r in rows],
        "mnav": [_r4(r["mnav"]) for r in rows],
        "btc_holdings": [int(r["btc_holdings"]) for r in rows],
        "market_cap": [round(r["market_cap"]) for r in rows],
        "btc_nav": [round(r["btc_nav"]) for r in rows],
    }
