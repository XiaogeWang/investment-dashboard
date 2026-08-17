"""把数据库内容导出成静态 JSON 文件，供 GitHub Pages 这类纯静态托管使用。

用法:
    python -m app.export_static

输出到 web/data/，目录结构和文件名固定，前端按约定路径直接 fetch：
    data/meta.json
    data/summary.json
    data/klines/{asset}_{period}_{value}.json
    data/ratio/{base}_{quote}_{period}.json   （资产两两组合，两个方向都生成）

每天抓取完新数据后跑一遍这个脚本，重新生成的文件连同 web/ 一起提交到仓库，
GitHub Actions 里就是「抓取 → 导出 → git commit & push」三步。
"""

import itertools
import json
from datetime import date
from pathlib import Path

from . import db
from .aggregate import PERIODS, aggregate, period_key
from .config import ASSETS, WEB_DIR

OUT_DIR = WEB_DIR / "data"


def _write(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def export_meta(conn) -> None:
    out = {}
    for asset, info in ASSETS.items():
        row = conn.execute(
            "SELECT MIN(date) AS first, MAX(date) AS last, COUNT(*) AS n "
            "FROM daily_metrics WHERE asset = ?",
            (asset,),
        ).fetchone()
        out[asset] = {**info, "first_date": row["first"], "last_date": row["last"], "days": row["n"]}
    last_run = conn.execute("SELECT run_at, status FROM ingest_log ORDER BY id DESC LIMIT 1").fetchone()
    _write(OUT_DIR / "meta.json", {
        "assets": out,
        "periods": list(PERIODS),
        "last_ingest": dict(last_run) if last_run else None,
    })


def export_summary(conn) -> None:
    out = {}
    for asset in ASSETS:
        rows = conn.execute(
            "SELECT date, price_close, cap_close, supply FROM daily_metrics "
            "WHERE asset = ? ORDER BY date DESC LIMIT 366",
            (asset,),
        ).fetchall()
        if not rows:
            continue
        latest = rows[0]

        def change(n, rows=rows, latest=latest):
            return (latest["cap_close"] / rows[n]["cap_close"] - 1) if len(rows) > n else None

        out[asset] = {
            "date": latest["date"],
            "price": latest["price_close"],
            "market_cap": latest["cap_close"],
            "supply": latest["supply"],
            "change_1d": change(1),
            "change_30d": change(30),
            "change_1y": change(365),
        }
    if "BTC" in out and "GOLD" in out:
        out["ratio"] = out["BTC"]["market_cap"] / out["GOLD"]["market_cap"]
    snap = conn.execute("SELECT * FROM cmc_snapshot ORDER BY date DESC LIMIT 1").fetchone()
    if snap:
        out["cmc_check"] = dict(snap)
    _write(OUT_DIR / "summary.json", out)


def export_klines(conn) -> None:
    for asset in ASSETS:
        rows = db.fetch_daily(conn, asset)
        for period in PERIODS:
            for value in ("cap", "price"):
                bars = aggregate(rows, period, value)
                _write(OUT_DIR / "klines" / f"{asset}_{period}_{value}.json",
                       {"asset": asset, "period": period, "value": value, "bars": bars})


def export_ratio(conn) -> None:
    cache = {a: db.fetch_daily(conn, a) for a in ASSETS}
    for base, quote in itertools.permutations(ASSETS, 2):
        num = {r["date"]: r["cap_close"] for r in cache[base]}
        series: dict[str, tuple[str, float]] = {}
        for period in PERIODS:
            series.clear()
            for r in cache[quote]:
                cap = num.get(r["date"])
                if not cap or not r["cap_close"]:
                    continue
                key = period_key(date.fromisoformat(r["date"]), period)
                series[key] = (r["date"], cap / r["cap_close"])
            _write(OUT_DIR / "ratio" / f"{base}_{quote}_{period}.json", {
                "base": base, "quote": quote, "period": period,
                "points": [{"t": k, "ratio": v[1], "date": v[0]} for k, v in sorted(series.items())],
            })


def run() -> None:
    with db.connect() as conn:
        export_meta(conn)
        export_summary(conn)
        export_klines(conn)
        export_ratio(conn)


if __name__ == "__main__":
    run()
