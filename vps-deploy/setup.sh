#!/bin/bash
# ═══════════════════════════════════════════════════════════════════════════════
#  Guardiola Farm 66 — Script d'installation VPS Ubuntu
#  Usage : sudo bash setup.sh
# ═══════════════════════════════════════════════════════════════════════════════
set -euo pipefail

DEPLOY_DIR="$(cd "$(dirname "$0")" && pwd)"
INSTALL_DIR="/opt/guardiola"
SERVICE_USER="guardiola"
DB_NAME="guardiola_bot"
DB_USER="guardiola"

echo ""
echo "╔══════════════════════════════════════════════════╗"
echo "║   Guardiola Farm 66 — Installation VPS           ║"
echo "╚══════════════════════════════════════════════════╝"
echo ""

# ── 1. Vérification des droits ─────────────────────────────────────────────────
if [[ $EUID -ne 0 ]]; then
  echo "❌  Ce script doit être lancé en root (sudo bash setup.sh)"
  exit 1
fi

# ── 2. Mise à jour système + dépendances ───────────────────────────────────────
echo "📦  Installation des dépendances système…"
apt-get update -qq
apt-get install -y -qq \
  python3 python3-pip python3-venv \
  nodejs npm \
  postgresql postgresql-contrib \
  nginx certbot python3-certbot-nginx \
  curl git

# ── 3. Création utilisateur système ───────────────────────────────────────────
echo "👤  Création de l'utilisateur $SERVICE_USER…"
id -u "$SERVICE_USER" &>/dev/null || useradd --system --no-create-home --shell /bin/false "$SERVICE_USER"

# ── 4. PostgreSQL — création base & utilisateur ────────────────────────────────
echo "🗄️   Configuration PostgreSQL…"
DB_PASS=$(openssl rand -base64 24 | tr -d '/+=')

# Crée l'utilisateur et la base s'ils n'existent pas
sudo -u postgres psql -tc "SELECT 1 FROM pg_user WHERE usename = '$DB_USER'" | grep -q 1 || \
  sudo -u postgres psql -c "CREATE USER $DB_USER WITH PASSWORD '$DB_PASS';"

sudo -u postgres psql -tc "SELECT 1 FROM pg_database WHERE datname = '$DB_NAME'" | grep -q 1 || \
  sudo -u postgres psql -c "CREATE DATABASE $DB_NAME OWNER $DB_USER;"

DATABASE_URL="postgresql://${DB_USER}:${DB_PASS}@localhost:5432/${DB_NAME}"
echo "✅  Base de données : $DATABASE_URL"

# ── 5. Création des répertoires ───────────────────────────────────────────────
echo "📁  Création des répertoires…"
mkdir -p "$INSTALL_DIR"/{bot,miniapp/public,logs}

# ── 6. Copie des fichiers bot Python ──────────────────────────────────────────
echo "🤖  Copie des fichiers bot…"
cp "$DEPLOY_DIR/../telegram-bot/bot.py"          "$INSTALL_DIR/bot/"
cp "$DEPLOY_DIR/../telegram-bot/database.py"     "$INSTALL_DIR/bot/"
cp "$DEPLOY_DIR/../telegram-bot/migrate_users.py" "$INSTALL_DIR/bot/"
cp "$DEPLOY_DIR/../telegram-bot/requirements.txt" "$INSTALL_DIR/bot/"
[ -f "$DEPLOY_DIR/../telegram-bot/welcome.jpg" ] && cp "$DEPLOY_DIR/../telegram-bot/welcome.jpg" "$INSTALL_DIR/bot/"

# ── 7. Copie de la Mini App ───────────────────────────────────────────────────
echo "🌐  Copie de la Mini App…"
cp "$DEPLOY_DIR/miniapp/server.js"   "$INSTALL_DIR/miniapp/"
cp "$DEPLOY_DIR/miniapp/package.json" "$INSTALL_DIR/miniapp/"
cp "$DEPLOY_DIR/../artifacts/api-server/public/index.html" "$INSTALL_DIR/miniapp/public/"
[ -f "$DEPLOY_DIR/../artifacts/api-server/public/logo.webp" ] && \
  cp "$DEPLOY_DIR/../artifacts/api-server/public/logo.webp" "$INSTALL_DIR/miniapp/public/"

# ── 8. Dépendances Python ─────────────────────────────────────────────────────
echo "🐍  Installation dépendances Python…"
pip3 install -q -r "$INSTALL_DIR/bot/requirements.txt"

# ── 9. Dépendances Node.js ────────────────────────────────────────────────────
echo "⬢   Installation dépendances Node.js…"
cd "$INSTALL_DIR/miniapp" && npm install --silent --production

# ── 10. Fichier .env ──────────────────────────────────────────────────────────
if [ ! -f "$INSTALL_DIR/.env" ]; then
  echo ""
  echo "⚠️   Fichier .env non trouvé — création depuis le modèle."
  cp "$DEPLOY_DIR/.env.example" "$INSTALL_DIR/.env"
  # Injecte automatiquement DATABASE_URL
  sed -i "s|DATABASE_URL=.*|DATABASE_URL=$DATABASE_URL|" "$INSTALL_DIR/.env"
  echo ""
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo "  ✏️   ÉDITEZ ce fichier avant de continuer :"
  echo "       nano $INSTALL_DIR/.env"
  echo ""
  echo "  Variables à remplir :"
  echo "    BOT_TOKEN   → votre token BotFather"
  echo "    ADMIN_ID    → votre Telegram user ID"
  echo "    MINIAPP_URL → https://VOTRE_DOMAINE/api"
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo ""
  read -rp "Appuyez sur Entrée une fois .env complété…"
fi

# ── 11. Migration des utilisateurs ────────────────────────────────────────────
echo "📊  Migration des utilisateurs…"
export $(grep -v '^#' "$INSTALL_DIR/.env" | xargs)
python3 "$INSTALL_DIR/bot/migrate_users.py" && echo "✅  Migration OK" || echo "⚠️   Migration ignorée (déjà fait ou erreur bénigne)"

# ── 12. Permissions ───────────────────────────────────────────────────────────
echo "🔒  Application des permissions…"
chown -R "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR"
chmod 600 "$INSTALL_DIR/.env"

# ── 13. Services systemd ──────────────────────────────────────────────────────
echo "⚙️   Installation des services systemd…"
cp "$DEPLOY_DIR/services/guardiola-bot.service"     /etc/systemd/system/
cp "$DEPLOY_DIR/services/guardiola-miniapp.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable guardiola-bot guardiola-miniapp
systemctl restart guardiola-miniapp
sleep 2
systemctl restart guardiola-bot

# ── 14. Nginx ─────────────────────────────────────────────────────────────────
echo "🌍  Configuration nginx…"
cp "$DEPLOY_DIR/nginx/guardiola.conf" /etc/nginx/sites-available/guardiola
ln -sf /etc/nginx/sites-available/guardiola /etc/nginx/sites-enabled/guardiola
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl reload nginx

# ── 15. Rapport ───────────────────────────────────────────────────────────────
echo ""
echo "╔══════════════════════════════════════════════════╗"
echo "║   ✅  Installation terminée !                    ║"
echo "╚══════════════════════════════════════════════════╝"
echo ""
echo "  Statut des services :"
systemctl is-active guardiola-bot     && echo "  ✅ guardiola-bot     : actif" || echo "  ❌ guardiola-bot     : ERREUR"
systemctl is-active guardiola-miniapp && echo "  ✅ guardiola-miniapp : actif" || echo "  ❌ guardiola-miniapp : ERREUR"
echo ""
echo "  Commandes utiles :"
echo "    journalctl -fu guardiola-bot       — logs bot en temps réel"
echo "    journalctl -fu guardiola-miniapp   — logs Mini App en temps réel"
echo "    systemctl restart guardiola-bot    — redémarrer le bot"
echo "    curl http://localhost:8080/api/healthz — tester la Mini App"
echo ""
echo "  ⚠️   SSL/HTTPS : sudo certbot --nginx -d VOTRE_DOMAINE.com"
echo ""
