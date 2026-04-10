"""Test rapide de l'integration Claude API."""
import asyncio
import os
from dotenv import load_dotenv

load_dotenv()

from claude_processor import process_message, process_message_batch

# Test 1 : Message de panne (devrait etre transfere)
TEST_OUTAGE = "Dear Reseller Our main server down we are checking what problem"

# Test 2 : Message de nouvelle chaine (devrait etre transfere)
TEST_NEW_CHANNEL = """Dear Reseller,

We are pleased to launch the New Category

TR| S SPORT+ PPV

This package contains 10 channels.
All channels will receive daily updates for live event !

Enjoy.
Team 8K

Queridos Revendedores,
Nos complace lanzar la nueva categoria..."""

# Test 3 : Message spam (ne devrait PAS etre transfere)
TEST_SPAM = "Your domain has been suspended due to misuse and multiple complaints"

# Test 4 : Message technique revendeur (ne devrait PAS etre transfere)
TEST_RESELLER = "please use only https://8k.cms-only.ru/index more link will be done Soon"

# Test 5 : Batch de messages de panne
TEST_BATCH = [
    "Dear Reseller Our main server down we are checking what problem",
    "we see there cpu error will try to put online fast until we replace.",
    "We have brought the main server back online. Replacing the CPU is not easy.",
    "system online now and panel https://8k.cms-only.ru/index",
]


async def run_tests():
    print("=" * 60)
    print("TEST CLAUDE PROCESSOR")
    print("=" * 60)

    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key:
        print("\n  ERREUR: ANTHROPIC_API_KEY non configuree dans .env")
        print("  Ajoutez votre cle API dans le fichier .env")
        return

    tests = [
        ("Panne serveur", TEST_OUTAGE, True),
        ("Nouvelle chaine", TEST_NEW_CHANNEL, True),
        ("Spam", TEST_SPAM, False),
        ("Technique revendeur", TEST_RESELLER, False),
    ]

    for name, text, expected_forward in tests:
        print(f"\n--- {name} ---")
        result = await process_message(text)

        if result is None:
            print(f"  ERREUR: Pas de reponse Claude")
            continue

        status = "OK" if result["should_forward"] == expected_forward else "INATTENDU"
        print(f"  {status} forward={result['should_forward']} (attendu: {expected_forward})")
        print(f"  category={result['category']}")
        print(f"  confidence={result['confidence']:.0%}")
        print(f"  reason={result.get('reason', 'N/A')}")
        if result["rewritten_message"]:
            print(f"  message: {result['rewritten_message'][:150]}...")

    # Test batch
    print(f"\n--- Batch ({len(TEST_BATCH)} messages) ---")
    result = await process_message_batch(TEST_BATCH)
    if result:
        print(f"  forward={result['should_forward']}")
        print(f"  category={result['category']}")
        print(f"  confidence={result['confidence']:.0%}")
        if result["rewritten_message"]:
            print(f"  message:\n{result['rewritten_message']}")
    else:
        print("  ERREUR: Pas de reponse batch")


if __name__ == "__main__":
    asyncio.run(run_tests())
