# PLAN — Refonte BingeBear TV Bot

## Contexte

Ce plan est destiné à Claude Code (VS Code) qui a accès au projet complet en local.
Le bot tourne sur **Railway** — seul le dossier `python-bot/` est déployé.
Le fichier d'entrée en production est `python-bot/run_all.py`.

**Deux fichiers de référence sont fournis avec ce plan :**
- `promotions.py` — Module de gestion des campagnes promos (à placer dans `python-bot/`)
- `promo_commands.py` — Code de référence contenant les commandes et le worker promo (à intégrer dans `run_all.py`, PAS à utiliser tel quel comme fichier séparé)

**Règle absolue** : ne JAMAIS casser le bot en production. Chaque modification doit être testable indépendamment. Si un doute existe, garder le comportement existant et ajouter par-dessus.

---

## Phase 1 — Nettoyage du repo (priorité haute)

### 1.1 Supprimer le code mort

Le repo contient trois versions du bot qui coexistent. Seul `python-bot/` est utilisé en production.

**Supprimer ces fichiers/dossiers à la racine :**
- `bot.py` (540 lignes, ancien bot Python standalone)
- `src/` (bot.js Node.js + streamer.js + database.js + live-streamer.js + userbot.js)
- `archive/` (bot.py, bot_python.py, news_forwarder.py, run_all.py — anciennes copies)
- `wordpress-plugin/` (plugin WP déconnecté, jamais utilisé par le bot Python)
- `package.json` et `package-lock.json` (dépendances Node.js inutilisées)
- `generate_session.py` à la racine (doublon de `python-bot/generate_session.py`)
- `run_all.py` à la racine (s'il existe — doublon de `python-bot/run_all.py`)
- `requirements.txt` à la racine (doublon divergent de `python-bot/requirements.txt`)
- `runtime.txt` à la racine (doublon de `python-bot/runtime.txt`)

**Garder :**
- `python-bot/` (tout le code actif)
- `deploy/` (scripts VPS utiles)
- `Dockerfile` à la racine (sera corrigé en 1.2)
- `docker-compose.yml` (sera corrigé en 1.2)
- `.gitignore`
- `.env.example` (sera mis à jour)
- `README.md` (sera mis à jour)
- `DOCUMENTATION.md` (sera mis à jour)

### 1.2 Corriger le Dockerfile racine

Le Dockerfile actuel lance `python bot.py` (le fichier mort). Le corriger pour pointer vers le bon code.

**Remplacer le contenu de `Dockerfile` :**

```dockerfile
FROM python:3.11-slim

RUN apt-get update && apt-get install -y \
    ffmpeg \
    libavcodec-extra \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY python-bot/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY python-bot/ .

CMD ["python", "run_all.py"]
```

**Mettre à jour `docker-compose.yml`** pour refléter la même structure (le build context est `.` et le Dockerfile copie `python-bot/`).

### 1.3 Corriger le Procfile racine

Le `Procfile` actuel pointe probablement vers l'ancien code. Le corriger :

```
worker: cd python-bot && python run_all.py
```

Vérifier aussi `nixpacks.toml` — il doit pointer vers `python-bot/run_all.py`.

### 1.4 Mettre à jour .env.example

Fusionner le `.env.example` de la racine avec celui de `python-bot/` (si existant). Le fichier final doit contenir TOUTES les variables utilisées par `run_all.py` :

```env
# === Telegram ===
API_ID=
API_HASH=
BOT_TOKEN=
CHAT_ID=
SESSION_STRING=

# === IPTV ===
IPTV_SERVER_URL=
IPTV_USERNAME=
IPTV_PASSWORD=

# === Claude API ===
ANTHROPIC_API_KEY=

# === Admin ===
ADMIN_IDS=
ALLOWED_USERNAMES=DefiMack

# === News Forwarder ===
NEWS_SOURCE_CHANNEL=-1001763758614
NEWS_DEST_CHANNEL=@bingebeartv_live
NEWS_POLL_INTERVAL=7200
CLAUDE_MAX_CALLS_PER_CYCLE=50

# === Timezone ===
TZ_OFFSET_HOURS=0

# === Health Check ===
HEALTH_PORT=8080
```

### 1.5 Mettre à jour le README.md

Simplifier le README pour refléter la réalité :
- Supprimer toutes les références à Node.js, npm, le plugin WordPress
- Indiquer clairement que le code actif est dans `python-bot/`
- Documenter les nouvelles commandes promo
- Garder les sections IPTV, déploiement, troubleshooting

---

## Phase 2 — Sécurité (priorité haute)

### 2.1 Masquer les credentials IPTV dans les logs et réponses

**Problème** : Les URLs de stream contiennent les credentials IPTV en clair :
`{IPTV_SERVER}/live/{IPTV_USER}/{IPTV_PASS}/{stream_id}.ts`

Ces URLs apparaissent dans :
- Les logs (`logger.info` avec le nom de chaîne + URL)
- Les réponses `/status` (si le code affiche l'URL)
- L'état sauvegardé dans `stream_state.json`

**Fix** : Créer une fonction `sanitize_url(url)` dans `run_all.py` qui remplace les credentials par `***` dans toute URL avant de la logger ou l'afficher :

```python
def sanitize_url(url: str) -> str:
    """Masquer les credentials IPTV dans les URLs pour les logs."""
    if IPTV_USER and IPTV_PASS:
        url = url.replace(IPTV_USER, "***")
        url = url.replace(IPTV_PASS, "***")
    return url
```

**Appliquer** `sanitize_url()` partout où une URL de stream est loggée ou affichée à l'utilisateur. NE PAS l'appliquer à l'URL passée à PyTgCalls (elle doit rester complète pour que le stream fonctionne).

### 2.2 Supprimer la commande /setiptv

**Problème** : La commande `/setiptv` dans `bot.py` (l'ancien code) permettait de changer les credentials IPTV par simple message Telegram sans confirmation. 

**Vérifier** si cette commande existe dans `python-bot/run_all.py`. Si oui, la supprimer. Les credentials IPTV doivent être changés uniquement via les variables d'environnement sur Railway.

---

## Phase 3 — Découpage du monolithe run_all.py (priorité moyenne)

### 3.1 Objectif

`run_all.py` fait ~1135 lignes. Le découper en modules cohérents sans changer le comportement.

**Structure cible de `python-bot/` après refactoring :**

```
python-bot/
  run_all.py              # Point d'entrée — init, event loop, post_init (~200 lignes)
  config.py               # Validation config (existe déjà, garder tel quel)
  logger.py               # Logging (existe déjà, garder tel quel)
  health.py               # Health check (existe déjà, garder tel quel)
  stream_state.py         # Persistance stream (existe déjà, garder tel quel)
  news_cache.py           # Cache anti-doublon (existe déjà, garder tel quel)
  news_queue.py           # File d'attente news (existe déjà, garder tel quel)
  reminders.py            # Rappels (existe déjà, garder tel quel)
  promotions.py           # Campagnes promo (NOUVEAU — fourni avec ce plan)
  claude_processor.py     # Traitement Claude (existe déjà, garder tel quel)
  commands/
    __init__.py
    streaming.py          # Commandes IPTV : /categories, /cat, /play, /stop, /status, /test
    news.py               # Commandes news : /importnews, /announcement
    admin.py              # Commandes admin : /start, /help, /reminder, /reminders, /delreminder, /testlistener
    promos.py             # Commandes promo : /promos, /addpromo, /editpromo, /delpromo + callback handler
  utils/
    __init__.py
    retry.py              # Retry avec backoff (existe déjà)
    helpers.py            # Fonctions partagées : is_admin, is_allowed_user, reply_private, escape_markdown, _is_duplicate_update, sanitize_url
  workers/
    __init__.py
    reminder_worker.py    # Worker rappels
    news_poll_worker.py   # Worker polling news
    stream_watchdog.py    # Watchdog stream
    promo_worker.py       # Worker campagnes promo (NOUVEAU)
```

### 3.2 Règles de découpage

1. **`run_all.py` ne garde que le bootstrap** : imports, chargement .env, création des clients (user_client, telegram_bot, pytgcalls), `post_init()` qui lance tous les workers, `main()` qui démarre la boucle événementielle, et l'enregistrement des handlers.

2. **Les variables globales partagées** (`current_stream`, `categories_cache`, `channels_cache`, `pytgcalls`, `health`, `news_cache`, `news_queue`, etc.) sont déclarées dans `run_all.py` et importées par les modules qui en ont besoin. Alternative : les regrouper dans un objet `AppState` passé aux handlers.

3. **Chaque fichier de commandes** exporte des fonctions async qui prennent `(update, context)` — le même signature que maintenant. `run_all.py` les importe et les enregistre avec `add_handler`.

4. **Chaque worker** exporte une fonction async qui prend les dépendances nécessaires (bot, logger, etc.) et tourne en boucle infinie.

5. **Tester après chaque déplacement** : le bot doit répondre à `/help` et `/status` après chaque étape.

### 3.3 Ordre de découpage recommandé

Faire un commit entre chaque étape pour pouvoir rollback.

1. Extraire `utils/helpers.py` (fonctions pures sans dépendances) → commit
2. Extraire `workers/` (fonctions isolées qui ne font que lire l'état global) → commit
3. Extraire `commands/streaming.py` (commandes IPTV) → commit
4. Extraire `commands/news.py` → commit
5. Extraire `commands/admin.py` → commit
6. Extraire `commands/promos.py` (nouvelles commandes promo) → commit
7. Nettoyer `run_all.py` (ne garder que le bootstrap) → commit

**ATTENTION** : Ce refactoring est le plus risqué. Si c'est trop ambitieux pour une seule session, il est acceptable de ne faire que l'étape 1 (helpers) + l'étape 6 (promos) et reporter le reste. Le système de promos peut être intégré directement dans `run_all.py` sans découpage si nécessaire — le plan est modulaire.

---

## Phase 4 — Intégration du système de campagnes promo (priorité haute)

### 4.1 Ajouter promotions.py

Copier le fichier `promotions.py` fourni dans `python-bot/promotions.py`.

Ce fichier contient :
- Persistence JSON (`promotions.json`)
- CRUD complet (add, delete, toggle, update)
- Scheduling intelligent (intervalle avec fenêtre horaire, jours spécifiques avec protection anti-doublon)
- 5 templates pré-configurés (free_trial, renewal, weekend_deal, sport_promo, new_user)
- Helpers de formatage et parsing

### 4.2 Intégrer les commandes promo dans run_all.py

Le fichier `promo_commands.py` fourni contient tout le code à intégrer. Il est organisé en sections clairement marquées. Voici ce qu'il faut faire :

**Imports à ajouter en haut de `run_all.py` :**

```python
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CallbackQueryHandler
from promotions import (
    load_promos, add_promo, delete_promo, toggle_promo,
    update_promo_message, get_promo, get_due_promos, mark_promo_sent,
    format_schedule, format_promo_summary, parse_weekdays,
    parse_interval as parse_promo_interval,
    TEMPLATES, WEEKDAY_NAMES,
)
```

**Fonctions à copier depuis `promo_commands.py` dans `run_all.py` :**
- `promos_command` — Panel principal avec inline keyboards
- `addpromo_command` — Création de promos (template / interval / days)
- `editpromo_command` — Modification du message
- `delpromo_command` — Suppression
- `promo_callback_handler` — Gestionnaire des boutons inline (toggle, preview, delete, templates, back)
- `promo_worker` — Tâche de fond (boucle 60s, vérifie les promos dues, envoie)

**Handlers à enregistrer dans `main()` :**

```python
application.add_handler(CommandHandler("promos", promos_command))
application.add_handler(CommandHandler("addpromo", addpromo_command))
application.add_handler(CommandHandler("editpromo", editpromo_command))
application.add_handler(CommandHandler("delpromo", delpromo_command))
application.add_handler(CallbackQueryHandler(promo_callback_handler, pattern="^promo_"))
```

**Worker à lancer dans `post_init()` :**

```python
asyncio.create_task(promo_worker(application.bot))
logger.info("[PROMO] Worker de campagnes promotionnelles actif")
```

**Mettre à jour `help_command` :**

Ajouter ces lignes dans le texte d'aide :
```
"/promos - Panel campagnes promo (admin)\n"
"/addpromo - Creer une campagne (admin)\n"
"/editpromo <id> <msg> - Modifier le message (admin)\n"
"/delpromo <id> - Supprimer une campagne (admin)\n"
```

### 4.3 Détails techniques des promos

**Types de schedule :**

| Type | Paramètres | Comportement |
|------|-----------|--------------|
| `interval` | `interval_seconds` + `send_hour` | Envoie si l'intervalle est écoulé ET que l'heure actuelle est dans la fenêtre [send_hour, send_hour+2h] |
| `weekdays` | `weekdays` (liste 0-6) + `send_hour` | Envoie si c'est le bon jour ET l'heure est dans [send_hour, send_hour+1h] ET pas déjà envoyé aujourd'hui |

**Templates pré-configurés :**

| Clé | Nom | Schedule | Heure |
|-----|-----|----------|-------|
| `free_trial` | Free Trial | Every 48h | 11h |
| `renewal` | Renewal Reminder | Every 3d | 18h |
| `weekend_deal` | Weekend Special | Fri+Sat | 12h |
| `sport_promo` | Sport Package | Thu+Fri | 17h |
| `new_user` | New User Welcome | Every 4d | 10h |

**Commandes utilisateur :**

```
/promos                                    → Panel interactif avec boutons inline
/addpromo template free_trial              → Créer depuis template
/addpromo interval 48h 11 Mon message      → Promo toutes les 48h vers 11h
/addpromo days weekends 12 Promo weekend!  → Promo samedi+dimanche vers 12h
/addpromo days fri,sat 18 Match ce soir!   → Promo vendredi+samedi vers 18h
/editpromo <id> <nouveau texte>            → Modifier le message
/delpromo <id>                             → Supprimer
```

**Jours acceptés par le parser :**
- Noms : `mon`, `tue`, `wed`, `thu`, `fri`, `sat`, `sun`
- Raccourcis : `weekends`, `weekdays`, `daily`
- Chiffres : `0` (lun) à `6` (dim)
- Séparateur : virgule (`fri,sat,sun`)

---

## Phase 5 — Améliorations mineures (priorité basse)

### 5.1 Remplacer requests par aiohttp pour les appels IPTV

Les fonctions `_fetch_categories_sync()` et `_fetch_channels_sync()` utilisent `requests` (synchrone) wrappées dans `asyncio.to_thread()`. Comme `aiohttp` est déjà dans les dépendances, les remplacer par des appels async natifs :

```python
async def get_categories():
    global categories_cache
    try:
        url = f"{IPTV_SERVER}/player_api.php?username={IPTV_USER}&password={IPTV_PASS}&action=get_live_categories"
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=HEADERS, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                categories = await resp.json()
        categories_cache = [{"id": cat["category_id"], "name": cat["category_name"]} for cat in categories]
        return categories_cache
    except Exception as e:
        logger.error(f"Erreur categories: {e}")
        return []
```

Faire de même pour `get_channels_by_category()`. Supprimer ensuite `_fetch_categories_sync()`, `_fetch_channels_sync()`, et le `from utils.retry import retry_sync` s'il n'est plus utilisé ailleurs.

### 5.2 Ajouter promotions.json au .gitignore

Ajouter ces lignes dans `.gitignore` :

```
promotions.json
news_cache.json
stream_state.json
reminders.json
```

---

## Checklist finale

Après toutes les modifications, vérifier :

- [ ] `python-bot/run_all.py` se lance sans erreur
- [ ] `/help` affiche les nouvelles commandes promo
- [ ] `/promos` affiche le panel avec boutons inline (même vide)
- [ ] `/addpromo template free_trial` crée une promo et confirme
- [ ] `/promos` affiche la promo créée avec boutons toggle/preview/delete
- [ ] Cliquer sur "👁 Preview" affiche le message complet
- [ ] Cliquer sur "⏸" met la promo en pause
- [ ] `/delpromo <id>` supprime la promo
- [ ] `promotions.json` est créé et contient les bonnes données
- [ ] Les fichiers morts sont supprimés (bot.py, src/, archive/, wordpress-plugin/)
- [ ] Le Dockerfile pointe vers `python-bot/run_all.py`
- [ ] Aucune URL de stream ne contient des credentials dans les logs
- [ ] `.gitignore` inclut les fichiers de persistance JSON

---

## Ordre d'exécution recommandé

1. **Phase 1.1** — Supprimer les fichiers morts (risque zéro, ne touche pas au code actif)
2. **Phase 4** — Intégrer le système promo (la feature principale demandée)
3. **Phase 2** — Fixes de sécurité (sanitize_url, supprimer /setiptv si présent)
4. **Phase 1.2-1.5** — Corriger Dockerfile, Procfile, .env.example, README
5. **Phase 5** — Améliorations mineures (aiohttp, .gitignore)
6. **Phase 3** — Découpage du monolithe (optionnel, reporter si trop long)

Commiter entre chaque phase. Tester `/help` et `/status` après chaque commit.
