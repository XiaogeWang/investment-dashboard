#!/usr/bin/env bash
# 每日抓取一次行情并更新市值。由 crontab 调用，日志追加到 logs/ingest.log。
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"
mkdir -p logs

"$PROJECT_DIR/.venv/bin/python" -m app.ingest >> logs/ingest.log 2>&1
"$PROJECT_DIR/.venv/bin/python" -m app.export_static >> logs/ingest.log 2>&1
