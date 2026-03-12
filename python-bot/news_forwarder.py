"""
BingeBear TV - News Forwarder (standalone)
Extrait les news IPTV d'un canal source et les envoie vers notre canal via le bot
Supporte texte + images, cache anti-doublons et file d'attente rate-limit
"""

import os
import re
import asyncio
from dotenv import load_dotenv
from pyrogram import Client, filters
from pyrogram.types import Message
from telegram import Bot
from logger import setup_logger
from news_cache import NewsCache
from news_queue import NewsQueue

# Charger les variables d'environnement
load_dotenv()

# Logger structuré
logger = setup_logger('bingebear.forwarder')

API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
SESSION_STRING = os.getenv("SESSION_STRING")
BOT_TOKEN = os.getenv("BOT_TOKEN")

# Configuration des canaux (configurable via .env)
SOURCE_CHANNEL = int(os.getenv("NEWS_SOURCE_CHANNEL", "-1001763758614"))
DEST_CHANNEL = os.getenv("NEWS_DEST_CHANNEL", "@bingebeartv_live")

# Patterns pour filtrer les messages (uniquement annonces en anglais)
PATTERNS = [
    r"Dear Reseller,\s*\n\s*We are pleased",  # Annonces de nouvelles chaînes/catégories
    r"^[A-Z\s]+VS\s+[A-Z\s]+",                 # Matchs (ex: GAETHJE VS PIMBLETT)
    r"^LIVE EVENT",                             # Événements live
]

# Mots à exclure (messages administratifs)
EXCLUDE_WORDS = [
    "domain has been suspended",
    "purchase a private domain",
    "misuse and multiple complaints",
    "Queridos Revendedores",
    "Nos complace",
]

# Remplacement de signature
REPLACE_TO = "Team BingeBearTV"

# Client utilisateur Pyrogram (pour écouter le canal source)
app = Client(
    "news_forwarder",
    api_id=API_ID,
    api_hash=API_HASH,
    session_string=SESSION_STRING
)

# Bot Telegram (pour envoyer les messages)
bot = Bot(token=BOT_TOKEN)

# Cache anti-doublons et file d'attente
news_cache = NewsCache()
news_queue = NewsQueue()


def should_forward(text: str) -> bool:
    """Vérifier si le message doit être transféré"""
    for exclude in EXCLUDE_WORDS:
        if exclude.lower() in text.lower():
            return False
    for pattern in PATTERNS:
        if re.search(pattern, text, re.IGNORECASE | re.MULTILINE):
            return True
    return False


def modify_message(text: str) -> str:
    """Modifier le message (remplacer la signature)"""
    # Supprimer les parties en espagnol
    text = re.sub(
        r'Queridos Revendedores.*?(?=Enjoy\.|Team|$)',
        '',
        text,
        flags=re.DOTALL | re.IGNORECASE
    )
    # Supprimer les lignes vides multiples
    text = re.sub(r'\n{3,}', '\n\n', text)
    # Remplacer Team 8K par Team BingeBearTV
    text = re.sub(r'Team\s*8K', REPLACE_TO, text, flags=re.IGNORECASE)
    return text.strip()


@app.on_message(filters.chat(SOURCE_CHANNEL))
async def forward_news(client: Client, message: Message):
    """Intercepter et transférer les messages filtrés (texte + images)"""

    text = message.text or message.caption or ""

    if not text:
        return

    # Verifier le cache anti-doublons
    if news_cache.is_forwarded(message.id):
        logger.debug(f"Message {message.id} deja transfere (cache), ignore")
        return

    # Vérifier si le message doit être transféré
    if should_forward(text):
        logger.info(f"Message news detecte! (id={message.id})")
        logger.debug(f"Apercu: {text[:100]}...")

        # Modifier le message
        modified_text = modify_message(text)

        # Verifier si le message contient une photo
        if message.photo:
            logger.info("Image detectee, telechargement...")
            photo_path = await message.download()

            async def send_photo():
                try:
                    with open(photo_path, 'rb') as photo_file:
                        await bot.send_photo(
                            chat_id=DEST_CHANNEL,
                            photo=photo_file,
                            caption=modified_text
                        )
                    logger.info(f"Image + texte envoyes vers {DEST_CHANNEL}")
                    news_cache.mark_forwarded(message.id)
                finally:
                    try:
                        os.remove(photo_path)
                    except OSError:
                        pass

            await news_queue.enqueue(send_photo)
        else:
            async def send_text():
                await bot.send_message(
                    chat_id=DEST_CHANNEL,
                    text=modified_text
                )
                logger.info(f"Message envoye vers {DEST_CHANNEL}")
                news_cache.mark_forwarded(message.id)

            await news_queue.enqueue(send_text)
    else:
        logger.debug("Message ignore")


async def main():
    """Fonction principale"""
    logger.info("=" * 50)
    logger.info("BingeBear TV - News Forwarder (standalone)")
    logger.info("=" * 50)
    logger.info(f"Canal source: {SOURCE_CHANNEL}")
    logger.info(f"Canal destination: {DEST_CHANNEL}")
    logger.info(f"Envoi via: @Bingebear_tv_bot")
    logger.info(f"Filtre: Annonces + Events (anglais)")
    logger.info(f"Remplacement: Team 8K -> {REPLACE_TO}")
    logger.info("=" * 50)

    # Demarrer la file d'attente
    await news_queue.start()

    me = await app.get_me()
    logger.info(f"Lecture via: {me.first_name} (@{me.username})")
    logger.info("En attente de nouveaux messages...")


app.run(main())
