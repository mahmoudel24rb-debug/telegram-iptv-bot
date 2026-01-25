"""
BingeBear TV - Combined Launcher
Lance le bot de streaming ET le news forwarder en parallele
"""

import os
import re
import asyncio
from dotenv import load_dotenv

from telegram import Bot
from telegram.ext import Application, CommandHandler, ContextTypes
from telegram import Update

from pyrogram import Client, filters
from pyrogram.types import Message

from pytgcalls import PyTgCalls
from pytgcalls.types import MediaStream, AudioQuality, VideoQuality

import requests

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

# Configuration News Forwarder
NEWS_SOURCE_CHANNEL = -1001763758614  # SERVICE INFORMATION
NEWS_DEST_CHANNEL = os.getenv("NEWS_DEST_CHANNEL", "@bingebeartv_live")

# Patterns pour filtrer les messages (uniquement annonces en anglais)
NEWS_PATTERNS = [
    r"Dear Reseller,\s*\n\s*We are pleased",
    r"^[A-Z\s]+VS\s+[A-Z\s]+",
    r"^LIVE EVENT",
]

NEWS_EXCLUDE_WORDS = [
    "domain has been suspended",
    "purchase a private domain",
    "misuse and multiple complaints",
    "Queridos Revendedores",
    "Nos complace",
]

NEWS_REPLACE_TO = "Team BingeBearTV"

# Client utilisateur Pyrogram (partage pour streaming et news)
if SESSION_STRING:
    user_client = Client(
        "combined_session",
        api_id=API_ID,
        api_hash=API_HASH,
        session_string=SESSION_STRING
    )
else:
    user_client = Client(
        "combined_session",
        api_id=API_ID,
        api_hash=API_HASH
    )

# Bot Telegram (pour envoyer les messages et commandes)
telegram_bot = Bot(token=BOT_TOKEN)

# PyTgCalls pour le streaming
pytgcalls = None

# Etat du streaming
current_stream = None
categories_cache = []
channels_cache = {}

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Accept': 'application/json, text/plain, */*',
}

ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x]
ALLOWED_USERNAMES = ["DefiMack"]


# ============== NEWS FORWARDER FUNCTIONS ==============

def should_forward_news(text: str) -> bool:
    """Verifier si le message doit etre transfere"""
    for exclude in NEWS_EXCLUDE_WORDS:
        if exclude.lower() in text.lower():
            return False
    for pattern in NEWS_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE | re.MULTILINE):
            return True
    return False


def modify_news_message(text: str) -> str:
    """Modifier le message (remplacer la signature)"""
    text = re.sub(
        r'Queridos Revendedores.*?(?=Enjoy\.|Team|$)',
        '',
        text,
        flags=re.DOTALL | re.IGNORECASE
    )
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = re.sub(r'Team\s*8K', NEWS_REPLACE_TO, text, flags=re.IGNORECASE)
    return text.strip()


@user_client.on_message(filters.chat(NEWS_SOURCE_CHANNEL))
async def forward_news(client: Client, message: Message):
    """Intercepter et transferer les messages filtres (texte + images)"""
    text = message.text or message.caption or ""

    if not text:
        return

    if should_forward_news(text):
        print(f"\n[NEWS] Message detecte!")
        print(f"[NEWS] Apercu: {text[:100]}...")

        modified_text = modify_news_message(text)

        try:
            # Verifier si le message contient une photo
            if message.photo:
                print(f"[NEWS] Image detectee, telechargement...")
                # Telecharger la photo
                photo_path = await message.download()

                # Envoyer la photo avec le texte modifie comme caption
                with open(photo_path, 'rb') as photo_file:
                    await telegram_bot.send_photo(
                        chat_id=NEWS_DEST_CHANNEL,
                        photo=photo_file,
                        caption=modified_text
                    )

                # Supprimer le fichier temporaire
                import os as os_module
                os_module.remove(photo_path)
                print(f"[NEWS] Image + texte envoyes vers {NEWS_DEST_CHANNEL}")
            else:
                # Pas d'image, envoyer juste le texte
                await telegram_bot.send_message(
                    chat_id=NEWS_DEST_CHANNEL,
                    text=modified_text
                )
                print(f"[NEWS] Message envoye vers {NEWS_DEST_CHANNEL}")

        except Exception as e:
            print(f"[NEWS ERREUR] {e}")
    else:
        print(f"[NEWS SKIP] Message ignore")


# ============== STREAMING BOT FUNCTIONS ==============

def is_admin(user_id):
    if not ADMIN_IDS:
        return True
    return user_id in ADMIN_IDS


def is_allowed_user(user):
    if user.username and user.username in ALLOWED_USERNAMES:
        return True
    if user.id in ADMIN_IDS:
        return True
    return False


def get_categories():
    global categories_cache
    try:
        url = f"{IPTV_SERVER}/player_api.php?username={IPTV_USER}&password={IPTV_PASS}&action=get_live_categories"
        response = requests.get(url, headers=HEADERS, timeout=30)
        categories = response.json()
        categories_cache = [{"id": cat["category_id"], "name": cat["category_name"]} for cat in categories]
        return categories_cache
    except Exception as e:
        print(f"Erreur categories: {e}")
        return []


def get_channels_by_category(category_id):
    global channels_cache
    try:
        url = f"{IPTV_SERVER}/player_api.php?username={IPTV_USER}&password={IPTV_PASS}&action=get_live_streams&category_id={category_id}"
        response = requests.get(url, headers=HEADERS, timeout=30)
        channels = response.json()
        channels_list = [
            {"id": ch["stream_id"], "name": ch["name"], "category_id": category_id,
             "url": f"{IPTV_SERVER}/live/{IPTV_USER}/{IPTV_PASS}/{ch['stream_id']}.ts"}
            for ch in channels
        ]
        channels_cache[category_id] = channels_list
        return channels_list
    except Exception as e:
        print(f"Erreur chaines: {e}")
        return []


def get_channel_by_id(channel_id):
    for cat_id, channels in channels_cache.items():
        for ch in channels:
            if str(ch["id"]) == str(channel_id):
                return ch
    return None


def escape_markdown(text):
    special_chars = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
    for char in special_chars:
        text = str(text).replace(char, f'\\{char}')
    return text


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "BingeBear TV - Live Streaming Bot\n\n"
        "Commandes:\n"
        "/categories - Liste des categories\n"
        "/cat <id> - Chaines d'une categorie\n"
        "/play <id> - Lancer un stream\n"
        "/stop - Arreter le stream\n"
        "/status - Statut actuel\n"
        "/test - Stream de test"
    )


async def categories_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Chargement des categories...")
    categories = get_categories()
    if not categories:
        await update.message.reply_text("Aucune categorie disponible")
        return

    text = "Categories disponibles:\n\n"
    for cat in categories[:50]:
        text += f"* {cat['id']} - {escape_markdown(cat['name'])}\n"
    if len(categories) > 50:
        text += f"\n... et {len(categories) - 50} autres\n"
    text += f"\nTotal: {len(categories)}\nUtilisez /cat <id>"

    if len(text) > 4000:
        text = text[:4000] + "..."
    await update.message.reply_text(text)


async def cat_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /cat <category_id>")
        return

    category_id = context.args[0]
    if not categories_cache:
        get_categories()

    category = None
    for cat in categories_cache:
        if str(cat["id"]) == str(category_id):
            category = cat
            break

    if not category:
        await update.message.reply_text(f"Categorie {category_id} non trouvee")
        return

    await update.message.reply_text(f"Chargement de {category['name']}...")
    channels = get_channels_by_category(category_id)

    if not channels:
        await update.message.reply_text("Aucune chaine")
        return

    text = f"{escape_markdown(category['name'])}\n\n"
    for ch in channels[:30]:
        text += f"* {ch['id']} - {escape_markdown(ch['name'])}\n"
    if len(channels) > 30:
        text += f"\n... et {len(channels) - 30} autres\n"
    text += f"\nTotal: {len(channels)}\nUtilisez /play <id>"

    if len(text) > 4000:
        text = text[:4000] + "..."
    await update.message.reply_text(text)


async def play_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global current_stream, pytgcalls

    if not is_allowed_user(update.effective_user):
        await update.message.reply_text("Non autorise")
        return

    if not context.args:
        await update.message.reply_text("Usage: /play <channel_id>")
        return

    channel_id = context.args[0]
    channel = get_channel_by_id(channel_id)
    if not channel:
        await update.message.reply_text("Chaine non trouvee. Utilisez /cat d'abord.")
        return

    await update.message.reply_text(f"Demarrage: {channel['name']}")

    try:
        if current_stream:
            await pytgcalls.leave_call(CHAT_ID)

        await pytgcalls.play(
            CHAT_ID,
            MediaStream(
                channel["url"],
                audio_parameters=AudioQuality.STUDIO,
                video_parameters=VideoQuality.HD_720p,
                ffmpeg_parameters="-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 -fflags nobuffer -flags low_delay -strict experimental"
            )
        )
        current_stream = channel
        await update.message.reply_text(f"Stream demarre: {channel['name']}")
    except Exception as e:
        await update.message.reply_text(f"Erreur: {e}")
        current_stream = None


async def stop_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global current_stream, pytgcalls

    if not is_allowed_user(update.effective_user):
        await update.message.reply_text("Non autorise")
        return

    try:
        await pytgcalls.leave_call(CHAT_ID)
        current_stream = None
        await update.message.reply_text("Stream arrete")
    except Exception as e:
        await update.message.reply_text(f"Erreur: {e}")


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if current_stream:
        await update.message.reply_text(f"Stream actif: {current_stream['name']}")
    else:
        await update.message.reply_text("Aucun stream en cours")


async def test_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global current_stream, pytgcalls

    if not is_allowed_user(update.effective_user):
        await update.message.reply_text("Non autorise")
        return

    await update.message.reply_text("Demarrage du test...")
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
                ffmpeg_parameters="-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 -fflags nobuffer -flags low_delay -strict experimental"
            )
        )
        current_stream = {"id": "test", "name": "Big Buck Bunny (Test)", "url": test_url}
        await update.message.reply_text("Stream de test demarre!")
    except Exception as e:
        await update.message.reply_text(f"Erreur: {e}")
        current_stream = None


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "BingeBear TV Bot\n\n"
        "/start - Demarrer\n"
        "/categories - Categories IPTV\n"
        "/cat <id> - Chaines\n"
        "/play <id> - Lancer stream\n"
        "/stop - Arreter\n"
        "/status - Statut\n"
        "/test - Test"
    )


async def post_init(application):
    """Initialiser pytgcalls apres le demarrage"""
    global pytgcalls

    print("[INIT] Demarrage du client utilisateur...")
    await user_client.start()

    me = await user_client.get_me()
    print(f"[INIT] Connecte: {me.first_name} (@{me.username})")

    pytgcalls = PyTgCalls(user_client)
    await pytgcalls.start()
    print("[INIT] PyTgCalls pret")

    print(f"[INIT] Groupe cible: @{CHAT_ID}")
    print(f"[NEWS] Ecoute canal source: {NEWS_SOURCE_CHANNEL}")
    print(f"[NEWS] Destination: {NEWS_DEST_CHANNEL}")


def main():
    """Fonction principale"""
    print("=" * 50)
    print("BingeBear TV - Combined Bot")
    print("=" * 50)
    print("- Streaming Bot: @Bingebear_tv_bot")
    print("- News Forwarder: Active")
    print("=" * 50)

    application = Application.builder().token(BOT_TOKEN).post_init(post_init).build()

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("categories", categories_command))
    application.add_handler(CommandHandler("cat", cat_command))
    application.add_handler(CommandHandler("play", play_command))
    application.add_handler(CommandHandler("stop", stop_command))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(CommandHandler("test", test_command))
    application.add_handler(CommandHandler("help", help_command))

    print("[READY] Bot pret!")

    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
