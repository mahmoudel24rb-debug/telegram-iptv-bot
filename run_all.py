"""
BingeBear TV - Combined Launcher
Lance le bot de streaming ET le news forwarder en parallele
"""

import os
import re
import time
import asyncio
import signal
from datetime import datetime, timedelta
from dotenv import load_dotenv
from logger import setup_logger
from config import validate_config

from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, CallbackQueryHandler
from telegram import Update

from pyrogram import Client, filters
from pyrogram.types import Message

from pytgcalls import PyTgCalls
from pytgcalls.types import MediaStream, AudioQuality, VideoQuality

import aiohttp
from health import HealthCheck
from stream_state import save_state, load_state, clear_state
from news_cache import NewsCache, compute_content_hash
from news_queue import NewsQueue
from reminders import load_reminders, add_reminder, delete_reminder, get_due_reminders, mark_sent, parse_interval, format_interval
from claude_processor import process_message, process_message_batch, CONFIDENCE_THRESHOLD
from dev_mode import PreviewBot, DevContext
from promotions import (
    load_promos, add_promo, delete_promo, toggle_promo,
    update_promo_message, get_promo, get_due_promos, mark_promo_sent,
    format_schedule, format_promo_summary, parse_weekdays,
    parse_interval as parse_promo_interval,
    TEMPLATES, WEEKDAY_NAMES,
)

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

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

# Configuration News Forwarder (configurable via .env)
def _parse_news_sources():
    """
    Recupere la liste des canaux source news.
    Supporte deux formats :
      - NEWS_SOURCE_CHANNELS (nouveau, pluriel) : "id1,id2,id3"
      - NEWS_SOURCE_CHANNEL  (ancien, singulier) : "id1"  → retrocompatibilite
    Retourne une liste d'ints.
    """
    plural = os.getenv("NEWS_SOURCE_CHANNELS", "").strip()
    if plural:
        try:
            return [int(x.strip()) for x in plural.split(",") if x.strip()]
        except ValueError as e:
            logger.critical(f"NEWS_SOURCE_CHANNELS contient une valeur invalide : {e}")
            raise
    singular = os.getenv("NEWS_SOURCE_CHANNEL", "-1001763758614").strip()
    return [int(singular)]


NEWS_SOURCE_CHANNELS = _parse_news_sources()
NEWS_SOURCE_CHANNEL = NEWS_SOURCE_CHANNELS[0]
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

# Flag pour le test du listener on_message
_listener_test_event = None
_listener_test_start = None

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


async def process_news_message(raw_text: str) -> tuple:
    """
    Traite un message news : decide s'il faut le transferer et le reecrit.

    Strategie :
    1. Si le message matche les patterns regex connus → traitement regex direct (pas d'appel API)
    2. Si le message est exclu par les mots interdits → skip direct (pas d'appel API)
    3. Sinon → appel Claude API pour les messages ambigus (pannes, urgences, etc.)
    4. Si Claude est indisponible → skip (les patterns connus sont deja traites en 1)

    Returns:
        (should_forward, modified_text, category)
    """
    global _claude_calls_total

    # ── Etape 1 : Exclusion rapide (mots interdits) ──
    for exclude in NEWS_EXCLUDE_WORDS:
        if exclude.lower() in raw_text.lower():
            return False, None, "excluded"

    # ── Etape 2 : Match regex connu → traitement direct sans Claude ──
    if should_forward_news(raw_text):
        modified = modify_news_message(raw_text)
        logger.info("[NEWS] Message matche pattern regex — traitement direct (pas d'appel Claude)")
        return True, modified, "regex_match"

    # ── Etape 3 : Message ambigu → appel Claude API ──
    _claude_calls_total += 1
    result = await process_message(raw_text)

    if result is not None:
        if result["should_forward"] and result.get("confidence", 0) >= CONFIDENCE_THRESHOLD:
            return True, result["rewritten_message"], result["category"]
        else:
            return False, None, result.get("category")

    # ── Claude indisponible et pas de match regex → skip ──
    logger.debug("[NEWS] Pas de match regex et Claude indisponible — skip")
    return False, None, None


async def forward_news(client: Client, message: Message):
    """Handler temps reel — traite chaque message via Claude API."""
    global _listener_test_event
    logger.info(f"[NEWS-RT] on_message declenche! msg_id={message.id}, chat={message.chat.id}, text={repr((message.text or message.caption or '')[:80])}")

    # Signal pour /testlistener
    if _listener_test_event and not _listener_test_event.is_set():
        _listener_test_event.set()

    text = message.text or message.caption or ""
    if not text.strip():
        return

    # Dedup niveau 1 : ce message source a-t-il deja ete traite ?
    if news_cache.is_source_seen(message.chat.id, message.id):
        logger.debug(f"[NEWS-RT] Message {message.chat.id}:{message.id} deja dans le cache — skip")
        return

    # Dedup niveau 2 : ce contenu a-t-il deja ete envoye depuis un autre canal ?
    content_hash = compute_content_hash(text)
    if news_cache.is_content_seen(content_hash):
        logger.info(f"[NEWS-RT] [DEDUP-CONTENT] Message {message.chat.id}:{message.id} a un contenu deja envoye — skip")
        news_cache.mark_source_seen(message.chat.id, message.id)
        return

    # Traitement via Claude (avec fallback regex)
    should_forward, modified_text, category = await process_news_message(text)

    logger.info(f"[NEWS-RT] Message {message.id} | forward={should_forward} | cat={category}")

    if should_forward and modified_text:
        if message.photo:
            photo_path = await message.download()
            try:
                with open(photo_path, 'rb') as photo_file:
                    await telegram_bot.send_photo(
                        chat_id=NEWS_DEST_CHANNEL,
                        photo=photo_file,
                        caption=modified_text
                    )
                logger.info(f"[NEWS-RT] Image + texte envoyes vers {NEWS_DEST_CHANNEL}")
                health.last_news_forwarded = time.time()
            except Exception as e:
                logger.error(f"[NEWS-RT] Erreur envoi photo: {e}")
                # Fallback texte
                await telegram_bot.send_message(
                    chat_id=NEWS_DEST_CHANNEL,
                    text=modified_text
                )
                health.last_news_forwarded = time.time()
            finally:
                try:
                    os.remove(photo_path)
                except OSError:
                    pass
        else:
            msg_id = message.id
            chan_id = message.chat.id

            async def send_text():
                await telegram_bot.send_message(
                    chat_id=NEWS_DEST_CHANNEL,
                    text=modified_text
                )
                logger.info(f"[NEWS-RT] Message envoye vers {NEWS_DEST_CHANNEL}")
                health.last_news_forwarded = time.time()
                news_cache.mark_source_seen(chan_id, msg_id)
                news_cache.mark_content_seen(content_hash)

            await news_queue.enqueue(send_text)
            return  # mark_source_seen sera appele dans le callback

    # Cacher dans tous les cas (transfere via photo ou non transfere)
    news_cache.mark_source_seen(message.chat.id, message.id)
    news_cache.mark_content_seen(content_hash)


# Enregistrer le handler news seulement si le client utilisateur est disponible
if HAS_USER_CLIENT and user_client:
    user_client.on_message(filters.chat(NEWS_SOURCE_CHANNELS))(forward_news)
    logger.info(f"Handler news enregistre pour {len(NEWS_SOURCE_CHANNELS)} canal(aux): {NEWS_SOURCE_CHANNELS}")


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


async def get_categories():
    global categories_cache
    url = f"{IPTV_SERVER}/player_api.php?username={IPTV_USER}&password={IPTV_PASS}&action=get_live_categories"
    try:
        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, headers=HEADERS) as resp:
                categories = await resp.json(content_type=None)
        categories_cache = [{"id": cat["category_id"], "name": cat["category_name"]} for cat in categories]
        return categories_cache
    except Exception as e:
        logger.error(f"Erreur categories: {e}")
        return []


async def get_channels_by_category(category_id):
    global channels_cache
    url = f"{IPTV_SERVER}/player_api.php?username={IPTV_USER}&password={IPTV_PASS}&action=get_live_streams&category_id={category_id}"
    try:
        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, headers=HEADERS) as resp:
                channels = await resp.json(content_type=None)
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


def sanitize_url(url: str) -> str:
    """Masquer les credentials IPTV dans une URL pour les logs."""
    if not url:
        return url
    if IPTV_USER:
        url = url.replace(IPTV_USER, "***")
    if IPTV_PASS:
        url = url.replace(IPTV_PASS, "***")
    return url


def escape_markdown(text):
    special_chars = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
    for char in special_chars:
        text = str(text).replace(char, f'\\{char}')
    return text


def _is_duplicate_update(update: Update) -> bool:
    """Detecter les messages auto-forwarded depuis un channel lie (cause de doublons)."""
    if not update.effective_user:
        return True
    if update.message and update.message.is_automatic_forward:
        return True
    return False


async def reply_private(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    """Envoyer la reponse en prive a l'utilisateur (jamais dans le canal)"""
    if not update.effective_user:
        return
    user_id = update.effective_user.id
    try:
        await context.bot.send_message(chat_id=user_id, text=text)
    except Exception:
        # Fallback: si le bot ne peut pas envoyer en DM (l'utilisateur n'a pas /start en prive)
        if update.message:
            await update.message.reply_text(text)


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if _is_duplicate_update(update):
        return
    await reply_private(update, context,
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
    if _is_duplicate_update(update):
        return
    await reply_private(update, context, "Chargement des categories...")
    categories = await get_categories()
    if not categories:
        await reply_private(update, context, "Aucune categorie disponible")
        return

    # Envoyer toutes les categories en plusieurs messages si necessaire
    header = f"Categories disponibles ({len(categories)}):\n\n"
    current_msg = header
    msg_count = 1

    for cat in categories:
        line = f"* {cat['id']} - {escape_markdown(cat['name'])}\n"
        # Si le message depasse 3800 caracteres, envoyer et recommencer
        if len(current_msg) + len(line) > 3800:
            await reply_private(update, context, current_msg)
            msg_count += 1
            current_msg = f"Categories (suite {msg_count}):\n\n"
        current_msg += line

    current_msg += f"\nTotal: {len(categories)}\nUtilisez /cat <id>"
    await reply_private(update, context, current_msg)


async def cat_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if _is_duplicate_update(update):
        return
    if not context.args:
        await reply_private(update, context, "Usage: /cat <category_id>")
        return

    category_id = context.args[0]
    if not categories_cache:
        await get_categories()

    category = None
    for cat in categories_cache:
        if str(cat["id"]) == str(category_id):
            category = cat
            break

    if not category:
        await reply_private(update, context, f"Categorie {category_id} non trouvee")
        return

    await reply_private(update, context, f"Chargement de {category['name']}...")
    channels = await get_channels_by_category(category_id)

    if not channels:
        await reply_private(update, context, "Aucune chaine")
        return

    header = f"{escape_markdown(category['name'])} ({len(channels)} chaines):\n\n"
    current_msg = header
    msg_count = 1

    for ch in channels:
        line = f"* {ch['id']} - {escape_markdown(ch['name'])}\n"
        if len(current_msg) + len(line) > 3800:
            await reply_private(update, context, current_msg)
            msg_count += 1
            current_msg = f"Chaines (suite {msg_count}):\n\n"
        current_msg += line

    current_msg += f"\nTotal: {len(channels)}\nUtilisez /play <id>"
    await reply_private(update, context, current_msg)


async def play_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global current_stream, pytgcalls

    if _is_duplicate_update(update):
        return
    if not pytgcalls:
        await reply_private(update, context, "Streaming non disponible (SESSION_STRING manquante)")
        return
    if not is_allowed_user(update.effective_user):
        await reply_private(update, context, "Non autorise")
        return

    if not context.args:
        await reply_private(update, context, "Usage: /play <channel_id>")
        return

    channel_id = context.args[0]
    channel = get_channel_by_id(channel_id)
    if not channel:
        await reply_private(update, context, "Chaine non trouvee. Utilisez /cat d'abord.")
        return

    await reply_private(update, context, f"Demarrage: {channel['name']}")

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
        await reply_private(update, context, f"Stream demarre: {channel['name']}")
    except Exception as e:
        logger.exception(f"Erreur dans play_command: {e}")
        await reply_private(update, context, f"Erreur: {e}")
        current_stream = None
        health.is_streaming = False
        clear_state()


async def stop_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global current_stream, pytgcalls

    if _is_duplicate_update(update):
        return
    if not pytgcalls:
        await reply_private(update, context, "Streaming non disponible")
        return
    if not is_allowed_user(update.effective_user):
        await reply_private(update, context, "Non autorise")
        return

    try:
        await pytgcalls.leave_call(CHAT_ID)
        current_stream = None
        health.is_streaming = False
        clear_state()
        await reply_private(update, context, "Stream arrete")
    except Exception as e:
        logger.exception(f"Erreur dans stop_command: {e}")
        await reply_private(update, context, f"Erreur: {e}")


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if _is_duplicate_update(update):
        return
    if current_stream:
        await reply_private(update, context, f"Stream actif: {current_stream['name']}")
    else:
        await reply_private(update, context, "Aucun stream en cours")


async def test_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global current_stream, pytgcalls

    if _is_duplicate_update(update):
        return
    if not pytgcalls:
        await reply_private(update, context, "Streaming non disponible (SESSION_STRING manquante)")
        return
    if not is_allowed_user(update.effective_user):
        await reply_private(update, context,"Non autorise")
        return

    await reply_private(update, context, "Demarrage du test...")
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
        await reply_private(update, context, "Stream de test demarre!")
    except Exception as e:
        logger.exception(f"Erreur dans test_command: {e}")
        await reply_private(update, context, f"Erreur: {e}")
        current_stream = None


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if _is_duplicate_update(update):
        return
    await reply_private(update, context,
        "BingeBear TV Bot\n\n"
        "/start - Demarrer\n"
        "/categories - Categories IPTV\n"
        "/cat <id> - Chaines\n"
        "/play <id> - Lancer stream\n"
        "/stop - Arreter\n"
        "/status - Statut\n"
        "/test - Test\n"
        "/announcement <msg> - Poster dans le canal (admin)\n"
        "/reminder <intervalle> <msg> - Rappel recurrent (admin)\n"
        "/reminders - Liste des rappels (admin)\n"
        "/delreminder <id> - Supprimer rappel (admin)\n"
        "/importnews <jours> - Importer les news (admin)\n"
        "/promos - Panel campagnes promo (admin)\n"
        "/addpromo - Creer une campagne (admin)\n"
        "/editpromo <id> <msg> - Modifier le message (admin)\n"
        "/delpromo <id> - Supprimer une campagne (admin)\n"
        "/dev <cmd> [args] - Mode preview admin (DM uniquement)"
    )


async def importnews_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Importer les messages du canal source depuis X jours (admin only)"""
    if _is_duplicate_update(update):
        return
    if not is_admin(update.effective_user.id):
        await reply_private(update, context,"Non autorise (admin uniquement)")
        return

    if not HAS_USER_CLIENT or not user_client:
        await reply_private(update, context,"Erreur: client utilisateur non connecte (SESSION_STRING manquante)")
        return

    # Nombre de jours (defaut: 7)
    days = 7
    if context.args:
        try:
            days = int(context.args[0])
            if days < 1 or days > 30:
                await reply_private(update, context,"Nombre de jours entre 1 et 30")
                return
        except ValueError:
            await reply_private(update, context,"Usage: /importnews <nombre_de_jours>\nExemple: /importnews 7")
            return

    since_date = datetime.now() - timedelta(days=days)
    await reply_private(update, context, f"Import des news depuis {days} jour(s)...\nCela peut prendre un moment.")

    imported = 0
    skipped = 0
    claude_calls = 0

    try:
        for source_channel in NEWS_SOURCE_CHANNELS:
            try:
                async for message in user_client.get_chat_history(source_channel):
                    if message.date.replace(tzinfo=None) < since_date:
                        break

                    text = message.text or message.caption or ""
                    if not text:
                        continue

                    # Dedup niveau 1 : message source deja vu ?
                    if news_cache.is_source_seen(source_channel, message.id):
                        skipped += 1
                        continue

                    # Dedup niveau 2 : contenu deja vu (depuis l'autre canal par exemple) ?
                    chash = compute_content_hash(text)
                    if news_cache.is_content_seen(chash):
                        skipped += 1
                        news_cache.mark_source_seen(source_channel, message.id)
                        logger.info(f"[NEWS-IMPORT] [DEDUP-CONTENT] {source_channel}:{message.id} doublon de contenu — skip")
                        continue

                    # Traitement via Claude (avec fallback regex)
                    should_fwd, modified_text, category = await process_news_message(text)
                    claude_calls += 1

                    if should_fwd and modified_text:
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

                        imported += 1
                        logger.info(f"Import news: {source_channel}:{message.id} transfere [{category}]")

                    news_cache.mark_source_seen(source_channel, message.id)
                    news_cache.mark_content_seen(chash)

                    # Pause anti-rate-limit
                    await asyncio.sleep(1.5 if should_fwd else 0.5)

            except Exception as e:
                logger.error(f"[NEWS-IMPORT] Erreur sur canal {source_channel}: {e}")
                continue

        logger.info(f"[NEWS-IMPORT] {claude_calls} appels Claude (~{claude_calls * 0.003:.2f}$ estime)")
        await reply_private(update, context,
            f"Import termine!\n"
            f"Canaux scrutes: {len(NEWS_SOURCE_CHANNELS)}\n"
            f"Messages importes: {imported}\n"
            f"Deja importes (ignores): {skipped}\n"
            f"Appels Claude: {claude_calls}"
        )
    except Exception as e:
        logger.exception(f"Erreur dans importnews_command: {e}")
        await reply_private(update, context, f"Erreur pendant l'import: {e}\nMessages importes avant erreur: {imported}")


async def announcement_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Poster un message dans le canal comme si c'etait le bot/canal"""
    if _is_duplicate_update(update):
        return
    if not is_admin(update.effective_user.id):
        await reply_private(update, context, "Non autorise (admin uniquement)")
        return

    if not context.args:
        await reply_private(update, context, "Usage: /announcement <message>\nExemple: /announcement Bienvenue sur BingeBear TV!")
        return

    text = " ".join(context.args)

    try:
        await context.bot.send_message(chat_id=NEWS_DEST_CHANNEL, text=text)
        await reply_private(update, context, "Annonce envoyee dans le canal.")
        logger.info(f"[ANNOUNCEMENT] Message envoye par {update.effective_user.id}: {text[:80]}")
    except Exception as e:
        logger.exception(f"Erreur dans announcement_command: {e}")
        await reply_private(update, context, f"Erreur: {e}")


async def reminder_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Creer un rappel recurrent"""
    if _is_duplicate_update(update):
        return
    if not is_admin(update.effective_user.id):
        await reply_private(update, context, "Non autorise (admin uniquement)")
        return

    if len(context.args) < 2:
        await reply_private(update, context,
            "Usage: /reminder <intervalle> <message>\n\n"
            "Intervalles: 30m, 12h, 36h, 48h, 2d, 7d\n\n"
            "Exemples:\n"
            "/reminder 36h Pensez a renouveler votre abonnement!\n"
            "/reminder 2d Nouveaux canaux disponibles!"
        )
        return

    interval_secs = parse_interval(context.args[0])
    if interval_secs is None:
        await reply_private(update, context, "Intervalle invalide. Utilisez: 30m, 12h, 36h, 48h, 2d...")
        return

    message = " ".join(context.args[1:])
    rid = add_reminder(message, interval_secs)

    await reply_private(update, context,
        f"Rappel cree!\n"
        f"ID: {rid}\n"
        f"Intervalle: {format_interval(interval_secs)}\n"
        f"Message: {message}"
    )
    logger.info(f"[REMINDER] Rappel {rid} cree par {update.effective_user.id}: intervalle={format_interval(interval_secs)}")


async def reminders_list_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lister tous les rappels actifs"""
    if _is_duplicate_update(update):
        return
    if not is_admin(update.effective_user.id):
        await reply_private(update, context, "Non autorise (admin uniquement)")
        return

    reminders = load_reminders()
    if not reminders:
        await reply_private(update, context, "Aucun rappel actif.")
        return

    lines = ["Rappels actifs:\n"]
    for rid, data in reminders.items():
        interval_str = format_interval(data["interval"])
        lines.append(f"- ID: {rid} | {interval_str}\n  {data['message']}")

    await reply_private(update, context, "\n".join(lines))


async def delreminder_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Supprimer un rappel"""
    if _is_duplicate_update(update):
        return
    if not is_admin(update.effective_user.id):
        await reply_private(update, context, "Non autorise (admin uniquement)")
        return

    if not context.args:
        await reply_private(update, context, "Usage: /delreminder <id>")
        return

    rid = context.args[0]
    if delete_reminder(rid):
        await reply_private(update, context, f"Rappel {rid} supprime.")
        logger.info(f"[REMINDER] Rappel {rid} supprime par {update.effective_user.id}")
    else:
        await reply_private(update, context, f"Rappel {rid} introuvable.")


async def dev_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Mode dev: execute une commande en redirigeant les envois canal vers le DM admin."""
    if _is_duplicate_update(update):
        return
    if not is_admin(update.effective_user.id):
        await reply_private(update, context, "Non autorise (admin uniquement)")
        return

    if not context.args:
        await reply_private(update, context,
            "Usage: /dev <commande> [args]\n\n"
            "Commandes disponibles:\n"
            "  /dev importnews [jours]   - preview import news\n"
            "  /dev announcement <texte> - preview annonce\n"
            "  /dev reminder <id>        - preview rappel\n"
            "  /dev promo <id|template>  - preview promo\n"
            "  /dev help                 - cette aide"
        )
        return

    sub_cmd = context.args[0].lower()
    sub_args = context.args[1:]
    admin_id = update.effective_user.id

    redirect_targets = {
        NEWS_DEST_CHANNEL,
        f"@{CHAT_ID}" if not str(CHAT_ID).startswith("@") else CHAT_ID,
        CHAT_ID,
    }

    preview_bot = PreviewBot(context.bot, admin_id, redirect_targets)
    dev_ctx = DevContext(context, preview_bot)

    class _FakeContext:
        def __init__(self, base, args):
            self._base = base
            self.args = args
            self.bot = base.bot
        def __getattr__(self, name):
            return getattr(self._base, name)

    sub_context = _FakeContext(dev_ctx, sub_args)

    await reply_private(update, context, f"🧪 Mode DEV actif — execution de /{sub_cmd}\nLes envois canal sont rediriges ici.")

    try:
        if sub_cmd == "importnews":
            if not sub_args:
                sub_context.args = ["1"]
            await _dev_run_importnews(update, sub_context)

        elif sub_cmd == "announcement":
            if not sub_args:
                await reply_private(update, context, "Usage: /dev announcement <texte>")
                return
            await announcement_command(update, sub_context)

        elif sub_cmd == "reminder":
            if not sub_args:
                await reply_private(update, context, "Usage: /dev reminder <id>\nUtilise /reminders pour lister.")
                return
            await _dev_run_reminder_preview(update, sub_context, sub_args[0])

        elif sub_cmd == "promo":
            if not sub_args:
                await reply_private(update, context, "Usage: /dev promo <id|template>")
                return
            await _dev_run_promo_preview(update, sub_context, sub_args[0])

        elif sub_cmd == "help":
            await reply_private(update, context,
                "Commandes /dev disponibles:\n"
                "/dev importnews [jours]\n"
                "/dev announcement <texte>\n"
                "/dev reminder <id>\n"
                "/dev promo <id|template>"
            )
            return

        else:
            await reply_private(update, context, f"Commande dev inconnue: {sub_cmd}\nFais /dev help pour voir la liste.")
            return

        await reply_private(update, context, f"✅ Preview termine.\nMessages interceptes: {preview_bot.intercepted_count}")

    except Exception as e:
        logger.exception(f"[DEV] Erreur dans /dev {sub_cmd}: {e}")
        await reply_private(update, context, f"❌ Erreur dev: {e}")


async def _dev_run_importnews(update, sub_context):
    """Variante de importnews qui utilise PreviewBot et ne marque PAS le cache."""
    if not HAS_USER_CLIENT or not user_client:
        await reply_private(update, sub_context, "Erreur: client utilisateur non connecte")
        return

    days = 1
    if sub_context.args:
        try:
            days = int(sub_context.args[0])
            if days < 1 or days > 7:
                await reply_private(update, sub_context, "En mode dev, jours entre 1 et 7")
                return
        except ValueError:
            await reply_private(update, sub_context, "Usage: /dev importnews <jours>")
            return

    since_date = datetime.now() - timedelta(days=days)
    await reply_private(update, sub_context, f"🧪 [DEV] Preview import news depuis {days} jour(s)...")

    previewed = 0
    skipped = 0
    claude_calls = 0

    for source_channel in NEWS_SOURCE_CHANNELS:
        try:
            async for message in user_client.get_chat_history(source_channel):
                if message.date.replace(tzinfo=None) < since_date:
                    break
                text = message.text or message.caption or ""
                if not text:
                    continue

                should_fwd, modified_text, category = await process_news_message(text)
                claude_calls += 1

                if should_fwd and modified_text:
                    if message.photo:
                        photo_path = await message.download()
                        try:
                            with open(photo_path, 'rb') as photo_file:
                                await sub_context.bot.send_photo(
                                    chat_id=NEWS_DEST_CHANNEL,
                                    photo=photo_file,
                                    caption=f"[{category}] {modified_text}"
                                )
                        finally:
                            try:
                                os.remove(photo_path)
                            except OSError:
                                pass
                    else:
                        await sub_context.bot.send_message(
                            chat_id=NEWS_DEST_CHANNEL,
                            text=f"[{category}] {modified_text}"
                        )
                    previewed += 1
                else:
                    skipped += 1
                await asyncio.sleep(0.5)
        except Exception as e:
            logger.error(f"[DEV-IMPORT] Erreur sur canal {source_channel}: {e}")
            continue

    await reply_private(update, sub_context,
        f"🧪 Preview import termine.\n"
        f"Messages affiches: {previewed}\n"
        f"Filtres/skip: {skipped}\n"
        f"Appels Claude: {claude_calls} (~${claude_calls * 0.003:.2f})"
    )


async def _dev_run_reminder_preview(update, sub_context, reminder_id: str):
    """Preview un rappel sans modifier last_sent."""
    reminders = load_reminders()
    if reminder_id not in reminders:
        await reply_private(update, sub_context, f"Rappel '{reminder_id}' introuvable. Utilise /reminders.")
        return
    msg = reminders[reminder_id]["message"]
    await sub_context.bot.send_message(chat_id=NEWS_DEST_CHANNEL, text=msg)


async def _dev_run_promo_preview(update, sub_context, identifier: str):
    """Preview d'une promo (par id ou par nom de template)."""
    promo = get_promo(identifier)
    if promo:
        await sub_context.bot.send_message(chat_id=NEWS_DEST_CHANNEL, text=promo["message"])
        return
    if identifier in TEMPLATES:
        await sub_context.bot.send_message(chat_id=NEWS_DEST_CHANNEL, text=TEMPLATES[identifier]["message"])
        return
    await reply_private(update, sub_context,
        f"Promo '{identifier}' introuvable.\n"
        f"Templates: {', '.join(TEMPLATES.keys())}\n"
        f"Promos actives: utilise /promos"
    )


async def testlistener_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Tester si le handler on_message Pyrogram fonctionne"""
    global _listener_test_event, _listener_test_start
    if _is_duplicate_update(update):
        return
    if not is_admin(update.effective_user.id):
        await reply_private(update, context, "Non autorise (admin uniquement)")
        return

    if not HAS_USER_CLIENT or not user_client:
        await reply_private(update, context, "Client utilisateur non connecte")
        return

    await reply_private(update, context, "Test du listener on_message...\nEn attente d'un message dans le canal source (60s max).")
    logger.info("[NEWS-RT] Test listener — en attente d'un message dans le canal source...")

    _listener_test_event = asyncio.Event()
    _listener_test_start = time.time()

    try:
        await asyncio.wait_for(_listener_test_event.wait(), timeout=60)
        elapsed = time.time() - _listener_test_start
        await reply_private(update, context, f"Listener actif — message capte en {elapsed:.1f}s")
        logger.info(f"[NEWS-RT] Test listener OK — message capte en {elapsed:.1f}s")
    except asyncio.TimeoutError:
        await reply_private(update, context, "Listener inactif — on_message ne se declenche pas apres 60s")
        logger.warning("[NEWS-RT] Test listener ECHEC — timeout 60s")
    finally:
        _listener_test_event = None
        _listener_test_start = None


async def promos_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/promos — Panel principal des campagnes promotionnelles."""
    if _is_duplicate_update(update):
        return
    if not is_admin(update.effective_user.id):
        await reply_private(update, context, "Non autorise (admin uniquement)")
        return

    promos = load_promos()

    if not promos:
        keyboard = [
            [InlineKeyboardButton("➕ Creer depuis un template", callback_data="promo_templates")],
            [InlineKeyboardButton("✍️ Creer une promo custom", callback_data="promo_help_add")],
        ]
        await reply_private(update, context, "Aucune campagne promo active.\n\nCreez votre premiere promo:")
        await context.bot.send_message(
            chat_id=update.effective_user.id,
            text="Choisissez une option:",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return

    lines = ["📢 Campagnes promotionnelles\n"]
    keyboard_rows = []

    for pid, data in promos.items():
        lines.append(format_promo_summary(pid, data))
        lines.append("")

        status_icon = "⏸" if data.get("active") else "▶️"
        keyboard_rows.append([
            InlineKeyboardButton(f"{status_icon} {data.get('name', pid)[:15]}", callback_data=f"promo_toggle_{pid}"),
            InlineKeyboardButton("👁 Preview", callback_data=f"promo_preview_{pid}"),
            InlineKeyboardButton("🗑", callback_data=f"promo_delete_{pid}"),
        ])

    keyboard_rows.append([
        InlineKeyboardButton("➕ Template", callback_data="promo_templates"),
        InlineKeyboardButton("✍️ Custom", callback_data="promo_help_add"),
    ])

    await context.bot.send_message(
        chat_id=update.effective_user.id,
        text="\n".join(lines),
        reply_markup=InlineKeyboardMarkup(keyboard_rows),
    )


async def addpromo_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/addpromo — Creer une campagne promotionnelle."""
    if _is_duplicate_update(update):
        return
    if not is_admin(update.effective_user.id):
        await reply_private(update, context, "Non autorise (admin uniquement)")
        return

    if not context.args or len(context.args) < 2:
        help_text = (
            "📢 Creer une campagne promo\n\n"
            "Depuis un template:\n"
            "  /addpromo template free_trial\n"
            "  /addpromo template renewal\n"
            "  /addpromo template weekend_deal\n"
            "  /addpromo template sport_promo\n"
            "  /addpromo template new_user\n\n"
            "Promo a intervalle:\n"
            "  /addpromo interval <freq> <heure> <message>\n"
            "  /addpromo interval 48h 11 Mon message ici\n"
            "  /addpromo interval 3d 18 Texte de la promo\n\n"
            "Promo sur jours specifiques:\n"
            "  /addpromo days <jours> <heure> <message>\n"
            "  /addpromo days weekends 12 Promo du weekend!\n"
            "  /addpromo days fri,sat 17 Match ce soir!\n"
            "  /addpromo days mon,wed,fri 10 Offre speciale\n\n"
            "Jours: mon,tue,wed,thu,fri,sat,sun\n"
            "Raccourcis: weekends, weekdays, daily\n"
            "Heure: 0-23 (heure locale UK/Ireland)"
        )
        await reply_private(update, context, help_text)
        return

    subcommand = context.args[0].lower()
    user_id = update.effective_user.id

    if subcommand == "template":
        template_key = context.args[1].lower()
        if template_key not in TEMPLATES:
            available = ", ".join(TEMPLATES.keys())
            await reply_private(update, context, f"Template inconnu: {template_key}\nDisponibles: {available}")
            return

        tpl = TEMPLATES[template_key]
        pid = add_promo(
            name=tpl["name"],
            message=tpl["message"],
            schedule_type=tpl["schedule_type"],
            interval_seconds=tpl.get("interval_seconds", 0),
            weekdays=tpl.get("weekdays", []),
            send_hour=tpl.get("send_hour", 10),
            created_by=user_id,
        )

        schedule_str = format_schedule(tpl)
        await reply_private(update, context,
            f"✅ Promo cree depuis template!\n\n"
            f"ID: {pid}\n"
            f"Nom: {tpl['name']}\n"
            f"Schedule: {schedule_str}\n\n"
            f"Message:\n{tpl['message'][:200]}\n\n"
            f"Utilisez /promos pour gerer vos campagnes."
        )
        logger.info(f"[PROMO] Campagne {pid} cree depuis template '{template_key}' par {user_id}")
        return

    if subcommand == "interval":
        if len(context.args) < 4:
            await reply_private(update, context, "Usage: /addpromo interval <freq> <heure> <message>\nExemple: /addpromo interval 48h 11 Mon message")
            return

        interval_str = context.args[1]
        interval_secs = parse_promo_interval(interval_str)
        if interval_secs is None:
            await reply_private(update, context, "Intervalle invalide. Utilisez: 30m, 12h, 48h, 2d, 1w...")
            return

        try:
            send_hour = int(context.args[2])
            if not (0 <= send_hour <= 23):
                raise ValueError
        except ValueError:
            await reply_private(update, context, "Heure invalide. Utilisez un nombre entre 0 et 23.")
            return

        message = " ".join(context.args[3:])
        auto_name = message[:30].strip()
        if len(message) > 30:
            auto_name += "..."

        pid = add_promo(
            name=auto_name,
            message=message,
            schedule_type="interval",
            interval_seconds=interval_secs,
            send_hour=send_hour,
            created_by=user_id,
        )

        await reply_private(update, context,
            f"✅ Promo cree!\n\n"
            f"ID: {pid}\n"
            f"Frequence: Every {interval_str}\n"
            f"Heure d'envoi: ~{send_hour}:00\n"
            f"Message: {message[:100]}"
        )
        logger.info(f"[PROMO] Campagne interval {pid} cree par {user_id}: every {interval_str} at {send_hour}h")
        return

    if subcommand == "days":
        if len(context.args) < 4:
            await reply_private(update, context, "Usage: /addpromo days <jours> <heure> <message>\nExemple: /addpromo days weekends 12 Ma promo")
            return

        days_str = context.args[1]
        weekdays = parse_weekdays(days_str)
        if weekdays is None:
            await reply_private(update, context,
                "Jours invalides.\n"
                "Utilisez: mon,tue,wed,thu,fri,sat,sun\n"
                "Raccourcis: weekends, weekdays, daily"
            )
            return

        try:
            send_hour = int(context.args[2])
            if not (0 <= send_hour <= 23):
                raise ValueError
        except ValueError:
            await reply_private(update, context, "Heure invalide. Utilisez un nombre entre 0 et 23.")
            return

        message = " ".join(context.args[3:])
        day_names = [WEEKDAY_NAMES.get(d, "?") for d in weekdays]
        auto_name = f"{','.join(day_names)} promo"

        pid = add_promo(
            name=auto_name,
            message=message,
            schedule_type="weekdays",
            weekdays=weekdays,
            send_hour=send_hour,
            created_by=user_id,
        )

        await reply_private(update, context,
            f"✅ Promo cree!\n\n"
            f"ID: {pid}\n"
            f"Jours: {', '.join(day_names)}\n"
            f"Heure d'envoi: ~{send_hour}:00\n"
            f"Message: {message[:100]}"
        )
        logger.info(f"[PROMO] Campagne weekdays {pid} cree par {user_id}: {','.join(day_names)} at {send_hour}h")
        return

    await reply_private(update, context, "Sous-commande inconnue. Utilisez: template, interval, ou days\nTapez /addpromo pour l'aide.")


async def editpromo_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/editpromo <id> <nouveau_message>"""
    if _is_duplicate_update(update):
        return
    if not is_admin(update.effective_user.id):
        await reply_private(update, context, "Non autorise (admin uniquement)")
        return

    if not context.args or len(context.args) < 2:
        await reply_private(update, context,
            "Usage: /editpromo <id> <nouveau_message>\n"
            "Exemple: /editpromo a3f2b1c9 Nouveau texte de la promo!"
        )
        return

    pid = context.args[0]
    new_message = " ".join(context.args[1:])

    if update_promo_message(pid, new_message):
        await reply_private(update, context, f"✅ Promo {pid} modifiee.\nNouveau message: {new_message[:100]}")
        logger.info(f"[PROMO] Campagne {pid} modifiee par {update.effective_user.id}")
    else:
        await reply_private(update, context, f"Promo {pid} introuvable.")


async def delpromo_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/delpromo <id>"""
    if _is_duplicate_update(update):
        return
    if not is_admin(update.effective_user.id):
        await reply_private(update, context, "Non autorise (admin uniquement)")
        return

    if not context.args:
        await reply_private(update, context, "Usage: /delpromo <id>")
        return

    pid = context.args[0]
    promo = get_promo(pid)
    if promo:
        delete_promo(pid)
        await reply_private(update, context, f"✅ Promo supprimee: {promo.get('name', pid)}")
        logger.info(f"[PROMO] Campagne {pid} supprimee par {update.effective_user.id}")
    else:
        await reply_private(update, context, f"Promo {pid} introuvable.")


async def promo_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Gere tous les callbacks des boutons inline du systeme promo."""
    query = update.callback_query
    await query.answer()

    data = query.data
    user_id = query.from_user.id

    if not is_admin(user_id):
        await query.edit_message_text("Non autorise.")
        return

    if data.startswith("promo_toggle_"):
        pid = data.replace("promo_toggle_", "")
        new_state = toggle_promo(pid)
        if new_state:
            emoji = "✅ Active" if new_state == "active" else "⏸️ En pause"
            promo = get_promo(pid)
            name = promo.get("name", pid) if promo else pid
            await query.edit_message_text(
                f"{emoji}: {name}\n\nUtilisez /promos pour voir le panel."
            )
            logger.info(f"[PROMO] Campagne {pid} -> {new_state} par {user_id}")
        else:
            await query.edit_message_text(f"Promo {pid} introuvable.")

    elif data.startswith("promo_preview_"):
        pid = data.replace("promo_preview_", "")
        promo = get_promo(pid)
        if promo:
            schedule_str = format_schedule(promo)
            preview = (
                f"👁 Preview — {promo.get('name', 'Sans nom')}\n"
                f"Schedule: {schedule_str}\n"
                f"Envois: {promo.get('times_sent', 0)}x\n"
                f"{'─' * 30}\n\n"
                f"{promo['message']}"
            )
            keyboard = [
                [
                    InlineKeyboardButton("⏸ Pause" if promo.get("active") else "▶️ Resume", callback_data=f"promo_toggle_{pid}"),
                    InlineKeyboardButton("🗑 Supprimer", callback_data=f"promo_confirm_delete_{pid}"),
                ],
                [InlineKeyboardButton("◀️ Retour", callback_data="promo_back")],
            ]
            await query.edit_message_text(preview, reply_markup=InlineKeyboardMarkup(keyboard))
        else:
            await query.edit_message_text(f"Promo {pid} introuvable.")

    elif data.startswith("promo_confirm_delete_"):
        pid = data.replace("promo_confirm_delete_", "")
        promo = get_promo(pid)
        if promo:
            keyboard = [
                [
                    InlineKeyboardButton("✅ Oui, supprimer", callback_data=f"promo_delete_{pid}"),
                    InlineKeyboardButton("❌ Annuler", callback_data="promo_back"),
                ],
            ]
            await query.edit_message_text(
                f"Supprimer la promo \"{promo.get('name', pid)}\" ?\nCette action est irreversible.",
                reply_markup=InlineKeyboardMarkup(keyboard),
            )

    elif data.startswith("promo_delete_"):
        pid = data.replace("promo_delete_", "")
        promo = get_promo(pid)
        name = promo.get("name", pid) if promo else pid
        if delete_promo(pid):
            await query.edit_message_text(f"🗑 Promo supprimee: {name}\n\nUtilisez /promos pour voir le panel.")
            logger.info(f"[PROMO] Campagne {pid} supprimee par {user_id} (via bouton)")
        else:
            await query.edit_message_text(f"Promo {pid} introuvable.")

    elif data == "promo_templates":
        lines = ["📋 Templates disponibles\n"]
        keyboard_rows = []

        for key, tpl in TEMPLATES.items():
            schedule_str = format_schedule(tpl)
            lines.append(f"🔹 {tpl['name']} ({schedule_str})")
            lines.append(f"   {tpl['message'][:50]}...")
            lines.append("")
            keyboard_rows.append([
                InlineKeyboardButton(f"✅ {tpl['name']}", callback_data=f"promo_use_tpl_{key}"),
            ])

        keyboard_rows.append([InlineKeyboardButton("◀️ Retour", callback_data="promo_back")])

        await query.edit_message_text(
            "\n".join(lines),
            reply_markup=InlineKeyboardMarkup(keyboard_rows),
        )

    elif data.startswith("promo_use_tpl_"):
        template_key = data.replace("promo_use_tpl_", "")
        if template_key not in TEMPLATES:
            await query.edit_message_text("Template introuvable.")
            return

        tpl = TEMPLATES[template_key]
        pid = add_promo(
            name=tpl["name"],
            message=tpl["message"],
            schedule_type=tpl["schedule_type"],
            interval_seconds=tpl.get("interval_seconds", 0),
            weekdays=tpl.get("weekdays", []),
            send_hour=tpl.get("send_hour", 10),
            created_by=user_id,
        )

        schedule_str = format_schedule(tpl)
        await query.edit_message_text(
            f"✅ Promo cree!\n\n"
            f"ID: {pid}\n"
            f"Nom: {tpl['name']}\n"
            f"Schedule: {schedule_str}\n\n"
            f"Utilisez /promos pour gerer vos campagnes.\n"
            f"Utilisez /editpromo {pid} <texte> pour modifier le message."
        )
        logger.info(f"[PROMO] Campagne {pid} cree depuis template '{template_key}' par {user_id} (via bouton)")

    elif data == "promo_help_add":
        help_text = (
            "✍️ Creer une promo custom\n\n"
            "Promo a intervalle:\n"
            "  /addpromo interval 48h 11 Votre message\n\n"
            "Promo sur jours specifiques:\n"
            "  /addpromo days weekends 12 Promo weekend!\n"
            "  /addpromo days fri,sat 18 Match ce soir!\n\n"
            "Raccourcis jours: weekends, weekdays, daily"
        )
        keyboard = [[InlineKeyboardButton("◀️ Retour", callback_data="promo_back")]]
        await query.edit_message_text(help_text, reply_markup=InlineKeyboardMarkup(keyboard))

    elif data == "promo_back":
        promos = load_promos()
        if not promos:
            await query.edit_message_text("Aucune campagne promo. Utilisez /promos pour commencer.")
            return

        lines = ["📢 Campagnes promotionnelles\n"]
        keyboard_rows = []

        for pid, pdata in promos.items():
            lines.append(format_promo_summary(pid, pdata))
            lines.append("")

            keyboard_rows.append([
                InlineKeyboardButton(
                    f"{'⏸' if pdata.get('active') else '▶️'} {pdata.get('name', pid)[:15]}",
                    callback_data=f"promo_toggle_{pid}"
                ),
                InlineKeyboardButton("👁", callback_data=f"promo_preview_{pid}"),
                InlineKeyboardButton("🗑", callback_data=f"promo_delete_{pid}"),
            ])

        keyboard_rows.append([
            InlineKeyboardButton("➕ Template", callback_data="promo_templates"),
            InlineKeyboardButton("✍️ Custom", callback_data="promo_help_add"),
        ])

        await query.edit_message_text(
            "\n".join(lines),
            reply_markup=InlineKeyboardMarkup(keyboard_rows),
        )


async def promo_worker(bot):
    """Tache de fond: envoyer les promos planifiees toutes les 60s."""
    while True:
        await asyncio.sleep(60)
        try:
            due = get_due_promos()
            for pid, data in due:
                try:
                    await bot.send_message(
                        chat_id=NEWS_DEST_CHANNEL,
                        text=data["message"],
                    )
                    mark_promo_sent(pid)
                    logger.info(f"[PROMO] Campagne {pid} '{data.get('name', '?')}' envoyee (total: {data.get('times_sent', 0) + 1}x)")
                except Exception as e:
                    logger.error(f"[PROMO] Erreur envoi campagne {pid}: {e}")
        except Exception as e:
            logger.error(f"[PROMO] Erreur worker: {e}")


async def reminder_worker(bot):
    """Tache de fond: envoyer les rappels echus"""
    while True:
        await asyncio.sleep(60)
        try:
            due = get_due_reminders()
            for rid, data in due:
                try:
                    await bot.send_message(chat_id=NEWS_DEST_CHANNEL, text=data["message"])
                    mark_sent(rid)
                    logger.info(f"[REMINDER] Rappel {rid} envoye")
                except Exception as e:
                    logger.error(f"[REMINDER] Erreur envoi rappel {rid}: {e}")
        except Exception as e:
            logger.error(f"[REMINDER] Erreur worker: {e}")


NEWS_POLL_INTERVAL = int(os.getenv("NEWS_POLL_INTERVAL", "7200"))  # 2h par defaut
CLAUDE_MAX_CALLS_PER_CYCLE = int(os.getenv("CLAUDE_MAX_CALLS_PER_CYCLE", "50"))  # Limite par cycle de poll
_claude_calls_total = 0


async def news_poll_worker():
    """Auto-import avec regroupement intelligent des messages."""
    global _claude_calls_total
    while True:
        await asyncio.sleep(NEWS_POLL_INTERVAL)
        if not HAS_USER_CLIENT or not user_client:
            continue
        try:
            logger.info("[NEWS-POLL] Debut du cycle d'import")
            cutoff = datetime.now() - timedelta(hours=3)
            pending_messages = []

            # Phase 1 : Collecter tous les nouveaux messages depuis TOUS les canaux sources
            for source_channel in NEWS_SOURCE_CHANNELS:
                try:
                    async for message in user_client.get_chat_history(source_channel):
                        if message.date.replace(tzinfo=None) < cutoff:
                            break
                        text = message.text or message.caption or ""
                        if not text.strip():
                            continue
                        # Dedup niveau 1 : message source deja vu ?
                        if news_cache.is_source_seen(source_channel, message.id):
                            continue
                        # Dedup niveau 2 : contenu deja vu (autre canal) ?
                        chash = compute_content_hash(text)
                        if news_cache.is_content_seen(chash):
                            logger.info(f"[NEWS-POLL] [DEDUP-CONTENT] {source_channel}:{message.id} doublon de contenu — skip")
                            news_cache.mark_source_seen(source_channel, message.id)
                            continue
                        pending_messages.append({
                            "id": message.id,
                            "channel_id": source_channel,
                            "content_hash": chash,
                            "text": text,
                            "has_photo": bool(message.photo),
                            "message": message,
                            "date": message.date,
                        })
                except Exception as e:
                    logger.error(f"[NEWS-POLL] Erreur collecte canal {source_channel}: {e}")
                    continue

            if not pending_messages:
                logger.info("[NEWS-POLL] Aucun nouveau message")
                continue

            # Phase 2 : Regrouper les messages proches (< 30 min d'ecart)
            pending_messages.sort(key=lambda m: m["date"])
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
                    # Batch : 3+ messages proches → synthese unique
                    texts = [m["text"] for m in group]
                    result = await process_message_batch(texts)

                    if result and result["should_forward"] and result.get("confidence", 0) >= CONFIDENCE_THRESHOLD:
                        await telegram_bot.send_message(
                            chat_id=NEWS_DEST_CHANNEL,
                            text=result["rewritten_message"]
                        )
                        imported += 1
                        health.last_news_forwarded = time.time()
                        logger.info(f"[NEWS-POLL] Batch de {len(group)} messages envoye [{result['category']}]")

                    for m in group:
                        news_cache.mark_source_seen(m["channel_id"], m["id"])
                        news_cache.mark_content_seen(m["content_hash"])
                    await asyncio.sleep(1.5)

                else:
                    # Traitement individuel (1-2 messages)
                    for m in group:
                        should_fwd, modified_text, category = await process_news_message(m["text"])

                        if should_fwd and modified_text:
                            if m["has_photo"]:
                                try:
                                    photo_path = await m["message"].download()
                                    with open(photo_path, 'rb') as photo_file:
                                        await telegram_bot.send_photo(
                                            chat_id=NEWS_DEST_CHANNEL,
                                            photo=photo_file,
                                            caption=modified_text
                                        )
                                    os.remove(photo_path)
                                except Exception as e:
                                    logger.error(f"[NEWS-POLL] Erreur photo: {e}")
                                    await telegram_bot.send_message(
                                        chat_id=NEWS_DEST_CHANNEL,
                                        text=modified_text
                                    )
                            else:
                                await telegram_bot.send_message(
                                    chat_id=NEWS_DEST_CHANNEL,
                                    text=modified_text
                                )
                            imported += 1
                            health.last_news_forwarded = time.time()
                            logger.info(f"[NEWS-POLL] Transfere msg {m['id']} [{category}]")

                        news_cache.mark_source_seen(m["channel_id"], m["id"])
                        news_cache.mark_content_seen(m["content_hash"])
                        await asyncio.sleep(1.5 if should_fwd else 0.5)

            logger.info(f"[NEWS-POLL] Cycle termine: {imported} envoye(s) depuis {len(pending_messages)} message(s) | appels Claude total: {_claude_calls_total}")

        except Exception as e:
            logger.error(f"[NEWS-POLL] Erreur: {e}")


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

        # Verifier l'acces a CHAQUE canal source
        accessible_channels = []
        for source_channel in NEWS_SOURCE_CHANNELS:
            try:
                chat = await user_client.get_chat(source_channel)
                logger.info(f"Canal source accessible: {chat.title} (id={chat.id})")
                try:
                    member = await user_client.get_chat_member(source_channel, "me")
                    logger.info(f"  -> Statut: {member.status}")
                    accessible_channels.append(source_channel)
                except Exception as e:
                    logger.warning(f"  -> Impossible de verifier le statut membre: {e}")
                    accessible_channels.append(source_channel)
            except Exception as e:
                logger.error(f"IMPOSSIBLE d'acceder au canal source {source_channel}: {e}")
                logger.error("Le compte doit etre ABONNE a ce canal pour recevoir les updates!")

        if not accessible_channels:
            logger.critical("AUCUN canal source accessible — le transfert de news ne fonctionnera pas!")

        logger.info(f"Ecoute {len(accessible_channels)}/{len(NEWS_SOURCE_CHANNELS)} canal(aux) source(s)")
        logger.info(f"Destination news: {NEWS_DEST_CHANNEL}")
        logger.info(f"Pyrogram dispatcher actif: {user_client.is_connected}")
        logger.info(f"Handlers Pyrogram enregistres: {len(user_client.dispatcher.groups)}")

        # Demarrer la file d'attente news
        await news_queue.start()

        # Auto-resume du stream precedent si applicable
        await auto_resume_stream()

        # Lancer le watchdog en tache de fond
        asyncio.create_task(stream_watchdog())

        # Lancer le polling auto des news toutes les 2h
        asyncio.create_task(news_poll_worker())
        logger.info(f"[NEWS-POLL] Auto-import actif (toutes les {NEWS_POLL_INTERVAL}s)")

        if ANTHROPIC_API_KEY:
            logger.info("[CLAUDE] API Claude configuree — traitement intelligent des news actif")
        else:
            logger.warning("[CLAUDE] ANTHROPIC_API_KEY absente — fallback regex uniquement")
    else:
        logger.warning("Mode commandes uniquement (pas de streaming/news)")

    # Lancer le worker de rappels (independant du user_client)
    asyncio.create_task(reminder_worker(application.bot))

    # Lancer le worker de campagnes promotionnelles
    asyncio.create_task(promo_worker(application.bot))
    logger.info("[PROMO] Worker de campagnes promotionnelles actif")

    logger.info(f"Groupe cible: @{CHAT_ID}")

    # Démarrer le health check HTTP
    health_port = int(os.getenv("HEALTH_PORT", "8080"))
    await health.start(port=health_port)


async def main():
    """Boucle principale — gere PTB et Pyrogram dans le meme event loop."""
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
    application.add_handler(CommandHandler("announcement", announcement_command))
    application.add_handler(CommandHandler("reminder", reminder_command))
    application.add_handler(CommandHandler("reminders", reminders_list_command))
    application.add_handler(CommandHandler("delreminder", delreminder_command))
    application.add_handler(CommandHandler("testlistener", testlistener_command))
    application.add_handler(CommandHandler("dev", dev_command))
    application.add_handler(CommandHandler("promos", promos_command))
    application.add_handler(CommandHandler("addpromo", addpromo_command))
    application.add_handler(CommandHandler("editpromo", editpromo_command))
    application.add_handler(CommandHandler("delpromo", delpromo_command))
    application.add_handler(CallbackQueryHandler(promo_callback_handler, pattern="^promo_"))

    logger.info("Bot pret!")

    # Demarrer PTB SANS run_polling() — on gere la boucle nous-memes
    async with application:
        await application.start()
        await application.updater.start_polling(
            allowed_updates=["message", "callback_query"],
            drop_pending_updates=True
        )

        logger.info("Bot PTB demarre en mode polling manuel")
        logger.info("Pyrogram et PTB partagent la meme boucle asyncio")

        # Initialiser Pyrogram et les taches de fond (remplace post_init)
        try:
            await post_init(application)
        except Exception as e:
            logger.error(f"Erreur dans post_init: {e}")

        # Attendre indefiniment (SIGTERM/SIGINT pour arreter)
        stop_event = asyncio.Event()

        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, stop_event.set)
            except NotImplementedError:
                # Windows ne supporte pas add_signal_handler
                pass

        try:
            await stop_event.wait()
        except KeyboardInterrupt:
            pass

        logger.info("Arret en cours...")
        await application.updater.stop()
        await application.stop()

        # Arreter Pyrogram proprement
        if HAS_USER_CLIENT and user_client:
            await user_client.stop()
            logger.info("Client Pyrogram arrete")


if __name__ == "__main__":
    asyncio.run(main())
