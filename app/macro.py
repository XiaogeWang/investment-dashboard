"""抓取宏观指标序列。

两个数据源都不需要 API Key：

- FRED 的 CSV 端点（fredgraph.csv?id=XXX）能直接下全历史。官方 REST API 要注册申请
  key，但这个 CSV 端点不用，正好保持整个项目零密钥、不必往 CI 里塞 secret。
- 美国财政部 FiscalData 的 debt_to_penny，公开无鉴权，1993 年至今每工作日一条。
"""

import csv
import io
import logging
import time
from datetime import datetime, timezone

import httpx

from .config import FRED_CSV_URL, MACRO, TREASURY_DEBT_URL

log = logging.getLogger("macro")

TIMEOUT = 90
RETRIES = 3
PAGE_SIZE = 10000  # 财政部接口允许的上限


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _get(url: str, params: dict) -> httpx.Response:
    """带重试的 GET。两个源偶尔会超时或限流，而这是每天只跑一次的任务，直接重试即可。"""
    last = None
    for attempt in range(1, RETRIES + 1):
        try:
            resp = httpx.get(url, params=params, timeout=TIMEOUT, follow_redirects=True)
            resp.raise_for_status()
            return resp
        except Exception as e:
            last = e
            if attempt < RETRIES:
                log.warning("请求失败 (%s/%s): %s，重试中", attempt, RETRIES, e)
                time.sleep(2 * attempt)
    raise last


def fetch_fred(series_id: str) -> list[tuple[str, float]]:
    """返回 [(date, value)]。FRED 用 '.' 表示缺失观测，跳过。"""
    resp = _get(FRED_CSV_URL, {"id": series_id})
    reader = csv.reader(io.StringIO(resp.text))
    header = next(reader, None)
    if not header or len(header) < 2:
        raise RuntimeError(f"FRED {series_id} 返回的 CSV 没有表头")

    out = []
    for row in reader:
        if len(row) < 2:
            continue
        d, raw = row[0].strip(), row[1].strip()
        if not d or raw in (".", ""):  # 停更/节假日等缺口
            continue
        try:
            out.append((d, float(raw)))
        except ValueError:
            continue
    if not out:
        raise RuntimeError(f"FRED {series_id} 没有解析出任何观测值")
    return out


def fetch_treasury_debt() -> list[tuple[str, float]]:
    """联邦债务总额（Total Public Debt Outstanding），每工作日一条。

    接口单页上限 10000 条，目前全量 8000 多条一页装得下，但再过几年就会超。
    这里老实翻页，避免将来悄悄被截断只拿到前 10000 条。
    """
    out: list[tuple[str, float]] = []
    page = 1
    while True:
        resp = _get(TREASURY_DEBT_URL, {
            "sort": "record_date",
            "page[size]": PAGE_SIZE,
            "page[number]": page,
            "fields": "record_date,tot_pub_debt_out_amt",
        })
        data = resp.json().get("data", [])
        for r in data:
            raw = r.get("tot_pub_debt_out_amt")
            if raw in (None, "", "null"):  # 早期记录部分字段为 null
                continue
            try:
                out.append((r["record_date"], float(raw)))
            except (ValueError, KeyError):
                continue
        if len(data) < PAGE_SIZE:
            break
        page += 1

    if not out:
        raise RuntimeError("财政部债务接口没有返回可用数据")
    return out


def fetch_series(key: str) -> list[dict]:
    """按配置抓一个指标，换算好单位后返回可直接入库的行。"""
    meta = MACRO[key]
    source = meta["source"]
    if source == "fred":
        raw = fetch_fred(meta["series_id"])
        src = f"fred:{meta['series_id']}"
    elif source == "treasury":
        raw = fetch_treasury_debt()
        src = "treasury:debt_to_penny"
    else:
        raise ValueError(f"未知数据源: {source}")

    scale, now = meta["scale"], _now()
    return [{"series": key, "date": d, "value": v * scale, "source": src, "updated_at": now}
            for d, v in raw]
