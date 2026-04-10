"""
Test du filtre de messages - Lit les messages depuis le 20 janvier
"""

import re
from datetime import datetime
from pyrogram import Client

API_ID = 33417585
API_HASH = "1fcac1db95bff35ca603b60c143f6856"
SESSION_STRING = "BAH96XEAu5_g3vKudB7zgPY2kfGRBqLuTZVF0qe6w8-VgqiYO0tg7OxK5vGLFa2Zpaqj2bfP8I-f0zDm5kDbC7uIBtdFokO0uje6C1ReRL9pg1j7jiTCvvnRPrfE2YgNgNgcMNK4q_YClpzWnQE787Pe-zniGnY8pMapmjCBZVfaM32ggR4vN5rWLBBlIzLGxpnB7x0sWxYD-1BM7JTYQQEaQ3qaEF6x5QEQGf2gVmd-HAsswmtkh1ty-PL2zN0HSlSr2dKAp36bBcEbnms5GhGt5-onckePU5pb9pBsJlQJzcB210nnfJGrUVFbq7onc-Lecw3O_UysevE4_jde6rx1IBvmFgAAAABb1DaJAA"

SOURCE_CHANNEL = -1001763758614

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

REPLACE_TO = "Team BingeBearTV"

app = Client(
    "test_filter",
    api_id=API_ID,
    api_hash=API_HASH,
    session_string=SESSION_STRING
)


def should_forward(text: str) -> bool:
    for exclude in EXCLUDE_WORDS:
        if exclude.lower() in text.lower():
            return False
    for pattern in PATTERNS:
        if re.search(pattern, text, re.IGNORECASE | re.MULTILINE):
            return True
    return False


def modify_message(text: str) -> str:
    # Supprimer les parties en espagnol
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
    async with app:
        print("=" * 60)
        print("Test du filtre - Messages depuis le 20 janvier 2026")
        print("=" * 60)

        date_limit = datetime(2026, 1, 20)

        matched = 0
        skipped = 0

        async for message in app.get_chat_history(SOURCE_CHANNEL, limit=100):
            if message.date < date_limit:
                continue

            text = message.text or message.caption or ""
            if not text:
                continue

            date_str = message.date.strftime("%d/%m %H:%M")

            if should_forward(text):
                matched += 1
                modified = modify_message(text)

                print(f"\n{'='*60}")
                print(f"✅ MATCH #{matched} - {date_str}")
                print(f"{'='*60}")
                print(f"MESSAGE MODIFIE:")
                print(modified[:400])
                print()
            else:
                skipped += 1
                print(f"[SKIP] {date_str} - {text[:50]}...")

        print(f"\n{'='*60}")
        print(f"RESUME:")
        print(f"  Messages qui seraient transferes: {matched}")
        print(f"  Messages ignores: {skipped}")
        print(f"{'='*60}")


app.run(main())
