---
name: BOT_ENV convention
description: Comment BOT_ENV contrôle le mode dev/prod du bot et évite les conflits de polling
---

## Règle

- `bot.py` ligne ~1082 : `bot_env = os.environ.get("BOT_ENV", "production")` — **défaut production**
- Le workflow dev ("Telegram Bot") passe `BOT_ENV=development` explicitement
- En production (`start.sh`), aucun `BOT_ENV` n'est défini → le bot se comporte correctement en prod

**Why:** Sans cette convention, un bot dev lancé sans variable d'env se croirait en production et entrerait en conflit de polling avec le vrai bot prod (double polling = `TelegramConflictError`).

**How to apply:**
- Ne JAMAIS retirer `BOT_ENV=development` du workflow "Telegram Bot"
- Ne JAMAIS setter `BOT_ENV=production` dans `start.sh` (inutile, c'est le défaut)
- La table `bot_heartbeat` fournit une couche supplémentaire de protection contre les conflits
