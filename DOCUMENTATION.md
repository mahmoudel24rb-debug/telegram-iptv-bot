# BingeBear TV Bot - Documentation Technique Complète

## Table des matières

1. [Vue d'ensemble](#1-vue-densemble)
2. [Architecture du projet](#2-architecture-du-projet)
3. [Stack technique](#3-stack-technique)
4. [Fichiers principaux en détail](#4-fichiers-principaux-en-détail)
5. [Système de streaming IPTV](#5-système-de-streaming-iptv)
6. [Système de transfert de news](#6-système-de-transfert-de-news)
7. [Commandes du bot](#7-commandes-du-bot)
8. [Authentification et autorisation](#8-authentification-et-autorisation)
9. [Modules de résilience](#9-modules-de-résilience)
10. [Variables d'environnement](#10-variables-denvironnement)
11. [Déploiement](#11-déploiement)
12. [Monitoring](#12-monitoring)
13. [Diagramme d'architecture](#13-diagramme-darchitecture)
14. [Historique des modifications](#14-historique-des-modifications)
15. [Diagnostic et debugging](#15-diagnostic-et-debugging)

---

## 1. Vue d'ensemble

**BingeBear TV Bot** est un bot Telegram multifonction qui :

1. **Diffuse du contenu IPTV** en streaming dans les groupes Telegram via PyTgCalls (WebRTC)
2. **Transfère automatiquement les actualités** d'un canal source vers un canal de destination avec filtrage intelligent et modifications de texte
3. **Offre une interface de commandes** pour contrôler le streaming, parcourir les catégories et importer des news

Le bot tourne 24/7 sur un VPS OVH (Ubuntu 25.04) via un service systemd avec auto-restart.

---

## 2. Architecture du projet

```
TelegramIPTVBot/
├── python-bot/                    # Application principale (production)
│   ├── run_all.py                 # Point d'entrée combiné (streaming + news)
│   ├── bot.py                     # Bot streaming uniquement (legacy)
│   ├── news_forwarder.py          # Forwarder de news standalone (legacy)
│   ├── config.py                  # Validation de la configuration
│   ├── logger.py                  # Logging structuré (console + fichier rotatif)
│   ├── health.py                  # Serveur HTTP de health check (port 8080)
│   ├── stream_state.py            # Persistance d'état du stream (auto-resume)
│   ├── news_cache.py              # Cache anti-doublon pour les news (JSON)
│   ├── news_queue.py              # File d'attente avec rate limiting
│   ├── utils/
│   │   └── retry.py               # Retry avec backoff exponentiel
│   ├── generate_session.py        # Utilitaire de génération de SESSION_STRING
│   ├── get_channel_id.py          # Utilitaire de découverte d'ID de canal
│   ├── test_*.py                  # Scripts de test (filtrage, envoi, stream)
│   ├── requirements.txt           # Dépendances Python
│   └── .env.example               # Template de configuration
├── deploy/                        # Scripts de déploiement VPS
│   ├── setup-vps.sh               # Installation initiale du VPS Ubuntu
│   ├── setup-monitoring.sh        # Configuration monitoring + cron
│   ├── monitor.sh                 # Health check + auto-recovery
│   ├── update-bot.sh              # Mise à jour et redémarrage
│   └── .env.example               # Template de config déploiement
├── docker-compose.yml             # Orchestration Docker (alternative)
└── README.md                      # Documentation utilisateur
```

### Fichiers legacy (non utilisés en production)
- `src/` — Ancienne implémentation Node.js (grammy + FFmpeg segmentation)
- `bot.py` (racine) — Ancien point d'entrée
- `wordpress-plugin/` — Plugin WordPress pour admin panel (non déployé)
- `session.txt` — Session GramJS Node.js (incompatible avec Pyrogram)

---

## 3. Stack technique

### Dépendances Python

| Package | Version | Rôle |
|---------|---------|------|
| python-telegram-bot | 21.10 | Framework bot Telegram (gestion des commandes) |
| pyrofork | 2.3.58 | Client utilisateur Pyrogram (accès canaux, écoute messages) |
| py-tgcalls | 2.2.10 | Streaming audio/vidéo dans les vocal chats Telegram (WebRTC) |
| python-dotenv | - | Chargement des variables d'environnement depuis `.env` |
| requests | - | Requêtes HTTP vers l'API IPTV (Xtream Codes) |
| tgcrypto | - | Cryptographie Telegram (accélère les opérations crypto) |
| aiohttp | - | Serveur HTTP asynchrone pour le health check |

### Prérequis système
- **Python 3.13** (VPS actuel) ou 3.11+
- **FFmpeg** avec libavcodec-extra (nécessaire pour PyTgCalls)

---

## 4. Fichiers principaux en détail

### `run_all.py` — Point d'entrée principal (production)

C'est le seul fichier lancé en production. Il combine toutes les fonctionnalités :

#### Initialisation
1. Charge les variables d'environnement (`.env`) via `python-dotenv`
2. Valide la configuration via `config.py` (vérifie les variables obligatoires)
3. Crée le client Pyrogram (`user_client`) si `SESSION_STRING` est présente
4. Crée le bot Telegram (`python-telegram-bot`) avec tous les handlers de commandes
5. Initialise PyTgCalls pour le streaming
6. Démarre le serveur de health check HTTP sur le port 8080

#### Mode dégradé (sans SESSION_STRING)
Si `SESSION_STRING` est absente, le bot fonctionne en mode réduit :
- Les commandes de base fonctionnent (`/start`, `/help`, `/status`, `/categories`, `/cat`)
- Le streaming est désactivé (pas de `/play`, `/stop`, `/test`)
- Le transfert de news est désactivé
- Un warning est loggé au démarrage

#### Variable `HAS_USER_CLIENT`
```python
if SESSION_STRING and SESSION_STRING != "votre_session_string_ici":
    user_client = Client("combined_session", ...)
    HAS_USER_CLIENT = True
else:
    user_client = None
    HAS_USER_CLIENT = False
```
Cette variable conditionne l'activation du streaming, du news handler et du watchdog.

#### Tâches de fond (lancées dans `post_init`)
```python
auto_resume_stream()    # Reprend le stream précédent si crash < 30 min
stream_watchdog()       # Surveille l'activité du stream toutes les 60s
news_queue.start()      # Démarre le worker de la file d'attente des news
```

#### Fonction `reply_private()`
Toutes les réponses aux commandes sont envoyées en **message privé** à l'utilisateur :
```python
async def reply_private(update, context, text):
    user_id = update.effective_user.id
    try:
        await context.bot.send_message(chat_id=user_id, text=text)
    except Exception:
        # Fallback si l'utilisateur n'a pas /start en privé
        await update.message.reply_text(text)
```
Cela garde le canal Telegram propre (pas de messages de log/commande visibles).

---

### `config.py` — Validation de la configuration

#### Variables obligatoires (le bot ne démarre pas sans) :
- `API_ID` — ID d'application Telegram
- `API_HASH` — Hash d'application Telegram
- `BOT_TOKEN` — Token du bot (@BotFather)
- `CHAT_ID` — Username du groupe/canal cible

#### Variables recommandées (warning si absentes) :
- `SESSION_STRING` — Session Pyrogram (streaming + news)
- `IPTV_SERVER_URL` — URL du serveur IPTV
- `IPTV_USERNAME` — Identifiant IPTV
- `IPTV_PASSWORD` — Mot de passe IPTV

#### Variables optionnelles avec valeurs par défaut :
- `ADMIN_IDS` : "" (vide = tous admins)
- `ALLOWED_USERNAMES` : "DefiMack"
- `NEWS_SOURCE_CHANNEL` : "-1001763758614"
- `NEWS_DEST_CHANNEL` : "@bingebeartv_live"
- `LOG_DIR` : "./logs"

---

### `logger.py` — Logging structuré

- **Console** : niveau INFO et supérieur
- **Fichier** : niveau DEBUG et supérieur avec rotation automatique
- **Rotation** : 10 MB par fichier, 5 fichiers de backup maximum
- **Format** : `%(asctime)s [%(levelname)s] %(name)s: %(message)s`
- **Encodage** : UTF-8
- **Usage** : `logger = setup_logger('bingebear.module')`

---

### `health.py` — Serveur HTTP de health check

Serveur HTTP asynchrone (aiohttp) sur le port 8080.

**Endpoint** : `GET /health`

**Réponse JSON** :
```json
{
    "status": "ok",
    "uptime_seconds": 3600,
    "is_streaming": true,
    "last_stream_activity": 1234567890.5,
    "last_news_forwarded": 1234567890.5
}
```

**Utilisé par** :
- Le script `monitor.sh` (cron toutes les 5 min)
- Docker health check
- Monitoring externe

---

### `stream_state.py` — Persistance et auto-resume du stream

- **Fichier** : `stream_state.json`
- **Contenu** : `{"channel": {"id": ..., "name": ..., "url": ...}, "timestamp": ...}`
- **TTL** : 30 minutes (configurable via `STREAM_STATE_MAX_AGE`)
- **Comportement** : Au redémarrage, si un état existe et a < 30 min, le stream reprend automatiquement

**Fonctions** :
```python
save_state(channel)         # Sauvegarde l'état actuel
load_state() -> dict|None   # Charge l'état précédent (None si trop vieux)
clear_state()               # Supprime le fichier (après /stop)
```

---

### `news_cache.py` — Cache anti-doublon

Empêche de transférer deux fois le même message après un redémarrage.

- **Fichier** : `news_cache.json`
- **Format** : `{message_id_str: timestamp}`
- **Capacité** : 500 entrées max (FIFO, les plus anciennes sont supprimées)
- **TTL** : 7 jours

**Méthodes** :
```python
is_forwarded(message_id) -> bool    # Vérifie si déjà envoyé
mark_forwarded(message_id)          # Marque comme envoyé
```

---

### `news_queue.py` — File d'attente avec rate limiting

Respecte les limites de taux de Telegram (~30 msg/sec par canal).

- **Délai minimum** entre envois : 1.5 secondes
- **Erreur 429** (rate limit) : pause de 30 secondes puis retry
- **Autres erreurs** : backoff exponentiel

**Méthodes** :
```python
async enqueue(send_func)    # Ajoute un envoi à la file
async start()               # Démarre le worker
```

---

### `utils/retry.py` — Retry avec backoff exponentiel

**Fonctions** :
```python
retry_async(func, max_retries=3, base_delay=1)   # Pour les fonctions async
retry_sync(func, max_retries=3, base_delay=1)     # Pour les fonctions sync
```

**Délais** : 1s → 2s → 4s (doublé à chaque tentative)

---

## 5. Système de streaming IPTV

### Flux de données complet

```
Commande /play <id>
    ↓
Vérification d'autorisation (is_allowed_user)
    ↓
Récupération de l'URL du flux via API IPTV (Xtream Codes)
    ↓
Arrêt du stream en cours (si existant)
    ↓
PyTgCalls.play(CHAT_ID, MediaStream(url))
    ↓
FFmpeg traite le flux IPTV en continu
    ↓
Audio/Vidéo envoyés au vocal chat du groupe Telegram (WebRTC)
    ↓
État sauvegardé dans stream_state.json
    ↓
Réponse envoyée en DM privé à l'utilisateur
```

### API IPTV (Xtream Codes)

Le bot communique avec un serveur IPTV via l'API Xtream Codes :

| Endpoint | Description |
|----------|-------------|
| `GET /player_api.php?action=get_live_categories` | Liste des catégories TV |
| `GET /player_api.php?action=get_live_streams&category_id=N` | Chaînes d'une catégorie |
| `GET /live/{user}/{pass}/{stream_id}.ts` | URL du flux live |

**Cache** : Les catégories et chaînes sont cachées en mémoire pour éviter les appels répétés.

**Retry** : Chaque appel API utilise `retry_sync()` avec backoff exponentiel (3 tentatives).

### Paramètres FFmpeg

```
-reconnect 1                    # Autorise la reconnexion
-reconnect_streamed 1           # Reconnexion sur les flux streamés
-reconnect_delay_max 5          # Délai max de reconnexion (5s)
-err_detect ignore_err          # Ignore les erreurs de décodage
```

### Watchdog

Le watchdog vérifie toutes les 60 secondes :
- Si `is_streaming=True` mais pas d'activité depuis 60s → redémarrage automatique du stream
- Log l'événement et met à jour le health check

---

## 6. Système de transfert de news

### Flux de données complet

```
Nouveau message dans le canal source (-1001763758614)
    ↓
Handler Pyrogram @on_message déclenché automatiquement
    ↓
Log diagnostic: [NEWS] Message recu (chat_id, msg_id, aperçu texte)
    ↓
Vérification dans le cache (news_cache : déjà transféré ?)
    ↓
Filtrage : ne contient pas de mots exclus ?
    ↓
Filtrage : correspond aux patterns d'inclusion ?
    ↓
Log: [NEWS] Message accepté pour transfert
    ↓
Modification du texte (rebranding, nettoyage)
    ↓
Téléchargement de l'image (si message contient une photo)
    ↓
Mise en file d'attente (NewsQueue, rate limiting 1.5s)
    ↓
Envoi via Bot API vers @bingebeartv_live
    ↓
Marquage dans le cache + suppression du fichier image temporaire
```

### Patterns de filtrage (`should_forward_news`)

Un message est transféré s'il correspond à **au moins un** de ces patterns regex :

| Pattern | Type de message | Exemple |
|---------|----------------|---------|
| `Dear Reseller,\s*\n\s*We are pleased` | Annonces de nouvelles chaînes/catégories | "Dear Reseller, We are pleased to launch..." |
| `^[A-Z\s]+VS\s+[A-Z\s]+` | Matchs sportifs | "FRANCE VS GERMANY" |
| `^LIVE EVENT` | Événements en direct | "LIVE EVENT - UFC 320..." |

> Les patterns utilisent les flags `re.IGNORECASE | re.MULTILINE`.

### Mots d'exclusion

Un message est **ignoré** s'il contient l'un de ces termes (vérification avant les patterns) :

| Mot/phrase | Raison |
|------------|--------|
| `domain has been suspended` | Message administratif |
| `purchase a private domain` | Publicité domaines |
| `misuse and multiple complaints` | Avertissements abus |
| `Queridos Revendedores` | Doublon espagnol |
| `Nos complace` | Doublon espagnol |

### Modifications appliquées au texte (`modify_news_message`)

Les transformations sont appliquées dans cet ordre :

1. **Suppression du contenu espagnol** : Bloc "Queridos Revendedores..." supprimé via regex `r'Queridos Revendedores.*?(?=Enjoy\.|Team|$)'` (flag `re.DOTALL`)
2. **Remplacement "Dear Reseller(s)"** : `Dear Reseller` ou `Dear Resellers` → `Dear Users`
3. **Nettoyage des sauts de ligne** : 3+ sauts de ligne consécutifs → 2
4. **Rebranding signature** : `Team 8K` (avec espaces variables) → `Team BingeBearTV`

### Support des images

Si le message source contient une photo :
1. L'image est téléchargée localement via Pyrogram (`message.download()`)
2. Envoyée via `bot.send_photo()` avec la caption modifiée
3. Le fichier temporaire est supprimé après envoi

---

## 7. Commandes du bot

| Commande | Paramètres | Autorisation | Description |
|----------|-----------|-------------|-------------|
| `/start` | - | Tous | Affiche le menu d'aide avec toutes les commandes |
| `/categories` | - | Tous | Liste toutes les catégories IPTV (paginé automatiquement) |
| `/cat` | `<id>` | Tous | Liste les chaînes d'une catégorie (paginé) |
| `/play` | `<id>` | Utilisateurs autorisés | Démarre le streaming d'une chaîne IPTV |
| `/stop` | - | Utilisateurs autorisés | Arrête le stream en cours |
| `/status` | - | Tous | Affiche le statut du stream actuel |
| `/test` | - | Utilisateurs autorisés | Lance un stream de test (Big Buck Bunny) |
| `/importnews` | `[jours]` | Admin uniquement | Importe les news des X derniers jours (1-30, défaut: 7) |
| `/help` | - | Tous | Affiche la liste des commandes |

### Pagination automatique

Les commandes `/categories` et `/cat` paginent les résultats :
- **Limite** : 3800 caractères par message (marge sous la limite Telegram de 4096)
- **Format** : "Categories (suite 2):", "Chaines (suite 3):", etc.
- **Total** affiché à la fin du dernier message

### Réponses en DM privé

**Toutes** les réponses aux commandes sont envoyées en message privé à l'utilisateur qui a lancé la commande, pas dans le canal/groupe. Cela garde le canal propre.

**Prérequis** : L'utilisateur doit avoir fait `/start` en privé avec `@Bingebear_tv_bot` au moins une fois pour que les DM fonctionnent.

---

## 8. Authentification et autorisation

### Niveaux d'accès

#### Admins (`ADMIN_IDS`)
- Liste d'IDs Telegram numériques séparés par des virgules
- Accès complet : toutes les commandes + `/importnews`
- **Si la liste est vide** : tous les utilisateurs sont considérés comme admins

#### Utilisateurs autorisés (`ALLOWED_USERNAMES`)
- Liste de noms d'utilisateur Telegram (sans @)
- Peuvent utiliser : `/play`, `/stop`, `/test`
- Les admins sont automatiquement autorisés

### Logique de vérification

```python
def is_admin(user_id):
    if not ADMIN_IDS:          # Pas d'admins définis
        return True            # Tout le monde est admin
    return user_id in ADMIN_IDS

def is_allowed_user(user):
    if is_admin(user.id):      # Les admins peuvent tout faire
        return True
    return user.username in ALLOWED_USERNAMES
```

---

## 9. Modules de résilience

### Auto-resume du stream
- Si le bot crash pendant un stream, il reprend automatiquement au redémarrage
- Condition : le crash date de moins de 30 minutes (`STREAM_STATE_MAX_AGE`)
- L'état est lu depuis `stream_state.json`

### Watchdog du stream
- Vérifie l'activité du stream toutes les 60 secondes
- Si `is_streaming=True` mais inactif depuis 60s → tentative de redémarrage

### Cache anti-doublon des news
- Persiste entre les redémarrages (fichier JSON)
- Empêche de transférer deux fois le même message
- Capacité : 500 entrées, TTL 7 jours

### Rate limiting des envois
- Délai de 1.5s entre chaque envoi de news
- Gestion automatique des erreurs 429 (Telegram rate limit)
- Backoff exponentiel pour les autres erreurs

### Retry avec backoff exponentiel
- Toutes les opérations réseau (API IPTV, Telegram) utilisent le retry
- 3 tentatives max avec délais de 1s → 2s → 4s

### Logging structuré
- Logs console (INFO+) et fichier (DEBUG+)
- Rotation automatique : 10 MB × 5 fichiers
- Permet le diagnostic en production

---

## 10. Variables d'environnement

### Obligatoires
```env
API_ID=33417585                              # ID d'application Telegram (my.telegram.org)
API_HASH=1fcac1db95bff35ca603b60c143f6856    # Hash d'application Telegram
BOT_TOKEN=<token>                            # Token du bot (@BotFather)
CHAT_ID=bingebeartv_live                     # Username du groupe/canal cible (sans @)
```

### Recommandées (nécessaires pour streaming + news)
```env
SESSION_STRING=<session_pyrogram>            # Session Pyrogram (générée par generate_session.py)
IPTV_SERVER_URL=http://...                   # URL du serveur IPTV Xtream Codes
IPTV_USERNAME=...                            # Identifiant IPTV
IPTV_PASSWORD=...                            # Mot de passe IPTV
```

### Optionnelles
```env
ADMIN_IDS=123456789,987654321                # IDs Telegram des admins (vide = tous admins)
ALLOWED_USERNAMES=DefiMack,User2             # Usernames autorisés pour le streaming
NEWS_SOURCE_CHANNEL=-1001763758614           # ID du canal source des news
NEWS_DEST_CHANNEL=@bingebeartv_live          # Canal de destination des news
LOG_DIR=./logs                               # Répertoire des logs
HEALTH_PORT=8080                             # Port du serveur health check
STREAM_STATE_FILE=./stream_state.json        # Fichier de persistance du stream
STREAM_STATE_MAX_AGE=1800                    # Durée max de l'état sauvegardé (30 min en sec)
NEWS_CACHE_FILE=./news_cache.json            # Fichier cache anti-doublon
```

---

## 11. Déploiement

### Production actuelle : VPS OVH + systemd

**Serveur** : OVH VPS Ubuntu 25.04 (`vps-5f6c616f.vps.ovh.net`, IP: 137.74.42.174)
**Utilisateur** : `ubuntu`
**Python** : 3.13 (natif Ubuntu 25.04)

#### Service systemd : `/etc/systemd/system/bingebear-bot.service`
```ini
[Unit]
Description=BingeBear TV Bot
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/TelegramIPTVBot/python-bot
ExecStart=/home/ubuntu/TelegramIPTVBot/python-bot/venv/bin/python run_all.py
Restart=always
RestartSec=10
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
```

#### Commandes de gestion
```bash
# Statut
sudo systemctl status bingebear-bot

# Redémarrer
sudo systemctl restart bingebear-bot

# Logs en temps réel
sudo journalctl -u bingebear-bot -f

# Logs récents
sudo journalctl -u bingebear-bot -n 50 --no-pager
```

#### Mise à jour du bot
```bash
cd ~/TelegramIPTVBot && git pull origin main && sudo systemctl restart bingebear-bot
```

### Alternative : Docker

```bash
docker-compose up -d --build
```

Le `docker-compose.yml` configure :
- Build depuis `python-bot/Dockerfile`
- Volumes persistants pour logs et état (stream_state, news_cache)
- Health check HTTP toutes les 30s avec 3 retries
- Port 8080 exposé

#### Dockerfile (python-bot/)
```dockerfile
FROM python:3.11-slim
RUN apt-get install ffmpeg, libavcodec-extra, curl
WORKDIR /app
COPY . .
RUN pip install -r requirements.txt
RUN mkdir -p /var/log/bingebear
EXPOSE 8080
CMD ["python", "run_all.py"]
```

### Alternative : Heroku/Render/Railway

- `Procfile` : `worker: python run_all.py`
- `runtime.txt` : `python-3.11.9`
- `nixpacks.toml` : configuration Railway

---

## 12. Monitoring

### Script `monitor.sh` (cron toutes les 5 minutes)
1. Vérifie que le service systemd `bingebear-bot` est actif
2. Vérifie que le health check HTTP (`GET /health`) répond 200
3. Si échec : redémarre le service et envoie une alerte Telegram à l'admin
4. Log dans `/var/log/bingebear/monitor.log`

### Setup monitoring (`setup-monitoring.sh`)
Installe :
- Cron : health check toutes les 5 minutes
- Cron : nettoyage des fichiers temporaires (.mp4, .jpg, .png) chaque nuit à 3h
- Logrotate : rotation quotidienne, conservation 14 jours, compression

---

## 13. Diagramme d'architecture

```
┌─────────────────────────────────────────────────────────┐
│                      run_all.py                         │
│                                                         │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────────┐  │
│  │ Bot Commands  │  │ News Handler │  │ Health Server │  │
│  │ (python-     │  │ (Pyrogram    │  │ (aiohttp      │  │
│  │  telegram-   │  │  on_message) │  │  port 8080)   │  │
│  │  bot)        │  │              │  │               │  │
│  └──────┬───────┘  └──────┬───────┘  └───────────────┘  │
│         │                 │                              │
│         │          ┌──────┴───────┐                      │
│         │          │ News Filter  │                      │
│         │          │ + Modifier   │                      │
│         │          │ (regex)      │                      │
│         │          └──────┬───────┘                      │
│         │                 │                              │
│         │          ┌──────┴───────┐                      │
│         │          │ News Queue   │                      │
│         │          │ (rate limit  │                      │
│         │          │  1.5s/msg)   │                      │
│         │          └──────┬───────┘                      │
│         │                 │                              │
│  ┌──────┴───────┐  ┌─────┴────────┐                     │
│  │  PyTgCalls   │  │ News Cache   │                     │
│  │  (WebRTC     │  │ (anti-dupes  │                     │
│  │   streaming) │  │  JSON file)  │                     │
│  └──────┬───────┘  └──────────────┘                     │
│         │                                               │
│  ┌──────┴───────┐  ┌──────────────┐                     │
│  │ Stream State │  │  Watchdog    │                     │
│  │ (auto-resume │  │  (60s check  │                     │
│  │  JSON file)  │  │   + restart) │                     │
│  └──────────────┘  └──────────────┘                     │
│                                                         │
│  ┌──────────────┐  ┌──────────────┐                     │
│  │   Logger     │  │  Retry       │                     │
│  │ (rotating    │  │  (exp.       │                     │
│  │  file + con) │  │   backoff)   │                     │
│  └──────────────┘  └──────────────┘                     │
└─────────────────────────────────────────────────────────┘
         │                    │
         ▼                    ▼
┌────────────────┐  ┌─────────────────┐  ┌─────────────────┐
│ Telegram Group │  │ Canal Telegram  │  │  Canal Source    │
│ (Voice Chat /  │  │ @bingebeartv_   │  │  -100176375     │
│  Streaming)    │  │ live (news)     │  │  8614 (écoute)  │
└────────────────┘  └─────────────────┘  └─────────────────┘
```

### Interactions entre composants

1. **`run_all.py`** orchestre tout : il démarre le bot, le client Pyrogram, PyTgCalls, le health server, et les tâches de fond
2. **`config.py`** est appelé au démarrage pour valider les variables d'environnement
3. **`logger.py`** est utilisé par tous les modules pour le logging
4. **`health.py`** est démarré comme tâche de fond et expose `/health`
5. **`stream_state.py`** est utilisé par les commandes `/play`, `/stop` et par `auto_resume_stream()`
6. **`news_cache.py`** est utilisé par le handler `forward_news()` et `/importnews`
7. **`news_queue.py`** est utilisé par le handler `forward_news()` pour respecter les rate limits
8. **`utils/retry.py`** est utilisé par les fonctions d'appel à l'API IPTV

---

## 14. Historique des modifications récentes

| Commit | Description |
|--------|-------------|
| `1cbc42e` | Fix récursion infinie dans reply_private + ajout logs de diagnostic pour le news forwarder |
| `e7955f1` | Toutes les réponses aux commandes envoyées en DM privé (pas dans le canal) |
| `3a4dccf` | Remplacement de "Dear Reseller(s)" par "Dear Users" dans les news transférées |
| `b790191` | Ajout de la commande `/importnews` pour importer les news depuis X jours (admin only) |
| `629f228` | Pagination des catégories et chaînes en plusieurs messages (plus de troncature) |
| `a5b36b7` | SESSION_STRING et identifiants IPTV rendus optionnels pour mode test |

---

## 15. Diagnostic et debugging

### Logs de diagnostic au démarrage

Le bot vérifie et log au démarrage :

1. **Connexion Pyrogram** : `Connecte: DeFi Mack (@DefiMack)` — confirme que la SESSION_STRING est valide
2. **PyTgCalls** : `PyTgCalls pret` — streaming disponible
3. **Canal source** : `Canal source accessible: SERVICE INFORMATION (id=-1001763758614)` — le canal existe et est lisible
4. **Statut membre** : `Statut dans le canal source: ChatMemberStatus.MEMBER` — le compte est abonné (indispensable pour recevoir les updates)
5. **Handlers** : `Handlers Pyrogram enregistres: 2` — les handlers on_message sont bien enregistrés

### Logs du news forwarder en fonctionnement

Chaque message reçu du canal source génère un log :

```
[NEWS] Message recu: chat_id=-1001763758614, msg_id=3480, text='Dear Reseller...'
[NEWS] Message 3480 accepte pour transfert        # ← matche un pattern
[NEWS] Message 3481 ne matche pas les patterns    # ← filtré (pas pertinent)
[NEWS] Message 3479 deja transfere (cache)        # ← anti-doublon
```

### Commandes de diagnostic sur le VPS

```bash
# Statut du service
sudo systemctl status bingebear-bot

# Logs en temps réel
sudo journalctl -u bingebear-bot -f

# Logs du jour filtrés sur les news
sudo journalctl -u bingebear-bot --since "today" | grep -i "news"

# Derniers 50 logs
sudo journalctl -u bingebear-bot -n 50 --no-pager
```

---

## Points d'attention

1. **SESSION_STRING** : Indispensable pour le streaming ET le transfert de news. Sans elle, le bot ne peut que répondre aux commandes basiques. Générée via `generate_session.py` ou un bot tiers.

2. **Rate limiting Telegram** : Le `NewsQueue` espace les envois de 1.5s. L'erreur 429 est gérée automatiquement (pause 30s + retry).

3. **Port 8080** : Utilisé par le health check. Des scanners internet peuvent envoyer des requêtes HTTP/2 qui génèrent des erreurs `BadHttpMessage: 400` dans les logs — c'est du bruit normal, pas un problème.

4. **Auto-resume** : Si le bot crash pendant un stream, il reprend automatiquement au redémarrage si le crash date de moins de 30 minutes.

5. **DM privés** : L'utilisateur doit avoir fait `/start` en privé avec le bot au moins une fois pour recevoir les réponses.

6. **Fichiers de persistance** : `stream_state.json` et `news_cache.json` sont créés automatiquement dans le working directory. Ils survivent aux redémarrages.
