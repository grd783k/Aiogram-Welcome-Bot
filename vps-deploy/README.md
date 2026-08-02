# Guardiola Farm 66 — Guide de déploiement VPS

## Contenu du package

```
vps-deploy/
├── miniapp/
│   ├── server.js          ← Serveur Express standalone (Mini App)
│   └── package.json
├── services/
│   ├── guardiola-bot.service      ← Service systemd bot Python
│   └── guardiola-miniapp.service  ← Service systemd Mini App
├── nginx/
│   └── guardiola.conf     ← Config nginx reverse-proxy
├── .env.example           ← Modèle de variables d'environnement
├── setup.sh               ← Script d'installation automatique
├── start-dev.sh           ← Démarrage local pour tests
└── README.md              ← Ce fichier
```

Les fichiers source du bot sont dans `telegram-bot/` et la Mini App dans `artifacts/api-server/public/`.

---

## Fonctionnalités incluses (toutes présentes dans le code)

| # | Fonctionnalité | Fichier |
|---|---|---|
| 1 | Animation chargement 0 → 100% | `artifacts/api-server/public/index.html` |
| 2 | Logo Guardiola Farm 66 | `artifacts/api-server/public/logo.webp` |
| 3 | Mini App plein écran (`tg.expand()`) | `artifacts/api-server/public/index.html` |
| 4 | Écran de bienvenue animé | `artifacts/api-server/public/index.html` |
| 5 | Compteur total utilisateurs | `telegram-bot/bot.py` + `database.py` |
| 6 | Statistiques visites quotidiennes | `telegram-bot/bot.py` + `database.py` |
| 7 | Programme fidélité (Bronze/Argent/Or/Diamant) | `telegram-bot/bot.py` + `database.py` |
| 8 | Suppression auto messages après 1h | `telegram-bot/bot.py` (`DELETE_AFTER=3600`) |
| 9 | Notification admin au `/start` | `telegram-bot/bot.py` (`_notify_admin_reliable`) |
| 10 | Boutons Réseaux sociaux | `telegram-bot/bot.py` (`social_keyboard`) |
| 11 | Bouton Retour à l'accueil | `telegram-bot/bot.py` (`home_button_keyboard`) |
| 12 | Messages auto midi (ouverture) / minuit (suppression) | `telegram-bot/bot.py` (`scheduler_open/close`) |
| 13 | Commandes admin (`/ladmin`, `/stats`, `/broadcast`) | `telegram-bot/bot.py` |
| 14 | Tables PostgreSQL créées automatiquement | `telegram-bot/database.py` (`init_db`) |

---

## Installation rapide (VPS Ubuntu 22.04+)

### Prérequis
- VPS Ubuntu 22.04 ou 24.04
- Accès root (ou sudo)
- Un domaine pointant vers le VPS (pour HTTPS)

### Étape 1 — Copier le projet sur le VPS

```bash
# Option A : depuis Replit (export zip + upload)
scp -r /chemin/vers/projet root@IP_VPS:/tmp/guardiola

# Option B : git clone si le repo est sur GitHub
git clone https://github.com/ton-repo /tmp/guardiola
```

### Étape 2 — Lancer l'installation automatique

```bash
cd /tmp/guardiola
sudo bash vps-deploy/setup.sh
```

Le script fait automatiquement :
1. Installation des dépendances (Python, Node, PostgreSQL, Nginx)
2. Création de l'utilisateur système `guardiola`
3. Création de la base de données PostgreSQL avec mot de passe aléatoire
4. Copie de tous les fichiers dans `/opt/guardiola/`
5. Installation des dépendances Python et Node
6. Migration des 97 utilisateurs existants
7. Création et activation des services systemd
8. Configuration Nginx

### Étape 3 — Compléter le fichier `.env`

Le script t'arrête à cette étape et te demande de compléter :

```bash
nano /opt/guardiola/.env
```

```env
BOT_TOKEN=TON_TOKEN_BOTFATHER
DATABASE_URL=postgresql://guardiola:MOTDEPASSE@localhost:5432/guardiola_bot  ← généré auto
ADMIN_ID=TON_TELEGRAM_USER_ID
MINIAPP_URL=https://TON_DOMAINE.com/api
BOT_ENV=production
```

### Étape 4 — Configurer nginx + HTTPS

```bash
# Remplace le domaine dans la config nginx
nano /etc/nginx/sites-available/guardiola
# Remplace TON_DOMAINE.com par ton vrai domaine

# Active HTTPS avec Let's Encrypt
sudo certbot --nginx -d TON_DOMAINE.com

# Recharge nginx
sudo nginx -t && sudo systemctl reload nginx
```

### Étape 5 — Mettre à jour MINIAPP_URL dans le bot

```bash
nano /opt/guardiola/.env
# MINIAPP_URL=https://TON_DOMAINE.com/api
sudo systemctl restart guardiola-bot
```

---

## Gestion des services

```bash
# Statut
systemctl status guardiola-bot
systemctl status guardiola-miniapp

# Logs en temps réel
journalctl -fu guardiola-bot
journalctl -fu guardiola-miniapp

# Redémarrage
systemctl restart guardiola-bot
systemctl restart guardiola-miniapp

# Arrêt
systemctl stop guardiola-bot
systemctl stop guardiola-miniapp
```

---

## Test local avant déploiement

```bash
# Depuis la racine du projet Replit, en local
cp vps-deploy/.env.example vps-deploy/.env.local
nano vps-deploy/.env.local    # remplis BOT_TOKEN, DATABASE_URL, etc.
bash vps-deploy/start-dev.sh
```

---

## Architecture sur le VPS

```
Internet
   │
   ▼
Nginx :80/:443
   │
   ├── /api/*  →  Express (port 8080)  →  Mini App Telegram
   │                                       (index.html, logo.webp)
   │
   └── (bot Python polling directement Telegram, pas de port exposé)

PostgreSQL (localhost:5432)
   │
   ├── table users            ← comptes utilisateurs
   ├── table visits           ← statistiques visites quotidiennes
   ├── table loyalty_accounts ← programme fidélité
   ├── table loyalty_history  ← historique points
   ├── table daily_messages   ← messages midi/minuit
   ├── table broadcast_messages
   ├── table pending_deletions ← suppression auto 1h
   ├── table bot_heartbeat    ← anti-conflit dev/prod
   └── table config
```

---

## Dépannage

| Problème | Solution |
|---|---|
| Bot ne démarre pas | `journalctl -u guardiola-bot -n 50` — vérifier BOT_TOKEN et DATABASE_URL |
| Mini App blanche | Vérifier que nginx proxy bien vers port 8080 (`curl localhost:8080/api/healthz`) |
| Erreur connexion DB | `psql $DATABASE_URL -c "\l"` — vérifier que la base existe |
| Logo manquant | `ls /opt/guardiola/miniapp/public/` — doit contenir `logo.webp` |
| Conflit de polling | Vérifier qu'un seul bot tourne : `ps aux | grep bot.py` |
