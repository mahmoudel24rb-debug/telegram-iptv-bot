"""
Script pour obtenir l'ID d'un canal/groupe Telegram
"""

from pyrogram import Client

API_ID = 33417585
API_HASH = "1fcac1db95bff35ca603b60c143f6856"
SESSION_STRING = "BAH96XEAu5_g3vKudB7zgPY2kfGRBqLuTZVF0qe6w8-VgqiYO0tg7OxK5vGLFa2Zpaqj2bfP8I-f0zDm5kDbC7uIBtdFokO0uje6C1ReRL9pg1j7jiTCvvnRPrfE2YgNgNgcMNK4q_YClpzWnQE787Pe-zniGnY8pMapmjCBZVfaM32ggR4vN5rWLBBlIzLGxpnB7x0sWxYD-1BM7JTYQQEaQ3qaEF6x5QEQGf2gVmd-HAsswmtkh1ty-PL2zN0HSlSr2dKAp36bBcEbnms5GhGt5-onckePU5pb9pBsJlQJzcB210nnfJGrUVFbq7onc-Lecw3O_UysevE4_jde6rx1IBvmFgAAAABb1DaJAA"

# Lien d'invitation complet
INVITE_LINK = "https://t.me/+N11nZvKS8ABjOGM0"

app = Client(
    "get_id",
    api_id=API_ID,
    api_hash=API_HASH,
    session_string=SESSION_STRING
)


async def main():
    async with app:
        print("=" * 50)
        print("Tentative de rejoindre/trouver le groupe...")
        print("=" * 50)

        try:
            # Essayer de rejoindre via le lien d'invitation complet
            chat = await app.join_chat(INVITE_LINK)
            print(f"\n✅ Groupe rejoint!")
            print(f"Nom: {chat.title}")
            print(f"ID: {chat.id}")
            print(f"Type: {chat.type}")

        except Exception as e:
            error_msg = str(e).lower()
            print(f"Resultat: {e}")

            if "already" in error_msg or "user_already" in error_msg:
                print("\nDeja membre! Recherche dans les dialogs...")

                async for dialog in app.get_dialogs():
                    title = dialog.chat.title or ""
                    if "SERVICE INFORMATION" in title.upper() or "SERVICE" in title.upper():
                        print(f"\n✅ Groupe trouve!")
                        print(f"Nom: {dialog.chat.title}")
                        print(f"ID: {dialog.chat.id}")
                        print(f"Type: {dialog.chat.type}")
                        return

                print("\nGroupe non trouve dans les dialogs.")
                print("Affichage de tous les chats...")
                count = 0
                async for dialog in app.get_dialogs():
                    count += 1
                    title = dialog.chat.title or dialog.chat.first_name or "Sans nom"
                    print(f"  {count}. {title} (ID: {dialog.chat.id})")
                print(f"\nTotal: {count} chats")


app.run(main())
