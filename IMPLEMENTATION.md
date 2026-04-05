# Plan d'implémentation — Commandes /announcement et /reminder

## Contexte

Le bot BingeBear TV (`run_all.py`) doit recevoir 2 nouvelles fonctionnalités admin :

1. **`/announcement`** — Poster un message dans le canal `NEWS_DEST_CHANNEL` comme si c'était le bot/canal qui l'avait écrit
2. **`/reminder`** — Programmer un message récurrent envoyé automatiquement dans le canal à intervalle configurable (ex: toutes les 36h, 48h, etc.)

Le bot utilise `python-telegram-bot 21.10` pour les commandes et `pyrofork` (Pyrogram) comme client utilisateur. Toutes les réponses aux commandes sont envoyées en DM privé via la fonction `reply_private()` existante. L'autorisation admin se fait via `is_admin(user_id)`.

---

## Partie 1 : /announcement

### Comportement attendu

- L'admin envoie `/announcement <message>` dans n'importe quel chat avec le bot
- Le bot envoie `<message>` dans le canal `NEWS_DEST_CHANNEL` (variable d'env, défaut `@bingebeartv_live`) via `context.bot.send_message()`
- Le bot confirme l'envoi en DM privé à l'admin
- Commande réservée aux admins (`is_admin()`)

### Implémentation dans `run_all.py`

1. Créer la fonction `announcement_command(update, context)` :
   - Vérifier `is_admin(update.effective_user.id)`, sinon répondre "⛔ Commande réservée aux admins."
   - Extraire le texte : `" ".join(context.args)` — si vide, répondre avec le usage
   - Envoyer via `context.bot.send_message(chat_id=NEWS_DEST_CHANNEL, text=text)`
   - Confirmer en DM privé : "✅ Annonce envoyée dans le canal."
   - Catch les exceptions et les logger + répondre avec l'erreur

2. Enregistrer le handler avec les autres :
   ```python
   app.add_handler(CommandHandler("announcement", announcement_command))
   ```

### Notes importantes

- Le bot doit être admin du canal avec la permission "Post Messages"
- Si "Sign messages" est désactivé dans les paramètres du canal Telegram, le message apparaît comme venant du canal lui-même (anonyme) — c'est le comportement souhaité
- `NEWS_DEST_CHANNEL` est déjà utilisé par le news forwarder, réutiliser la même variable : `os.getenv("NEWS_DEST_CHANNEL", "@bingebeartv_live")`

---

## Partie 2 : /reminder (messages récurrents)

### Comportement attendu

- `/reminder <intervalle> <message>` — Crée un rappel récurrent
- `/reminders` — Liste tous les rappels actifs avec leurs IDs
- `/delreminder <id>` — Supprime un rappel
- Les rappels sont persistés dans un fichier JSON (survit aux redémarrages)
- Une tâche de fond envoie les messages dans `NEWS_DEST_CHANNEL` quand l'intervalle est écoulé

### Nouveau fichier : `reminders.py`

Créer `python-bot/reminders.py` avec :

#### Constantes et config

- `REMINDERS_FILE` : chemin du fichier JSON, lu depuis `os.getenv("REMINDERS_FILE", "./reminders.json")`

#### Fonctions à implémenter

```python
def load_reminders() -> dict
```
- Charge et retourne le contenu de `REMINDERS_FILE`
- Retourne `{}` si le fichier n'existe pas ou est corrompu

```python
def save_reminders(reminders: dict) -> None
```
- Écrit le dict dans `REMINDERS_FILE` avec `ensure_ascii=False, indent=2`

```python
def add_reminder(message: str, interval_seconds: int) -> str
```
- Génère un ID court : `str(uuid.uuid4())[:8]`
- Ajoute au dict :
  ```python
  {
      "message": message,
      "interval": interval_seconds,
      "last_sent": 0,
      "created_at": time.time()
  }
  ```
- `last_sent: 0` signifie que le premier envoi se fera au prochain cycle du worker
- Sauvegarde et retourne l'ID

```python
def delete_reminder(reminder_id: str) -> bool
```
- Supprime l'entrée du dict, sauvegarde, retourne True si trouvé

```python
def get_due_reminders() -> list[tuple[str, dict]]
```
- Parcourt tous les rappels
- Retourne ceux où `time.time() - last_sent >= interval`

```python
def mark_sent(reminder_id: str) -> None
```
- Met à jour `last_sent` à `time.time()` et sauvegarde

```python
def parse_interval(text: str) -> int | None
```
- Parse les formats : `30m`, `12h`, `36h`, `48h`, `2d`, `7d`
- Multiplicateurs : `m` → 60, `h` → 3600, `d` → 86400
- Retourne les secondes ou `None` si invalide

### Commandes dans `run_all.py`

#### `/reminder <intervalle> <message>`

1. Vérifier `is_admin()`
2. Vérifier qu'il y a au moins 2 args (intervalle + message), sinon afficher le usage avec exemples
3. Parser l'intervalle avec `parse_interval(context.args[0])`
4. Si invalide, répondre "❌ Intervalle invalide. Utilisez: 30m, 12h, 36h, 48h, 2d..."
5. Extraire le message : `" ".join(context.args[1:])`
6. Appeler `add_reminder(message, interval_secs)`
7. Confirmer en DM avec l'ID, le message, et l'intervalle

#### `/reminders`

1. Vérifier `is_admin()`
2. Charger `load_reminders()`
3. Si vide, répondre "📭 Aucun rappel actif."
4. Sinon, formater la liste :
   ```
   📋 Rappels actifs:

   • ID: a3f2b1c9 | ⏱ 36.0h
     📨 Pensez à renouveler votre abonnement !
   • ID: b7e4d2a1 | ⏱ 48.0h
     📨 Nouveaux canaux disponibles !
   ```

#### `/delreminder <id>`

1. Vérifier `is_admin()`
2. Vérifier qu'un arg est fourni
3. Appeler `delete_reminder(context.args[0])`
4. Confirmer ou répondre "introuvable"

### Enregistrement des handlers

```python
app.add_handler(CommandHandler("reminder", reminder_command))
app.add_handler(CommandHandler("reminders", reminders_list_command))
app.add_handler(CommandHandler("delreminder", delreminder_command))
```

### Tâche de fond : `reminder_worker`

#### Fonction async `reminder_worker(bot)`

- Boucle infinie avec `await asyncio.sleep(60)` entre chaque cycle (vérifie toutes les 60 secondes)
- À chaque cycle :
  1. Appeler `get_due_reminders()`
  2. Pour chaque rappel échu, envoyer `bot.send_message(chat_id=NEWS_DEST_CHANNEL, text=data["message"])`
  3. Appeler `mark_sent(reminder_id)` après envoi réussi
  4. Logger chaque envoi : `logger.info(f"[REMINDER] Rappel {rid} envoyé")`
  5. Logger les erreurs sans crasher le worker

#### Démarrage

Dans la fonction `post_init` de `run_all.py`, à côté des autres `asyncio.create_task()` :

```python
asyncio.create_task(reminder_worker(app.bot))
```

---

## Partie 3 : Variable d'environnement

Ajouter dans `.env.example` :

```env
REMINDERS_FILE=./reminders.json            # Fichier de persistance des rappels récurrents
```

Ajouter `REMINDERS_FILE` comme variable optionnelle dans `config.py` si ce fichier a une section pour les variables optionnelles.

---

## Partie 4 : Résumé des fichiers touchés

| Fichier | Action |
|---------|--------|
| `python-bot/reminders.py` | **CRÉER** — Module de gestion des rappels |
| `python-bot/run_all.py` | **MODIFIER** — Ajouter import, 4 commandes, 3 handlers, 1 tâche de fond |
| `python-bot/.env.example` | **MODIFIER** — Ajouter `REMINDERS_FILE` |
| `python-bot/config.py` | **MODIFIER** (optionnel) — Documenter la nouvelle variable |

### Nouvelles commandes

| Commande | Args | Admin | Description |
|----------|------|-------|-------------|
| `/announcement` | `<message>` | Oui | Poste un message dans le canal |
| `/reminder` | `<intervalle> <message>` | Oui | Crée un rappel récurrent |
| `/reminders` | — | Oui | Liste les rappels actifs |
| `/delreminder` | `<id>` | Oui | Supprime un rappel |

### Nouveau fichier de persistance

`reminders.json` — Créé automatiquement au premier `/reminder`, même pattern que `stream_state.json` et `news_cache.json`.

---

## Partie 5 : Tests

Après implémentation, vérifier :

1. **`/announcement`** : Envoyer `/announcement Test annonce` → le message "Test annonce" apparaît dans le canal, confirmation en DM
2. **`/announcement`** sans texte → affiche le usage
3. **`/announcement`** par un non-admin → message d'erreur
4. **`/reminder 1m Message test`** → rappel créé, le message s'envoie dans le canal après ~60 secondes
5. **`/reminders`** → liste le rappel créé avec son ID
6. **`/delreminder <id>`** → supprime le rappel, plus d'envois
7. **Redémarrage du bot** → les rappels dans `reminders.json` sont repris automatiquement par le worker
8. **`/reminder`** sans args → affiche le usage avec exemples d'intervalles
