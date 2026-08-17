import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)
DB_PATH = Path(os.getenv("DB_PATH") or DATA_DIR / "market.db")

WEB_DIR = BASE_DIR / "web"

CMC_API_KEY = os.getenv("CMC_API_KEY", "").strip()
CMC_BASE_URL = "https://pro-api.coinmarketcap.com"

BTC_TICKER = "BTC-USD"
GOLD_TICKER = os.getenv("GOLD_TICKER", "GC=F")

# 新增资产：在这里加一条，并在 supply.py 的 SUPPLY_FN 里注册对应的供应量模型，
# 前端的勾选项和配色会自动跟着出现，不需要改前端代码。
ASSETS = {
    "BTC": {
        "name": "Bitcoin",
        "name_cn": "比特币",
        "ticker": BTC_TICKER,
        "supply_unit": "BTC",
        "price_unit": "USD",
        "color": "#f7931a",
    },
    "GOLD": {
        "name": "Gold",
        "name_cn": "黄金",
        "ticker": GOLD_TICKER,
        "supply_unit": "troy oz",
        "price_unit": "USD/oz",
        "color": "#ffd166",
    },
}

# 宏观指标。和资产不同，这些是单值序列（没有 OHLC），频率也不统一，
# 单独存在 macro_series 表里，不混进 daily_metrics。
#
# scale: 把源数据换算成基准单位。FRED 的 M2 以「十亿美元」计，所以要 ×1e9 变成美元；
#        利率本身就是百分数，保持原样。
# denominator: 能否作为「相对 XX」口径的分母。利率是比率，做分母没有意义。
MACRO = {
    "M2": {
        "name_cn": "M2 货币供应",
        "short_cn": "M2",
        "source": "fred",
        "series_id": "M2SL",
        "scale": 1e9,
        "unit": "USD",
        "freq": "monthly",
        "color": "#4c8dff",
        "denominator": True,
        "note": "月频，发布滞后约 2 个月",
    },
    "DEBT": {
        "name_cn": "美国联邦债务",
        "short_cn": "联邦债务",
        "source": "treasury",
        "series_id": "debt_to_penny",
        "scale": 1.0,
        "unit": "USD",
        "freq": "daily",
        "color": "#c678dd",
        "denominator": True,
        "note": "财政部每工作日更新",
    },
    "REAL10Y": {
        "name_cn": "10 年期实际利率",
        "short_cn": "实际利率",
        "source": "fred",
        "series_id": "DFII10",
        "scale": 1.0,
        "unit": "percent",
        "freq": "daily",
        "color": "#56b6c2",
        "denominator": False,
        "note": "10 年期 TIPS 收益率，黄金最强的单一驱动因子",
    },
}

FRED_CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv"
TREASURY_DEBT_URL = (
    "https://api.fiscaldata.treasury.gov/services/api/fiscal_service"
    "/v2/accounting/od/debt_to_penny"
)
