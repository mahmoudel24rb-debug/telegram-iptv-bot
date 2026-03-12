"""
BingeBear TV - Bot de live streaming IPTV vers Telegram
Utilise python-telegram-bot pour les commandes et pytgcalls pour le streaming
"""

import os
import asyncio
import requests
from dotenv import load_dotenv

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from pyrogram import Client
from pytgcalls import PyTgCalls
from pytgcalls.types import MediaStream, AudioQuality, VideoQuality

# Charger les variables d'environnement
load_dotenv()

API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
SESSION_STRING = os.getenv("SESSION_STRING")

IPTV_SERVER = os.getenv("IPTV_SERVER_URL")
IPTV_USER = os.getenv("IPTV_USERNAME")
IPTV_PASS = os.getenv("IPTV_PASSWORD")

# Client utilisateur Pyrogram (avec session string pour le cloud)
if SESSION_STRING:
    user_client = Client(
        "user_session",
        api_id=API_ID,
        api_hash=API_HASH,
        session_string=SESSION_STRING
    )
else:
    # Mode local sans session string
    user_client = Client(
        "user_session",
        api_id=API_ID,
        api_hash=API_HASH
    )

# PyTgCalls pour le streaming
pytgcalls = None

# État du streaming
current_stream = None
categories_cache = []
channels_cache = {}  # Dict par category_id

# Headers pour les requêtes
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'application/json, text/plain, */*',
}

# Liste des admins autorisés (ajoutez votre user_id Telegram)
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x]

# Username autorisé pour les commandes de streaming
ALLOWED_USERNAMES = ["DefiMack"]


def is_admin(user_id):
    """Vérifier si l'utilisateur est admin"""
    # Si pas d'admins configurés, tout le monde peut utiliser
    if not ADMIN_IDS:
        return True
    return user_id in ADMIN_IDS


def is_allowed_user(user):
    """Vérifier si l'utilisateur est autorisé à streamer"""
    if user.username and user.username in ALLOWED_USERNAMES:
        return True
    if user.id in ADMIN_IDS:
        return True
    return False


def get_categories():
    """Récupérer la liste des catégories IPTV"""
    global categories_cache

    try:
        url = f"{IPTV_SERVER}/player_api.php?username={IPTV_USER}&password={IPTV_PASS}&action=get_live_categories"
        print(f"Requete categories...")
        response = requests.get(url, headers=HEADERS, timeout=30)

        categories = response.json()

        categories_cache = [
            {
                "id": cat["category_id"],
                "name": cat["category_name"]
            }
            for cat in categories
        ]

        print(f"Categories chargees: {len(categories_cache)}")
        return categories_cache
    except Exception as e:
        print(f"Erreur chargement categories: {e}")
        return []


def get_channels_by_category(category_id):
    """Récupérer les chaînes d'une catégorie"""
    global channels_cache

    try:
        url = f"{IPTV_SERVER}/player_api.php?username={IPTV_USER}&password={IPTV_PASS}&action=get_live_streams&category_id={category_id}"
        print(f"Requete chaines categorie {category_id}...")
        response = requests.get(url, headers=HEADERS, timeout=30)

        channels = response.json()

        channels_list = [
            {
                "id": ch["stream_id"],
                "name": ch["name"],
                "category_id": category_id,
                "url": f"{IPTV_SERVER}/live/{IPTV_USER}/{IPTV_PASS}/{ch['stream_id']}.ts"
            }
            for ch in channels
        ]

        # Stocker dans le cache
        channels_cache[category_id] = channels_list

        print(f"Chaines chargees: {len(channels_list)}")
        return channels_list
    except Exception as e:
        print(f"Erreur chargement chaines: {e}")
        return []


def get_channel_by_id(channel_id):
    """Trouver une chaîne par son ID dans le cache"""
    for cat_id, channels in channels_cache.items():
        for ch in channels:
            if str(ch["id"]) == str(channel_id):
                return ch
    return None


def escape_markdown(text):
    """Échapper les caractères spéciaux Markdown"""
    special_chars = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
    for char in special_chars:
        text = str(text).replace(char, f'\\{char}')
    return text


# Commandes du bot
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Commande /start"""
    print(f"Commande /start recue de {update.effective_user.first_name}")
    await update.message.reply_text(
        "🐻 BingeBear TV - Live Streaming Bot\n\n"
        "Commandes disponibles:\n"
        "/categories - Liste des categories\n"
        "/cat <id> - Voir les chaines d'une categorie\n"
        "/play <id> - Lancer un stream\n"
        "/stop - Arreter le stream\n"
        "/status - Statut actuel\n"
        "/test - Stream de test\n"
        "/help - Aide"
    )


async def categories_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Liste des catégories"""
    print("Commande /categories recue")
    await update.message.reply_text("Chargement des categories...")

    categories = get_categories()

    if not categories:
        await update.message.reply_text("Aucune categorie disponible")
        return

    text = "📂 Categories disponibles:\n\n"
    for cat in categories:
        safe_name = escape_markdown(cat['name'])
        text += f"• {cat['id']} - {safe_name}\n"

    text += f"\nTotal: {len(categories)} categories\n"
    text += "\nUtilisez /cat <id> pour voir les chaines"

    # Telegram limite les messages à 4096 caractères
    if len(text) > 4000:
        # Envoyer en plusieurs parties
        parts = []
        current_part = "📂 Categories disponibles:\n\n"
        for cat in categories:
            safe_name = escape_markdown(cat['name'])
            line = f"• {cat['id']} - {safe_name}\n"
            if len(current_part) + len(line) > 3900:
                parts.append(current_part)
                current_part = ""
            current_part += line

        current_part += f"\nTotal: {len(categories)} categories\n"
        current_part += "\nUtilisez /cat <id> pour voir les chaines"
        parts.append(current_part)

        for part in parts:
            await update.message.reply_text(part)
    else:
        await update.message.reply_text(text)


async def cat_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Liste des chaînes d'une catégorie"""
    print("Commande /cat recue")

    if not context.args:
        await update.message.reply_text("Usage: /cat <category_id>\nExemple: /cat 1")
        return

    category_id = context.args[0]

    # Vérifier que la catégorie existe
    if not categories_cache:
        get_categories()

    category = None
    for cat in categories_cache:
        if str(cat["id"]) == str(category_id):
            category = cat
            break

    if not category:
        await update.message.reply_text(f"Categorie {category_id} non trouvee\nUtilisez /categories pour voir la liste")
        return

    await update.message.reply_text(f"Chargement des chaines de {category['name']}...")

    channels = get_channels_by_category(category_id)

    if not channels:
        await update.message.reply_text("Aucune chaine dans cette categorie")
        return

    text = f"📺 {escape_markdown(category['name'])}\n\n"

    # Afficher les 30 premières chaînes
    for ch in channels[:30]:
        safe_name = escape_markdown(ch['name'])
        text += f"• {ch['id']} - {safe_name}\n"

    if len(channels) > 30:
        text += f"\n... et {len(channels) - 30} autres chaines\n"

    text += f"\nTotal: {len(channels)} chaines\n"
    text += "\nUtilisez /play <id> pour lancer un stream"

    # Telegram limite les messages à 4096 caractères
    if len(text) > 4000:
        parts = []
        current_part = f"📺 {escape_markdown(category['name'])}\n\n"
        for ch in channels[:30]:
            safe_name = escape_markdown(ch['name'])
            line = f"• {ch['id']} - {safe_name}\n"
            if len(current_part) + len(line) > 3900:
                parts.append(current_part)
                current_part = ""
            current_part += line

        if len(channels) > 30:
            current_part += f"\n... et {len(channels) - 30} autres chaines\n"
        current_part += f"\nTotal: {len(channels)} chaines\n"
        current_part += "\nUtilisez /play <id> pour lancer un stream"
        parts.append(current_part)

        for part in parts:
            await update.message.reply_text(part)
    else:
        await update.message.reply_text(text)


async def play_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lancer un stream"""
    global current_stream, pytgcalls
    print("Commande /play recue")

    # Vérifier si l'utilisateur est autorisé
    if not is_allowed_user(update.effective_user):
        await update.message.reply_text("❌ Vous n'etes pas autorise a utiliser cette commande")
        return

    if not context.args:
        await update.message.reply_text("Usage: /play <channel_id>\nExemple: /play 123456")
        return

    channel_id = context.args[0]

    channel = get_channel_by_id(channel_id)
    if not channel:
        await update.message.reply_text(
            f"Chaine {channel_id} non trouvee dans le cache.\n"
            "Utilisez d'abord /cat <category_id> pour charger les chaines."
        )
        return

    safe_name = escape_markdown(channel['name'])
    await update.message.reply_text(f"Demarrage du stream...\n{safe_name}")

    try:
        if current_stream:
            await pytgcalls.leave_call(CHAT_ID)

        await pytgcalls.play(
            CHAT_ID,
            MediaStream(
                channel["url"],
                audio_parameters=AudioQuality.STUDIO,
                video_parameters=VideoQuality.HD_720p,
            )
        )

        current_stream = channel

        await update.message.reply_text(
            f"✅ Stream demarre!\n\n"
            f"{safe_name}\n"
            f"ID: {channel['id']}\n\n"
            f"Le stream est maintenant en direct dans le groupe!"
        )

    except Exception as e:
        await update.message.reply_text(f"Erreur: {e}")
        current_stream = None


async def stop_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Arrêter le stream"""
    global current_stream, pytgcalls
    print("Commande /stop recue")

    # Vérifier si l'utilisateur est autorisé
    if not is_allowed_user(update.effective_user):
        await update.message.reply_text("❌ Vous n'etes pas autorise a utiliser cette commande")
        return

    try:
        await pytgcalls.leave_call(CHAT_ID)
        current_stream = None
        await update.message.reply_text("Stream arrete")
    except Exception as e:
        await update.message.reply_text(f"Erreur: {e}")


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Statut du stream"""
    print("Commande /status recue")
    if current_stream:
        safe_name = escape_markdown(current_stream['name'])
        await update.message.reply_text(
            f"📺 Stream actif\n\n"
            f"{safe_name}\n"
            f"ID: {current_stream['id']}"
        )
    else:
        await update.message.reply_text("❌ Aucun stream en cours")


async def test_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Tester le streaming avec un flux public"""
    global current_stream, pytgcalls
    print("Commande /test recue")

    # Vérifier si l'utilisateur est autorisé
    if not is_allowed_user(update.effective_user):
        await update.message.reply_text("❌ Vous n'etes pas autorise a utiliser cette commande")
        return

    await update.message.reply_text("Demarrage du stream de test...")

    # URL d'un stream de test public (Big Buck Bunny)
    test_url = "http://commondatastorage.googleapis.com/gtv-videos-bucket/sample/BigBuckBunny.mp4"

    try:
        if current_stream:
            await pytgcalls.leave_call(CHAT_ID)

        await pytgcalls.play(
            CHAT_ID,
            MediaStream(
                test_url,
                audio_parameters=AudioQuality.STUDIO,
                video_parameters=VideoQuality.HD_720p,
            )
        )

        current_stream = {"id": "test", "name": "Big Buck Bunny (Test)", "url": test_url}

        await update.message.reply_text(
            f"✅ Stream de test demarre!\n\n"
            f"Video: Big Buck Bunny\n"
            f"Le stream est maintenant en direct dans le groupe @{CHAT_ID}"
        )

    except Exception as e:
        await update.message.reply_text(f"Erreur: {e}")
        current_stream = None


async def setiptv_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Changer les identifiants IPTV (admin seulement)"""
    global IPTV_SERVER, IPTV_USER, IPTV_PASS, categories_cache, channels_cache

    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("❌ Commande reservee aux admins")
        return

    if len(context.args) < 3:
        await update.message.reply_text(
            "Usage: /setiptv <url> <username> <password>\n\n"
            "Exemple:\n"
            "/setiptv http://server.com user123 pass456\n\n"
            f"Config actuelle:\n"
            f"URL: {IPTV_SERVER}\n"
            f"User: {IPTV_USER}"
        )
        return

    new_server = context.args[0]
    new_user = context.args[1]
    new_pass = context.args[2]

    # Tester la connexion
    try:
        test_url = f"{new_server}/player_api.php?username={new_user}&password={new_pass}&action=get_live_categories"
        response = requests.get(test_url, headers=HEADERS, timeout=15)
        data = response.json()

        if isinstance(data, list) and len(data) > 0:
            # Connexion OK, mettre à jour
            IPTV_SERVER = new_server
            IPTV_USER = new_user
            IPTV_PASS = new_pass

            # Vider le cache
            categories_cache = []
            channels_cache = {}

            await update.message.reply_text(
                f"✅ IPTV mis a jour!\n\n"
                f"URL: {IPTV_SERVER}\n"
                f"User: {IPTV_USER}\n"
                f"Categories trouvees: {len(data)}\n\n"
                f"Utilisez /categories pour voir les chaines"
            )
        else:
            await update.message.reply_text("❌ Identifiants invalides ou serveur inaccessible")

    except Exception as e:
        await update.message.reply_text(f"❌ Erreur de connexion: {e}")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Aide"""
    print("Commande /help recue")
    help_text = (
        "📖 Aide - BingeBear TV Bot\n\n"
        "Commandes:\n"
        "/start - Demarrer le bot\n"
        "/categories - Liste des categories IPTV\n"
        "/cat <id> - Voir les chaines d'une categorie\n"
        "/play <id> - Lancer le stream d'une chaine\n"
        "/stop - Arreter le stream en cours\n"
        "/status - Voir le statut actuel\n"
        "/test - Stream de test\n"
    )

    if is_admin(update.effective_user.id):
        help_text += "/setiptv - Changer les identifiants IPTV\n"

    help_text += (
        "\nComment ca marche:\n"
        "1. Utilisez /categories pour voir les categories\n"
        "2. Utilisez /cat <id> pour voir les chaines\n"
        "3. Utilisez /play <id> pour lancer le stream\n"
        "4. Le stream sera diffuse dans le video chat du groupe"
    )

    await update.message.reply_text(help_text)


async def post_init(application):
    """Initialiser pytgcalls après le démarrage du bot"""
    global pytgcalls

    print("Demarrage du client utilisateur...")
    await user_client.start()

    me = await user_client.get_me()
    print(f"Connecte en tant que: {me.first_name} (@{me.username})")

    pytgcalls = PyTgCalls(user_client)
    await pytgcalls.start()
    print("PyTgCalls pret")

    print(f"\nGroupe cible: @{CHAT_ID}")


def main():
    """Fonction principale"""
    print("BingeBear TV - Live Streaming Bot")
    print("=" * 40)

    # Créer l'application bot
    application = Application.builder().token(BOT_TOKEN).post_init(post_init).build()

    # Ajouter les handlers de commandes
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("categories", categories_command))
    application.add_handler(CommandHandler("cat", cat_command))
    application.add_handler(CommandHandler("play", play_command))
    application.add_handler(CommandHandler("stop", stop_command))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(CommandHandler("test", test_command))
    application.add_handler(CommandHandler("setiptv", setiptv_command))
    application.add_handler(CommandHandler("help", help_command))

    print("Bot pret! Envoyez /start a @Bingebear_tv_bot")

    # Lancer le bot
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
