---
name: VPS Hetzner
description: Accès et emplacements des services sur le VPS de production
---
# VPS Hetzner (production)

- Accès SSH : `sshpass -p "$VPS_SSH_PASSWORD" ssh root@<IP>` — l'IP est dans le secret `VPS_HOST`, mais la valeur contient IPv4 **et** IPv6 collées ; extraire l'IPv4 avec `grep -oE '([0-9]{1,3}\.){3}[0-9]{1,3}'`.
- Bot Telegram : `/root/Aiogram-Welcome-Bot/telegram-bot/`, service systemd `telegram-bot`.
- Site guardiola66.com : `/var/www/guardiola-site/public/` (pages HTML statiques, ex. `login.html`).
- La Mini App Telegram ouvre `https://www.guardiola66.com/login` (env `MINIAPP_URL`), pas la page splash du repo Replit.
- **Règle Mini App** : toute page servie à la Mini App doit charger `telegram-web-app.js` dans `<head>`, appeler `ready()`+`expand()` tôt, utiliser `var(--tg-viewport-height, 100dvh)` au lieu de `100vh`, et écouter `viewportChanged`.
