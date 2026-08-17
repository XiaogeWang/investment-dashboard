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
