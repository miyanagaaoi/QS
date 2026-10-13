#!/usr/bin/env bash
# 前后端一起启动（开发环境，Windows Git Bash / Linux 通用）
# 用法：bash scripts/dev-all.sh
# 说明：前端首次运行会自动 npm install；两个进程任一退出则整体退出。
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

cleanup() {
  echo
  echo "[停止] 正在关闭子进程……"
  [ -n "${BACK_PID:-}" ] && kill "$BACK_PID" 2>/dev/null || true
  [ -n "${FRONT_PID:-}" ] && kill "$FRONT_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

echo "[1/2] 启动后端 …"
bash "$ROOT/scripts/dev-backend.sh" &
BACK_PID=$!

echo "[2/2] 启动前端 …"
cd "$ROOT/frontend"
if [ ! -d node_modules ]; then
  echo "[提示] 首次运行，安装前端依赖（npm install）……"
  npm install --no-audit --no-fund
fi
npm run dev &
FRONT_PID=$!

wait -n "$BACK_PID" "$FRONT_PID" 2>/dev/null || wait
