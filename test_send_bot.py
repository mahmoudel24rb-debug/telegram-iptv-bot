"""
Test - Envoie les messages avec le Bot BingeBear TV
"""

import re
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
    "test_read",
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
    print("Test - Envoi via Bot BingeBear TV")
    print("=" * 60)

    async with user_client:
        date_limit = datetime(2026, 1, 20)
        messages_to_send = []

        # Collecter les messages qui correspondent au filtre
        async for message in user_client.get_chat_history(SOURCE_CHANNEL, limit=50):
            if message.date < date_limit:
                continue

            text = message.text or message.caption or ""
            if not text:
                continue

            if should_forward(text):
                modified = modify_message(text)
                messages_to_send.append({
                    "date": message.date,
                    "text": modified
                })

        print(f"\n{len(messages_to_send)} messages trouves")

        if messages_to_send:
            # Envoyer seulement le premier message pour test
            msg = messages_to_send[0]
            print(f"\nEnvoi du message du {msg['date'].strftime('%d/%m %H:%M')}...")
            print(f"Apercu: {msg['text'][:100]}...")

            try:
                await bot.send_message(
                    chat_id=DEST_CHANNEL,
                    text=msg['text']
                )
                print(f"\n✅ Message envoye via @Bingebear_tv_bot!")
                print(f"Verifiez dans {DEST_CHANNEL}")
            except Exception as e:
                print(f"\n❌ Erreur: {e}")
                print("\nAssurez-vous que le bot est admin du canal avec permission de poster!")
        else:
            print("Aucun message a envoyer")


if __name__ == "__main__":
    asyncio.run(main())
