#!/bin/bash
# Production startup — runs both the Express API server (splash screen) and the Telegram bot.
set -e

echo "[start.sh] Building API server…"
pnpm --filter @workspace/api-server run build

echo "[start.sh] Starting Telegram bot with supervision…"
# Supervision loop: restarts the bot if it exits for any reason.
# 'set +e' inside the subshell prevents 'set -e' (from the outer script) from
# aborting the loop when python3 exits with a non-zero code.
# In production, bot.py retries TelegramConflictError internally — the outer
# loop is a failsafe for unexpected crashes only.
(
  set +e
  while true; do
    echo "[start.sh] Starting bot process…"
    python3 telegram-bot/bot.py
    EXIT_CODE=$?
    echo "[start.sh] Bot exited with code ${EXIT_CODE}. Restarting in 5 s…"
    sleep 5
  done
) &

echo "[start.sh] Starting API server on PORT=${PORT}…"
# exec replaces this shell; if Express exits the container restarts automatically.
cd artifacts/api-server
exec node --enable-source-maps ./dist/index.mjs
