#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
#  Guardiola Farm 66 — Démarrage LOCAL (test avant déploiement)
#  Lance le bot + la Mini App depuis le répertoire courant du projet
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="$ROOT/vps-deploy/.env.local"

echo "🔍  Racine du projet : $ROOT"

# Crée .env.local depuis l'exemple si absent
if [ ! -f "$ENV_FILE" ]; then
  cp "$ROOT/vps-deploy/.env.example" "$ENV_FILE"
  echo ""
  echo "⚠️   Renseignez $ENV_FILE puis relancez ce script."
  exit 1
fi

export $(grep -v '^#' "$ENV_FILE" | xargs)

# ── Mini App (Node) ───────────────────────────────────────────────────────────
echo "🌐  Démarrage Mini App sur le port ${PORT:-8080}…"
cd "$ROOT/vps-deploy/miniapp"
[ ! -d node_modules ] && npm install --silent
PORT="${PORT:-8080}" node server.js &
MINIAPP_PID=$!

sleep 1
echo "✅  Mini App PID=$MINIAPP_PID — http://localhost:${PORT:-8080}/api/"

# ── Bot Python ────────────────────────────────────────────────────────────────
echo "🤖  Démarrage bot Python…"
cd "$ROOT"
pip3 install -q -r telegram-bot/requirements.txt
python3 telegram-bot/bot.py &
BOT_PID=$!

echo "✅  Bot PID=$BOT_PID"
echo ""
echo "  Ctrl+C pour tout arrêter."

# Arrêt propre sur Ctrl+C
trap "kill $MINIAPP_PID $BOT_PID 2>/dev/null; echo 'Arrêté.'; exit 0" INT TERM

wait
