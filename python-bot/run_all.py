"""
BingeBear TV - Combined Launcher
Lance le bot de streaming ET le news forwarder en parallele
"""

import os
import re
import time
import asyncio
from datetime import datetime, timedelta
from dotenv import load_dotenv
from logger import setup_logger
from config import validate_config
from utils.retry import retry_sync

from telegram import Bot
from telegram.ext import Application, CommandHandler, ContextTypes
from telegram import Update

from pyrogram import Client, filters
from pyrogram.types import Message

from pytgcalls import PyTgCalls
from pytgcalls.types import MediaStream, AudioQuality, VideoQuality

import requests
from health import HealthCheck
from stream_state import save_state, load_state, clear_state
from news_cache import NewsCache
from news_queue import NewsQueue

# Charger les variables d'environnement
load_dotenv()

# Logger structuré
logger = setup_logger('bingebear.combined')

# Valider la configuration au démarrage
validate_config()

API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
SESSION_STRING = os.getenv("SESSION_STRING")

IPTV_SERVER = os.getenv("IPTV_SERVER_URL")
IPTV_USER = os.getenv("IPTV_USERNAME")
IPTV_PASS = os.getenv("IPTV_PASSWORD")

# Configuration News Forwarder (configurable via .env)
NEWS_SOURCE_CHANNEL = int(os.getenv("NEWS_SOURCE_CHANNEL", "-1001763758614"))
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
# Si pas de SESSION_STRING, le streaming et le news forwarder sont desactives
if SESSION_STRING and SESSION_STRING != "votre_session_string_ici":
    user_client = Client(
        "combined_session",
        api_id=API_ID,
        api_hash=API_HASH,
        session_string=SESSION_STRING
    )
    HAS_USER_CLIENT = True
else:
    user_client = None
    HAS_USER_CLIENT = False
    logger.warning("SESSION_STRING absente — streaming et news forwarder desactives")

# Bot Telegram (pour envoyer les messages et commandes)
telegram_bot = Bot(token=BOT_TOKEN)

# PyTgCalls pour le streaming
pytgcalls = None

# Health check
health = HealthCheck()

# Cache et file d'attente pour le news forwarder
news_cache = NewsCache()
news_queue = NewsQueue()

# Etat du streaming
current_stream = None
categories_cache = []
channels_cache = {}

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Accept': 'application/json, text/plain, */*',
}

ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x]
ALLOWED_USERNAMES = [u.strip() for u in os.getenv("ALLOWED_USERNAMES", "DefiMack").split(",") if u.strip()]


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
    """Modifier le message (remplacer la signature et les mentions revendeurs)"""
    text = re.sub(
        r'Queridos Revendedores.*?(?=Enjoy\.|Team|$)',
        '',
        text,
        flags=re.DOTALL | re.IGNORECASE
    )
    text = re.sub(r'Dear Resellers?\b', 'Dear Users', text, flags=re.IGNORECASE)
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = re.sub(r'Team\s*8K', NEWS_REPLACE_TO, text, flags=re.IGNORECASE)
    return text.strip()


async def forward_news(client: Client, message: Message):
    """Intercepter et transferer les messages filtres (texte + images)"""
    text = message.text or message.caption or ""

    if not text:
        return

    # Verifier le cache anti-doublons
    if news_cache.is_forwarded(message.id):
        logger.debug(f"Message {message.id} deja transfere (cache), ignore")
        return

    if should_forward_news(text):
        logger.info(f"Message news detecte! (id={message.id})")
        logger.debug(f"Apercu: {text[:100]}...")

        modified_text = modify_news_message(text)

        # Preparer la fonction d'envoi selon le type de contenu
        if message.photo:
            logger.info("Image detectee, telechargement...")
            photo_path = await message.download()

            async def send_photo():
                try:
                    with open(photo_path, 'rb') as photo_file:
                        await telegram_bot.send_photo(
                            chat_id=NEWS_DEST_CHANNEL,
                            photo=photo_file,
                            caption=modified_text
                        )
                    logger.info(f"Image + texte envoyes vers {NEWS_DEST_CHANNEL}")
                    health.last_news_forwarded = time.time()
                    news_cache.mark_forwarded(message.id)
                finally:
                    # Supprimer le fichier temporaire
                    try:
                        os.remove(photo_path)
                    except OSError:
                        pass

            await news_queue.enqueue(send_photo)
        else:
            async def send_text():
                await telegram_bot.send_message(
                    chat_id=NEWS_DEST_CHANNEL,
                    text=modified_text
                )
                logger.info(f"Message envoye vers {NEWS_DEST_CHANNEL}")
                health.last_news_forwarded = time.time()
                news_cache.mark_forwarded(message.id)

            await news_queue.enqueue(send_text)
    else:
        logger.debug("Message news ignore")


# Enregistrer le handler news seulement si le client utilisateur est disponible
if HAS_USER_CLIENT and user_client:
    user_client.on_message(filters.chat(NEWS_SOURCE_CHANNEL))(forward_news)


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
        response = retry_sync(
            lambda: requests.get(url, headers=HEADERS, timeout=30),
            description='chargement categories IPTV'
        )
        categories = response.json()
        categories_cache = [{"id": cat["category_id"], "name": cat["category_name"]} for cat in categories]
        return categories_cache
    except Exception as e:
        logger.error(f"Erreur categories: {e}")
        return []


def get_channels_by_category(category_id):
    global channels_cache
    try:
        url = f"{IPTV_SERVER}/player_api.php?username={IPTV_USER}&password={IPTV_PASS}&action=get_live_streams&category_id={category_id}"
        response = retry_sync(
            lambda: requests.get(url, headers=HEADERS, timeout=30),
            description=f'chargement chaines categorie {category_id}'
        )
        channels = response.json()
        channels_list = [
            {"id": ch["stream_id"], "name": ch["name"], "category_id": category_id,
             "url": f"{IPTV_SERVER}/live/{IPTV_USER}/{IPTV_PASS}/{ch['stream_id']}.ts"}
            for ch in channels
        ]
        channels_cache[category_id] = channels_list
        return channels_list
    except Exception as e:
        logger.error(f"Erreur chaines: {e}")
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

    # Envoyer toutes les categories en plusieurs messages si necessaire
    header = f"Categories disponibles ({len(categories)}):\n\n"
    current_msg = header
    msg_count = 1

    for cat in categories:
        line = f"* {cat['id']} - {escape_markdown(cat['name'])}\n"
        # Si le message depasse 3800 caracteres, envoyer et recommencer
        if len(current_msg) + len(line) > 3800:
            await update.message.reply_text(current_msg)
            msg_count += 1
            current_msg = f"Categories (suite {msg_count}):\n\n"
        current_msg += line

    current_msg += f"\nTotal: {len(categories)}\nUtilisez /cat <id>"
    await update.message.reply_text(current_msg)


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

    header = f"{escape_markdown(category['name'])} ({len(channels)} chaines):\n\n"
    current_msg = header
    msg_count = 1

    for ch in channels:
        line = f"* {ch['id']} - {escape_markdown(ch['name'])}\n"
        if len(current_msg) + len(line) > 3800:
            await update.message.reply_text(current_msg)
            msg_count += 1
            current_msg = f"Chaines (suite {msg_count}):\n\n"
        current_msg += line

    current_msg += f"\nTotal: {len(channels)}\nUtilisez /play <id>"
    await update.message.reply_text(current_msg)


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
                ffmpeg_parameters="-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 -err_detect ignore_err"
            )
        )
        current_stream = channel
        health.is_streaming = True
        health.last_stream_activity = time.time()
        save_state(channel)
        await update.message.reply_text(f"Stream demarre: {channel['name']}")
    except Exception as e:
        logger.exception(f"Erreur dans play_command: {e}")
        await update.message.reply_text(f"Erreur: {e}")
        current_stream = None
        health.is_streaming = False
        clear_state()


async def stop_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global current_stream, pytgcalls

    if not is_allowed_user(update.effective_user):
        await update.message.reply_text("Non autorise")
        return

    try:
        await pytgcalls.leave_call(CHAT_ID)
        current_stream = None
        health.is_streaming = False
        clear_state()
        await update.message.reply_text("Stream arrete")
    except Exception as e:
        logger.exception(f"Erreur dans stop_command: {e}")
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
                ffmpeg_parameters="-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 -err_detect ignore_err"
            )
        )
        current_stream = {"id": "test", "name": "Big Buck Bunny (Test)", "url": test_url}
        await update.message.reply_text("Stream de test demarre!")
    except Exception as e:
        logger.exception(f"Erreur dans test_command: {e}")
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
        "/test - Test\n"
        "/importnews <jours> - Importer les news (admin)"
    )


async def importnews_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Importer les messages du canal source depuis X jours (admin only)"""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("Non autorise (admin uniquement)")
        return

    if not HAS_USER_CLIENT or not user_client:
        await update.message.reply_text("Erreur: client utilisateur non connecte (SESSION_STRING manquante)")
        return

    # Nombre de jours (defaut: 7)
    days = 7
    if context.args:
        try:
            days = int(context.args[0])
            if days < 1 or days > 30:
                await update.message.reply_text("Nombre de jours entre 1 et 30")
                return
        except ValueError:
            await update.message.reply_text("Usage: /importnews <nombre_de_jours>\nExemple: /importnews 7")
            return

    since_date = datetime.now() - timedelta(days=days)
    await update.message.reply_text(f"Import des news depuis {days} jour(s)...\nCela peut prendre un moment.")

    imported = 0
    skipped = 0

    try:
        async for message in user_client.get_chat_history(NEWS_SOURCE_CHANNEL):
            # Arreter si le message est trop ancien
            if message.date.replace(tzinfo=None) < since_date:
                break

            text = message.text or message.caption or ""
            if not text:
                continue

            # Verifier si deja transfere
            if news_cache.is_forwarded(message.id):
                skipped += 1
                continue

            if should_forward_news(text):
                modified_text = modify_news_message(text)

                if message.photo:
                    photo_path = await message.download()
                    try:
                        with open(photo_path, 'rb') as photo_file:
                            await telegram_bot.send_photo(
                                chat_id=NEWS_DEST_CHANNEL,
                                photo=photo_file,
                                caption=modified_text
                            )
                    finally:
                        try:
                            os.remove(photo_path)
                        except OSError:
                            pass
                else:
                    await telegram_bot.send_message(
                        chat_id=NEWS_DEST_CHANNEL,
                        text=modified_text
                    )

                news_cache.mark_forwarded(message.id)
                imported += 1
                logger.info(f"Import news: message {message.id} transfere")

                # Pause anti-rate-limit
                await asyncio.sleep(1.5)

        await update.message.reply_text(
            f"Import termine!\n"
            f"Messages importes: {imported}\n"
            f"Deja importes (ignores): {skipped}"
        )
    except Exception as e:
        logger.exception(f"Erreur dans importnews_command: {e}")
        await update.message.reply_text(f"Erreur pendant l'import: {e}\nMessages importes avant erreur: {imported}")


async def auto_resume_stream():
    """Reprendre le stream précédent si un état sauvegardé existe."""
    global current_stream

    previous = load_state()
    if not previous:
        return

    logger.info(f"Auto-resume: tentative de reprise de '{previous.get('name', '?')}'...")
    try:
        await pytgcalls.play(
            CHAT_ID,
            MediaStream(
                previous["url"],
                ffmpeg_parameters="-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 -err_detect ignore_err"
            )
        )
        current_stream = previous
        health.is_streaming = True
        health.last_stream_activity = time.time()
        logger.info(f"Auto-resume reussi: {previous['name']}")
    except Exception as e:
        logger.warning(f"Auto-resume echoue: {e}")
        clear_state()


async def stream_watchdog():
    """Surveille le stream et le relance si coupe (pas d'activite depuis 30s)."""
    global current_stream
    watchdog_interval = 30  # Verification toutes les 30s

    while True:
        await asyncio.sleep(watchdog_interval)

        if not current_stream or not health.is_streaming:
            continue

        # Verifier si le stream est encore actif
        last_activity = health.last_stream_activity or 0
        inactivity = time.time() - last_activity

        if inactivity > 60:
            logger.warning(f"Stream inactif depuis {int(inactivity)}s, tentative de relance...")
            try:
                await pytgcalls.leave_call(CHAT_ID)
            except Exception:
                pass

            try:
                await pytgcalls.play(
                    CHAT_ID,
                    MediaStream(
                        current_stream["url"],
                        ffmpeg_parameters="-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 -err_detect ignore_err"
                    )
                )
                health.last_stream_activity = time.time()
                logger.info(f"Stream relance: {current_stream['name']}")
            except Exception as e:
                logger.error(f"Echec relance stream: {e}")
                current_stream = None
                health.is_streaming = False
                clear_state()


async def post_init(application):
    """Initialiser pytgcalls apres le demarrage"""
    global pytgcalls

    if HAS_USER_CLIENT and user_client:
        logger.info("Demarrage du client utilisateur...")
        await user_client.start()

        me = await user_client.get_me()
        logger.info(f"Connecte: {me.first_name} (@{me.username})")

        pytgcalls = PyTgCalls(user_client)
        await pytgcalls.start()
        logger.info("PyTgCalls pret")

        logger.info(f"Ecoute canal source: {NEWS_SOURCE_CHANNEL}")
        logger.info(f"Destination news: {NEWS_DEST_CHANNEL}")

        # Demarrer la file d'attente news
        await news_queue.start()

        # Auto-resume du stream precedent si applicable
        await auto_resume_stream()

        # Lancer le watchdog en tache de fond
        asyncio.create_task(stream_watchdog())
    else:
        logger.warning("Mode commandes uniquement (pas de streaming/news)")

    logger.info(f"Groupe cible: @{CHAT_ID}")

    # Démarrer le health check HTTP
    health_port = int(os.getenv("HEALTH_PORT", "8080"))
    await health.start(port=health_port)


def main():
    """Fonction principale"""
    logger.info("=" * 50)
    logger.info("BingeBear TV - Combined Bot")
    logger.info("=" * 50)
    logger.info("Streaming Bot: @Bingebear_tv_bot")
    logger.info("News Forwarder: Active")
    logger.info("=" * 50)

    application = Application.builder().token(BOT_TOKEN).post_init(post_init).build()

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("categories", categories_command))
    application.add_handler(CommandHandler("cat", cat_command))
    application.add_handler(CommandHandler("play", play_command))
    application.add_handler(CommandHandler("stop", stop_command))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(CommandHandler("test", test_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("importnews", importnews_command))

    logger.info("Bot pret!")

    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
