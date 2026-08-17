"""把日线 OHLC 聚合成周/月/季/年 K 线。

聚合规则遵循 K 线惯例：open 取区间首日开盘，close 取区间末日收盘，
high/low 取区间极值，volume 求和。
"""

from datetime import date, timedelta

PERIODS = ("day", "week", "month", "quarter", "year")


def period_key(d: date, period: str) -> str:
    if period == "day":
        return d.isoformat()
    if period == "week":
        return (d - timedelta(days=d.weekday())).isoformat()  # 归到周一
    if period == "month":
        return date(d.year, d.month, 1).isoformat()
    if period == "quarter":
        return date(d.year, (d.month - 1) // 3 * 3 + 1, 1).isoformat()
    if period == "year":
        return date(d.year, 1, 1).isoformat()
    raise ValueError(f"未知周期: {period}")


def aggregate(rows, period: str, value: str = "cap") -> list[dict]:
    """rows 需按日期升序。value 为 'cap'（市值）或 'price'（价格）。"""
    if period not in PERIODS:
        raise ValueError(f"未知周期: {period}")
    o_col, h_col, l_col, c_col = (f"{value}_{k}" for k in ("open", "high", "low", "close"))

    out: list[dict] = []
    current_key = None
    for r in rows:
        key = period_key(date.fromisoformat(r["date"]), period)
        if key != current_key:
            current_key = key
            out.append({
                "t": key,
                "o": r[o_col], "h": r[h_col], "l": r[l_col], "c": r[c_col],
                "v": r["volume"] or 0.0,
                "supply": r["supply"],
                "start": r["date"], "end": r["date"],
            })
            continue
        bar = out[-1]
        bar["h"] = max(bar["h"], r[h_col])
        bar["l"] = min(bar["l"], r[l_col])
        bar["c"] = r[c_col]
        bar["v"] += r["volume"] or 0.0
        bar["supply"] = r["supply"]
        bar["end"] = r["date"]
    return out
