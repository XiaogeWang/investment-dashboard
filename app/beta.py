"""加密股相对 BTC 的滚动 Beta。

β = Cov(R_股票, R_BTC) / Var(R_BTC)，R 为对数日收益率。

对齐方式：以股票交易日为准，取同一日期的 BTC 收盘价。BTC 全天交易，周末的涨跌
自然并入下周一的收益里。BTC 日收盘是 UTC 0 点、美股是美东 16:00，存在几个小时的
错位，会让日频 Beta 略微偏低；Yahoo 的小时数据只保留最近两年，覆盖不了全区间，
所以这里接受这个误差，而不是只对近两年做精确对齐。
"""

import logging
import random
import time
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from . import db
from .config import BETA

log = logging.getLogger("beta")

RETRIES = 4
BACKOFF = 8


def fetch_equity(symbol: str) -> list[dict]:
    """全量抓复权收盘价。必须用复权价：MSTR 2024-08 做过 10:1 拆股，
    不复权的话拆股当天会算出一个 -90% 的假收益，直接把 Beta 打歪。"""
    import yfinance as yf

    ticker = BETA["stocks"][symbol]["ticker"]
    # Yahoo 限流时直接抛 Too Many Requests。一次任务要连着请求 8 个 ticker，
    # 这里多加的 4 个带退避重试，免得因为新增的请求把整个每日任务拖垮。
    for attempt in range(1, RETRIES + 1):
        try:
            df = yf.Ticker(ticker).history(period="max", interval="1d", auto_adjust=True)
            if df.empty:
                raise RuntimeError(f"{ticker} 未返回任何数据")
            break
        except Exception as e:
            if attempt == RETRIES:
                raise
            delay = BACKOFF * attempt + random.uniform(0, 2)
            log.warning("%s 抓取失败 (%s/%s): %s，%.1fs 后重试", ticker, attempt, RETRIES, e, delay)
            time.sleep(delay)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    rows = []
    for ts, r in df.iterrows():
        c = float(r["Close"])
        if c != c or c <= 0:
            continue
        rows.append({"symbol": symbol, "date": ts.date().isoformat(), "close": c,
                     "source": f"yahoo:{ticker}", "updated_at": now})
    if not rows:
        raise RuntimeError(f"{ticker} 没有解析出任何收盘价")
    return rows


def start_date(symbol: str) -> str:
    return max(BETA["floor"], BETA["stocks"][symbol]["listed"])


def _round(v) -> float | None:
    return None if v is None or not np.isfinite(v) else round(float(v), 4)


def _returns(conn, symbol: str, btc: pd.Series) -> pd.DataFrame:
    rows = db.fetch_equity(conn, symbol, start_date(symbol))
    if not rows:
        return pd.DataFrame(columns=["s", "b"])
    s = pd.Series({r["date"]: r["close"] for r in rows}, dtype=float)
    df = pd.DataFrame({"s": s, "b": btc.reindex(s.index)}).dropna()
    return np.log(df).diff().dropna()


def build(conn) -> dict:
    """算出前端需要的全部数据：每只股票每个窗口的滚动 Beta、滚动相关系数，以及全区间值。"""
    bench = BETA["benchmark"]
    btc = pd.Series({r["date"]: r["price_close"] for r in db.fetch_daily(conn, bench)},
                    dtype=float)
    windows = BETA["windows"]
    stocks = {}
    for symbol, info in BETA["stocks"].items():
        rets = _returns(conn, symbol, btc)
        if len(rets) < 2:
            log.warning("%s 没有足够的数据算 Beta", symbol)
            continue
        beta, corr = {}, {}
        for w in windows:
            cov = rets["s"].rolling(w).cov(rets["b"])
            beta[w] = [_round(v) for v in cov / rets["b"].rolling(w).var()]
            corr[w] = [_round(v) for v in rets["s"].rolling(w).corr(rets["b"])]
        c = rets.cov()
        stocks[symbol] = {
            **info,
            "start": rets.index[0],
            "dates": list(rets.index),
            "beta": beta,
            "corr": corr,
            "full": {
                "beta": _round(c.loc["s", "b"] / c.loc["b", "b"]),
                "corr": _round(rets["s"].corr(rets["b"])),
                "n": len(rets),
            },
        }
    as_of = max((s["dates"][-1] for s in stocks.values()), default=None)
    return {"benchmark": bench, "floor": BETA["floor"], "windows": windows,
            "as_of": as_of, "stocks": stocks}
