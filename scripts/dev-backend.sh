#!/usr/bin/env bash
# 后端开发启动脚本（Windows Git Bash / Linux 通用）
# 用法：bash scripts/dev-backend.sh
set -euo pipefail
cd "$(dirname "$0")/../backend"

PY="./.venv/Scripts/python.exe"
[ -x "$PY" ] || PY="./.venv/bin/python"
if [ ! -x "$PY" ]; then
  echo "[错误] 未找到虚拟环境，请先执行："
  echo "  cd backend && python -m venv .venv && ./.venv/Scripts/python.exe -m pip install -r requirements.txt"
  exit 1
fi

if [ ! -f .env ]; then
  echo "[提示] 未找到 backend/.env，正在从 .env.example 复制……"
  cp .env.example .env
  echo "[提示] 请修改 .env 中的 XUNJIA_SECRET_KEY 后重新启动。"
fi

echo "[启动] 后端 http://127.0.0.1:8000  文档 http://127.0.0.1:8000/docs"
exec "$PY" -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
