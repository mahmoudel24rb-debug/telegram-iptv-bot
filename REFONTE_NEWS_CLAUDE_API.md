# REFONTE : Intégration Claude API dans le système de transfert de news

## Contexte

Le bot BingeBear TV (`run_all.py`, ~877 lignes) transfère automatiquement les news du canal fournisseur IPTV (`SERVICE INFORMATION`, ID: -1001763758614) vers le canal BingeBear (`@bingebeartv_live`). Le système actuel utilise du pattern matching regex rigide qui rate tous les messages "hors template" — notamment les annonces critiques de pannes serveur, migrations, et urgences techniques.

Cette refonte remplace le filtrage regex + les modifications texte par un appel à l'API Claude (Anthropic) qui analyse, décide, catégorise et réécrit chaque message intelligemment.

**En parallèle**, cette refonte inclut le fix du bug `on_message` (handler Pyrogram temps réel qui ne se déclenche jamais — voir section dédiée en fin de document).

---

## PARTIE 1 : Fix du bug `on_message` (PRIORITÉ HAUTE)

### Diagnostic du problème

Le handler `on_message(filters.chat(NEWS_SOURCE_CHANNEL))` ne se déclenche jamais. Après analyse de la documentation et de l'architecture, la cause racine est identifiée :

**Cause principale : `run_polling()` de python-telegram-bot (PTB) v21 contrôle la boucle asyncio et empêche Pyrogram de recevoir ses updates.**

`run_polling()` appelle en interne `asyncio.run()` qui crée et gère la boucle événementielle. Pyrogram's `user_client.start()` connecte le client et démarre le dispatcher comme tâche asyncio, mais le dispatcher de Pyrogram (qui reçoit les updates et les dispatche aux handlers) ne reçoit pas assez de temps CPU ou est bloqué par la boucle de polling de PTB.

En effet, `get_chat_history()` fonctionne (c'est un appel actif/pull) mais `on_message` (écoute passive/push qui dépend du dispatcher) ne fonctionne pas — ce qui confirme que le client est connecté mais que le dispatcher d'updates ne tourne pas correctement.

### Fix à implémenter

**Remplacer `run_polling()` par une gestion manuelle de la boucle asyncio** pour que les deux frameworks (PTB et Pyrogram) cohabitent correctement.

#### Code actuel (fin de `run_all.py`, section main) :

```python
def main():
    application = Application.builder().token(BOT_TOKEN).post_init(post_init).build()
    # ... enregistrement des handlers ...
    application.run_polling(allowed_updates=Update.ALL_TYPES)
```

#### Code corrigé :

```python
import signal

async def main():
    """Boucle principale — gère PTB et Pyrogram dans le même event loop."""
    application = Application.builder().token(BOT_TOKEN).post_init(post_init).build()

    # Enregistrement de tous les handlers de commandes (identique à l'existant)
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("categories", categories_command))
    application.add_handler(CommandHandler("cat", cat_command))
    application.add_handler(CommandHandler("play", play_command))
    application.add_handler(CommandHandler("stop", stop_command))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(CommandHandler("test", test_command))
    application.add_handler(CommandHandler("importnews", import_news_command))
    application.add_handler(CommandHandler("announcement", announcement_command))
    application.add_handler(CommandHandler("reminder", reminder_command))
    application.add_handler(CommandHandler("reminders", list_reminders_command))
    application.add_handler(CommandHandler("delreminder", delete_reminder_command))

    # Démarrer PTB SANS run_polling() — on gère la boucle nous-mêmes
    async with application:
        await application.start()
        await application.updater.start_polling(allowed_updates=Update.ALL_TYPES)

        logger.info("Bot PTB démarré en mode polling manuel")
        logger.info("Pyrogram et PTB partagent la même boucle asyncio")

        # Attendre indéfiniment (CTRL+C ou signal SIGTERM pour arrêter)
        stop_event = asyncio.Event()

        # Gérer l'arrêt propre sur SIGTERM/SIGINT
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, stop_event.set)

        await stop_event.wait()

        logger.info("Arrêt en cours...")
        await application.updater.stop()
        await application.stop()

        # Arrêter Pyrogram proprement
        if HAS_USER_CLIENT and user_client:
            await user_client.stop()
            logger.info("Client Pyrogram arrêté")


if __name__ == "__main__":
    asyncio.run(main())
```

### Pourquoi ça fixe le problème

- `run_polling()` fait TOUT en interne : créer la boucle, démarrer, bloquer, arrêter. Il ne laisse pas d'espace pour d'autres frameworks asyncio.
- Avec `start()` + `updater.start_polling()`, PTB lance son polling comme une **tâche asyncio** dans la boucle existante, pas comme un blocage total.
- Pyrogram's dispatcher (démarré par `user_client.start()` dans `post_init()`) peut maintenant recevoir ses updates normalement car la boucle asyncio est partagée équitablement.

### Vérification après le fix

Ajouter ce log dans `post_init()` APRÈS `user_client.start()` :

```python
# Après user_client.start() dans post_init()
logger.info(f"Pyrogram dispatcher actif: {user_client.is_connected}")
logger.info(f"Handlers Pyrogram: {len(user_client.dispatcher.groups)}")
```

Et ajouter un log au DÉBUT de `forward_news()` :

```python
async def forward_news(client, message):
    logger.info(f"[NEWS-RT] on_message déclenché! msg_id={message.id}, chat={message.chat.id}")
    # ... reste du code ...
```

Après déploiement, un nouveau message dans le canal source doit produire le log `[NEWS-RT] on_message déclenché!`. Si ce n'est toujours pas le cas, vérifier :

1. Que `forward_news` est bien une coroutine (`async def`)
2. Que le handler est enregistré APRÈS la création du client mais ce point est normalement déjà OK
3. Ajouter un handler catch-all pour debug :

```python
# Handler de debug temporaire — capture TOUS les messages reçus par Pyrogram
@user_client.on_message()
async def debug_all_messages(client, message):
    logger.debug(f"[PYRO-DEBUG] Message reçu: chat_id={message.chat.id}, type={message.chat.type}")
```

Si ce handler catch-all ne se déclenche pas non plus, le problème est bien au niveau du dispatcher/event loop (ce que le fix main devrait résoudre).

### Gestion des signaux sur le VPS

Le service systemd envoie `SIGTERM` pour arrêter le bot. Avec l'ancien `run_polling()`, PTB gérait ça en interne. Avec le nouveau code, on le gère explicitement via `loop.add_signal_handler()`. Le comportement est identique : arrêt propre sur `systemctl stop/restart`.

**Note** : Sur Windows (dev local), `add_signal_handler` ne fonctionne pas. Si besoin de tester localement sur Windows, utiliser un try/except KeyboardInterrupt à la place.

---

## PARTIE 2 : Nouveau module `claude_processor.py`

### Création du fichier

Créer un nouveau fichier `python-bot/claude_processor.py` avec le contenu suivant.

### Dépendances

Ajouter au `requirements.txt` :

```
anthropic>=0.40.0
```

Installer :

```bash
pip install anthropic
```

### Variable d'environnement

Ajouter dans `.env` :

```env
ANTHROPIC_API_KEY=sk-ant-api03-xxxxxxxxxxxxx
```

Ajouter dans `.env.example` :

```env
ANTHROPIC_API_KEY=                               # Clé API Anthropic (Claude) pour le traitement intelligent des news
```

### Code du module `claude_processor.py`

```python
"""
claude_processor.py — Traitement intelligent des messages news via Claude API.

Remplace le filtrage regex + les modifications texte manuelles.
Un seul appel API fait tout : décider si le message est pertinent,
le catégoriser, et le réécrire dans le ton BingeBear.
"""

import os
import json
import logging
import asyncio
from anthropic import AsyncAnthropic, APIError, RateLimitError

logger = logging.getLogger(__name__)

# ── Client Claude (async) ──
_api_key = os.getenv("ANTHROPIC_API_KEY", "")
client = AsyncAnthropic(api_key=_api_key) if _api_key else None

# Seuil de confiance minimum pour transférer un message
CONFIDENCE_THRESHOLD = 0.7

SYSTEM_PROMPT = """Tu es l'assistant éditorial de BingeBearTV, un service de streaming IPTV basé en Irlande/UK.

Tu reçois des messages bruts provenant du canal interne de notre fournisseur technique (destinés aux revendeurs).
Ton rôle est de décider si un message doit être transmis à nos utilisateurs finaux, et si oui, de le réécrire.

## RÈGLES DE DÉCISION (should_forward)

TRANSFÉRER (true) :
- Annonces de nouvelles chaînes, bouquets, contenus ajoutés
- Événements sportifs, matchs, événements live
- Pannes serveur, maintenance, interruptions de service
- Mises à jour de statut (serveur en ligne, problème résolu, etc.)
- Changements importants (URLs, apps, mises à jour)
- Toute info qui impacte l'expérience utilisateur

NE PAS TRANSFÉRER (false) :
- Messages purement techniques destinés aux revendeurs uniquement (configs panel, API credentials, instructions de gestion de comptes revendeur)
- Spam, messages en espagnol sans rapport avec le service
- Messages contenant "domain has been suspended", "purchase a private domain", "misuse and multiple complaints"
- Doublons évidents ou messages vides/très courts sans contenu utile
- URLs de panels d'administration revendeur (cms-only.ru, panel login, etc.)
- Instructions spécifiques aux revendeurs (créer des comptes, gérer des crédits, configurer un panel)

## RÈGLES DE RÉÉCRITURE

1. "Dear Reseller(s)" → "Dear Users" ou "Hi everyone" selon le ton
2. "Team 8K" / "8K" (comme nom de marque/signature) → "BingeBearTV" ou "Team BingeBearTV"
3. Supprimer tout contenu en espagnol (bloc "Queridos Revendedores..." et similaire)
4. Supprimer les URLs de panels admin/revendeur (ex: cms-only.ru, panel links, downloader codes)
5. Simplifier le jargon technique pour les utilisateurs finaux (pas de "CPU error", "moving server" etc. — reformuler en langage simple)
6. Garder un ton professionnel mais amical et rassurant
7. Ajouter un emoji pertinent en début de message selon la catégorie :
   - 🔴 pour panne/maintenance
   - ✅ pour retour en ligne
   - 🆕 pour nouveau contenu
   - ⚽ pour événement sportif
   - 📢 pour info générale
   - 📱 pour mise à jour d'app
8. Si c'est une panne : rassurer que l'équipe technique travaille dessus, ne pas donner de détails techniques internes
9. Si c'est un retour en ligne : célébrer brièvement, remercier pour la patience
10. Nettoyer les sauts de ligne excessifs (max 2 consécutifs)
11. Le message réécrit doit être en ANGLAIS (même si l'original est mal écrit ou en franglais)
12. Terminer par "— Team BingeBearTV" si c'est une annonce formelle

## CATÉGORIES
- "service_outage" : panne, maintenance, serveur down
- "service_restored" : retour en ligne, problème résolu
- "new_content" : nouvelles chaînes, bouquets, contenus
- "live_event" : match sportif, événement live
- "app_update" : mise à jour d'app, changement technique côté utilisateur
- "general_info" : autre info pertinente pour les utilisateurs

## FORMAT DE RÉPONSE

Réponds UNIQUEMENT avec un objet JSON valide, sans markdown, sans backticks, sans explication. Exemple :

{"should_forward": true, "category": "service_outage", "confidence": 0.95, "rewritten_message": "🔴 Hi everyone,\\n\\nWe're currently experiencing a brief service interruption. Our technical team has identified the issue and is working on a fix right now.\\n\\nWe'll keep you updated. Thanks for your patience!\\n\\n— Team BingeBearTV", "reason": "Panne serveur annoncée — info critique pour les utilisateurs"}"""


async def process_message(raw_text: str) -> dict | None:
    """
    Envoie le message brut à Claude pour analyse et réécriture.

    Args:
        raw_text: Le texte brut du message du canal source

    Returns:
        dict avec should_forward, category, confidence, rewritten_message, reason
        None en cas d'erreur (API down, JSON invalide, etc.)
    """
    if not client:
        logger.error("[CLAUDE] ANTHROPIC_API_KEY non configurée — skip traitement")
        return None

    if not raw_text or len(raw_text.strip()) < 5:
        logger.debug("[CLAUDE] Message trop court, ignoré")
        return None

    try:
        response = await client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": f"Analyse et réécris ce message du fournisseur :\n\n{raw_text}"
                }
            ]
        )

        # Extraire le texte de la réponse
        result_text = response.content[0].text

        # Parser le JSON — Claude peut parfois wrapper dans ```json
        cleaned = result_text.strip()
        if cleaned.startswith("```"):
            # Enlever ```json ou ``` au début
            first_newline = cleaned.find("\n")
            if first_newline != -1:
                cleaned = cleaned[first_newline + 1:]
            # Enlever ``` à la fin
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3]
            cleaned = cleaned.strip()

        result = json.loads(cleaned)

        # Validation de la structure
        required_keys = {"should_forward", "rewritten_message", "category", "confidence"}
        missing = required_keys - set(result.keys())
        if missing:
            logger.error(f"[CLAUDE] Réponse incomplète, clés manquantes: {missing}")
            return None

        logger.info(
            f"[CLAUDE] Décision: forward={result['should_forward']} "
            f"| cat={result['category']} "
            f"| conf={result['confidence']:.0%} "
            f"| reason={result.get('reason', 'N/A')}"
        )

        return result

    except json.JSONDecodeError as e:
        logger.error(f"[CLAUDE] Réponse non-JSON: {e} — raw: {result_text[:200]}")
        return None
    except RateLimitError as e:
        logger.warning(f"[CLAUDE] Rate limit atteint, retry dans 30s: {e}")
        await asyncio.sleep(30)
        return None
    except APIError as e:
        logger.error(f"[CLAUDE] Erreur API: {e.status_code} — {e.message}")
        return None
    except Exception as e:
        logger.error(f"[CLAUDE] Erreur inattendue: {type(e).__name__}: {e}")
        return None


async def process_message_batch(messages: list[str]) -> dict | None:
    """
    Envoie un lot de messages à Claude pour qu'il produise un résumé unique.
    Utile pour les séquences de mises à jour rapides (ex: panne avec 10 updates successives).

    Args:
        messages: Liste de textes bruts (ordonnés chronologiquement)

    Returns:
        dict avec should_forward, category, confidence, rewritten_message, reason
        None en cas d'erreur
    """
    if not client:
        logger.error("[CLAUDE] ANTHROPIC_API_KEY non configurée — skip traitement batch")
        return None

    if not messages:
        return None

    # Formater les messages comme une séquence numérotée
    numbered = "\n\n".join(
        f"[Message {i+1}/{len(messages)}] {text}"
        for i, text in enumerate(messages)
    )

    batch_prompt = (
        "Tu reçois une SÉQUENCE de messages envoyés à la suite dans le canal fournisseur. "
        "Ils concernent probablement le même sujet (panne, maintenance, etc.). "
        "Produis UN SEUL message de synthèse pour nos utilisateurs qui résume toute la séquence. "
        "Utilise le même format JSON que d'habitude.\n\n"
        f"{numbered}"
    )

    try:
        response = await client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": batch_prompt}]
        )

        cleaned = response.content[0].text.strip()
        if cleaned.startswith("```"):
            first_newline = cleaned.find("\n")
            if first_newline != -1:
                cleaned = cleaned[first_newline + 1:]
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3]
            cleaned = cleaned.strip()

        result = json.loads(cleaned)

        required_keys = {"should_forward", "rewritten_message", "category", "confidence"}
        if required_keys - set(result.keys()):
            logger.error("[CLAUDE] Réponse batch incomplète")
            return None

        logger.info(
            f"[CLAUDE-BATCH] {len(messages)} messages → 1 synthèse "
            f"| cat={result['category']} | conf={result['confidence']:.0%}"
        )

        return result

    except Exception as e:
        logger.error(f"[CLAUDE-BATCH] Erreur: {type(e).__name__}: {e}")
        return None
```

---

## PARTIE 3 : Modifications de `run_all.py`

### 3.1 Imports à ajouter (en haut du fichier)

```python
# Ajouter ces imports
from claude_processor import process_message, process_message_batch, CONFIDENCE_THRESHOLD
```

### 3.2 Variable d'environnement à charger

Dans la section de chargement des variables d'environnement (vers ligne 30-50), ajouter :

```python
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
```

Et dans `config.py`, ajouter `ANTHROPIC_API_KEY` aux variables **recommandées** (pas obligatoires) pour qu'un warning s'affiche si elle est absente.

### 3.3 Remplacement de `should_forward_news()` et `modify_news_message()`

**NE PAS supprimer** ces fonctions. Les garder comme fallback si Claude API est indisponible.

Ajouter une fonction wrapper qui choisit le mode de traitement :

```python
async def process_news_message(raw_text: str) -> tuple[bool, str | None, str | None]:
    """
    Traite un message news : décide s'il faut le transférer et le réécrit.

    Utilise Claude API en priorité, fallback sur le filtrage regex si l'API
    est indisponible ou en erreur.

    Returns:
        (should_forward, modified_text, category)
        - should_forward: True si le message doit être envoyé
        - modified_text: Le texte réécrit (None si should_forward=False)
        - category: La catégorie du message (None si should_forward=False)
    """
    # ── Tentative Claude API ──
    result = await process_message(raw_text)

    if result is not None:
        # Claude a répondu — utiliser sa décision
        if result["should_forward"] and result.get("confidence", 0) >= CONFIDENCE_THRESHOLD:
            return True, result["rewritten_message"], result["category"]
        else:
            return False, None, result.get("category")

    # ── Fallback regex (Claude indisponible) ──
    logger.warning("[NEWS] Claude API indisponible — fallback regex")

    if not should_forward_news(raw_text):
        return False, None, None

    modified = modify_news_message(raw_text)
    return True, modified, "unknown"
```

### 3.4 Modification de `forward_news()` (handler on_message)

Remplacer le corps de la fonction `forward_news` (le handler on_message temps réel).

**Avant** (code actuel approximatif) :

```python
async def forward_news(client, message):
    text = message.text or message.caption or ""
    if not text.strip():
        return
    if news_cache.is_forwarded(message.id):
        return
    if not should_forward_news(text):
        return
    modified = modify_news_message(text)
    # ... envoi via news_queue ...
```

**Après** :

```python
async def forward_news(client, message):
    """Handler temps réel — traite chaque message via Claude API."""
    logger.info(f"[NEWS-RT] on_message déclenché! msg_id={message.id}, chat={message.chat.id}")

    text = message.text or message.caption or ""
    if not text.strip():
        return

    # Anti-doublon
    if news_cache.is_forwarded(message.id):
        logger.debug(f"[NEWS-RT] Message {message.id} déjà dans le cache — skip")
        return

    # Traitement via Claude (avec fallback regex)
    should_forward, modified_text, category = await process_news_message(text)

    logger.info(
        f"[NEWS-RT] Message {message.id} | forward={should_forward} | cat={category}"
    )

    if should_forward and modified_text:
        # Gestion des images (identique à l'existant)
        if message.photo:
            try:
                photo_path = await message.download()
                await telegram_bot.bot.send_photo(
                    chat_id=NEWS_DEST_CHANNEL,
                    photo=open(photo_path, "rb"),
                    caption=modified_text
                )
                os.remove(photo_path)
            except Exception as e:
                logger.error(f"[NEWS-RT] Erreur envoi photo: {e}")
                # Fallback : envoyer en texte
                await news_queue.enqueue(modified_text)
        else:
            await news_queue.enqueue(modified_text)

    # Cacher dans tous les cas (transféré ou non)
    news_cache.mark_forwarded(message.id)
```

### 3.5 Modification de `news_poll_worker()`

Remplacer la logique de filtrage/modification dans le worker de polling.

**Modifier la boucle interne** du `news_poll_worker()` :

```python
async def news_poll_worker():
    """Auto-import toutes les NEWS_POLL_INTERVAL secondes via Claude API."""
    while True:
        try:
            logger.info("[NEWS-POLL] Début du cycle d'import")
            cutoff = datetime.utcnow() - timedelta(hours=3)
            imported = 0
            skipped = 0
            errors = 0

            async for message in user_client.get_chat_history(NEWS_SOURCE_CHANNEL):
                # Stop si message trop ancien
                if message.date.replace(tzinfo=None) < cutoff:
                    break

                text = message.text or message.caption or ""
                if not text.strip():
                    continue

                # Anti-doublon
                if news_cache.is_forwarded(message.id):
                    skipped += 1
                    continue

                # Traitement via Claude (avec fallback regex)
                should_forward, modified_text, category = await process_news_message(text)

                if should_forward and modified_text:
                    # Gestion des images
                    if message.photo:
                        try:
                            photo_path = await message.download()
                            await telegram_bot.bot.send_photo(
                                chat_id=NEWS_DEST_CHANNEL,
                                photo=open(photo_path, "rb"),
                                caption=modified_text
                            )
                            os.remove(photo_path)
                        except Exception as e:
                            logger.error(f"[NEWS-POLL] Erreur envoi photo msg {message.id}: {e}")
                            # Fallback texte
                            await telegram_bot.bot.send_message(
                                chat_id=NEWS_DEST_CHANNEL,
                                text=modified_text
                            )
                    else:
                        await telegram_bot.bot.send_message(
                            chat_id=NEWS_DEST_CHANNEL,
                            text=modified_text
                        )
                    imported += 1
                    logger.info(f"[NEWS-POLL] ✅ Transféré msg {message.id} [{category}]")
                else:
                    skipped += 1

                # Cacher dans tous les cas
                news_cache.mark_forwarded(message.id)

                # Rate limiting : 1.5s entre les envois + 1s pour l'API Claude
                if should_forward:
                    await asyncio.sleep(1.5)
                else:
                    await asyncio.sleep(0.5)  # Délai réduit si pas d'envoi

            logger.info(
                f"[NEWS-POLL] Cycle terminé: {imported} importé(s), "
                f"{skipped} ignoré(s), {errors} erreur(s)"
            )

        except Exception as e:
            logger.error(f"[NEWS-POLL] Erreur dans le cycle: {e}")

        await asyncio.sleep(NEWS_POLL_INTERVAL)
```

### 3.6 Modification de `import_news_command()` (commande /importnews)

Même logique : remplacer l'appel à `should_forward_news()` + `modify_news_message()` par `process_news_message()`.

Chercher dans `import_news_command()` le bloc qui teste `should_forward_news(text)` et remplacer par :

```python
# Dans la boucle de /importnews, remplacer le bloc de filtrage par :
should_forward, modified_text, category = await process_news_message(text)

if should_forward and modified_text:
    # ... envoi identique à l'existant ...
```

**Note** : `/importnews` peut traiter beaucoup de messages (jusqu'à 30 jours). Ajouter un compteur d'appels Claude et un log d'estimation du coût :

```python
claude_calls = 0
# ... dans la boucle ...
claude_calls += 1
# ... après la boucle ...
logger.info(f"[NEWS-IMPORT] {claude_calls} appels Claude (~{claude_calls * 0.003:.2f}$ estimé)")
```

### 3.7 Ajout du log dans `post_init()`

Ajouter ces logs dans `post_init()` pour confirmer la disponibilité de Claude API :

```python
# Dans post_init(), après les logs existants
if ANTHROPIC_API_KEY:
    logger.info("[CLAUDE] API Claude configurée — traitement intelligent des news actif")
else:
    logger.warning("[CLAUDE] ANTHROPIC_API_KEY absente — fallback regex uniquement")
```

---

## PARTIE 4 : Modification de `config.py`

Ajouter `ANTHROPIC_API_KEY` aux variables recommandées :

```python
# Dans la liste des variables recommandées (celles qui génèrent un warning)
RECOMMENDED_VARS = [
    "SESSION_STRING",
    "IPTV_SERVER_URL",
    "IPTV_USERNAME",
    "IPTV_PASSWORD",
    "ANTHROPIC_API_KEY",  # ← AJOUTER
]
```

---

## PARTIE 5 : Mise à jour du cache (`news_cache.py`)

Le cache actuel utilise `message.id` comme clé. Cela fonctionne toujours avec la refonte Claude — **aucune modification nécessaire** sur `news_cache.py`.

Le cache continue de :
- Empêcher les doublons entre les 3 mécanismes (on_message, poll, /importnews)
- Survivre aux redémarrages
- Se nettoyer automatiquement (max 500 entrées, TTL 7 jours)

---

## PARTIE 6 : Fonctionnalité batch (V2 — optionnelle mais recommandée)

### Concept

Quand le fournisseur envoie une rafale de messages sur le même sujet (ex: 10 updates pendant une panne), au lieu d'envoyer 10 messages séparés aux utilisateurs, on les regroupe et on envoie UN SEUL résumé.

### Implémentation dans `news_poll_worker()`

Ajouter une logique de regroupement AVANT l'envoi :

```python
async def news_poll_worker():
    """Auto-import avec regroupement intelligent des messages."""
    while True:
        try:
            cutoff = datetime.utcnow() - timedelta(hours=3)
            pending_messages = []  # Collecter d'abord, envoyer ensuite

            # Phase 1 : Collecter tous les nouveaux messages
            async for message in user_client.get_chat_history(NEWS_SOURCE_CHANNEL):
                if message.date.replace(tzinfo=None) < cutoff:
                    break

                text = message.text or message.caption or ""
                if not text.strip():
                    continue

                if news_cache.is_forwarded(message.id):
                    continue

                pending_messages.append({
                    "id": message.id,
                    "text": text,
                    "has_photo": bool(message.photo),
                    "message": message,
                    "date": message.date,
                })

            if not pending_messages:
                logger.info("[NEWS-POLL] Aucun nouveau message")
                await asyncio.sleep(NEWS_POLL_INTERVAL)
                continue

            # Phase 2 : Regrouper les messages proches (< 30 min d'écart)
            # et qui ne sont pas des annonces structurées (Dear Reseller...)
            pending_messages.sort(key=lambda m: m["date"])  # Ordre chronologique

            groups = []
            current_group = [pending_messages[0]]

            for msg in pending_messages[1:]:
                time_diff = (msg["date"] - current_group[-1]["date"]).total_seconds()
                if time_diff <= 1800:  # 30 minutes
                    current_group.append(msg)
                else:
                    groups.append(current_group)
                    current_group = [msg]
            groups.append(current_group)

            # Phase 3 : Traiter chaque groupe
            imported = 0

            for group in groups:
                if len(group) >= 3:
                    # Batch : 3+ messages proches → synthèse unique
                    texts = [m["text"] for m in group]
                    result = await process_message_batch(texts)

                    if result and result["should_forward"] and result.get("confidence", 0) >= CONFIDENCE_THRESHOLD:
                        await telegram_bot.bot.send_message(
                            chat_id=NEWS_DEST_CHANNEL,
                            text=result["rewritten_message"]
                        )
                        imported += 1
                        logger.info(f"[NEWS-POLL] ✅ Batch de {len(group)} messages envoyé [{result['category']}]")

                    # Cacher tous les messages du groupe
                    for m in group:
                        news_cache.mark_forwarded(m["id"])

                    await asyncio.sleep(1.5)

                else:
                    # Traitement individuel (1-2 messages)
                    for m in group:
                        should_forward, modified_text, category = await process_news_message(m["text"])

                        if should_forward and modified_text:
                            if m["has_photo"]:
                                try:
                                    photo_path = await m["message"].download()
                                    await telegram_bot.bot.send_photo(
                                        chat_id=NEWS_DEST_CHANNEL,
                                        photo=open(photo_path, "rb"),
                                        caption=modified_text
                                    )
                                    os.remove(photo_path)
                                except Exception as e:
                                    logger.error(f"[NEWS-POLL] Erreur photo: {e}")
                                    await telegram_bot.bot.send_message(
                                        chat_id=NEWS_DEST_CHANNEL,
                                        text=modified_text
                                    )
                            else:
                                await telegram_bot.bot.send_message(
                                    chat_id=NEWS_DEST_CHANNEL,
                                    text=modified_text
                                )
                            imported += 1
                            logger.info(f"[NEWS-POLL] ✅ Transféré msg {m['id']} [{category}]")

                        news_cache.mark_forwarded(m["id"])
                        await asyncio.sleep(1.5)

            logger.info(f"[NEWS-POLL] Cycle terminé: {imported} envoyé(s) depuis {len(pending_messages)} message(s)")

        except Exception as e:
            logger.error(f"[NEWS-POLL] Erreur: {e}")

        await asyncio.sleep(NEWS_POLL_INTERVAL)
```

---

## PARTIE 7 : Tests et validation

### Test 1 : Vérifier que Claude API fonctionne

Créer un script de test `python-bot/test_claude.py` :

```python
"""Test rapide de l'intégration Claude API."""
import asyncio
import os
from dotenv import load_dotenv

load_dotenv()

from claude_processor import process_message, process_message_batch

# Test 1 : Message de panne (devrait être transféré)
TEST_OUTAGE = "Dear Reseller Our main server down we are checking what problem"

# Test 2 : Message de nouvelle chaîne (devrait être transféré)
TEST_NEW_CHANNEL = """Dear Reseller,

We are pleased to launch the New Category

TR| S SPORT+ PPV

This package contains 10 channels.
All channels will receive daily updates for live event !

Enjoy.
Team 8K

Queridos Revendedores,
Nos complace lanzar la nueva categoria..."""

# Test 3 : Message spam (ne devrait PAS être transféré)
TEST_SPAM = "Your domain has been suspended due to misuse and multiple complaints"

# Test 4 : Message technique revendeur (ne devrait PAS être transféré)
TEST_RESELLER = "please use only https://8k.cms-only.ru/index more link will be done Soon"

# Test 5 : Batch de messages de panne
TEST_BATCH = [
    "Dear Reseller Our main server down we are checking what problem",
    "we see there cpu error will try to put online fast until we replace.",
    "We have brought the main server back online. Replacing the CPU is not easy.",
    "system online now and panel https://8k.cms-only.ru/index",
]


async def run_tests():
    print("=" * 60)
    print("TEST CLAUDE PROCESSOR")
    print("=" * 60)

    tests = [
        ("Panne serveur", TEST_OUTAGE, True),
        ("Nouvelle chaîne", TEST_NEW_CHANNEL, True),
        ("Spam", TEST_SPAM, False),
        ("Technique revendeur", TEST_RESELLER, False),
    ]

    for name, text, expected_forward in tests:
        print(f"\n--- {name} ---")
        result = await process_message(text)

        if result is None:
            print(f"  ❌ ERREUR: Pas de réponse Claude")
            continue

        status = "✅" if result["should_forward"] == expected_forward else "⚠️ INATTENDU"
        print(f"  {status} forward={result['should_forward']} (attendu: {expected_forward})")
        print(f"  category={result['category']}")
        print(f"  confidence={result['confidence']:.0%}")
        print(f"  reason={result['reason']}")
        if result["rewritten_message"]:
            print(f"  message: {result['rewritten_message'][:150]}...")

    # Test batch
    print(f"\n--- Batch ({len(TEST_BATCH)} messages) ---")
    result = await process_message_batch(TEST_BATCH)
    if result:
        print(f"  forward={result['should_forward']}")
        print(f"  category={result['category']}")
        print(f"  confidence={result['confidence']:.0%}")
        if result["rewritten_message"]:
            print(f"  message:\n{result['rewritten_message']}")
    else:
        print("  ❌ ERREUR: Pas de réponse batch")


if __name__ == "__main__":
    asyncio.run(run_tests())
```

Exécuter :

```bash
cd python-bot
python test_claude.py
```

### Test 2 : Vérifier le fix on_message

Après déploiement du fix de la boucle asyncio :

1. Redémarrer le bot : `sudo systemctl restart bingebear-bot`
2. Vérifier les logs de démarrage : `sudo journalctl -u bingebear-bot -n 30 --no-pager`
3. Poster un message test dans le canal source (si possible)
4. Vérifier si `[NEWS-RT] on_message déclenché!` apparaît dans les logs

### Test 3 : Vérifier le polling avec Claude

1. Attendre le prochain cycle de polling (ou réduire temporairement `NEWS_POLL_INTERVAL` à 120 pour tester)
2. Vérifier les logs : `sudo journalctl -u bingebear-bot --since "5 min ago" | grep -E "CLAUDE|NEWS-POLL"`
3. Confirmer que les décisions Claude sont loguées

---

## PARTIE 8 : Résumé des fichiers modifiés

| Fichier | Action | Description |
|---------|--------|-------------|
| `python-bot/claude_processor.py` | **CRÉER** | Nouveau module — traitement Claude API |
| `python-bot/run_all.py` | **MODIFIER** | Fix boucle asyncio + intégration Claude dans forward_news, news_poll_worker, import_news_command |
| `python-bot/config.py` | **MODIFIER** | Ajouter ANTHROPIC_API_KEY aux variables recommandées |
| `python-bot/requirements.txt` | **MODIFIER** | Ajouter `anthropic>=0.40.0` |
| `python-bot/.env` | **MODIFIER** | Ajouter ANTHROPIC_API_KEY |
| `python-bot/.env.example` | **MODIFIER** | Ajouter ANTHROPIC_API_KEY (vide) |
| `python-bot/test_claude.py` | **CRÉER** | Script de test pour valider l'intégration |

### Fichiers NON modifiés

- `news_cache.py` — Aucune modification nécessaire
- `news_queue.py` — Aucune modification nécessaire
- `health.py` — Aucune modification nécessaire
- `logger.py` — Aucune modification nécessaire
- `reminders.py` — Aucune modification nécessaire
- `stream_state.py` — Aucune modification nécessaire
- `deploy/*` — Aucune modification nécessaire

---

## PARTIE 9 : Checklist de déploiement

```
[ ] 1. Obtenir une clé API Anthropic sur console.anthropic.com
[ ] 2. Ajouter ANTHROPIC_API_KEY dans .env sur le VPS
[ ] 3. Créer claude_processor.py
[ ] 4. Installer la dépendance : pip install anthropic
[ ] 5. Modifier run_all.py (fix asyncio + intégration Claude)
[ ] 6. Modifier config.py (variable recommandée)
[ ] 7. Mettre à jour requirements.txt
[ ] 8. Exécuter test_claude.py pour valider
[ ] 9. Commit + push
[ ] 10. Déployer sur VPS : git pull && sudo systemctl restart bingebear-bot
[ ] 11. Vérifier les logs de démarrage (CLAUDE API configurée, handlers Pyrogram)
[ ] 12. Monitorer les premiers cycles de polling pour confirmer le bon fonctionnement
[ ] 13. Vérifier si on_message se déclenche maintenant (logs [NEWS-RT])
```

---

## PARTIE 10 : Estimation des coûts Claude API

- **Modèle** : Claude Sonnet 4 ($3/M tokens input, $15/M tokens output)
- **System prompt** : ~800 tokens (envoyé à chaque appel)
- **Message typique** : ~50-200 tokens input, ~150-300 tokens output
- **Coût par message** : ~$0.002-0.005
- **Volume estimé** : 10-30 messages/jour
- **Coût mensuel estimé** : $1-5/mois

Le batch (`process_message_batch`) est plus économique car il traite plusieurs messages en un seul appel.

---

## Notes importantes

1. **Les fonctions `should_forward_news()` et `modify_news_message()` sont conservées** comme fallback. Si Claude API est down, le bot continue de fonctionner avec le filtrage regex (certes limité, mais mieux que rien).

2. **Le cache anti-doublon reste identique**. Il utilise toujours `message.id` comme clé. Claude ne change pas la logique de déduplication.

3. **Le rate limiting reste en place**. 1.5s entre les envois Telegram. L'appel Claude ajoute ~1-2s de latence par message, ce qui espace naturellement les envois.

4. **Ne pas réduire `NEWS_POLL_INTERVAL` sous 1800s (30 min)** en production. Avec Claude API, chaque cycle génère des appels payants.

5. **Le handler `on_message` et le `news_poll_worker` utilisent la MÊME fonction `process_news_message()`**. Pas de duplication de logique.
