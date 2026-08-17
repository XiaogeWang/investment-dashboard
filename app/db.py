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
