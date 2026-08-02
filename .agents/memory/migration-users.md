---
name: Migration utilisateurs dev → prod
description: Comment les 97 utilisateurs réels sont injectés en production
---

## Règle

`telegram-bot/migrate_users.py` contient une liste hardcodée des 97 utilisateurs (Telegram user_id, username, etc.) et fait un UPSERT avec `ON CONFLICT DO NOTHING`.

**Why:** La prod était vide (0 users) car le déploiement ne lançait pas start.sh. Les données réelles ne sont que dans la DB dev. Ce script permet de les pousser sans risque de doublon.

**How to apply:**
- Le script est appelé automatiquement par `start.sh` à chaque démarrage prod
- Il est idempotent — peut être relancé sans risque
- Si de nouveaux utilisateurs s'ajoutent en dev et qu'il faut les pousser en prod, mettre à jour la liste dans `migrate_users.py` et republier
- Pour forcer une migration manuelle sans redéploiement : `python3 telegram-bot/migrate_users.py` (nécessite `DATABASE_URL` prod)
