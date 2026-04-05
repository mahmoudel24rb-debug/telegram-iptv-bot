"""
claude_processor.py — Traitement intelligent des messages news via Claude API.

Remplace le filtrage regex + les modifications texte manuelles.
Un seul appel API fait tout : decider si le message est pertinent,
le categoriser, et le reecrire dans le ton BingeBear.
"""

import os
import json
import logging
import asyncio
from anthropic import AsyncAnthropic, APIError, RateLimitError

logger = logging.getLogger('bingebear.claude')

# ── Client Claude (async) ──
_api_key = os.getenv("ANTHROPIC_API_KEY", "")
client = AsyncAnthropic(api_key=_api_key) if _api_key else None

# Seuil de confiance minimum pour transferer un message
CONFIDENCE_THRESHOLD = 0.7

SYSTEM_PROMPT = """Tu es l'assistant editorial de BingeBearTV, un service de streaming IPTV base en Irlande/UK.

Tu recois des messages bruts provenant du canal interne de notre fournisseur technique (destines aux revendeurs).
Ton role est de decider si un message doit etre transmis a nos utilisateurs finaux, et si oui, de le reecrire.

## REGLES DE DECISION (should_forward)

TRANSFERER (true) :
- Annonces de nouvelles chaines, bouquets, contenus ajoutes
- Evenements sportifs, matchs, evenements live
- Pannes serveur, maintenance, interruptions de service
- Mises a jour de statut (serveur en ligne, probleme resolu, etc.)
- Changements importants (URLs, apps, mises a jour)
- Toute info qui impacte l'experience utilisateur

NE PAS TRANSFERER (false) :
- Messages purement techniques destines aux revendeurs uniquement (configs panel, API credentials, instructions de gestion de comptes revendeur)
- Spam, messages en espagnol sans rapport avec le service
- Messages contenant "domain has been suspended", "purchase a private domain", "misuse and multiple complaints"
- Doublons evidents ou messages vides/tres courts sans contenu utile
- URLs de panels d'administration revendeur (cms-only.ru, panel login, etc.)
- Instructions specifiques aux revendeurs (creer des comptes, gerer des credits, configurer un panel)

## REGLES DE REECRITURE

1. "Dear Reseller(s)" -> "Dear Users" ou "Hi everyone" selon le ton
2. "Team 8K" / "8K" (comme nom de marque/signature) -> "BingeBearTV" ou "Team BingeBearTV"
3. Supprimer tout contenu en espagnol (bloc "Queridos Revendedores..." et similaire)
4. Supprimer les URLs de panels admin/revendeur (ex: cms-only.ru, panel links, downloader codes)
5. Simplifier le jargon technique pour les utilisateurs finaux (pas de "CPU error", "moving server" etc. — reformuler en langage simple)
6. Garder un ton professionnel mais amical et rassurant
7. Ajouter un emoji pertinent en debut de message selon la categorie :
   - 🔴 pour panne/maintenance
   - ✅ pour retour en ligne
   - 🆕 pour nouveau contenu
   - ⚽ pour evenement sportif
   - 📢 pour info generale
   - 📱 pour mise a jour d'app
8. Si c'est une panne : rassurer que l'equipe technique travaille dessus, ne pas donner de details techniques internes
9. Si c'est un retour en ligne : celebrer brievement, remercier pour la patience
10. Nettoyer les sauts de ligne excessifs (max 2 consecutifs)
11. Le message reecrit doit etre en ANGLAIS (meme si l'original est mal ecrit ou en franglais)
12. Terminer par "— Team BingeBearTV" si c'est une annonce formelle

## CATEGORIES
- "service_outage" : panne, maintenance, serveur down
- "service_restored" : retour en ligne, probleme resolu
- "new_content" : nouvelles chaines, bouquets, contenus
- "live_event" : match sportif, evenement live
- "app_update" : mise a jour d'app, changement technique cote utilisateur
- "general_info" : autre info pertinente pour les utilisateurs

## FORMAT DE REPONSE

Reponds UNIQUEMENT avec un objet JSON valide, sans markdown, sans backticks, sans explication. Exemple :

{"should_forward": true, "category": "service_outage", "confidence": 0.95, "rewritten_message": "🔴 Hi everyone,\\n\\nWe're currently experiencing a brief service interruption. Our technical team has identified the issue and is working on a fix right now.\\n\\nWe'll keep you updated. Thanks for your patience!\\n\\n— Team BingeBearTV", "reason": "Panne serveur annoncee — info critique pour les utilisateurs"}"""


async def process_message(raw_text: str) -> dict | None:
    """
    Envoie le message brut a Claude pour analyse et reecriture.

    Args:
        raw_text: Le texte brut du message du canal source

    Returns:
        dict avec should_forward, category, confidence, rewritten_message, reason
        None en cas d'erreur (API down, JSON invalide, etc.)
    """
    if not client:
        logger.error("[CLAUDE] ANTHROPIC_API_KEY non configuree — skip traitement")
        return None

    if not raw_text or len(raw_text.strip()) < 5:
        logger.debug("[CLAUDE] Message trop court, ignore")
        return None

    try:
        response = await client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": f"Analyse et reecris ce message du fournisseur :\n\n{raw_text}"
                }
            ]
        )

        # Extraire le texte de la reponse
        result_text = response.content[0].text

        # Parser le JSON — Claude peut parfois wrapper dans ```json
        cleaned = result_text.strip()
        if cleaned.startswith("```"):
            first_newline = cleaned.find("\n")
            if first_newline != -1:
                cleaned = cleaned[first_newline + 1:]
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3]
            cleaned = cleaned.strip()

        result = json.loads(cleaned)

        # Validation de la structure
        required_keys = {"should_forward", "rewritten_message", "category", "confidence"}
        missing = required_keys - set(result.keys())
        if missing:
            logger.error(f"[CLAUDE] Reponse incomplete, cles manquantes: {missing}")
            return None

        logger.info(
            f"[CLAUDE] Decision: forward={result['should_forward']} "
            f"| cat={result['category']} "
            f"| conf={result['confidence']:.0%} "
            f"| reason={result.get('reason', 'N/A')}"
        )

        return result

    except json.JSONDecodeError as e:
        logger.error(f"[CLAUDE] Reponse non-JSON: {e} — raw: {result_text[:200]}")
        return None
    except RateLimitError as e:
        logger.warning(f"[CLAUDE] Rate limit atteint, retry dans 30s: {e}")
        await asyncio.sleep(30)
        return None
    except APIError as e:
        logger.error(f"[CLAUDE] Erreur API: {e.status_code} — {e.message}")
        return None
    except Exception as e:
        logger.error(f"[CLAUDE] Erreur inattendue: {type(e).__name__}: {e}")
        return None


async def process_message_batch(messages: list[str]) -> dict | None:
    """
    Envoie un lot de messages a Claude pour qu'il produise un resume unique.
    Utile pour les sequences de mises a jour rapides (ex: panne avec 10 updates successives).

    Args:
        messages: Liste de textes bruts (ordonnes chronologiquement)

    Returns:
        dict avec should_forward, category, confidence, rewritten_message, reason
        None en cas d'erreur
    """
    if not client:
        logger.error("[CLAUDE] ANTHROPIC_API_KEY non configuree — skip traitement batch")
        return None

    if not messages:
        return None

    # Formater les messages comme une sequence numerotee
    numbered = "\n\n".join(
        f"[Message {i+1}/{len(messages)}] {text}"
        for i, text in enumerate(messages)
    )

    batch_prompt = (
        "Tu recois une SEQUENCE de messages envoyes a la suite dans le canal fournisseur. "
        "Ils concernent probablement le meme sujet (panne, maintenance, etc.). "
        "Produis UN SEUL message de synthese pour nos utilisateurs qui resume toute la sequence. "
        "Utilise le meme format JSON que d'habitude.\n\n"
        f"{numbered}"
    )

    try:
        response = await client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": batch_prompt}]
        )

        cleaned = response.content[0].text.strip()
        if cleaned.startswith("```"):
            first_newline = cleaned.find("\n")
            if first_newline != -1:
                cleaned = cleaned[first_newline + 1:]
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3]
            cleaned = cleaned.strip()

        result = json.loads(cleaned)

        required_keys = {"should_forward", "rewritten_message", "category", "confidence"}
        if required_keys - set(result.keys()):
            logger.error("[CLAUDE] Reponse batch incomplete")
            return None

        logger.info(
            f"[CLAUDE-BATCH] {len(messages)} messages -> 1 synthese "
            f"| cat={result['category']} | conf={result['confidence']:.0%}"
        )

        return result

    except Exception as e:
        logger.error(f"[CLAUDE-BATCH] Erreur: {type(e).__name__}: {e}")
        return None
