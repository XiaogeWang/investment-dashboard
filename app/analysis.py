"""相关性分析用的对齐面板。

**为什么要单独做一个「面板」而不是预生成相关性结果**

相关性分析要的是任意两个序列的组合：12 个序列有 66 个组合，再乘上滚动窗口长度和
变换方式，预生成会是几百个文件。所以这里只导出一份「所有序列对齐到月频」的面板
（约 800 行 × 十几列），前端拿到后自己算相关性、滚动相关和散点，切换起来也没有网络往返。

**为什么是月频**

面板里既有日频（利率、股指）也有月频（M2），把月频前向填充到日频再算相关性会
人为抬高相关系数（填充出来的值之间是完全自相关的）。降到共同的最低频率才是干净做法。

**去趋势：这是整个分析里最容易出错的地方**

两个都在长期上涨的序列，用水平值算相关必然接近 1 —— 它衡量的只是「都有上升趋势」。
实测美国联邦债务和纳斯达克指数用水平值算是 +0.93，用同比变化算是 -0.02，
前者会让人得出完全错误的结论。所以默认必须用变化量，水平值只作为可选项。

变化量怎么取又要看单位：
- 利率类（percent）：用**差分**。2% → 4% 是 +2 个百分点；用百分比变化不但语义不对，
  遇到期限利差这种会跨零的序列还会直接爆炸。
- 水平类（USD / index）：用**百分比变化**。
"""

from datetime import date

from . import db
from .aggregate import period_key
from .config import MACRO

PANEL_PERIOD = "month"


def diff_mode(unit: str) -> str:
    """percent 用差分，其余用百分比变化。见模块开头的说明。"""
    return "diff" if unit == "percent" else "pct"


def build_panel(conn) -> dict:
    """所有宏观序列对齐到月频（取区间末值），缺失留 None。"""
    monthly: dict[str, dict[str, float]] = {}
    for key in MACRO:
        buckets: dict[str, float] = {}
        for r in db.fetch_macro(conn, key):
            buckets[period_key(date.fromisoformat(r["date"]), PANEL_PERIOD)] = r["value"]
        if buckets:
            monthly[key] = buckets

    # 资产市值也放进来，这样能分析「BTC / 黄金 vs 利率」这类关系
    for asset in ("BTC", "GOLD"):
        buckets = {}
        for r in db.fetch_daily(conn, asset):
            buckets[period_key(date.fromisoformat(r["date"]), PANEL_PERIOD)] = r["cap_close"]
        if buckets:
            monthly[f"CAP_{asset}"] = buckets

    dates = sorted({d for b in monthly.values() for d in b})
    series = {}
    for key, buckets in monthly.items():
        meta = MACRO.get(key)
        if meta:
            info = {"name_cn": meta["name_cn"], "short_cn": meta["short_cn"],
                    "unit": meta["unit"], "color": meta["color"], "group": meta["group"]}
        else:  # 资产市值
            asset = key.removeprefix("CAP_")
            info = {"name_cn": f"{'比特币' if asset == 'BTC' else '黄金'}市值",
                    "short_cn": f"{'BTC' if asset == 'BTC' else '黄金'}市值",
                    "unit": "USD", "color": "#f7931a" if asset == "BTC" else "#ffd166",
                    "group": "asset"}
        info["diff_mode"] = diff_mode(info["unit"])
        info["values"] = [buckets.get(d) for d in dates]
        series[key] = info

    return {"freq": PANEL_PERIOD, "dates": dates, "series": series}
