---
name: Production deployment entrypoint
description: Comment le bot + API démarrent en production via artifact.toml
---

## Règle

`artifacts/api-server/.replit-artifact/artifact.toml` doit avoir :

```toml
[services.production.run]
args = ["bash", "start.sh"]
```

**Why:** En mode monorepo/artifact Replit, le `.replit` racine (`deployment.run`) est ignoré. Seul `artifact.toml` contrôle ce qui tourne en production. Si on pointe directement sur `node`, le bot Telegram ne démarre jamais.

**How to apply:** Toute modification du run de production doit passer par `verifyAndReplaceArtifactToml`. Après chaque changement, l'utilisateur doit republier (Publish) pour que ça prenne effet.

## Ce que fait start.sh

1. `pnpm --filter @workspace/api-server run build` — build Express
2. `python3 telegram-bot/migrate_users.py` — UPSERT 97 utilisateurs (idempotent)
3. Bot Python lancé en boucle de supervision (background, redémarre toutes les 5s si crash)
4. `exec node --enable-source-maps ./dist/index.mjs` — Express en foreground (signal de vie pour le container)
