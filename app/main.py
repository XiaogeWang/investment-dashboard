from datetime import date

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import db
from .aggregate import (PERIODS, AsOf, aggregate, aggregate_macro, denominator_modes,
                        derive_ratio_rows, period_key, value_modes)
from .config import ASSETS, MACRO, WEB_DIR

app = FastAPI(title="Investment Dashboard", description="BTC 与黄金市值走势")

db.init_db()


@app.get("/api/meta")
def meta():
    out = {}
    with db.connect() as conn:
        for asset, info in ASSETS.items():
            row = conn.execute(
                "SELECT MIN(date) AS first, MAX(date) AS last, COUNT(*) AS n "
                "FROM daily_metrics WHERE asset = ?",
                (asset,),
            ).fetchone()
            out[asset] = {**info, "first_date": row["first"],
                          "last_date": row["last"], "days": row["n"]}
        macro_meta = {}
        for key, info in MACRO.items():
            row = conn.execute(
                "SELECT MIN(date) AS first, MAX(date) AS last, COUNT(*) AS n "
                "FROM macro_series WHERE series = ?",
                (key,),
            ).fetchone()
            macro_meta[key] = {**info, "first_date": row["first"],
                               "last_date": row["last"], "points": row["n"]}
        last_run = conn.execute(
            "SELECT run_at, status FROM ingest_log ORDER BY id DESC LIMIT 1"
        ).fetchone()
    return {
        "assets": out,
        "macro": macro_meta,
        "periods": list(PERIODS),
        "value_modes": value_modes(),
        "last_ingest": dict(last_run) if last_run else None,
    }


@app.get("/api/klines")
def klines(
    asset: str = Query(..., description="BTC 或 GOLD"),
    period: str = Query("day"),
    value: str = Query("cap", description="cap=市值, price=价格"),
    start: str | None = None,
    end: str | None = None,
):
    asset = asset.upper()
    modes = denominator_modes()
    if asset not in ASSETS:
        raise HTTPException(400, f"未知资产: {asset}")
    if period not in PERIODS:
        raise HTTPException(400, f"未知周期: {period}")
    if value not in ("cap", "price") and value not in modes:
        raise HTTPException(400, f"未知取值口径: {value}")

    with db.connect() as conn:
        rows = db.fetch_daily(conn, asset, start, end)
        if value in modes:
            mkey = modes[value]
            denom = AsOf([(r["date"], r["value"]) for r in db.fetch_macro(conn, mkey)])
            derived = derive_ratio_rows(rows, denom, value)
            return {"asset": asset, "period": period, "value": value,
                    "denominator": mkey, "denominator_last_date": denom.last_date,
                    "bars": aggregate(derived, period, value) if derived else []}
    return {"asset": asset, "period": period, "value": value,
            "bars": aggregate(rows, period, value)}


@app.get("/api/ratio")
def ratio(
    base: str = Query("BTC"),
    quote: str = Query("GOLD"),
    period: str = Query("day"),
    start: str | None = None,
    end: str | None = None,
):
    """base 市值 / quote 市值。只在两者都有数据的交易日上取值（黄金周末休市）。"""
    base, quote = base.upper(), quote.upper()
    for a in (base, quote):
        if a not in ASSETS:
            raise HTTPException(400, f"未知资产: {a}")
    if period not in PERIODS:
        raise HTTPException(400, f"未知周期: {period}")

    with db.connect() as conn:
        num = {r["date"]: r["cap_close"] for r in db.fetch_daily(conn, base, start, end)}
        den = db.fetch_daily(conn, quote, start, end)

    series: dict[str, tuple[str, float]] = {}
    for r in den:
        cap = num.get(r["date"])
        if not cap or not r["cap_close"]:
            continue
        key = period_key(date.fromisoformat(r["date"]), period)
        series[key] = (r["date"], cap / r["cap_close"])  # 后写覆盖 → 取区间末值
    return {"base": base, "quote": quote, "period": period,
            "points": [{"t": k, "ratio": v[1], "date": v[0]}
                       for k, v in sorted(series.items())]}


@app.get("/api/macro")
def macro_series(series: str = Query(...), period: str = Query("day"),
                 start: str | None = None, end: str | None = None):
    series = series.upper()
    if series not in MACRO:
        raise HTTPException(400, f"未知宏观指标: {series}")
    if period not in PERIODS:
        raise HTTPException(400, f"未知周期: {period}")
    with db.connect() as conn:
        obs = [(r["date"], r["value"]) for r in db.fetch_macro(conn, series, start, end)]
    return {"series": series, "period": period, "unit": MACRO[series]["unit"],
            "points": aggregate_macro(obs, period)}


@app.get("/api/summary")
def summary():
    out = {}
    with db.connect() as conn:
        for asset in ASSETS:
            rows = conn.execute(
                "SELECT date, price_close, cap_close, supply FROM daily_metrics "
                "WHERE asset = ? ORDER BY date DESC LIMIT 366",
                (asset,),
            ).fetchall()
            if not rows:
                continue
            latest = rows[0]
            def change(n):
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
        snap = conn.execute(
            "SELECT * FROM cmc_snapshot ORDER BY date DESC LIMIT 1"
        ).fetchone()

    if "BTC" in out and "GOLD" in out:
        out["ratio"] = out["BTC"]["market_cap"] / out["GOLD"]["market_cap"]
    if snap:
        out["cmc_check"] = dict(snap)
    return out


@app.get("/")
def index():
    return FileResponse(WEB_DIR / "index.html")


# 挂载在根路径而非 /static，这样本地跑 uvicorn 时资源路径（vendor/、data/）
# 和纯静态托管（GitHub Pages 等）完全一致，前端不用区分两种环境。
app.mount("/", StaticFiles(directory=WEB_DIR), name="static")
