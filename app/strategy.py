"""Strategy (MSTR) 的 BTC 买卖账本、持仓成本与可转债回售时间表。

数据来源分两部分：

- snapshots/strategy.json：官网 /ledger 与 /debt 页面的快照（scripts/strategy_snapshot.js 导出）。
  这两份数据没有公开 API，www.strategy.com 又拒绝非浏览器请求，只能在浏览器里手动导出。
- mstr_nav 表（api.strategy.com/btc/timeSeries，每天自动更新）：快照之后持币量的变化
  就是新的买卖，按当天币价估算成交价补进账本，标记为估算，下次刷新快照时被官网数据替换。

平均成本：官网 2025-06-30 起给出累计成本，直接用；更早的按每笔金额累加（只有买入，和官网
2025-06-30 的累计成本只差 0.02%）。官网账本自带的「平均成本」一列早期有几处明显录错，不用。
卖出时官网扣掉的不是平均成本而是高成本批次（2026 年几笔卖出每枚扣 9~12.5 万美元），
所以估算的卖出也没法精确复现，按平均成本扣，误差在下次刷新快照时消除。
"""

import json
from datetime import date

from . import db
from .config import SNAPSHOT_PATH

STALE_DAYS = 45          # 快照超过这么多天没刷新就在页面提示
DEBT_TOLERANCE = 0.02    # 可转债本金合计与接口债务相差超过 2% 就提示快照可能过期


def _load_snapshot() -> dict | None:
    if not SNAPSHOT_PATH.exists():
        return None
    return json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))


def _ledger(snapshot: dict, nav_rows) -> list[dict]:
    out, cost = [], 0.0
    for t in snapshot["transactions"]:
        if t["total_cost_musd"] is not None:
            removed = cost - t["total_cost_musd"] if t["sale"] else None
            cost = t["total_cost_musd"]
        elif t["btc"] > 0:
            removed, cost = None, cost + t["amount_musd"]
        else:
            removed = cost / (t["holdings"] - t["btc"]) * -t["btc"]
            cost -= removed
        out.append({
            "date": t["date"], "btc": t["btc"], "price": t["price"], "amount": round(t["amount_musd"], 2),
            "holdings": t["holdings"], "avg_cost": round(cost * 1e6 / t["holdings"]),
            "total_cost": round(cost),
            # 卖出的实现盈亏 = 卖出金额 − 扣掉的成本，百万美元
            "realized": round(-t["amount_musd"] - removed, 1) if t["sale"] and removed is not None else None,
            "filing": t["filing"], "estimated": False,
        })

    # 快照之后：从时序接口的持币量变化补估算记录。要先等时序接口追上快照的持币量，
    # 否则接口滞后一两天时会把「还没更新」误判成一笔卖出。
    last = out[-1]
    holdings, synced = last["holdings"], False
    for r in nav_rows:
        if r["date"] < last["date"]:
            continue
        h = int(r["btc_holdings"])
        if not synced:
            synced = h == holdings
            continue
        if h == holdings:
            continue
        diff = h - holdings
        price = r["btc_nav"] * 1e6 / h
        if diff > 0:
            cost += diff * price / 1e6
        else:
            cost -= cost / holdings * -diff
        holdings = h
        out.append({
            "date": r["date"], "btc": diff, "price": round(price), "amount": round(diff * price / 1e6, 2),
            "holdings": h, "avg_cost": round(cost * 1e6 / h), "total_cost": round(cost),
            "realized": None, "filing": None, "estimated": True,
        })
    return out


def build(conn) -> dict | None:
    snapshot = _load_snapshot()
    if snapshot is None:
        return None
    nav = db.fetch_mstr_nav(conn)
    ledger = _ledger(snapshot, nav)

    latest = nav[-1] if nav else None
    debt_api = None
    if latest is not None and latest["debt_pref_pct"] is not None:
        debt_api = (latest["debt_pref_pct"] - (latest["pref_pct"] or 0)) / 100 * latest["btc_nav"]
    notional = sum(c["notional_musd"] for c in snapshot["converts"])
    age = (date.today() - date.fromisoformat(snapshot["exported_at"])).days

    return {
        "snapshot_date": snapshot["exported_at"],
        "snapshot_age_days": age,
        "snapshot_stale": age > STALE_DAYS,
        "transactions": ledger,
        "converts": sorted(snapshot["converts"], key=lambda c: (c["put_date"], c["name"])),
        "converts_notional": round(notional, 2),
        "debt_api": None if debt_api is None else round(debt_api),
        # 接口债务和可转债明细对不上，说明有新发行、赎回或转股，需要刷新快照
        "converts_mismatch": debt_api is not None and abs(debt_api - notional) > notional * DEBT_TOLERANCE,
    }
