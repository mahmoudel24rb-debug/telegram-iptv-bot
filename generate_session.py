"""
Générateur de session string pour Pyrogram
Exécutez ce script une seule fois en local pour obtenir votre SESSION_STRING
"""

import asyncio
from pyrogram import Client

API_ID = 33417585
API_HASH = "1fcac1db95bff35ca603b60c143f6856"

async def main():
    print("=" * 50)
    print("Generateur de Session String pour BingeBear TV")
    print("=" * 50)
    print()
    print("Vous allez recevoir un code sur Telegram.")
    print("Entrez-le quand demande.")
    print()

    async with Client("session_generator", api_id=API_ID, api_hash=API_HASH) as app:
        session_string = await app.export_session_string()

        print()
        print("=" * 50)
        print("VOTRE SESSION STRING (copiez TOUT):")
        print("=" * 50)
        print()
        print(session_string)
        print()
        print("=" * 50)
        print()
        print("IMPORTANT: Gardez cette session string secrete!")
        print("Ajoutez-la dans les variables Railway sous le nom SESSION_STRING")
        print()

if __name__ == "__main__":
    asyncio.run(main())
