"""
Test - Forward tous les messages valides depuis le 10 janvier
Inclut les images
"""

import re
import os
import asyncio
from datetime import datetime
from pyrogram import Client
from telegram import Bot

API_ID = 33417585
API_HASH = "1fcac1db95bff35ca603b60c143f6856"
SESSION_STRING = "BAH96XEAu5_g3vKudB7zgPY2kfGRBqLuTZVF0qe6w8-VgqiYO0tg7OxK5vGLFa2Zpaqj2bfP8I-f0zDm5kDbC7uIBtdFokO0uje6C1ReRL9pg1j7jiTCvvnRPrfE2YgNgNgcMNK4q_YClpzWnQE787Pe-zniGnY8pMapmjCBZVfaM32ggR4vN5rWLBBlIzLGxpnB7x0sWxYD-1BM7JTYQQEaQ3qaEF6x5QEQGf2gVmd-HAsswmtkh1ty-PL2zN0HSlSr2dKAp36bBcEbnms5GhGt5-onckePU5pb9pBsJlQJzcB210nnfJGrUVFbq7onc-Lecw3O_UysevE4_jde6rx1IBvmFgAAAABb1DaJAA"
BOT_TOKEN = "8500861189:AAFWCj_tc2-jGt3PO-H3wafk9q5ilMBRTdQ"

SOURCE_CHANNEL = -1001763758614
DEST_CHANNEL = "@bingebeartv_live"

# Patterns pour filtrer
PATTERNS = [
    r"Dear Reseller,\s*\n\s*We are pleased",
    r"^[A-Z\s]+VS\s+[A-Z\s]+",
    r"^LIVE EVENT",
]

EXCLUDE_WORDS = [
    "domain has been suspended",
    "purchase a private domain",
    "misuse and multiple complaints",
    "Queridos Revendedores",
    "Nos complace",
]

REPLACE_TO = "Team BingeBearTV"

# Client Pyrogram pour lire les messages
user_client = Client(
    "test_forward",
    api_id=API_ID,
    api_hash=API_HASH,
    session_string=SESSION_STRING
)

# Bot Telegram pour envoyer
bot = Bot(token=BOT_TOKEN)


def should_forward(text: str) -> bool:
    for exclude in EXCLUDE_WORDS:
        if exclude.lower() in text.lower():
            return False
    for pattern in PATTERNS:
        if re.search(pattern, text, re.IGNORECASE | re.MULTILINE):
            return True
    return False


def modify_message(text: str) -> str:
    text = re.sub(
        r'Queridos Revendedores.*?(?=Enjoy\.|Team|$)',
        '',
        text,
        flags=re.DOTALL | re.IGNORECASE
    )
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = re.sub(r'Team\s*8K', REPLACE_TO, text, flags=re.IGNORECASE)
    return text.strip()


async def main():
    print("=" * 60)
    print("Test - Forward messages depuis le 10 janvier 2026")
    print("=" * 60)

    async with user_client:
        date_limit = datetime(2026, 1, 10)
        messages_to_send = []

        print("\nCollecte des messages...")

        # Collecter les messages qui correspondent au filtre
        async for message in user_client.get_chat_history(SOURCE_CHANNEL, limit=200):
            if message.date < date_limit:
                continue

            text = message.text or message.caption or ""
            if not text:
                continue

            if should_forward(text):
                messages_to_send.append({
                    "date": message.date,
                    "text": modify_message(text),
                    "has_photo": message.photo is not None,
                    "message": message
                })

        print(f"\n{len(messages_to_send)} messages trouves")

        # Trier par date (plus ancien en premier)
        messages_to_send.sort(key=lambda x: x["date"])

        if messages_to_send:
            print("\nMessages a envoyer:")
            for i, msg in enumerate(messages_to_send):
                photo_icon = "[IMG]" if msg["has_photo"] else "[TXT]"
                print(f"  {i+1}. {photo_icon} {msg['date'].strftime('%d/%m %H:%M')} - {msg['text'][:50]}...")

            print(f"\n{'='*60}")
            # Envoi automatique pour le test
            if True:
                print("\nEnvoi en cours...")

                for i, msg in enumerate(messages_to_send):
                    print(f"\n[{i+1}/{len(messages_to_send)}] Envoi du {msg['date'].strftime('%d/%m %H:%M')}...")

                    try:
                        if msg["has_photo"]:
                            # Telecharger et envoyer la photo
                            photo_path = await msg["message"].download()
                            with open(photo_path, 'rb') as photo_file:
                                await bot.send_photo(
                                    chat_id=DEST_CHANNEL,
                                    photo=photo_file,
                                    caption=msg["text"]
                                )
                            os.remove(photo_path)
                            print(f"  [IMG] Envoye avec image")
                        else:
                            # Envoyer juste le texte
                            await bot.send_message(
                                chat_id=DEST_CHANNEL,
                                text=msg["text"]
                            )
                            print(f"  [TXT] Envoye")

                        # Pause pour eviter le rate limit
                        await asyncio.sleep(2)

                    except Exception as e:
                        print(f"  ERREUR: {e}")

                print(f"\n{'='*60}")
                print(f"Termine! {len(messages_to_send)} messages envoyes vers {DEST_CHANNEL}")
        else:
            print("Aucun message a envoyer")


if __name__ == "__main__":
    asyncio.run(main())
