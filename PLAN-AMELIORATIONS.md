# BingeBear TV Bot — Plan d'Améliorations & Déploiement VPS

> Ce document est un plan d'action pour Claude Code.
> Suivre les phases dans l'ordre. Chaque tâche est autonome et testable.

---

## Contexte

- **Projet** : TelegramIPTVBot (BingeBear TV) — bot Telegram diffusant de l'IPTV 24/7
- **Double implémentation** : Node.js (`src/`) et Python (`python-bot/`)
- **Recommandation** : Déployer uniquement l'implémentation **Python** (plus mature, WebRTC natif via PyTgCalls, news forwarding intégré)
- **Cible** : VPS OVH `vps-5f6c616f.vps.ovh.net` — Ubuntu 25.04 — Gravelines (GRA)
- **Objectif** : Fonctionnement stable 24/7 avec auto-restart, monitoring et logging

---

## Phase 1 — Corrections Critiques & Hautes (à faire AVANT le déploiement)

### 1.1 Sécuriser les credentials (Bug #1 — CRITIQUE)

**Fichiers** : `.env`, `session.txt`, `python-bot/.env`, `*.session`

- [x] Vérifier que `.gitignore` à la racine contient :
  ```
  .env
  *.env
  session.txt
  *.session
  output/
  __pycache__/
  *.pyc
  venv/
  ```
- [ ] Si le dépôt a déjà été pushé avec des secrets : révoquer TOUS les tokens immédiatement (BotFather, API Telegram, mot de passe Xtream Codes, session Pyrogram)
- [ ] Vérifier avec `git log --all --full-history -- '*.env' 'session.txt'` qu'aucun secret n'est dans l'historique Git. Si oui, utiliser `git filter-repo` pour purger
- [ ] Restreindre les permissions des fichiers sensibles : `chmod 600 .env session.txt *.session`

### 1.2 Corriger la race condition dans startStream() (Bug #2 — HAUTE)

**Fichier** : `src/streamer.js`

Le flag `isStreaming` est mis à `true` APRÈS l'appel async. Des `/play` successifs peuvent lancer plusieurs FFmpeg.

```javascript
// AVANT (bugué)
async startStream(content) {
    this.currentContent = content;
    await this.streamToTelegram(content);
    this.isStreaming = true;
    return true;
}

// APRÈS (corrigé)
async startStream(content) {
    if (this.isStreaming) {
        console.warn('[STREAM] Déjà en cours, commande ignorée');
        return false;
    }
    this.isStreaming = true; // AVANT l'appel async
    this.currentContent = content;
    try {
        await this.streamToTelegram(content);
        return true;
    } catch (err) {
        this.isStreaming = false; // Reset en cas d'erreur
        this.currentContent = null;
        throw err;
    }
}
```

### 1.3 Gérer les erreurs FFmpeg (Bug #3 — HAUTE)

**Fichier** : `src/streamer.js`

- [x] Ajouter un timeout de démarrage (10s) : si FFmpeg n'émet pas de données dans les 10 premières secondes, considérer le lancement comme échoué
- [x] Logger **toutes** les sorties stderr dans un fichier dédié, pas seulement en console
- [x] Utiliser le callback `on('start')` de fluent-ffmpeg pour confirmer le démarrage avant de continuer
- [x] Ajouter un watchdog : si aucun nouveau segment n'est produit pendant 2× la durée d'un segment (10 min), redémarrer FFmpeg

### 1.4 Sécuriser les promesses dans watchSegments() (Bug #4 — HAUTE)

**Fichier** : `src/streamer.js`

- [x] Remplacer `fs.readdirSync()` et `fs.statSync()` par `fs.promises.readdir()` et `fs.promises.stat()` dans un try/catch
- [x] Entourer tout le contenu du callback `setInterval` d'un try/catch
- [x] Ajouter un handler global comme filet de sécurité :
  ```javascript
  process.on('unhandledRejection', (reason, promise) => {
      console.error('[FATAL] Unhandled rejection:', reason);
      // logger.error(...) quand le logging sera implémenté
  });
  ```

---

## Phase 2 — Corrections Moyennes (stabilité production)

### 2.1 Corriger waitForFileStable() (Bug #5)

**Fichier** : `src/streamer.js`

La fonction retourne **toujours** `true`, même en timeout. Un fichier en cours d'écriture peut être uploadé partiellement.

```javascript
// AVANT
async waitForFileStable(filePath, timeout = 30000) {
    // ... logique de vérification ...
    return true; // Retourne TOUJOURS true !
}

// APRÈS
async waitForFileStable(filePath, timeout = 30000) {
    const startTime = Date.now();
    let lastSize = 0;
    while (Date.now() - startTime < timeout) {
        try {
            const stat = await fs.promises.stat(filePath);
            if (stat.size > 0 && stat.size === lastSize) {
                return true; // Fichier stable
            }
            lastSize = stat.size;
        } catch {
            return false; // Fichier supprimé/inaccessible
        }
        await new Promise(r => setTimeout(r, 2000));
    }
    return false; // TIMEOUT = fichier pas stable
}
```

Et dans le code appelant, ne pas uploader si `false`.

### 2.2 Corriger la fuite du segment watcher (Bug #6)

**Fichier** : `src/streamer.js`

- [x] Stocker l'ID du `setInterval` dans `this.watcherInterval`
- [x] Appeler `clearInterval(this.watcherInterval)` dans :
  - `stopStream()`
  - Le handler `on('error')` de FFmpeg
  - Le handler `on('end')` de FFmpeg
- [x] Ajouter un guard : si `this.watcherInterval` existe déjà, le nettoyer avant d'en créer un nouveau

### 2.3 Null safety (Bug #7)

**Fichier** : `src/bot.js`

- [x] Remplacer :
  ```javascript
  message += `URL: ${content.url.substring(0, 50)}...`;
  ```
  par :
  ```javascript
  message += `URL: ${content?.url?.substring(0, 50) ?? 'N/A'}...`;
  ```
- [x] Faire un audit global des accès sans vérification à `content`, `content.url`, `content.name` dans tout `bot.js`

### 2.4 Externaliser les valeurs hardcodées (Bug #8)

**Fichiers** : `python-bot/bot.py`, `python-bot/run_all.py`, `python-bot/news_forwarder.py`

- [x] Déplacer ces valeurs vers `.env` :
  ```env
  NEWS_SOURCE_CHANNEL=-1001763758614
  NEWS_DEST_CHANNEL=@bingebeartv_live
  ADMIN_IDS=123456789
  ALLOWED_USERNAMES=DefiMack
  ```
- [x] Charger avec `os.getenv()` et des valeurs par défaut raisonnables
- [x] Supprimer les constantes hardcodées dans le code Python

### 2.5 Terminaison FFmpeg robuste (Bug #9)

**Fichier** : `src/streamer.js`

```javascript
async killFFmpeg(process) {
    if (!process || process.killed) return;

    process.kill('SIGINT'); // Arrêt propre
    
    // Attendre 5s, puis forcer
    const forceKill = setTimeout(() => {
        if (!process.killed) {
            console.warn('[FFMPEG] SIGINT ignoré, envoi SIGKILL');
            process.kill('SIGKILL');
        }
    }, 5000);

    process.on('exit', () => clearTimeout(forceKill));
}
```

### 2.6 Implémenter le logging structuré (Bug #10)

**Fichiers** : Tous

C'est la correction la plus impactante pour la maintenabilité en production.

#### Python (`python-bot/`)

Créer un fichier `python-bot/logger.py` :

```python
import logging
import os
from logging.handlers import RotatingFileHandler

def setup_logger(name='bingebear'):
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)

    # Console
    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    console.setFormatter(logging.Formatter(
        '%(asctime)s [%(levelname)s] %(name)s: %(message)s'
    ))

    # Fichier avec rotation
    log_dir = os.getenv('LOG_DIR', '/var/log/bingebear')
    os.makedirs(log_dir, exist_ok=True)
    file_handler = RotatingFileHandler(
        os.path.join(log_dir, f'{name}.log'),
        maxBytes=10 * 1024 * 1024,  # 10 MB
        backupCount=5
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(
        '%(asctime)s [%(levelname)s] %(name)s (%(filename)s:%(lineno)d): %(message)s'
    ))

    logger.addHandler(console)
    logger.addHandler(file_handler)
    return logger
```

- [x] Remplacer tous les `print()` et `console.log()` par des appels au logger
- [x] Utiliser les niveaux : `DEBUG` (détail), `INFO` (flow normal), `WARNING` (récupérable), `ERROR` (erreur gérée), `CRITICAL` (crash)

#### Node.js (`src/`) — si conservé

- [ ] Installer Winston : `npm install winston`
- [ ] Même pattern : console + fichier avec rotation

### 2.7 Validation des variables d'environnement au démarrage (Bug #11)

Créer un fichier `python-bot/config.py` :

```python
import os
import sys

REQUIRED_VARS = [
    'API_ID',
    'API_HASH',
    'BOT_TOKEN',
    'CHAT_ID',
    'SESSION_STRING',
    'IPTV_SERVER_URL',
    'IPTV_USERNAME',
    'IPTV_PASSWORD',
]

OPTIONAL_VARS = {
    'ADMIN_IDS': '',
    'ALLOWED_USERNAMES': 'DefiMack',
    'NEWS_SOURCE_CHANNEL': '-1001763758614',
    'NEWS_DEST_CHANNEL': '@bingebeartv_live',
    'LOG_DIR': '/var/log/bingebear',
}

def validate_config():
    """Vérifie toutes les variables requises au démarrage."""
    missing = [var for var in REQUIRED_VARS if not os.getenv(var)]
    if missing:
        print(f"[FATAL] Variables d'environnement manquantes : {', '.join(missing)}")
        print("Vérifiez votre fichier .env ou vos variables système.")
        sys.exit(1)

def get_config(key, default=None):
    """Récupère une variable avec valeur par défaut optionnelle."""
    return os.getenv(key, OPTIONAL_VARS.get(key, default))
```

- [x] Appeler `validate_config()` au tout début de `run_all.py`, `bot.py` et `news_forwarder.py`

### 2.8 Retry logic (Bug #12)

Créer `python-bot/utils/retry.py` :

```python
import asyncio
import logging

logger = logging.getLogger('bingebear')

async def retry_async(func, max_retries=3, base_delay=1, description='operation'):
    """Retry exponentiel pour les opérations async."""
    for attempt in range(max_retries):
        try:
            return await func()
        except Exception as e:
            if attempt == max_retries - 1:
                logger.error(f'[RETRY] {description} échoué après {max_retries} tentatives: {e}')
                raise
            delay = base_delay * (2 ** attempt)
            logger.warning(f'[RETRY] {description} tentative {attempt + 1}/{max_retries} échouée, retry dans {delay}s: {e}')
            await asyncio.sleep(delay)
```

- [x] Appliquer sur : appels API IPTV (Xtream Codes), envois Telegram, uploads de fichiers

### 2.9 Health checks (Bug #13)

Ajouter un mini-serveur HTTP dans `run_all.py` :

```python
from aiohttp import web
import time

class HealthCheck:
    def __init__(self):
        self.bot_started = time.time()
        self.last_stream_activity = None
        self.is_streaming = False
        self.last_news_forwarded = None

    async def handle(self, request):
        uptime = int(time.time() - self.bot_started)
        status = {
            'status': 'ok',
            'uptime_seconds': uptime,
            'is_streaming': self.is_streaming,
            'last_stream_activity': self.last_stream_activity,
            'last_news_forwarded': self.last_news_forwarded,
        }
        return web.json_response(status)

    async def start(self, port=8080):
        app = web.Application()
        app.router.add_get('/health', self.handle)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, '0.0.0.0', port)
        await site.start()
```

- [x] Ajouter `aiohttp` à `requirements.txt`
- [x] Lancer le health check dans `run_all.py` au démarrage
- [x] Ce endpoint sera utilisé par le watchdog systemd et le script de monitoring

---

## Phase 3 — Corrections Basses + Nettoyage

### 3.1 Comparaison stricte (Bug #14)

**Fichier** : `src/database.js`

- [x] Remplacer `==` par `===` avec fallback `String()` dans `getChannelById()`

### 3.2 Logging des erreurs Python (Bug #15)

**Fichier** : `python-bot/bot.py`, `python-bot/run_all.py`

- [x] Ajouter `logger.exception()` avant chaque `reply_text("Erreur: ...")` dans tous les handlers

### 3.3 Nettoyer le DatabaseManager (Bug #16)

**Fichier** : `src/database.js`, `src/bot.js`

- [x] Classe renommée `IPTVApiClient` (reflète son rôle réel)
- [x] Méthodes mortes `logStream()` et `updateStreamLog()` supprimées
- [x] Export rétro-compatible conservé (`DatabaseManager: IPTVApiClient`)
- [x] `bot.js` mis à jour pour utiliser `IPTVApiClient`

---

## Phase 4 — Améliorations Architecturales

### 4.1 Auto-restart intelligent du streaming

- [x] Sauvegarder l'état courant (chaîne, timestamp) dans `stream_state.json` (configurable via `STREAM_STATE_FILE`)
- [x] Au démarrage, vérifier si un état précédent existe et reprendre le streaming automatiquement (`auto_resume_stream()`)
- [x] Détecter les flux coupés (pas d'activité depuis 60s) et relancer automatiquement (`stream_watchdog()`)
- [x] Module `stream_state.py` créé (save/load/clear avec TTL de 30min)

### 4.2 News Forwarder amélioré

- [x] Cache anti-doublons `news_cache.py` (fichier JSON, TTL 7 jours, max 500 entrées)
- [x] File d'attente rate-limit `news_queue.py` (délai 1.5s entre envois, retry auto sur 429)
- [x] Support images ajouté dans `news_forwarder.py` standalone (photo + caption)
- [x] Cache et queue intégrés dans `run_all.py` et `news_forwarder.py`

### 4.3 Docker Compose

- [x] `python-bot/Dockerfile` mis à jour (run_all.py, health check, curl, logs)
- [x] `docker-compose.yml` créé à la racine (volumes persistants, health check, env vars)
- [x] `.gitignore` mis à jour (stream_state.json, news_cache.json)

---

## Phase 5 — Déploiement VPS OVH (guide pas à pas)

**Fichiers de déploiement créés dans `deploy/` :**

### 5.1 Sécurisation du VPS + 5.2 Installation des dépendances

- [x] Script `deploy/setup-vps.sh` créé — automatise : mise à jour système, création utilisateur `bingebear`, installation Python 3.11 + FFmpeg + git, firewall UFW (ports 2222 + 8080), sécurisation SSH
- [x] Template `deploy/.env.example` créé — toutes les variables documentées avec descriptions

```bash
# Usage sur le VPS :
ssh root@vps-5f6c616f.vps.ovh.net
sudo bash setup-vps.sh
```

### 5.3 Déployer le bot

- [x] Instructions de déploiement incluses dans la sortie du script `setup-vps.sh`
- [x] `deploy/.env.example` fournit un template complet de toutes les variables

```bash
# Apres setup-vps.sh, en tant que bingebear :
su - bingebear
git clone https://github.com/VOTRE_USER/TelegramIPTVBot.git
cd TelegramIPTVBot/python-bot
python3.11 -m venv venv && source venv/bin/activate
pip install --upgrade pip && pip install -r requirements.txt
cp ../deploy/.env.example .env && nano .env  # Remplir les valeurs
chmod 600 .env
python run_all.py  # Test manuel, puis Ctrl+C
```

### 5.4 Service systemd (fonctionnement 24/7)

- [x] Fichier `deploy/bingebear-bot.service` créé (prêt à copier dans `/etc/systemd/system/`)
- [x] Securité : `NoNewPrivileges`, `ProtectSystem=strict`, `PrivateTmp`
- [x] Watchdog systemd (120s) + auto-restart (`RestartSec=10`)

```bash
sudo cp ~/TelegramIPTVBot/deploy/bingebear-bot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable bingebear-bot
sudo systemctl start bingebear-bot
```

### 5.5 Commandes utiles au quotidien

- [x] Script `deploy/update-bot.sh` créé — git pull + pip install + restart + health check en une commande

```bash
# Mise a jour rapide :
bash ~/TelegramIPTVBot/deploy/update-bot.sh

# Commandes manuelles :
sudo systemctl status bingebear-bot        # Statut
journalctl -u bingebear-bot -f             # Logs temps reel
journalctl -u bingebear-bot --since '1h'   # Logs derniere heure
sudo systemctl restart bingebear-bot       # Redemarrer
curl http://localhost:8080/health           # Health check
```

---

## Phase 6 — Monitoring & Maintenance

**Fichiers créés dans `deploy/` :**

### 6.1 Script de monitoring (alerte Telegram si le bot est down)

- [x] `deploy/monitor.sh` — vérifie le service systemd ET le health check HTTP
- [x] Lit `BOT_TOKEN` et `ADMIN_IDS` depuis le `.env` (pas de secrets en dur)
- [x] Alerte Telegram avec statut (DOWN / RECOVERED / CRITICAL)
- [x] Redémarrage automatique + confirmation du résultat
- [x] Log dans `/var/log/bingebear/monitor.log`

### 6.2 Rotation des logs

- [x] `deploy/logrotate-bingebear` — rotation quotidienne, 14 jours de rétention, compression

### 6.3 Nettoyage automatique des segments temporaires

- [x] Cron quotidien à 3h inclus dans `deploy/setup-monitoring.sh` (`.mp4`, `.jpg`, `.png`)

### Installation du monitoring

- [x] `deploy/setup-monitoring.sh` — installe tout en une commande :

```bash
sudo bash ~/TelegramIPTVBot/deploy/setup-monitoring.sh
```

---

## Checklist de mise en production

### Critique (bloquant)
- [ ] VPS sécurisé (SSH clé, firewall, utilisateur dédié `bingebear`)
- [ ] Credentials régénérés si le dépôt a été public
- [ ] `.gitignore` vérifié — aucun secret dans le dépôt

### Haute (avant mise en prod)
- [ ] Python 3.11 + FFmpeg installés sur le VPS
- [ ] Virtualenv créé, dépendances installées
- [ ] Fichier `.env` complet et `chmod 600`
- [ ] Test manuel réussi (`python run_all.py`)
- [ ] Service systemd créé, activé et fonctionnel
- [ ] Test de reboot VPS : le bot redémarre-t-il automatiquement ?
- [ ] Bugs Phase 1 corrigés (#1 à #4)

### Moyenne (première semaine de prod)
- [ ] Logging structuré implémenté
- [ ] Dossier `/var/log/bingebear/` créé avec bonnes permissions
- [ ] Script de monitoring cron actif
- [ ] Logrotate configuré
- [ ] Nettoyage auto du dossier `output/`
- [ ] Validation des env vars au démarrage
- [ ] Health check HTTP `/health` opérationnel

### Basse (amélioration continue)
- [ ] Bugs Phase 3 corrigés (#14 à #16)
- [ ] Auto-restart intelligent du streaming
- [ ] Docker Compose en place
- [ ] Documentation de maintenance à jour
