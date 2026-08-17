"""把数据库内容导出成静态 JSON 文件，供 GitHub Pages 这类纯静态托管使用。

用法:
    python -m app.export_static

输出到 web/data/，目录结构和文件名固定，前端按约定路径直接 fetch：
    data/meta.json
    data/summary.json
    data/klines/{asset}_{period}_{value}.json    value ∈ cap/price/per_m2/per_debt
    data/ratio/{base}_{quote}_{period}.json      资产两两组合，两个方向都生成
    data/macro/{series}_{period}.json            宏观单值序列

每天抓取完新数据后跑一遍这个脚本，重新生成的文件连同 web/ 一起提交到仓库，
GitHub Actions 里就是「抓取 → 导出 → git commit & push」三步。
"""

import itertools
import json
from datetime import date
from pathlib import Path

from . import db
from .aggregate import (PERIODS, AsOf, aggregate, aggregate_macro, denominator_modes,
                        derive_ratio_rows, period_key, value_modes)
from .analysis import build_panel
from .config import ASSETS, MACRO, MACRO_GROUPS, WEB_DIR

OUT_DIR = WEB_DIR / "data"

SPARK_POINTS = 60  # 指标卡 sparkline 取最近多少个月


def _write(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def _macro_asof(conn) -> dict[str, AsOf]:
    return {k: AsOf([(r["date"], r["value"]) for r in db.fetch_macro(conn, k)]) for k in MACRO}


def export_meta(conn) -> None:
    out = {}
    for asset, info in ASSETS.items():
        row = conn.execute(
            "SELECT MIN(date) AS first, MAX(date) AS last, COUNT(*) AS n "
            "FROM daily_metrics WHERE asset = ?",
            (asset,),
        ).fetchone()
        out[asset] = {**info, "first_date": row["first"], "last_date": row["last"], "days": row["n"]}

    macro_meta = {}
    for key, info in MACRO.items():
        row = conn.execute(
            "SELECT MIN(date) AS first, MAX(date) AS last, COUNT(*) AS n "
            "FROM macro_series WHERE series = ?",
            (key,),
        ).fetchone()
        macro_meta[key] = {**info, "first_date": row["first"],
                           "last_date": row["last"], "points": row["n"]}

    last_run = conn.execute("SELECT run_at, status FROM ingest_log ORDER BY id DESC LIMIT 1").fetchone()
    _write(OUT_DIR / "meta.json", {
        "assets": out,
        "macro": macro_meta,
        "macro_groups": MACRO_GROUPS,
        "periods": list(PERIODS),
        "value_modes": value_modes(),
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

    # 宏观指标卡：最新值 + 同比 + 用于 sparkline 的月度序列
    macro_out = {}
    for key, info in MACRO.items():
        obs = [(r["date"], r["value"]) for r in db.fetch_macro(conn, key)]
        if not obs:
            continue
        monthly = aggregate_macro(obs, "month")
        spark = [p["v"] for p in monthly[-SPARK_POINTS:]]
        latest_date, latest_val = obs[-1]
        # 同比：拿 12 个月前那条月度观测比
        yoy = None
        if len(monthly) > 12:
            prev = monthly[-13]["v"]
            if prev:
                yoy = latest_val / prev - 1
        macro_out[key] = {
            "name_cn": info["name_cn"],
            "short_cn": info["short_cn"],
            "unit": info["unit"],
            "color": info["color"],
            "note": info["note"],
            "date": latest_date,
            "value": latest_val,
            "change_1y": yoy,
            "spark": spark,
        }
    if macro_out:
        out["macro"] = macro_out

    # 资产市值相对各宏观分母的当前占比，供卡片直接展示
    asof = _macro_asof(conn)
    ratios = {}
    for mode, mkey in denominator_modes().items():
        for asset in ASSETS:
            if asset not in out:
                continue
            dv = asof[mkey](out[asset]["date"])
            if dv:
                ratios[f"{asset}_{mode}"] = out[asset]["market_cap"] / dv
    if ratios:
        out["macro_ratios"] = ratios

    snap = conn.execute("SELECT * FROM cmc_snapshot ORDER BY date DESC LIMIT 1").fetchone()
    if snap:
        out["cmc_check"] = dict(snap)
    _write(OUT_DIR / "summary.json", out)


def export_klines(conn) -> None:
    asof = _macro_asof(conn)
    modes = denominator_modes()
    for asset in ASSETS:
        rows = db.fetch_daily(conn, asset)
        for period in PERIODS:
            for value in ("cap", "price"):
                _write(OUT_DIR / "klines" / f"{asset}_{period}_{value}.json",
                       {"asset": asset, "period": period, "value": value,
                        "bars": aggregate(rows, period, value)})
        # 派生比值口径：市值 / 宏观分母
        for mode, mkey in modes.items():
            derived = derive_ratio_rows(rows, asof[mkey], mode)
            for period in PERIODS:
                _write(OUT_DIR / "klines" / f"{asset}_{period}_{mode}.json", {
                    "asset": asset, "period": period, "value": mode,
                    "denominator": mkey,
                    "denominator_last_date": asof[mkey].last_date,
                    "bars": aggregate(derived, period, mode) if derived else [],
                })


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


def export_macro(conn) -> None:
    for key in MACRO:
        obs = [(r["date"], r["value"]) for r in db.fetch_macro(conn, key)]
        for period in PERIODS:
            _write(OUT_DIR / "macro" / f"{key}_{period}.json", {
                "series": key, "period": period, "unit": MACRO[key]["unit"],
                "points": aggregate_macro(obs, period) if obs else [],
            })


def export_panel(conn) -> None:
    """相关性分析用的对齐月度面板。前端在这一份数据上算相关性，见 analysis.py 的说明。"""
    _write(OUT_DIR / "panel_month.json", build_panel(conn))


def run() -> None:
    with db.connect() as conn:
        export_meta(conn)
        export_summary(conn)
        export_klines(conn)
        export_ratio(conn)
        export_macro(conn)
        export_panel(conn)


if __name__ == "__main__":
    run()
