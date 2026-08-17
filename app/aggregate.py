"""把日线 OHLC 聚合成周/月/季/年 K 线，并派生「市值 / 宏观指标」这类比值口径。

聚合规则遵循 K 线惯例：open 取区间首日开盘，close 取区间末日收盘，
high/low 取区间极值，volume 求和。
"""

import bisect
from datetime import date, timedelta

from .config import MACRO

PERIODS = ("day", "week", "month", "quarter", "year")


def denominator_modes() -> dict[str, str]:
    """可用作分母的宏观指标 → 对应的取值口径名。加一个 denominator=True 的指标就自动多一个口径。"""
    return {f"per_{k.lower()}": k for k, v in MACRO.items() if v.get("denominator")}


class AsOf:
    """按日期做「最近已知值」查询。

    宏观指标频率低于行情：M2 是月频且发布滞后约 2 个月，债务只有工作日。
    要把它们当分母除到每个交易日上，就得用不晚于当天的最后一个观测值，
    而不是简单按日期精确匹配（否则绝大多数交易日都取不到值）。
    """

    def __init__(self, obs):
        self._dates = [d for d, _ in obs]
        self._values = [v for _, v in obs]

    def __call__(self, d: str) -> float | None:
        i = bisect.bisect_right(self._dates, d) - 1
        return self._values[i] if i >= 0 else None

    @property
    def last_date(self) -> str | None:
        return self._dates[-1] if self._dates else None


def derive_ratio_rows(rows, denom: AsOf, mode: str) -> list[dict]:
    """把市值 OHLC 逐列除以当日（或最近已知）的分母，产出能直接喂给 aggregate 的行。

    分母在一天之内是常数，所以 high/denom 仍是当天比值的最高点；跨周期聚合时
    aggregate 会在各日比值上取极值，分母变动已经体现在每日比值里了。
    """
    out = []
    for r in rows:
        dv = denom(r["date"])
        if not dv:  # 早于该宏观序列的起始日期，没有分母可用
            continue
        out.append({
            "date": r["date"],
            f"{mode}_open": r["cap_open"] / dv,
            f"{mode}_high": r["cap_high"] / dv,
            f"{mode}_low": r["cap_low"] / dv,
            f"{mode}_close": r["cap_close"] / dv,
            "volume": r["volume"],
            "supply": r["supply"],
        })
    return out


def value_modes() -> list[dict]:
    """前端「口径」按钮的数据源。kind 决定 Y 轴怎么格式化。"""
    modes = [
        {"key": "cap", "label": "市值", "kind": "usd"},
        {"key": "price", "label": "价格", "kind": "usd"},
    ]
    for mode, key in denominator_modes().items():
        modes.append({
            "key": mode,
            "label": f"相对{MACRO[key]['short_cn']}",
            "kind": "ratio",
            "denominator": key,
        })
    return modes


def aggregate_macro(obs, period: str) -> list[dict]:
    """宏观单值序列按周期取区间末值。"""
    if period not in PERIODS:
        raise ValueError(f"未知周期: {period}")
    series: dict[str, tuple[str, float]] = {}
    for d, v in obs:
        key = period_key(date.fromisoformat(d), period)
        series[key] = (d, v)  # 后写覆盖 → 区间末值
    return [{"t": k, "v": v[1], "date": v[0]} for k, v in sorted(series.items())]


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
