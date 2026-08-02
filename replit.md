# Guardiola Farm 66 Coffee — Telegram Bot

Bot Telegram de fidélité pour "Guardiola Farm 66 Coffee" (`@Guardiola66_bot`). Les clients ouvrent une Mini App Telegram pour voir leur solde de points, leur niveau, et leur historique. L'admin gère les points via `/ladmin`.

---

## Run & Operate

- `BOT_ENV=development python3 telegram-bot/bot.py` — lancer le bot en développement
- `pnpm --filter @workspace/api-server run dev` — lancer le serveur API (splash screen Mini App)
- `bash start.sh` — démarrage production complet (build API + migration + bot + serveur)
- `python3 telegram-bot/migrate_users.py` — ré-injecter les 97 utilisateurs en base (idempotent, ON CONFLICT DO NOTHING)

Secrets requis : `BOT_TOKEN`, `DATABASE_URL`, `SESSION_SECRET`, `ADMIN_ID`

---

## Stack

- **Bot** : Python 3, `python-telegram-bot` (polling en dev, webhook prévu en prod — tâche en cours)
- **Base de données** : PostgreSQL via `psycopg2` (`DATABASE_URL`)
- **Splash screen / Mini App** : Express 5, artifact `artifacts/api-server`, servi sur `/api`
- **Monorepo** : pnpm workspaces, Node.js 24, TypeScript 5.9

---

## Where things live

| Fichier | Rôle |
|---|---|
| `telegram-bot/bot.py` | Tous les handlers : fidélité, admin FSM, splash |
| `telegram-bot/database.py` | Init DB, fonctions CRUD loyalty + history |
| `telegram-bot/migrate_users.py` | UPSERT des 97 utilisateurs dev → prod (idempotent) |
| `start.sh` | Entrypoint production : build → migrate → bot (supervisé) → Express |
| `artifacts/api-server/` | Serveur Express (splash screen Mini App) |
| `artifacts/api-server/.replit-artifact/artifact.toml` | Config déploiement production |
| `artifacts/api-server/public/index.html` | Page splash Telegram Mini App |

---

## Architecture decisions

- **`BOT_ENV`** : défaut `"production"` dans `bot.py` (ligne ~1082). Le workflow dev le force à `"development"` explicitement. Ne jamais changer ce défaut.
- **Démarrage production via `start.sh`** : l'artifact.toml `[services.production.run]` pointe sur `bash start.sh`. C'est la **seule** façon de démarrer à la fois le bot et l'API en production. Ne pas le changer pour pointer directement sur node.
- **Supervision bot** : `start.sh` lance le bot dans une boucle `while true` en background, puis `exec node` pour l'API. Si le bot plante, il redémarre automatiquement toutes les 5 s.
- **Migration idempotente** : `migrate_users.py` utilise `ON CONFLICT DO NOTHING` — peut être relancé sans risque.
- **Tables DB** : toutes créées avec `CREATE TABLE IF NOT EXISTS` dans `database.py:init_db()`.
- **Conflit polling dev/prod** : résolu par la table `bot_heartbeat` + check avant polling. Transition vers webhook en cours (tâche projet active).

---

## Product

- Mini App Telegram : splash screen → tableau de bord fidélité (points, niveau Bronze/Argent/Or/Diamant, barre de progression, historique)
- Admin (`/ladmin`) : FSM avec ajout/retrait rapide ±1–5 pts + montant personnalisé + motif
- 97 utilisateurs réels (données dev migrées en prod via `migrate_users.py`)

---

## Gotchas

- **Ne jamais pointer `[services.production.run]` directement sur `node`** — le bot ne démarrerait pas. Toujours passer par `bash start.sh`.
- **Ne jamais retirer `BOT_ENV=development`** du workflow Telegram Bot — sans ça, le bot dev se croit en production et entre en conflit avec le bot prod.
- **Republier après chaque modif de `artifact.toml`** — les changements ne prennent effet en production qu'après un nouveau déploiement.
- **`migrate_users.py` ne tourne qu'au démarrage** (appelé par `start.sh`) — pour forcer une re-migration manuelle : `python3 telegram-bot/migrate_users.py` directement en prod.
- Bug mineur connu : `loyalty_callback` peut lever `TelegramBadRequest: message is not modified` — inoffensif, à wrapper dans un try/except si gênant.

---

## User preferences

- Langue de communication : français
- Le bot doit tourner 24/7 sans interruption
- Les données des 97 utilisateurs réels doivent toujours être présentes en production
