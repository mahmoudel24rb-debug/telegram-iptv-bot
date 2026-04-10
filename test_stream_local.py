"""
Test stream local pour debugger le problème audio
"""
import os
import asyncio
from dotenv import load_dotenv

from pyrogram import Client
from pytgcalls import PyTgCalls
from pytgcalls.types import MediaStream, AudioQuality, VideoQuality

load_dotenv()

API_ID = int(os.getenv("API_ID", "33417585"))
API_HASH = os.getenv("API_HASH", "1fcac1db95bff35ca603b60c143f6856")
SESSION_STRING = os.getenv("SESSION_STRING", "BAH96XEAu5_g3vKudB7zgPY2kfGRBqLuTZVF0qe6w8-VgqiYO0tg7OxK5vGLFa2Zpaqj2bfP8I-f0zDm5kDbC7uIBtdFokO0uje6C1ReRL9pg1j7jiTCvvnRPrfE2YgNgNgcMNK4q_YClpzWnQE787Pe-zniGnY8pMapmjCBZVfaM32ggR4vN5rWLBBlIzLGxpnB7x0sWxYD-1BM7JTYQQEaQ3qaEF6x5QEQGf2gVmd-HAsswmtkh1ty-PL2zN0HSlSr2dKAp36bBcEbnms5GhGt5-onckePU5pb9pBsJlQJzcB210nnfJGrUVFbq7onc-Lecw3O_UysevE4_jde6rx1IBvmFgAAAABb1DaJAA")
CHAT_ID = os.getenv("CHAT_ID", "bingebeartv_live")

# IPTV Config
IPTV_SERVER = os.getenv("IPTV_SERVER_URL", "http://cf.business-cdn-8k.ru")
IPTV_USER = os.getenv("IPTV_USERNAME", "fd99f6f6e43e")
IPTV_PASS = os.getenv("IPTV_PASSWORD", "5eb99b6e81")

# Test avec une chaine specifique - change l'ID si besoin
CHANNEL_ID = "292499"  # Change cet ID pour tester une autre chaine

user_client = Client(
    "test_stream_session",
    api_id=API_ID,
    api_hash=API_HASH,
    session_string=SESSION_STRING
)


async def on_stream_end(client, update):
    print(f"[PYTGCALLS EVENT] Stream ended: {update}")


async def on_closed_voice_chat(client, update):
    print(f"[PYTGCALLS EVENT] Voice chat closed: {update}")


async def on_kicked(client, update):
    print(f"[PYTGCALLS EVENT] Kicked: {update}")


async def on_left(client, update):
    print(f"[PYTGCALLS EVENT] Left: {update}")


async def main():
    print("=" * 60)
    print("Test Stream Local - Debug Audio")
    print("=" * 60)

    # URL du stream
    stream_url = f"{IPTV_SERVER}/live/{IPTV_USER}/{IPTV_PASS}/{CHANNEL_ID}.ts"
    print(f"\nURL: {stream_url}")

    await user_client.start()
    me = await user_client.get_me()
    print(f"Connecte: {me.first_name}")

    pytgcalls = PyTgCalls(user_client)

    # Ajouter des handlers pour les events
    pytgcalls.on_stream_end()(on_stream_end)
    pytgcalls.on_closed_voice_chat()(on_closed_voice_chat)
    pytgcalls.on_kicked()(on_kicked)
    pytgcalls.on_left()(on_left)

    await pytgcalls.start()
    print("PyTgCalls demarre")

    print(f"\nDemarrage du stream vers @{CHAT_ID}...")

    try:
        await pytgcalls.play(
            CHAT_ID,
            MediaStream(
                stream_url,
                audio_parameters=AudioQuality.STUDIO,
                video_parameters=VideoQuality.HD_720p,
                ffmpeg_parameters="-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 -analyzeduration 10000000 -probesize 10000000 -fflags +genpts"
            )
        )
        print("\n[OK] Stream demarre!")
        print("\nRegarde les logs ci-dessous pour voir les erreurs...")
        print("Appuie sur Ctrl+C pour arreter\n")
        print("-" * 60)

        # Garder le script en vie et afficher un timer
        seconds = 0
        while True:
            await asyncio.sleep(10)
            seconds += 10
            print(f"[{seconds}s] Stream en cours...")

    except KeyboardInterrupt:
        print("\nArret...")
    except Exception as e:
        print(f"\n[ERREUR] {e}")
    finally:
        await pytgcalls.leave_call(CHAT_ID)
        await user_client.stop()
        print("Termine")


if __name__ == "__main__":
    asyncio.run(main())
