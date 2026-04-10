# BingeBear TV Bot

Bot Telegram multifonction pour BingeBear TV : streaming IPTV via PyTgCalls, transfert de news multi-canaux avec analyse IA Claude et dedup de contenu, rappels recurrents, campagnes promotionnelles.

## Fonctionnalites

- **Transfert automatique de news** depuis plusieurs canaux source vers le canal destination
  - Deduplication double index (source + contenu) anti-doublons entre canaux
  - Filtrage regex rapide pour les patterns connus
  - Analyse Claude API pour les messages ambigus (pannes, urgences)
  - Polling automatique toutes les 2h
- **Streaming IPTV** dans les vocal chats Telegram via PyTgCalls (WebRTC)
- **Campagnes promotionnelles** programmees (intervalle ou jours specifiques, 5 templates)
- **Rappels recurrents** configurables
- **Annonces admin** dans le canal
- **Reponses en DM prive** pour garder le canal propre

## Architecture

```
run_all.py              # Point d'entree principal
news_cache.py           # Cache double index (source + contenu)
claude_processor.py     # Integration Claude API
promotions.py           # Campagnes promo + scheduling
reminders.py            # Rappels recurrents
news_queue.py           # File rate-limited
stream_state.py         # Auto-resume stream
health.py               # HTTP health check
config.py               # Validation env
logger.py               # Logging structure
utils/retry.py          # Retry exponential backoff
Dockerfile              # Image Docker (Python 3.11 + FFmpeg)
requirements.txt        # Dependances Python
.env.example            # Template configuration
DOCUMENTATION.md        # Documentation technique complete
```

## Deploiement (Railway)

```bash
npm install -g @railway/cli
railway login
railway init
railway up
railway variables set BOT_TOKEN=... API_ID=... ...
railway logs
```

## Configuration

Variables d'environnement (voir `.env.example`) :

**Requises** : `API_ID`, `API_HASH`, `BOT_TOKEN`, `CHAT_ID`, `SESSION_STRING`

**News** : `NEWS_SOURCE_CHANNELS` (liste d'IDs separes par virgules), `NEWS_DEST_CHANNEL`, `ANTHROPIC_API_KEY` (optionnel)

**IPTV** : `IPTV_SERVER_URL`, `IPTV_USERNAME`, `IPTV_PASSWORD`

## Commandes

| Commande | Description |
|----------|-------------|
| `/categories` | Liste des categories IPTV |
| `/cat <id>` | Chaines d'une categorie |
| `/play <id>` | Lancer un stream |
| `/stop` | Arreter le stream |
| `/importnews [jours]` | Importer les news (admin) |
| `/announcement <msg>` | Poster dans le canal (admin) |
| `/promos` | Panel campagnes promo (admin) |
| `/addpromo` | Creer une campagne (admin) |
| `/reminder <intervalle> <msg>` | Rappel recurrent (admin) |

Voir [DOCUMENTATION.md](DOCUMENTATION.md) pour la documentation technique complete.
