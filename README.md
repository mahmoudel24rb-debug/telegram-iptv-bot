# BingeBear TV Bot

Bot Telegram multifonction pour BingeBear TV : streaming IPTV via PyTgCalls, transfert de news avec analyse IA Claude, rappels recurrents, campagnes promotionnelles, et plus.

## Fonctionnalites

- **Streaming IPTV** dans les vocal chats Telegram via PyTgCalls (WebRTC)
- **Transfert automatique de news** depuis un canal source vers `@bingebeartv_live`
  - Filtrage regex rapide pour les patterns connus
  - Analyse Claude API pour les messages ambigus (pannes, urgences, etc.)
  - Polling automatique toutes les 2h en backup
- **Campagnes promotionnelles** programmees (intervalle ou jours specifiques)
- **Rappels recurrents** configurables
- **Annonces admin** dans le canal
- **Reponses en DM prive** pour garder le canal propre

## Architecture

```
TelegramIPTVBot/
  python-bot/              # Code de production (deploye sur Railway)
    run_all.py             # Point d'entree principal
    promotions.py          # Module campagnes promo
    claude_processor.py    # Integration Claude API
    reminders.py           # Module rappels recurrents
    news_cache.py          # Cache anti-doublon
    news_queue.py          # File rate-limited
    stream_state.py        # Auto-resume du stream
    health.py              # HTTP health check
    config.py              # Validation env
    logger.py              # Logging structure
    utils/retry.py         # Retry exponential backoff
    Dockerfile             # Image Docker (Python 3.11 + FFmpeg)
    requirements.txt       # Dependances Python
    .env.example           # Template configuration
  Dockerfile               # Build racine (copie python-bot/)
  Procfile                 # Pour Heroku/Railway worker
  nixpacks.toml            # Config Nixpacks (Railway)
  docker-compose.yml       # Pour deploiement Docker local
  DOCUMENTATION.md         # Documentation technique complete
  PLAN.md                  # Plan de refactoring
  deploy/                  # Scripts VPS (legacy, archive)
```

## Deploiement (Railway)

Le bot tourne sur Railway via le Dockerfile dans `python-bot/`.

```bash
# Installer le CLI Railway
npm install -g @railway/cli

# Se connecter
railway login

# Depuis le dossier python-bot/
cd python-bot
railway init
railway up

# Configurer les variables d'environnement
railway variables set BOT_TOKEN=... API_ID=... ...

# Voir les logs
railway logs
```

## Configuration

Toutes les variables d'environnement sont documentees dans `python-bot/.env.example`. Les variables requises :

- `API_ID`, `API_HASH` (Telegram, depuis my.telegram.org)
- `BOT_TOKEN` (depuis @BotFather)
- `CHAT_ID` (username du groupe/canal cible)
- `SESSION_STRING` (genere via `python-bot/generate_session.py`)
- `IPTV_SERVER_URL`, `IPTV_USERNAME`, `IPTV_PASSWORD`
- `ANTHROPIC_API_KEY` (optionnel, pour l'analyse Claude des news)

## Commandes du bot

### Streaming IPTV
- `/categories` — Liste des categories
- `/cat <id>` — Chaines d'une categorie
- `/play <id>` — Lancer un stream
- `/stop` — Arreter le stream
- `/status` — Statut actuel
- `/test` — Test stream (Big Buck Bunny)

### News
- `/importnews [jours]` — Importer les news depuis X jours (admin)
- `/announcement <msg>` — Poster dans le canal (admin)

### Rappels recurrents
- `/reminder <intervalle> <msg>` — Creer un rappel (admin)
- `/reminders` — Liste des rappels (admin)
- `/delreminder <id>` — Supprimer (admin)

### Campagnes promotionnelles
- `/promos` — Panel admin avec boutons inline
- `/addpromo template <nom>` — Creer depuis un template
- `/addpromo interval <freq> <heure> <msg>` — Promo a intervalle
- `/addpromo days <jours> <heure> <msg>` — Promo sur jours specifiques
- `/editpromo <id> <msg>` — Modifier une promo
- `/delpromo <id>` — Supprimer une promo

### Diagnostic
- `/testlistener` — Tester le handler on_message Pyrogram (admin)
- `/help` — Liste de toutes les commandes

## Documentation

Pour plus de details sur l'architecture, les bugs connus, les choix techniques, voir [DOCUMENTATION.md](DOCUMENTATION.md).

## Licence

Usage prive — BingeBear TV.
