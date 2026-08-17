"""把价格换算成市值所需的供应量模型。

市值 = 当日价格 × 当日供应量。两种资产的供应量都不来自行情 API：
  BTC  —— 由减半规则确定性推算已挖出总量
  GOLD —— 由 WGC 年度矿产量反推地上黄金存量（估算值）
"""

from datetime import date

TROY_OZ_PER_TONNE = 32150.7466

# 已发生的减半：(区块高度, 出块日期)。段内按线性插值估算区块高度，
# 段外（最后一次减半之后）按 10 分钟/块外推。
_HALVING_ANCHORS = [
    (0, date(2009, 1, 3)),
    (210_000, date(2012, 11, 28)),
    (420_000, date(2016, 7, 9)),
    (630_000, date(2020, 5, 11)),
    (840_000, date(2024, 4, 20)),
]
_BLOCKS_PER_DAY = 144.0
_HALVING_INTERVAL = 210_000
_INITIAL_SUBSIDY = 50.0


def btc_block_height(d: date) -> float:
    if d <= _HALVING_ANCHORS[0][1]:
        return 0.0
    for (h0, d0), (h1, d1) in zip(_HALVING_ANCHORS, _HALVING_ANCHORS[1:]):
        if d <= d1:
            ratio = (d - d0).days / (d1 - d0).days
            return h0 + ratio * (h1 - h0)
    h_last, d_last = _HALVING_ANCHORS[-1]
    return h_last + (d - d_last).days * _BLOCKS_PER_DAY


def btc_supply(d: date) -> float:
    """截至该日已挖出的 BTC 总量（丢失的币仍计入，与 CMC circulating supply 口径一致）。"""
    height = btc_block_height(d)
    total = 0.0
    subsidy = _INITIAL_SUBSIDY
    remaining = height
    while remaining > 0 and subsidy > 1e-12:
        blocks = min(remaining, _HALVING_INTERVAL)
        total += blocks * subsidy
        remaining -= blocks
        subsidy /= 2
    return total


# 地上黄金存量锚点：WGC 口径 2024 年底 216,265 吨，按年度矿产量逐年回推。
# 黄金几乎不被消耗，故地上存量 ≈ 人类累计开采量。
_GOLD_STOCK_2024_END_TONNES = 216_265.0
_ANNUAL_MINE_OUTPUT_TONNES = {
    2000: 2591, 2001: 2646, 2002: 2590, 2003: 2593, 2004: 2464,
    2005: 2550, 2006: 2496, 2007: 2500, 2008: 2429, 2009: 2612,
    2010: 2749, 2011: 2846, 2012: 2864, 2013: 3076, 2014: 3346,
    2015: 3477, 2016: 3509, 2017: 3576, 2018: 3656, 2019: 3597,
    2020: 3478, 2021: 3580, 2022: 3628, 2023: 3644, 2024: 3661,
}
_ASSUMED_FUTURE_OUTPUT_TONNES = 3650


def _year_end_stock_tonnes() -> dict[int, float]:
    stock = {2024: _GOLD_STOCK_2024_END_TONNES}
    for year in range(2023, 1998, -1):
        stock[year] = stock[year + 1] - _ANNUAL_MINE_OUTPUT_TONNES.get(
            year + 1, _ASSUMED_FUTURE_OUTPUT_TONNES
        )
    for year in range(2025, date.today().year + 3):
        stock[year] = stock[year - 1] + _ANNUAL_MINE_OUTPUT_TONNES.get(
            year, _ASSUMED_FUTURE_OUTPUT_TONNES
        )
    return stock


_YEAR_END_STOCK = _year_end_stock_tonnes()


def gold_stock_tonnes(d: date) -> float:
    """该日地上黄金存量（吨），按年末锚点在年内线性插值。"""
    prev_end = _YEAR_END_STOCK[d.year - 1]
    this_end = _YEAR_END_STOCK[d.year]
    day_of_year = (d - date(d.year, 1, 1)).days
    days_in_year = (date(d.year + 1, 1, 1) - date(d.year, 1, 1)).days
    return prev_end + (this_end - prev_end) * (day_of_year / days_in_year)


def gold_supply(d: date) -> float:
    """该日地上黄金存量（金衡盎司），与 USD/oz 报价直接相乘即为市值。"""
    return gold_stock_tonnes(d) * TROY_OZ_PER_TONNE


SUPPLY_FN = {"BTC": btc_supply, "GOLD": gold_supply}
