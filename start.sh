#!/bin/bash
# Production startup — runs both the Express API server (splash screen) and the Telegram bot.
set -e

echo "[start.sh] Building API server…"
pnpm --filter @workspace/api-server run build

echo "[start.sh] Starting Telegram bot in background…"
python3 telegram-bot/bot.py &
BOT_PID=$!

echo "[start.sh] Starting API server on PORT=${PORT}…"
# exec replaces this shell; if Express exits the container restarts automatically.
cd artifacts/api-server
exec node --enable-source-maps ./dist/index.mjs
