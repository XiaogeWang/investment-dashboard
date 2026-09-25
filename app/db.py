import sqlite3
from contextlib import contextmanager

from .config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS daily_metrics (
    asset       TEXT NOT NULL,
    date        TEXT NOT NULL,
    price_open  REAL NOT NULL,
    price_high  REAL NOT NULL,
    price_low   REAL NOT NULL,
    price_close REAL NOT NULL,
    supply      REAL NOT NULL,
    cap_open    REAL NOT NULL,
    cap_high    REAL NOT NULL,
    cap_low     REAL NOT NULL,
    cap_close   REAL NOT NULL,
    volume      REAL,
    source      TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    PRIMARY KEY (asset, date)
);

CREATE TABLE IF NOT EXISTS ingest_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    run_at     TEXT NOT NULL,
    asset      TEXT NOT NULL,
    status     TEXT NOT NULL,
    rows       INTEGER NOT NULL DEFAULT 0,
    message    TEXT
);

-- 宏观指标：单值时间序列。频率不统一（日/月），按各自的观测日期存原样，
-- 需要对齐到交易日时由查询侧做前向填充，不在这里补齐。
CREATE TABLE IF NOT EXISTS macro_series (
    series     TEXT NOT NULL,
    date       TEXT NOT NULL,
    value      REAL NOT NULL,
    source     TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (series, date)
);

-- 股票复权收盘价，只用于算相对 BTC 的 Beta。拆股/分红会回溯调整历史复权价，
-- 所以每次都全量重抓覆盖。
CREATE TABLE IF NOT EXISTS equity_close (
    symbol     TEXT NOT NULL,
    date       TEXT NOT NULL,
    close      REAL NOT NULL,
    source     TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (symbol, date)
);

-- Strategy (MSTR) 的 mNAV 相关日度数据，来自 Strategy 官网的公开接口。
-- 金额单位均为「百万美元」，和接口原样保持一致。
CREATE TABLE IF NOT EXISTS mstr_nav (
    date         TEXT PRIMARY KEY,
    price        REAL,
    market_cap   REAL NOT NULL,
    btc_nav      REAL NOT NULL,
    btc_holdings REAL NOT NULL,
    mnav_ev      REAL,
    mnav         REAL,
    source       TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);

-- CMC 官方口径快照，用于校验自算供应量的偏差；无 API Key 时该表为空
CREATE TABLE IF NOT EXISTS cmc_snapshot (
    date                TEXT PRIMARY KEY,
    price               REAL NOT NULL,
    circulating_supply  REAL NOT NULL,
    market_cap          REAL NOT NULL,
    fetched_at          TEXT NOT NULL
);
"""


@contextmanager
def connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with connect() as conn:
        conn.executescript(SCHEMA)


def upsert_daily(conn, rows: list[dict]) -> int:
    conn.executemany(
        """
        INSERT INTO daily_metrics
            (asset, date, price_open, price_high, price_low, price_close,
             supply, cap_open, cap_high, cap_low, cap_close, volume, source, updated_at)
        VALUES
            (:asset, :date, :price_open, :price_high, :price_low, :price_close,
             :supply, :cap_open, :cap_high, :cap_low, :cap_close, :volume, :source, :updated_at)
        ON CONFLICT(asset, date) DO UPDATE SET
            price_open=excluded.price_open, price_high=excluded.price_high,
            price_low=excluded.price_low,   price_close=excluded.price_close,
            supply=excluded.supply,
            cap_open=excluded.cap_open,     cap_high=excluded.cap_high,
            cap_low=excluded.cap_low,       cap_close=excluded.cap_close,
            volume=excluded.volume,         source=excluded.source,
            updated_at=excluded.updated_at
        """,
        rows,
    )
    return len(rows)


def upsert_macro(conn, rows: list[dict]) -> int:
    conn.executemany(
        """
        INSERT INTO macro_series (series, date, value, source, updated_at)
        VALUES (:series, :date, :value, :source, :updated_at)
        ON CONFLICT(series, date) DO UPDATE SET
            value=excluded.value, source=excluded.source, updated_at=excluded.updated_at
        """,
        rows,
    )
    return len(rows)


def fetch_macro(conn, series: str, start: str | None = None, end: str | None = None):
    sql = "SELECT date, value FROM macro_series WHERE series = ?"
    params: list = [series]
    if start:
        sql += " AND date >= ?"
        params.append(start)
    if end:
        sql += " AND date <= ?"
        params.append(end)
    sql += " ORDER BY date"
    return conn.execute(sql, params).fetchall()


def upsert_equity(conn, rows: list[dict]) -> int:
    conn.executemany(
        """
        INSERT INTO equity_close (symbol, date, close, source, updated_at)
        VALUES (:symbol, :date, :close, :source, :updated_at)
        ON CONFLICT(symbol, date) DO UPDATE SET
            close=excluded.close, source=excluded.source, updated_at=excluded.updated_at
        """,
        rows,
    )
    return len(rows)


def fetch_equity(conn, symbol: str, start: str | None = None):
    sql = "SELECT date, close FROM equity_close WHERE symbol = ?"
    params: list = [symbol]
    if start:
        sql += " AND date >= ?"
        params.append(start)
    sql += " ORDER BY date"
    return conn.execute(sql, params).fetchall()


def upsert_mstr_nav(conn, rows: list[dict]) -> int:
    conn.executemany(
        """
        INSERT INTO mstr_nav (date, price, market_cap, btc_nav, btc_holdings, mnav_ev, mnav,
                              source, updated_at)
        VALUES (:date, :price, :market_cap, :btc_nav, :btc_holdings, :mnav_ev, :mnav,
                :source, :updated_at)
        ON CONFLICT(date) DO UPDATE SET
            price=excluded.price, market_cap=excluded.market_cap, btc_nav=excluded.btc_nav,
            btc_holdings=excluded.btc_holdings, mnav_ev=excluded.mnav_ev, mnav=excluded.mnav,
            source=excluded.source, updated_at=excluded.updated_at
        """,
        rows,
    )
    return len(rows)


def fetch_mstr_nav(conn):
    return conn.execute("SELECT * FROM mstr_nav ORDER BY date").fetchall()


def log_ingest(conn, run_at: str, asset: str, status: str, rows: int, message: str = ""):
    conn.execute(
        "INSERT INTO ingest_log (run_at, asset, status, rows, message) VALUES (?,?,?,?,?)",
        (run_at, asset, status, rows, message),
    )


def fetch_daily(conn, asset: str, start: str | None = None, end: str | None = None):
    sql = "SELECT * FROM daily_metrics WHERE asset = ?"
    params: list = [asset]
    if start:
        sql += " AND date >= ?"
        params.append(start)
    if end:
        sql += " AND date <= ?"
        params.append(end)
    sql += " ORDER BY date"
    return conn.execute(sql, params).fetchall()
