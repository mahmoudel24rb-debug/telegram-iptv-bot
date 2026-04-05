# BingeBear TV Bot - Documentation Technique Complete

## Table des matieres

1. [Vue d'ensemble](#1-vue-densemble)
2. [Architecture du projet](#2-architecture-du-projet)
3. [Stack technique](#3-stack-technique)
4. [Fichier principal run_all.py](#4-fichier-principal-run_allpy)
5. [Systeme de transfert de news (DETAIL)](#5-systeme-de-transfert-de-news-detail)
6. [Systeme de streaming IPTV](#6-systeme-de-streaming-iptv)
7. [Commandes du bot](#7-commandes-du-bot)
8. [Systeme de rappels (reminders)](#8-systeme-de-rappels-reminders)
9. [Modules auxiliaires](#9-modules-auxiliaires)
10. [Authentification et autorisation](#10-authentification-et-autorisation)
11. [Variables d'environnement](#11-variables-denvironnement)
12. [Deploiement VPS](#12-deploiement-vps)
13. [Diagnostic et debugging](#13-diagnostic-et-debugging)
14. [Bug connu : on_message ne se declenche pas](#14-bug-connu--on_message-ne-se-declenche-pas)
15. [Historique des modifications](#15-historique-des-modifications)

---

## 1. Vue d'ensemble

**BingeBear TV Bot** est un bot Telegram multifonction qui :

1. **Transfere automatiquement les news** d'un canal source vers un canal de destination avec filtrage intelligent, modifications de texte et support des images
2. **Diffuse du contenu IPTV** en streaming dans les groupes Telegram via PyTgCalls (WebRTC)
3. **Offre des commandes admin** pour poster des annonces, programmer des rappels recurrents, et importer des news manuellement
4. **Envoie toutes les reponses en DM prive** pour garder le canal propre

Le bot tourne 24/7 sur un VPS OVH (Ubuntu 25.04) via un service systemd avec auto-restart.

**Identifiants du projet** :
- Bot : `@Bingebear_tv_bot` (ID: 8500861189)
- Compte utilisateur Pyrogram : DeFi Mack (`@DefiMack`, ID: 1540634249)
- Canal source des news : `SERVICE INFORMATION` (ID: -1001763758614)
- Canal de destination : `@bingebeartv_live`
- VPS : OVH Ubuntu 25.04, IP 137.74.42.174, user `ubuntu`

---

## 2. Architecture du projet

```
TelegramIPTVBot/
python-bot/                        # Application principale (production)
  run_all.py                       # Point d'entree combine (streaming + news + commandes)
  config.py                        # Validation de la configuration au demarrage
  logger.py                        # Logging structure (console + fichier rotatif)
  health.py                        # Serveur HTTP health check (port 8080)
  stream_state.py                  # Persistance d'etat du stream (auto-resume apres crash)
  news_cache.py                    # Cache anti-doublon pour les news (fichier JSON)
  news_queue.py                    # File d'attente avec rate limiting (1.5s entre envois)
  reminders.py                     # Gestionnaire de rappels recurrents (fichier JSON)
  utils/retry.py                   # Retry avec backoff exponentiel (1s, 2s, 4s)
  generate_session.py              # Utilitaire pour generer une SESSION_STRING Pyrogram
  get_channel_id.py                # Utilitaire pour trouver l'ID d'un canal Telegram
  requirements.txt                 # Dependances Python
  .env                             # Variables d'environnement (non commite)
  .env.example                     # Template de configuration
deploy/                            # Scripts de deploiement VPS
  setup-vps.sh                     # Installation initiale du VPS Ubuntu
  setup-monitoring.sh              # Configuration monitoring + cron
  monitor.sh                       # Health check + auto-recovery (cron 5 min)
  update-bot.sh                    # Mise a jour et redemarrage
```

### Fichiers de persistance crees a l'execution (dans python-bot/)
- `news_cache.json` — IDs des messages deja transferes (max 500, TTL 7 jours)
- `stream_state.json` — etat du stream en cours (pour auto-resume, TTL 30 min)
- `reminders.json` — rappels recurrents actifs

---

## 3. Stack technique

| Package | Version | Role |
|---------|---------|------|
| python-telegram-bot | 21.10 | Framework bot Telegram (commandes, envoi de messages) |
| pyrofork | 2.3.58 | Client utilisateur Pyrogram (ecoute canaux, lecture historique) |
| py-tgcalls | 2.2.10 | Streaming audio/video dans les vocal chats Telegram (WebRTC) |
| python-dotenv | - | Chargement des variables d'environnement depuis `.env` |
| requests | - | Requetes HTTP vers l'API IPTV (Xtream Codes) |
| tgcrypto | - | Cryptographie Telegram (accelere les operations) |
| aiohttp | - | Serveur HTTP asynchrone pour le health check |

**Prerequis systeme** : Python 3.13 (ou 3.11+), FFmpeg avec libavcodec-extra

---

## 4. Fichier principal run_all.py

C'est le SEUL fichier lance en production. Il fait ~877 lignes et combine tout :

### 4.1 Demarrage et initialisation (lignes 1-112)

1. Charge `.env` via `python-dotenv`
2. Valide les variables obligatoires via `config.py` (quitte si manquantes)
3. Cree le client Pyrogram `user_client` SI `SESSION_STRING` est presente
4. Si `SESSION_STRING` absente → `HAS_USER_CLIENT = False` → mode degrade (pas de streaming, pas de news)
5. Cree le bot Telegram `telegram_bot` (pour envoyer les messages)
6. Initialise le cache news, la file d'attente news, le health check

### 4.2 Deux clients Telegram distincts

Le bot utilise DEUX connexions Telegram separees :

**1. `user_client` (Pyrogram / pyrofork)**
- C'est un COMPTE UTILISATEUR reel (DeFi Mack @DefiMack)
- Authentifie via `SESSION_STRING` (genere une fois avec `generate_session.py`)
- Sert a : ecouter les messages du canal source, lire l'historique, streamer via PyTgCalls
- DOIT etre abonne/membre du canal source pour recevoir les updates
- Demarre dans `post_init()` avec `await user_client.start()`

**2. `telegram_bot` (python-telegram-bot)**
- C'est un BOT Telegram (@Bingebear_tv_bot)
- Authentifie via `BOT_TOKEN`
- Sert a : recevoir les commandes (/play, /importnews...), envoyer les messages dans le canal destination, repondre en DM prive
- DOIT etre admin du canal destination pour pouvoir y poster

### 4.3 Fonction post_init() (lignes 788-842)

Executee automatiquement apres le demarrage du bot. C'est la qu'on demarre tout :

```
1. Demarre user_client (Pyrogram) → await user_client.start()
2. Recupere l'identite → "Connecte: DeFi Mack (@DefiMack)"
3. Demarre PyTgCalls → streaming disponible
4. Verifie l'acces au canal source → log si accessible ou non
5. Verifie le statut membre → "ChatMemberStatus.MEMBER"
6. Log le nombre de handlers Pyrogram enregistres
7. Demarre la file d'attente news (news_queue)
8. Tente un auto-resume du stream precedent (si crash < 30 min)
9. Lance le watchdog stream en tache de fond (asyncio.create_task)
10. Lance le news_poll_worker en tache de fond (auto-import toutes les 2h)
11. Lance le reminder_worker en tache de fond (rappels recurrents)
12. Demarre le serveur HTTP health check sur port 8080
```

### 4.4 Fonction reply_private() (lignes 275-282)

TOUTES les reponses aux commandes passent par cette fonction :

```python
async def reply_private(update, context, text):
    user_id = update.effective_user.id
    try:
        await context.bot.send_message(chat_id=user_id, text=text)
    except Exception:
        await update.message.reply_text(text)
```

- Envoie la reponse en DM prive a l'utilisateur
- Si le DM echoue (l'utilisateur n'a pas fait /start en prive), fallback sur reply dans le chat
- Objectif : garder le canal @bingebeartv_live propre, sans messages de log/commande

### 4.5 Boucle evenementielle (lignes 845-877)

```python
def main():
    application = Application.builder().token(BOT_TOKEN).post_init(post_init).build()
    # Enregistrement de tous les handlers de commandes
    application.run_polling(allowed_updates=Update.ALL_TYPES)
```

`run_polling()` est BLOQUANT — il prend le controle de la boucle asyncio. Pyrogram et toutes les taches de fond (watchdog, news_poll, reminder_worker) tournent dans la MEME boucle asyncio grace a `post_init()` qui les lance avant que `run_polling` ne bloque.

---

## 5. Systeme de transfert de news (DETAIL)

C'est la fonctionnalite principale du bot. Le but : reprendre automatiquement les annonces du canal fournisseur IPTV (`SERVICE INFORMATION`) et les publier dans le canal BingeBear TV (`@bingebeartv_live`), avec du rebranding.

### 5.1 Les deux mecanismes de transfert

Le bot a DEUX mecanismes independants pour capter les news :

#### Mecanisme 1 : Ecoute temps reel (on_message) — ACTUELLEMENT NON FONCTIONNEL

```python
# Ligne 202-204 de run_all.py
if HAS_USER_CLIENT and user_client:
    user_client.on_message(filters.chat(NEWS_SOURCE_CHANNEL))(forward_news)
```

- Pyrogram enregistre un handler qui ecoute le canal source
- A chaque nouveau message dans le canal source, la fonction `forward_news()` est appelee
- Le handler est enregistre au chargement du module (avant `user_client.start()`)
- Le filtre `filters.chat(NEWS_SOURCE_CHANNEL)` utilise un INT (-1001763758614)
- **PROBLEME** : ce handler ne se declenche jamais en production (voir section 14)

#### Mecanisme 2 : Auto-import toutes les 2h (news_poll_worker) — FONCTIONNEL

```python
# Ligne 671 de run_all.py
NEWS_POLL_INTERVAL = int(os.getenv("NEWS_POLL_INTERVAL", "7200"))  # 2h par defaut
```

C'est le WORKAROUND pour le bug du mecanisme 1. Toutes les 2 heures :

1. Le worker se reveille
2. Lit l'historique des 3 dernieres heures du canal source via `user_client.get_chat_history()`
3. Pour chaque message : verifie le cache → filtre → modifie → envoie
4. Le cache empeche les doublons entre les deux mecanismes
5. Log le nombre de messages importes

Ce mecanisme fonctionne car `get_chat_history()` est un appel actif (pull), contrairement a `on_message` qui est passif (push).

#### Mecanisme 3 : Import manuel (/importnews) — FONCTIONNEL

Commande admin pour forcer un import. Meme logique que le news_poll_worker mais :
- Parametrable : nombre de jours (1-30, defaut 7)
- Feedback en DM prive (nombre d'imports/skips)
- Utilise aussi le cache anti-doublon

### 5.2 Flux detaille du transfert d'un message

```
Message dans le canal source (-1001763758614)
    |
    v
[ETAPE 1] Detection
    - Mecanisme 1 (on_message) : Pyrogram appelle forward_news() automatiquement
    - Mecanisme 2 (poll) : news_poll_worker lit l'historique toutes les 2h
    - Mecanisme 3 (manuel) : admin lance /importnews
    |
    v
[ETAPE 2] Extraction du texte
    text = message.text or message.caption or ""
    - message.text : messages texte purs
    - message.caption : texte accompagnant une photo
    - Si vide → ignore
    |
    v
[ETAPE 3] Verification cache anti-doublon
    news_cache.is_forwarded(message.id)
    - Verifie dans news_cache.json si ce message_id a deja ete transfere
    - Si oui → skip (log "deja transfere")
    - Le cache contient max 500 entrees, TTL 7 jours
    |
    v
[ETAPE 4] Filtrage d'exclusion (should_forward_news - partie 1)
    Verifie si le texte contient un mot/phrase INTERDIT :
    - "domain has been suspended" → message administratif
    - "purchase a private domain" → publicite domaines
    - "misuse and multiple complaints" → avertissements abus
    - "Queridos Revendedores" → doublon en espagnol
    - "Nos complace" → doublon en espagnol
    Si un mot exclu est trouve → IGNORE (return False)
    |
    v
[ETAPE 5] Filtrage d'inclusion (should_forward_news - partie 2)
    Verifie si le texte matche AU MOINS UN pattern regex :

    Pattern 1 : r"Dear Reseller,\s*\n\s*We are pleased"
    → Annonces de nouvelles chaines/categories
    → Exemple : "Dear Reseller, We are pleased to launch the New Category..."

    Pattern 2 : r"^[A-Z\s]+VS\s+[A-Z\s]+""
    → Matchs sportifs (doit etre en debut de ligne)
    → Exemple : "FRANCE VS GERMANY"

    Pattern 3 : r"^LIVE EVENT"
    → Evenements en direct
    → Exemple : "LIVE EVENT - UFC 320..."

    Flags utilises : re.IGNORECASE | re.MULTILINE
    Si AUCUN pattern ne matche → IGNORE
    |
    v
[ETAPE 6] Modification du texte (modify_news_message)
    4 transformations appliquees dans cet ordre :

    1. Suppression du contenu espagnol :
       regex: r'Queridos Revendedores.*?(?=Enjoy\.|Team|$)'
       flags: re.DOTALL | re.IGNORECASE
       → Supprime tout le bloc en espagnol

    2. Remplacement "Dear Reseller(s)" :
       regex: r'Dear Resellers?\b'
       → Remplace par "Dear Users"

    3. Nettoyage des sauts de ligne :
       regex: r'\n{3,}'
       → Remplace 3+ sauts de ligne par 2

    4. Rebranding signature :
       regex: r'Team\s*8K'
       → Remplace par "Team BingeBearTV"
    |
    v
[ETAPE 7] Gestion des images
    Si message.photo existe :
    - Telecharge l'image localement via Pyrogram (message.download())
    - Envoie via telegram_bot.send_photo() avec caption = texte modifie
    - Supprime le fichier temporaire apres envoi
    Sinon :
    - Envoie via telegram_bot.send_message() avec text = texte modifie
    |
    v
[ETAPE 8] Envoi vers le canal destination
    - Mecanisme 1 (on_message) : passe par la NewsQueue (rate limiting 1.5s)
    - Mecanisme 2 (poll) : envoi direct avec asyncio.sleep(1.5) entre chaque
    - Mecanisme 3 (manuel) : envoi direct avec asyncio.sleep(1.5) entre chaque
    - Destination : NEWS_DEST_CHANNEL = @bingebeartv_live
    - Envoye via le BOT (telegram_bot), pas via le user_client
    |
    v
[ETAPE 9] Marquage dans le cache
    news_cache.mark_forwarded(message.id)
    - Ajoute message_id + timestamp dans news_cache.json
    - Si le cache depasse 500 entrees, supprime les plus anciennes (FIFO)
    - Persiste sur disque immediatement
```

### 5.3 Exemple concret de transformation

**Message original dans le canal source :**
```
Dear Reseller,

We are pleased to launch the New Category

TR| S SPORT+ PPV

This package contains 10 channels.
All channels will receive daily updates for live event !

Enjoy.
Team 8K

Queridos Revendedores,

Nos complace lanzar la nueva categoria...
```

**Message envoye dans @bingebeartv_live :**
```
Dear Users,

We are pleased to launch the New Category

TR| S SPORT+ PPV

This package contains 10 channels.
All channels will receive daily updates for live event !

Enjoy.
Team BingeBearTV
```

**Transformations appliquees :**
1. Bloc espagnol "Queridos Revendedores..." → supprime entierement
2. "Dear Reseller" → "Dear Users"
3. "Team 8K" → "Team BingeBearTV"
4. Sauts de ligne excessifs → nettoyes

### 5.4 Le cache anti-doublon (news_cache.py)

**Fichier** : `news_cache.json`

**Format** :
```json
{
  "3476": 1710547717.5,
  "3475": 1710547719.0,
  "3480": 1710634051.2
}
```

Chaque entree = `message_id` (string) → `timestamp` (float, moment du transfert)

**Comportement** :
- Au chargement : filtre les entrees > 7 jours (TTL)
- `is_forwarded(id)` : verifie si l'ID existe dans le cache
- `mark_forwarded(id)` : ajoute l'ID + sauvegarde immediatement
- Si > 500 entrees : supprime les plus anciennes (tri par timestamp, garde les 500 plus recentes)
- Taille typique du fichier : ~25 KB maximum
- Persiste entre les redemarrages du bot

**Pourquoi c'est important** : Sans le cache, le news_poll_worker (toutes les 2h) re-enverrait tous les messages a chaque execution. Le cache garantit qu'un message n'est JAMAIS envoye deux fois.

### 5.5 La file d'attente (news_queue.py)

Utilisee uniquement par le mecanisme 1 (on_message). Le mecanisme 2 (poll) fait son propre rate limiting avec `asyncio.sleep(1.5)`.

**Fonctionnement** :
- File asyncio standard (asyncio.Queue)
- Worker en tache de fond qui depile et envoie
- Delai minimum entre deux envois : 1.5 secondes
- Si erreur 429 (Telegram rate limit) : pause 30 secondes puis retry une fois
- Autres erreurs : log et continue

### 5.6 Configuration du transfert de news

```env
# Canal source (ID numerique negatif du canal Telegram)
NEWS_SOURCE_CHANNEL=-1001763758614

# Canal destination (username avec @)
NEWS_DEST_CHANNEL=@bingebeartv_live

# Intervalle du polling automatique (en secondes, defaut 7200 = 2h)
NEWS_POLL_INTERVAL=7200
```

---

## 6. Systeme de streaming IPTV

### 6.1 Flux complet

```
Commande /play <id>
    |
    v
Verification d'autorisation (is_allowed_user)
    |
    v
Recherche de la chaine dans le cache memoire (channels_cache)
    |
    v
Arret du stream en cours (si existant) via pytgcalls.leave_call()
    |
    v
PyTgCalls.play(CHAT_ID, MediaStream(url_iptv))
    |
    v
FFmpeg traite le flux IPTV en continu avec parametres de reconnexion
    |
    v
Audio/Video envoyes au vocal chat du groupe Telegram (WebRTC)
    |
    v
Etat sauvegarde dans stream_state.json (pour auto-resume)
    |
    v
Reponse envoyee en DM prive a l'utilisateur
```

### 6.2 API IPTV (Xtream Codes)

Le bot communique avec un serveur IPTV via l'API Xtream Codes :

| Endpoint | Description |
|----------|-------------|
| `GET /player_api.php?action=get_live_categories` | Liste des categories TV |
| `GET /player_api.php?action=get_live_streams&category_id=N` | Chaines d'une categorie |
| `GET /live/{user}/{pass}/{stream_id}.ts` | URL du flux live |

- Les categories et chaines sont cachees en memoire pour eviter les appels repetes
- Chaque appel API utilise `retry_sync()` avec backoff exponentiel (3 tentatives, delais 1s → 2s → 4s)

### 6.3 Parametres FFmpeg

```
-reconnect 1                    # Autorise la reconnexion
-reconnect_streamed 1           # Reconnexion sur les flux streames
-reconnect_delay_max 5          # Delai max de reconnexion (5s)
-err_detect ignore_err          # Ignore les erreurs de decodage
```

### 6.4 Auto-resume et watchdog

**Auto-resume** (auto_resume_stream) :
- Au demarrage, verifie si `stream_state.json` existe et a < 30 minutes
- Si oui, relance automatiquement le meme stream
- Utile apres un crash ou un redemarrage systemd

**Watchdog** (stream_watchdog) :
- Verifie toutes les 30 secondes si le stream est actif
- Si `is_streaming=True` mais pas d'activite depuis 60s → relance automatique
- Si la relance echoue → arrete le stream, supprime l'etat

### 6.5 Pagination des categories et chaines

Les commandes `/categories` et `/cat` paginent les resultats :
- Limite : 3800 caracteres par message (marge sous la limite Telegram de 4096)
- Si un message depasse la limite, il est coupe et envoye, puis un nouveau message commence
- Format : "Categories (suite 2):", "Chaines (suite 3):", etc.
- Total affiche a la fin du dernier message

---

## 7. Commandes du bot

| Commande | Parametres | Autorisation | Description |
|----------|-----------|-------------|-------------|
| `/start` | - | Tous | Affiche le menu d'aide |
| `/help` | - | Tous | Affiche la liste complete des commandes |
| `/categories` | - | Tous | Liste toutes les categories IPTV (pagine) |
| `/cat` | `<id>` | Tous | Liste les chaines d'une categorie (pagine) |
| `/play` | `<id>` | Utilisateurs autorises | Demarre le streaming d'une chaine IPTV |
| `/stop` | - | Utilisateurs autorises | Arrete le stream en cours |
| `/status` | - | Tous | Affiche le statut du stream actuel |
| `/test` | - | Utilisateurs autorises | Lance un stream de test (Big Buck Bunny) |
| `/importnews` | `[jours]` | Admin uniquement | Importe les news des X derniers jours (1-30, defaut 7) |
| `/announcement` | `<message>` | Admin uniquement | Poste un message dans le canal @bingebeartv_live |
| `/reminder` | `<intervalle> <message>` | Admin uniquement | Programme un rappel recurrent (ex: 36h, 2d) |
| `/reminders` | - | Admin uniquement | Liste tous les rappels actifs |
| `/delreminder` | `<id>` | Admin uniquement | Supprime un rappel |

**Important** : Toutes les reponses sont envoyees en DM prive a l'utilisateur, jamais dans le canal.

---

## 8. Systeme de rappels (reminders)

### 8.1 Fonctionnement

Les rappels sont des messages recurrents envoyes automatiquement dans le canal `@bingebeartv_live` a intervalles reguliers.

**Cycle de vie d'un rappel :**
1. Admin cree avec `/reminder 36h Pensez a renouveler votre abonnement!`
2. Le bot genere un ID unique (8 caracteres, ex: `a3f2b1c9`)
3. Sauvegarde dans `reminders.json` avec : message, intervalle (en secondes), last_sent=0, created_at
4. Le `reminder_worker` tourne en tache de fond, verifie toutes les 60 secondes
5. Si `now - last_sent >= interval` → envoie le message dans le canal, met a jour `last_sent`
6. Le rappel se repete indefiniment jusqu'a suppression avec `/delreminder <id>`

### 8.2 Format des intervalles

| Format | Duree |
|--------|-------|
| `30m` | 30 minutes |
| `12h` | 12 heures |
| `36h` | 36 heures |
| `2d` | 2 jours |
| `7d` | 7 jours |

### 8.3 Fichier reminders.json

```json
{
  "a3f2b1c9": {
    "message": "Pensez a renouveler votre abonnement!",
    "interval": 129600,
    "last_sent": 1710634051.2,
    "created_at": 1710547717.5
  }
}
```

### 8.4 Persistance

Les rappels survivent aux redemarrages du bot car ils sont sauvegardes dans un fichier JSON. Au demarrage, le `reminder_worker` recharge les rappels et reprend la ou il s'est arrete.

---

## 9. Modules auxiliaires

### 9.1 config.py — Validation de la configuration

**Variables obligatoires** (le bot quitte si absentes) :
- `API_ID`, `API_HASH`, `BOT_TOKEN`, `CHAT_ID`

**Variables recommandees** (warning si absentes, mode degrade) :
- `SESSION_STRING`, `IPTV_SERVER_URL`, `IPTV_USERNAME`, `IPTV_PASSWORD`

### 9.2 logger.py — Logging structure

- Console : niveau INFO et superieur
- Fichier : niveau DEBUG et superieur avec rotation automatique
- Rotation : 10 MB par fichier, 5 fichiers de backup
- Format : `%(asctime)s [%(levelname)s] %(name)s: %(message)s`
- Encodage UTF-8

### 9.3 health.py — Serveur HTTP health check

Serveur HTTP asynchrone (aiohttp) sur le port 8080.

**Endpoint** : `GET /health`

**Reponse** :
```json
{
    "status": "ok",
    "uptime_seconds": 3600,
    "is_streaming": true,
    "last_stream_activity": 1234567890.5,
    "last_news_forwarded": 1234567890.5
}
```

### 9.4 stream_state.py — Auto-resume du stream

- Fichier : `stream_state.json`
- Contenu : `{"channel": {"id": ..., "name": ..., "url": ...}, "timestamp": ...}`
- TTL : 30 minutes (configurable via `STREAM_STATE_MAX_AGE`)
- Au redemarrage, si l'etat a < 30 min, le stream reprend automatiquement

### 9.5 utils/retry.py — Retry avec backoff exponentiel

```python
retry_sync(func, max_retries=3, base_delay=1)   # Pour les fonctions sync (API IPTV)
retry_async(func, max_retries=3, base_delay=1)   # Pour les fonctions async
```

Delais : 1s → 2s → 4s (double a chaque tentative)

---

## 10. Authentification et autorisation

### Niveaux d'acces

**Admins** (`ADMIN_IDS` dans .env) :
- Liste d'IDs Telegram numeriques separes par des virgules
- Acces a toutes les commandes y compris `/importnews`, `/announcement`, `/reminder`
- Si la liste est vide : tous les utilisateurs sont consideres comme admins

**Utilisateurs autorises** (`ALLOWED_USERNAMES` dans .env) :
- Liste de noms d'utilisateur Telegram (sans @)
- Peuvent utiliser : `/play`, `/stop`, `/test`
- Les admins sont automatiquement autorises

### Logique de verification

```python
def is_admin(user_id):
    if not ADMIN_IDS:       # Pas d'admins definis
        return True          # Tout le monde est admin
    return user_id in ADMIN_IDS

def is_allowed_user(user):
    if is_admin(user.id):   # Les admins peuvent tout faire
        return True
    return user.username in ALLOWED_USERNAMES
```

---

## 11. Variables d'environnement

### Obligatoires
```env
API_ID=33417585                              # ID application Telegram (my.telegram.org)
API_HASH=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx    # Hash application Telegram
BOT_TOKEN=xxxxxxxxxx:xxxxxxxxxxxxxxxxxxx    # Token du bot (@BotFather)
CHAT_ID=bingebeartv_live                     # Username du groupe/canal cible (sans @)
```

### Recommandees (necessaires pour streaming + news)
```env
SESSION_STRING=BAH96XEA...                   # Session Pyrogram (generate_session.py)
IPTV_SERVER_URL=http://...                   # URL du serveur IPTV Xtream Codes
IPTV_USERNAME=...                            # Identifiant IPTV
IPTV_PASSWORD=...                            # Mot de passe IPTV
```

### Optionnelles
```env
ADMIN_IDS=1540634249                         # IDs Telegram des admins
ALLOWED_USERNAMES=DefiMack                   # Usernames autorises pour le streaming
NEWS_SOURCE_CHANNEL=-1001763758614           # ID du canal source des news
NEWS_DEST_CHANNEL=@bingebeartv_live          # Canal de destination des news
NEWS_POLL_INTERVAL=7200                      # Intervalle polling news en secondes (defaut 2h)
LOG_DIR=/var/log/bingebear                   # Repertoire des logs
HEALTH_PORT=8080                             # Port du serveur health check
STREAM_STATE_MAX_AGE=1800                    # Duree max etat sauvegarde (30 min)
```

---

## 12. Deploiement VPS

### Configuration actuelle

- **Serveur** : OVH VPS Ubuntu 25.04 (vps-5f6c616f.vps.ovh.net, IP: 137.74.42.174)
- **Utilisateur** : `ubuntu`
- **Python** : 3.13 (natif Ubuntu 25.04)
- **Connexion SSH** : `ssh ubuntu@137.74.42.174` (cle SSH, pas de mot de passe)

### Service systemd

Fichier : `/etc/systemd/system/bingebear-bot.service`

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

### Commandes de gestion

```bash
# Statut
sudo systemctl status bingebear-bot

# Redemarrer
sudo systemctl restart bingebear-bot

# Logs en temps reel
sudo journalctl -u bingebear-bot -f

# Derniers 50 logs
sudo journalctl -u bingebear-bot -n 50 --no-pager

# Mise a jour du bot
cd ~/TelegramIPTVBot && git pull origin main && sudo systemctl restart bingebear-bot
```

---

## 13. Diagnostic et debugging

### Logs de diagnostic au demarrage

Le bot verifie et log au demarrage :

```
Configuration validee — toutes les variables requises sont presentes
BingeBear TV - Combined Bot
Demarrage du client utilisateur...
Connecte: DeFi Mack (@DefiMack)                              ← SESSION_STRING valide
PyTgCalls pret                                                 ← streaming disponible
Canal source accessible: SERVICE INFORMATION (id=-1001763758614) ← canal lisible
Statut dans le canal source: ChatMemberStatus.MEMBER           ← compte abonne
Ecoute canal source: -1001763758614
Destination news: @bingebeartv_live
Handlers Pyrogram enregistres: 2                               ← handlers actifs
[NEWS-POLL] Auto-import actif (toutes les 7200s)               ← polling 2h actif
Groupe cible: @bingebeartv_live
```

### Logs du news forwarder

```
[NEWS] Message recu: chat_id=-1001763758614, msg_id=3480, text='Dear Reseller...'
[NEWS] Message 3480 accepte pour transfert        ← matche un pattern
[NEWS] Message 3481 ne matche pas les patterns    ← filtre (pas pertinent)
[NEWS] Message 3479 deja transfere (cache)        ← anti-doublon
[NEWS-POLL] 3 message(s) importe(s)               ← polling automatique
[NEWS-POLL] Aucun nouveau message                 ← rien de nouveau
```

### Commandes de diagnostic

```bash
# Logs du jour filtres sur les news
sudo journalctl -u bingebear-bot --since "today" | grep -i "news"

# Verifier si le polling a tourne
sudo journalctl -u bingebear-bot --since "today" | grep "NEWS-POLL"

# Verifier les erreurs
sudo journalctl -u bingebear-bot --since "today" | grep -i "error"
```

### Erreurs frequentes dans les logs

**`BadHttpMessage: 400, Pause on PRI/Upgrade`** :
- Des scanners internet (Censys, Shodan...) envoient des requetes HTTP/2 sur le port 8080
- C'est du bruit normal, pas un probleme pour le bot

**`Task was destroyed but it is pending`** :
- Apparait a l'arret du bot (systemctl stop/restart)
- Normal : les taches de fond (watchdog, reminder_worker) sont interrompues

**`NetworkError: httpx.ReadError`** :
- Erreur reseau temporaire avec l'API Telegram
- Le bot se reconnecte automatiquement

---

## 14. Bug connu : on_message ne se declenche pas

### Description du probleme

Le handler Pyrogram `on_message(filters.chat(NEWS_SOURCE_CHANNEL))` ne se declenche JAMAIS quand un nouveau message arrive dans le canal source. Pourtant :

- Le compte est bien abonne au canal (ChatMemberStatus.MEMBER)
- Le handler est bien enregistre (2 handlers Pyrogram actifs)
- `get_chat_history()` fonctionne parfaitement (prouve par /importnews)
- Le filtre utilise bien un INT (-1001763758614)
- `user_client.start()` est bien appele dans `post_init()`

### Hypotheses non confirmees

1. **Conflit de boucle evenementielle** : `run_polling()` de python-telegram-bot est bloquant et prend le controle de la boucle asyncio. Pyrogram pourrait ne pas recevoir ses updates dans cette configuration.

2. **Probleme avec pyrofork** : La version pyrofork 2.3.58 pourrait avoir un bug avec les handlers `on_message` sur les canaux.

3. **Pas de `idle()`** : Pyrogram a normalement besoin de `idle()` pour maintenir la connexion active, mais dans notre cas `run_polling()` maintient la boucle.

### Workaround en place

Le `news_poll_worker` toutes les 2 heures contourne le probleme en utilisant `get_chat_history()` (appel actif) au lieu de `on_message` (ecoute passive). Ce workaround fonctionne et est fiable.

---

## 15. Historique des modifications recentes

| Commit | Description |
|--------|-------------|
| `892d826` | Ajout auto-import des news toutes les 2h (news_poll_worker) comme fallback du on_message |
| `544f690` | Ajout commandes /announcement et /reminder pour gestion admin du canal |
| `434c9b2` | Mise a jour documentation avec logs de diagnostic |
| `1cbc42e` | Fix recursion infinie dans reply_private + ajout logs diagnostic news |
| `e7955f1` | Toutes les reponses aux commandes envoyees en DM prive |
| `3a4dccf` | Remplacement "Dear Reseller(s)" par "Dear Users" dans les news |
| `b790191` | Ajout commande /importnews pour import manuel des news (admin) |
| `629f228` | Pagination des categories et chaines en plusieurs messages |
| `a5b36b7` | SESSION_STRING et identifiants IPTV rendus optionnels pour mode test |

---

## Points d'attention

1. **SESSION_STRING** : Indispensable pour le streaming ET le transfert de news. Sans elle, le bot ne peut que repondre aux commandes basiques. Generee via `generate_session.py`.

2. **Deux clients Telegram** : Le bot utilise un client utilisateur (Pyrogram, compte DeFi Mack) ET un bot (@Bingebear_tv_bot). Les deux sont necessaires : le user_client ecoute/lit, le bot envoie.

3. **Rate limiting** : Telegram limite a ~30 msg/sec par canal. Le bot espace les envois de 1.5s. L'erreur 429 est geree automatiquement.

4. **Port 8080** : Utilise par le health check. Les erreurs `BadHttpMessage` dans les logs viennent de scanners internet — c'est du bruit, pas un probleme.

5. **DM prives** : L'utilisateur doit avoir fait `/start` en prive avec le bot au moins une fois pour recevoir les reponses.

6. **Fichiers de persistance** : `news_cache.json`, `stream_state.json` et `reminders.json` sont crees automatiquement dans le working directory et survivent aux redemarrages.

7. **Bug on_message** : Le transfert automatique en temps reel ne fonctionne pas. Le workaround (polling toutes les 2h) est en place et fiable. Le delai maximum entre un message dans le canal source et sa publication dans @bingebeartv_live est donc de 2 heures.
