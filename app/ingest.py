"""抓取日线行情、换算成市值并落库。

用法:
    python -m app.ingest --full          首次回填全部历史
    python -m app.ingest                 每日增量（默认只补最近 10 天）
"""

import argparse
import logging
import sys
from datetime import datetime, timezone

import yfinance as yf

from . import db, macro
from .config import ASSETS, CMC_API_KEY, CMC_BASE_URL, MACRO
from .supply import SUPPLY_FN

log = logging.getLogger("ingest")

INCREMENTAL_DAYS = 10


def _download(ticker: str, full: bool):
    period = "max" if full else f"{INCREMENTAL_DAYS}d"
    df = yf.Ticker(ticker).history(period=period, interval="1d", auto_adjust=False)
    if df.empty:
        raise RuntimeError(f"{ticker} 未返回任何数据")
    return df


def build_rows(asset: str, df, source: str) -> list[dict]:
    supply_fn = SUPPLY_FN[asset]
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    rows = []
    for ts, r in df.iterrows():
        d = ts.date()
        o, h, l, c = float(r["Open"]), float(r["High"]), float(r["Low"]), float(r["Close"])
        if any(v != v or v <= 0 for v in (o, h, l, c)):  # NaN 或非正价格，跳过
            continue
        supply = supply_fn(d)
        volume = float(r["Volume"]) if r["Volume"] == r["Volume"] else None
        rows.append({
            "asset": asset, "date": d.isoformat(),
            "price_open": o, "price_high": h, "price_low": l, "price_close": c,
            "supply": supply,
            "cap_open": o * supply, "cap_high": h * supply,
            "cap_low": l * supply, "cap_close": c * supply,
            "volume": volume, "source": source, "updated_at": now,
        })
    return rows


def fetch_cmc_snapshot() -> dict | None:
    """用 CMC 官方 BTC 报价校验自算供应量。免费版只有实时值，故仅记录当日快照。"""
    if not CMC_API_KEY:
        return None
    import httpx

    resp = httpx.get(
        f"{CMC_BASE_URL}/v1/cryptocurrency/quotes/latest",
        params={"symbol": "BTC", "convert": "USD"},
        headers={"X-CMC_PRO_API_KEY": CMC_API_KEY, "Accept": "application/json"},
        timeout=20,
    )
    resp.raise_for_status()
    data = resp.json()["data"]["BTC"]
    quote = data["quote"]["USD"]
    return {
        "date": datetime.now(timezone.utc).date().isoformat(),
        "price": quote["price"],
        "circulating_supply": data["circulating_supply"],
        "market_cap": quote["market_cap"],
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def run(full: bool = False) -> int:
    db.init_db()
    run_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    failures = 0

    for asset, meta in ASSETS.items():
        ticker = meta["ticker"]
        try:
            df = _download(ticker, full)
            rows = build_rows(asset, df, source=f"yahoo:{ticker}")
            with db.connect() as conn:
                n = db.upsert_daily(conn, rows)
                db.log_ingest(conn, run_at, asset, "ok", n,
                              f"{rows[0]['date']}..{rows[-1]['date']}")
            log.info("%s: 写入 %d 行 (%s..%s)", asset, n, rows[0]["date"], rows[-1]["date"])
        except Exception as e:
            failures += 1
            log.error("%s 抓取失败: %s", asset, e)
            with db.connect() as conn:
                db.log_ingest(conn, run_at, asset, "error", 0, str(e)[:500])

    # 宏观序列。两个源都是一次拉全历史，没有增量模式：数据量本身不大（最多几千条），
    # 而且宏观数据会被回溯修订（CPI、GDP 尤其明显），每次全量覆盖反而更准。
    for key in MACRO:
        try:
            rows = macro.fetch_series(key)
            with db.connect() as conn:
                n = db.upsert_macro(conn, rows)
                db.log_ingest(conn, run_at, f"macro:{key}", "ok", n,
                              f"{rows[0]['date']}..{rows[-1]['date']}")
            log.info("%s: 写入 %d 行 (%s..%s)", key, n, rows[0]["date"], rows[-1]["date"])
        except Exception as e:
            failures += 1
            log.error("%s 抓取失败: %s", key, e)
            with db.connect() as conn:
                db.log_ingest(conn, run_at, f"macro:{key}", "error", 0, str(e)[:500])

    try:
        snap = fetch_cmc_snapshot()
        if snap:
            with db.connect() as conn:
                conn.execute(
                    "INSERT INTO cmc_snapshot VALUES (:date,:price,:circulating_supply,"
                    ":market_cap,:fetched_at) ON CONFLICT(date) DO UPDATE SET "
                    "price=excluded.price, circulating_supply=excluded.circulating_supply, "
                    "market_cap=excluded.market_cap, fetched_at=excluded.fetched_at",
                    snap,
                )
            log.info("CMC 校准: supply=%.0f market_cap=%.4g",
                     snap["circulating_supply"], snap["market_cap"])
    except Exception as e:
        log.warning("CMC 校准跳过: %s", e)

    return failures


def main():
    parser = argparse.ArgumentParser(description="抓取 BTC / 黄金日线并换算市值")
    parser.add_argument("--full", action="store_true", help="回填全部历史")
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s | %(message)s",
    )
    sys.exit(1 if run(full=args.full) else 0)


if __name__ == "__main__":
    main()
