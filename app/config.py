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
# group: 宏观页里的分组，决定它出现在哪个视图。
#
# unit 还决定了做相关性分析时怎么去趋势（见 analysis.py）：
# percent 的序列用「差分」（2% → 4% 是 +2 个百分点，不是 +100%，而且跨零时百分比变化会爆炸），
# 其余用「百分比变化」。
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
        "group": "money",
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
        "group": "debt",
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
        "group": "rate",
        "note": "10 年期 TIPS 收益率，黄金最强的单一驱动因子",
    },

    # ---- 利率期限结构 ----
    # DGS10 ≈ REAL10Y + BREAK10Y（名义 = 实际 + 通胀预期），三者可以拆出
    # 「利率上涨到底来自通胀预期还是真实资金成本」。
    "FEDFUNDS": {
        "name_cn": "联邦基金利率",
        "short_cn": "政策利率",
        "source": "fred",
        "series_id": "DFF",
        "scale": 1.0,
        "unit": "percent",
        "freq": "daily",
        "color": "#98a2b8",
        "denominator": False,
        "group": "rate",
        "note": "有效联邦基金利率，美联储实际政策利率",
    },
    "DGS3MO": {
        "name_cn": "3 个月期国债利率",
        "short_cn": "3个月",
        "source": "fred",
        "series_id": "DGS3MO",
        "scale": 1.0,
        "unit": "percent",
        "freq": "daily",
        "color": "#7dd3c0",
        "denominator": False,
        "group": "rate",
        "note": "1981 年至今",
    },
    "DGS2": {
        "name_cn": "2 年期国债利率",
        "short_cn": "2年期",
        "source": "fred",
        "series_id": "DGS2",
        "scale": 1.0,
        "unit": "percent",
        "freq": "daily",
        "color": "#45b7e8",
        "denominator": False,
        "group": "rate",
        "note": "对美联储政策预期最敏感",
    },
    "DGS10": {
        "name_cn": "10 年期国债利率",
        "short_cn": "10年期",
        "source": "fred",
        "series_id": "DGS10",
        "scale": 1.0,
        "unit": "percent",
        "freq": "daily",
        "color": "#f0883e",
        "denominator": False,
        "group": "rate",
        "note": "全球资产定价的基准利率，1962 年至今",
    },
    "DGS30": {
        "name_cn": "30 年期国债利率",
        "short_cn": "30年期",
        "source": "fred",
        "series_id": "DGS30",
        "scale": 1.0,
        "unit": "percent",
        "freq": "daily",
        "color": "#e05c5c",
        "denominator": False,
        "group": "rate",
        "note": "1977 年至今，中间有一段停发",
    },
    "SPREAD10Y2Y": {
        "name_cn": "10 年 − 2 年期限利差",
        "short_cn": "期限利差",
        "source": "fred",
        "series_id": "T10Y2Y",
        "scale": 1.0,
        "unit": "percent",
        "freq": "daily",
        "color": "#d8a657",
        "denominator": False,
        "group": "spread",
        "note": "小于 0 即收益率曲线倒挂，历史上是衰退的领先信号",
    },
    "BREAK10Y": {
        "name_cn": "10 年期盈亏平衡通胀率",
        "short_cn": "通胀预期",
        "source": "fred",
        "series_id": "T10YIE",
        "scale": 1.0,
        "unit": "percent",
        "freq": "daily",
        "color": "#b48ead",
        "denominator": False,
        "group": "rate",
        "note": "市场隐含的未来 10 年通胀预期，2003 年至今",
    },

    # ---- 股指 ----
    # 指数点位不是市值（换算成市值需要股本数据），所以放在宏观序列里而不是 ASSETS。
    "IXIC": {
        "name_cn": "纳斯达克综合指数",
        "short_cn": "纳斯达克",
        "source": "yahoo",
        "series_id": "^IXIC",
        "scale": 1.0,
        "unit": "index",
        "freq": "daily",
        "color": "#98c379",
        "denominator": False,
        "group": "equity",
        "note": "长久期成长股占比高，对利率最敏感，1971 年至今",
    },
    "GSPC": {
        "name_cn": "标普 500 指数",
        "short_cn": "标普500",
        "source": "yahoo",
        "series_id": "^GSPC",
        "scale": 1.0,
        "unit": "index",
        "freq": "daily",
        "color": "#61afef",
        "denominator": False,
        "group": "equity",
        "note": "做纳斯达克的对照，1927 年至今",
    },
}

# 宏观页各视图用到的分组
MACRO_GROUPS = {
    "rate": "利率",
    "spread": "利差",
    "equity": "股指",
    "debt": "债务",
    "money": "货币",
}

FRED_CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv"
TREASURY_DEBT_URL = (
    "https://api.fiscaldata.treasury.gov/services/api/fiscal_service"
    "/v2/accounting/od/debt_to_penny"
)
