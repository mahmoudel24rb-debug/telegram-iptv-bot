# TelegramIPTVBot (BingeBear TV) - Documentation Complète

## Table des matières

1. [Aperçu du projet](#1-aperçu-du-projet)
2. [Architecture et structure](#2-architecture-et-structure)
3. [Stack technique](#3-stack-technique)
4. [Comment ça marche](#4-comment-ça-marche)
5. [News Forwarder - Transfert automatique de messages](#5-news-forwarder---transfert-automatique-de-messages)
6. [Hébergement et déploiement](#6-hébergement-et-déploiement)
7. [Configuration](#7-configuration)
8. [API et intégrations](#8-api-et-intégrations)
9. [Bugs et problèmes identifiés](#9-bugs-et-problèmes-identifiés)

---

## 1. Aperçu du projet

**TelegramIPTVBot** (aussi appelé **BingeBear TV**) est un bot Telegram qui diffuse automatiquement du contenu IPTV (chaînes TV en direct, films, séries) vers un canal ou groupe Telegram, 24h/24 et 7j/7.

### Fonctionnalités principales

- Streaming IPTV automatisé vers des canaux Telegram
- Transcodage vidéo via FFmpeg (segmentation en fichiers MP4)
- Streaming WebRTC en direct dans les appels vidéo Telegram (via Python/PyTgCalls)
- Panneau d'administration WordPress pour gérer les chaînes et la programmation
- Support des playlists M3U/M3U8 et des serveurs Xtream Codes
- Transfert automatique de news entre canaux Telegram
- Contrôle via commandes bot (`/play`, `/stop`, `/status`, etc.)

### Double implémentation

Le projet existe en **deux versions** :

| | Node.js (`src/`) | Python (`python-bot/`) |
|---|---|---|
| **Framework bot** | grammy | python-telegram-bot + Pyrogram |
| **Streaming** | FFmpeg → segments MP4 → upload | PyTgCalls (WebRTC direct) |
| **Maturité** | Basique, segments uploadés | Plus complet, streaming live |
| **News forwarding** | Non | Oui |

---

## 2. Architecture et structure

```
TelegramIPTVBot/
│
├── src/                              # Implémentation Node.js
│   ├── bot.js                        # Bot Telegram principal (grammy)
│   ├── streamer.js                   # Gestionnaire FFmpeg + upload segments
│   ├── database.js                   # Client API IPTV (Xtream Codes)
│   ├── live-streamer.js              # Streaming WebRTC (expérimental)
│   └── userbot.js                    # Client utilisateur Telegram (MTCute)
│
├── python-bot/                       # Implémentation Python (plus complète)
│   ├── bot.py                        # Bot streaming (Pyrogram + PyTgCalls)
│   ├── news_forwarder.py             # Transfert automatique de news
│   ├── run_all.py                    # Lanceur combiné (bot + forwarder)
│   ├── generate_session.py           # Générateur de session Pyrogram
│   ├── get_channel_id.py             # Utilitaire pour récupérer les IDs
│   ├── test_*.py                     # Scripts de test
│   ├── Dockerfile                    # Conteneurisation Docker
│   ├── requirements.txt              # Dépendances Python
│   ├── runtime.txt                   # Version Python (3.11.9)
│   ├── Procfile                      # Déploiement cloud (Heroku/Render)
│   └── nixpacks.toml                 # Config Nixpacks (Railway)
│
├── wordpress-plugin/                 # Panneau d'administration
│   └── telegram-iptv-manager.php     # Plugin WordPress complet
│
├── output/                           # Stockage temporaire des segments vidéo
├── .env / .env.example               # Configuration
├── package.json                      # Dépendances Node.js
├── session.txt                       # Token de session Telegram
└── README.md                         # Documentation (en français)
```

### Composants détaillés

#### Node.js - `bot.js`
- Classe `TelegramIPTVBot` basée sur grammy
- Commandes : `/start`, `/status`, `/channels`, `/play`, `/stop`, `/current`, `/help`
- Clavier inline pour la sélection de chaînes
- Upload de segments vidéo vers le canal Telegram

#### Node.js - `streamer.js`
- Classe `StreamManager` qui gère le processus FFmpeg
- Découpe le flux IPTV en segments MP4 de 5 minutes
- Surveille le dossier `output/` toutes les 10 secondes pour détecter et uploader les nouveaux segments
- Paramètres FFmpeg : H.264, AAC, 2500k bitrate, 720p

#### Node.js - `database.js`
- Classe `DatabaseManager` (nom trompeur : pas de base de données réelle)
- Client HTTP pour l'API Xtream Codes IPTV
- Récupère les catégories, chaînes live et contenu VOD

#### Python - `bot.py`
- Utilise Pyrogram (client user) + PyTgCalls (WebRTC) pour le streaming direct
- Streaming en temps réel dans les appels vidéo Telegram (pas de segmentation)
- Système de cache pour les catégories et chaînes
- Gestion des autorisations admin

#### Python - `news_forwarder.py`
- Écoute le canal source `@SERVICE INFORMATION` (ID: -1001763758614)
- Filtre les messages (uniquement les annonces en anglais)
- Remplace "Team 8K" par "Team BingeBearTV"
- Transfère vers `@bingebeartv_live`

#### WordPress - `telegram-iptv-manager.php`
- Plugin admin avec 4 pages : Dashboard, Channels, Schedule, Logs
- Crée 3 tables MySQL : `wp_telegram_iptv_channels`, `wp_telegram_iptv_schedule`, `wp_telegram_iptv_logs`
- API REST pour importer des playlists M3U et gérer la programmation

---

## 3. Stack technique

### Node.js

| Package | Version | Rôle |
|---------|---------|------|
| grammy | ^1.21.1 | Framework bot Telegram |
| @mtcute/node | ^0.27.6 | Client Telegram alternatif |
| telegram | ^2.26.22 | Client utilisateur Telegram |
| fluent-ffmpeg | ^2.1.2 | Wrapper FFmpeg |
| axios | ^1.6.0 | Client HTTP |
| m3u8-parser | ^7.1.0 | Parser de playlists M3U |
| node-cron | ^3.0.3 | Planification cron |
| dotenv | ^16.3.1 | Variables d'environnement |

### Python

| Package | Version | Rôle |
|---------|---------|------|
| python-telegram-bot | 21.10 | API Bot Telegram |
| pyrofork | 2.3.58 | Fork Pyrogram (client user) |
| py-tgcalls | 2.2.10 | Streaming WebRTC |
| tgcrypto | Latest | Chiffrement Telegram |
| python-dotenv | Latest | Variables d'environnement |
| requests | Latest | Client HTTP |

### Prérequis système

- **FFmpeg** avec libavcodec-extra
- **Python 3.11.9** (bot Python)
- **Node.js 18+** (bot Node.js)
- **MySQL/MariaDB** (optionnel, pour WordPress)

---

## 4. Comment ça marche

### Pipeline de streaming Node.js (segmentation)

```
Commande /play
    │
    ▼
Récupération du flux via API Xtream Codes
    │
    ▼
Lancement du processus FFmpeg
    │  Input:  flux M3U8/RTMP/HTTP
    │  Codec:  H.264 (vidéo) + AAC (audio)
    │  Output: segments MP4 de 5 min dans ./output/
    │
    ▼
Surveillance du dossier (toutes les 10s)
    │  Détecte les nouveaux fichiers .mp4
    │  Attend la stabilisation du fichier
    │
    ▼
Upload vers le canal Telegram
    │  Via bot.sendVideoToChannel()
    │
    ▼
Suppression du fichier local
    │  Nettoyage après upload réussi
    │
    ▼
Boucle continue jusqu'à /stop
```

### Pipeline de streaming Python (WebRTC)

```
Commande /play
    │
    ▼
Récupération du flux via API Xtream Codes
    │
    ▼
Initialisation Pyrogram + PyTgCalls
    │
    ▼
Connexion à l'appel vidéo du groupe (WebRTC)
    │
    ▼
Streaming en temps réel dans le chat vidéo Telegram
    │  Affichage direct, pas de segmentation
    │
    ▼
Continue jusqu'à /stop
```

### API IPTV (Xtream Codes)

```
Base URL: ${IPTV_SERVER_URL}

Endpoints utilisés:
─────────────────────────────────────────────────────────────
GET /player_api.php?username=X&password=Y
    → Authentification et info utilisateur

GET /player_api.php?...&action=get_live_categories
    → Liste des catégories TV

GET /player_api.php?...&action=get_live_streams&category_id=N
    → Chaînes d'une catégorie

GET /player_api.php?...&action=get_vod_streams
    → Catalogue VOD (films)

GET /live/{user}/{pass}/{stream_id}.m3u8
    → URL du flux live (HLS)

GET /movie/{user}/{pass}/{movie_id}.{ext}
    → URL du film VOD
```

---

## 5. News Forwarder - Transfert automatique de messages

Le projet inclut un système de **transfert automatique de messages** entre canaux Telegram. Ce module écoute un canal source (fournisseur IPTV) et retransfère les annonces pertinentes vers le canal BingeBear TV, en les modifiant au passage.

### Architecture

Le news forwarder existe en deux versions :

| | `news_forwarder.py` (standalone) | `run_all.py` (combiné) |
|---|---|---|
| **Exécution** | Processus séparé | Intégré avec le bot streaming |
| **Client Pyrogram** | Dédié (`news_forwarder`) | Partagé (`combined_session`) |
| **Support images** | Non (texte uniquement) | Oui (photos + caption) |
| **Nettoyage fichiers** | N/A | Supprime les photos temporaires |

### Flux de fonctionnement

```
Canal source: "📣 SERVICE INFORMATION 📣" (ID: -1001763758614)
    │
    ▼
Pyrogram écoute via @user_client.on_message(filters.chat(...))
    │  Intercepte TOUS les messages du canal source
    │
    ▼
Extraction du texte (message.text ou message.caption)
    │
    ▼
Filtre d'exclusion (EXCLUDE_WORDS)
    │  ✗ "domain has been suspended"     → IGNORÉ
    │  ✗ "purchase a private domain"     → IGNORÉ
    │  ✗ "misuse and multiple complaints"→ IGNORÉ
    │  ✗ "Queridos Revendedores"         → IGNORÉ (espagnol)
    │  ✗ "Nos complace"                  → IGNORÉ (espagnol)
    │
    ▼
Filtre d'inclusion (PATTERNS) — au moins un doit matcher
    │  ✓ r"Dear Reseller,\s*\n\s*We are pleased"
    │     → Annonces de nouvelles chaînes/catégories
    │  ✓ r"^[A-Z\s]+VS\s+[A-Z\s]+""
    │     → Matchs sportifs (ex: "GAETHJE VS PIMBLETT")
    │  ✓ r"^LIVE EVENT"
    │     → Événements en direct
    │
    ▼
Modification du message (modify_message / modify_news_message)
    │  1. Supprime les sections en espagnol
    │     regex: r'Queridos Revendedores.*?(?=Enjoy\.|Team|$)'
    │  2. Nettoie les lignes vides multiples (max 2 consécutives)
    │     regex: r'\n{3,}' → '\n\n'
    │  3. Remplace la signature du fournisseur
    │     regex: r'Team\s*8K' → "Team BingeBearTV"
    │
    ▼
Envoi vers le canal destination
    │  Canal: @bingebeartv_live (configurable via NEWS_DEST_CHANNEL)
    │  Envoyé via: Bot Telegram (@Bingebear_tv_bot)
    │
    │  Version run_all.py uniquement:
    │  ├── Si message avec photo → bot.send_photo(photo + caption modifiée)
    │  │   puis suppression du fichier temporaire
    │  └── Si texte seul → bot.send_message(texte modifié)
    │
    ▼
Log console: "[NEWS] ✅ Message envoyé" ou "[NEWS ERREUR] ..."
```

### Patterns regex détaillés

#### Patterns d'inclusion

| Pattern | Type de message | Exemple |
|---------|----------------|---------|
| `Dear Reseller,\s*\n\s*We are pleased` | Annonce de nouvelles chaînes ou catégories ajoutées par le fournisseur | "Dear Reseller, We are pleased to announce new HD channels..." |
| `^[A-Z\s]+VS\s+[A-Z\s]+` | Annonce de matchs sportifs en direct | "GAETHJE VS PIMBLETT", "FRANCE VS ENGLAND" |
| `^LIVE EVENT` | Événement en direct | "LIVE EVENT - UFC 320..." |

> Les patterns utilisent les flags `re.IGNORECASE | re.MULTILINE`.

#### Mots d'exclusion

| Mot/phrase | Raison de l'exclusion |
|------------|----------------------|
| `domain has been suspended` | Message administratif sur les domaines suspendus |
| `purchase a private domain` | Publicité pour achat de domaines privés |
| `misuse and multiple complaints` | Avertissements pour abus — non pertinent pour les utilisateurs |
| `Queridos Revendedores` | Contenu en espagnol (doublon de l'annonce anglaise) |
| `Nos complace` | Contenu en espagnol |

> L'exclusion est vérifiée **avant** l'inclusion. Si un mot exclu est trouvé, le message est immédiatement ignoré, même s'il contient un pattern d'inclusion.

### Transformations appliquées au message

1. **Suppression du contenu espagnol** : Tout le bloc commençant par "Queridos Revendedores" jusqu'à "Enjoy." ou "Team" est supprimé via regex `r'Queridos Revendedores.*?(?=Enjoy\.|Team|$)'` avec le flag `re.DOTALL`
2. **Nettoyage des sauts de ligne** : 3+ sauts de ligne consécutifs sont réduits à 2
3. **Rebranding de la signature** : "Team 8K" (avec espaces variables) est remplacé par "Team BingeBearTV"

### Configuration

| Variable | Défaut | Description |
|----------|--------|-------------|
| `NEWS_SOURCE_CHANNEL` | `-1001763758614` | ID du canal source (hardcodé) |
| `NEWS_DEST_CHANNEL` | `@bingebeartv_live` | Canal de destination (env var) |
| `SESSION_STRING` | — | Session Pyrogram pour écouter le canal source |
| `BOT_TOKEN` | — | Token du bot qui envoie les messages |

### Différence entre `news_forwarder.py` et `run_all.py`

- **`news_forwarder.py`** : Version standalone, ne gère que le transfert de texte. Utilise son propre client Pyrogram.
- **`run_all.py`** : Version intégrée qui combine le bot streaming + le forwarder. Partage le même client Pyrogram. Supporte en plus le **transfert de photos** avec caption modifiée, et supprime les fichiers temporaires après envoi.

---

## 6. Hébergement et déploiement

### Option 1 : Docker (recommandé)

Le bot Python dispose d'un Dockerfile :

```dockerfile
# Base: python:3.11-slim
# Installe: FFmpeg + dépendances système
# Entry point: python bot.py
```

```bash
docker build -f python-bot/Dockerfile -t telegram-iptv-bot .
docker run --env-file python-bot/.env telegram-iptv-bot
```

### Option 2 : Heroku / Render (via Procfile)

Le fichier `Procfile` est configuré pour un worker :

```
worker: python run_all.py
```

Ceci lance le bot + le news forwarder simultanément.

### Option 3 : Railway (via nixpacks.toml)

```toml
# Setup: Python 3.11, pip install
# Start: python bot.py
```

### Option 4 : VPS / Serveur dédié

Installation manuelle avec systemd pour le redémarrage automatique.

### Commandes de lancement

```bash
# Node.js
npm install
npm start              # node src/bot.js
npm run dev            # nodemon src/bot.js (dev avec hot-reload)
npm run stream         # node src/streamer.js

# Python
python bot.py          # Bot seul
python run_all.py      # Bot + news forwarder
python news_forwarder.py  # Forwarder seul
```

---

## 7. Configuration

### Variables d'environnement (Node.js - `.env`)

```env
# Telegram
TELEGRAM_BOT_TOKEN=<token du bot>
TELEGRAM_CHAT_ID=@bingebeartv
TELEGRAM_API_ID=<api_id>
TELEGRAM_API_HASH=<api_hash>

# Serveur IPTV (Xtream Codes)
IPTV_SERVER_URL=http://<serveur>
IPTV_USERNAME=<username>
IPTV_PASSWORD=<password>

# WordPress (optionnel)
WORDPRESS_URL=https://bingebear.tv
WORDPRESS_API_KEY=<api_key>

# Streaming
STREAM_QUALITY=720p
STREAM_BITRATE=2500k
STREAM_CHECK_INTERVAL=60000
```

### Variables d'environnement (Python - `python-bot/.env`)

```env
API_ID=<api_id>
API_HASH=<api_hash>
BOT_TOKEN=<token du bot>
CHAT_ID=<username du groupe>
SESSION_STRING=<session Pyrogram>
IPTV_SERVER_URL=http://<serveur>
IPTV_USERNAME=<username>
IPTV_PASSWORD=<password>
ADMIN_IDS=<id1,id2,...>
```

### Schéma de la base WordPress

```sql
-- Chaînes IPTV
wp_telegram_iptv_channels (
    id, name, stream_url, type, category,
    icon_url, is_active, created_at, updated_at
)

-- Programmation
wp_telegram_iptv_schedule (
    id, content_id, content_type, content_name, content_url,
    start_time, end_time, is_active, is_loop, created_at, updated_at
)

-- Logs de streaming
wp_telegram_iptv_logs (
    id, content_id, content_name, content_type,
    start_time, end_time, duration_seconds, status, error_message
)
```

---

## 8. API et intégrations

- **Telegram Bot API** : Contrôle du bot via commandes, envoi de messages/vidéos
- **Telegram Client API** : Authentification en tant qu'utilisateur pour les appels vidéo
- **Xtream Codes API** : Récupération des flux IPTV (chaînes, catégories, VOD)
- **WordPress REST API** : Gestion des chaînes et programmation via le plugin admin
- **FFmpeg** : Transcodage et segmentation des flux vidéo

---

## 9. Bugs et problèmes identifiés

### Sévérité CRITIQUE

#### 9.1Credentials exposés dans les fichiers `.env`

Les fichiers `.env` et `session.txt` contiennent des tokens et mots de passe en clair. Si le projet est poussé sur un dépôt public, toutes les credentials seront compromises.

**Fichiers concernés** : `.env`, `session.txt`, `python-bot/.env`, `*.session`

**Correction** : S'assurer que `.gitignore` contient bien :
```
.env
session.txt
*.session
output/
```

---

### Sévérité HAUTE

#### 9.2Race condition dans `startStream()` (`src/streamer.js`)

La fonction met `this.isStreaming = true` **après** l'appel asynchrone à `streamToTelegram()`. Si une erreur survient dans le processus FFmpeg, le flag ne reflète pas la réalité. De plus, des commandes `/play` rapides et successives peuvent lancer plusieurs processus FFmpeg simultanément.

```javascript
async startStream(content) {
    this.currentContent = content;
    await this.streamToTelegram(content);  // Asynchrone - erreur mal gérée
    this.isStreaming = true;               // Set APRÈS l'opération async
    return true;
}
```

#### 9.3Gestion d'erreur insuffisante du processus FFmpeg (`src/streamer.js`)

- Les erreurs stderr de FFmpeg sont partiellement loguées mais peuvent causer des échecs silencieux
- Pas de vérification que FFmpeg a bien démarré avant de continuer
- Le callback `on('error')` met `isStreaming = false`, mais `startStream()` a déjà retourné `true`

#### 9.4Promesses non gérées dans `watchSegments()` (`src/streamer.js`)

- Le callback `setInterval` contient des opérations async sans catch approprié
- `fs.readdirSync()` peut throw si le dossier est inaccessible
- `fs.statSync()` peut échouer si le fichier est supprimé entre le check et l'accès (race condition)

---

### Sévérité MOYENNE

#### 9.5Vérification de stabilité de fichier fragile (`src/streamer.js`)

`waitForFileStable()` retourne **toujours `true`**, même en cas de timeout. Un fichier encore en cours d'écriture pourrait être uploadé partiellement.

```javascript
async waitForFileStable(filePath, timeout = 30000) {
    // ...
    return true;  // Retourne TOUJOURS true, même en timeout !
}
```

#### 9.6Fuite du segment watcher (`src/streamer.js`)

Le `setInterval` est créé à chaque nouveau stream mais n'est nettoyé que dans `stopStream()`. Si `stopStream()` échoue, l'interval continue à tourner indéfiniment.

#### 9.7Crash potentiel sur null (`src/bot.js`)

```javascript
message += `URL: ${content.url.substring(0, 50)}...`;
// Aucune vérification que content ou content.url existe !
```

#### 9.8Valeurs hardcodées qui devraient être configurables

| Fichier | Valeur hardcodée |
|---------|-----------------|
| `python-bot/run_all.py` | `NEWS_SOURCE_CHANNEL = -1001763758614` |
| `python-bot/run_all.py` | `ALLOWED_USERNAMES = ["DefiMack"]` |
| `python-bot/bot.py` | `ALLOWED_USERNAMES = ["DefiMack"]` |
| `python-bot/news_forwarder.py` | Channel ID source hardcodé |

#### 9.9Terminaison de processus non vérifiée (`src/streamer.js`)

FFmpeg est tué avec `SIGINT`, ce qui peut ne pas être assez agressif. Aucune vérification que le processus a bien quitté. Devrait utiliser `SIGKILL` en fallback.

#### 9.10Aucun système de logging

Tout le projet utilise uniquement `console.log()` / `console.error()`. Aucun log persistant, aucune rotation, impossible de diagnostiquer des problèmes en production.

#### 9.11Aucune validation des variables d'environnement

Les variables d'environnement requises ne sont jamais vérifiées au démarrage. Si une variable manque, le bot crashera avec une erreur peu claire au moment de l'utiliser.

#### 9.12Pas de retry logic

Aucune logique de retry sur les appels réseau (API IPTV, API Telegram, upload de fichiers). Une erreur réseau temporaire fait échouer l'opération définitivement.

#### 9.13Pas de health checks

Aucun mécanisme pour détecter si le processus FFmpeg meurt silencieusement ou si le bot est dans un état incohérent.

---

### Sévérité BASSE

#### 9.14Comparaison de type faible (`src/database.js`)

```javascript
return this.channels.find(ch => ch.id == id);  // == au lieu de ===
```

Utilise `==` (comparaison lâche) au lieu de `===` (comparaison stricte), ce qui peut produire des résultats inattendus.

#### 9.15Messages d'erreur vides côté Python (`python-bot/bot.py`)

```python
except Exception as e:
    await update.message.reply_text(f"Erreur: {e}")
    # Pas de logging → impossible de debugger en production
```

#### 9.16Base de données non connectée (`src/database.js`)

Le `DatabaseManager` contient des credentials MySQL dans le `.env` mais ne se connecte jamais réellement à la base. Les méthodes `logStream()` et `updateStreamLog()` ne font que `console.log()`.

---

### Tableau récapitulatif

| # | Problème | Sévérité | Fichier(s) |
|---|----------|----------|------------|
| 8.1 | Credentials exposés | CRITIQUE | .env, session.txt |
| 8.2 | Race condition startStream | HAUTE | streamer.js |
| 8.3 | Erreurs FFmpeg silencieuses | HAUTE | streamer.js |
| 8.4 | Promesses non gérées | HAUTE | streamer.js |
| 8.5 | waitForFileStable toujours true | MOYENNE | streamer.js |
| 8.6 | Fuite segment watcher | MOYENNE | streamer.js |
| 8.7 | Crash null sur content.url | MOYENNE | bot.js |
| 8.8 | Valeurs hardcodées | MOYENNE | bot.py, run_all.py |
| 8.9 | Terminaison process non vérifiée | MOYENNE | streamer.js |
| 8.10 | Aucun système de logging | MOYENNE | Tous |
| 8.11 | Pas de validation env vars | MOYENNE | Tous |
| 8.12 | Pas de retry logic | MOYENNE | Tous |
| 8.13 | Pas de health checks | MOYENNE | Tous |
| 8.14 | Comparaison == vs === | BASSE | database.js |
| 8.15 | Erreurs Python non loguées | BASSE | bot.py |
| 8.16 | DB jamais connectée | BASSE | database.js |
