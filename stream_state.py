"""
BingeBear TV - Persistance de l'état du streaming
Sauvegarde/restaure la chaîne en cours pour auto-restart après un crash ou redémarrage
"""

import json
import os
import time
import logging

logger = logging.getLogger('bingebear')

# Chemin du fichier d'état (configurable via env)
STATE_FILE = os.getenv("STREAM_STATE_FILE", os.path.join(os.path.dirname(__file__), "stream_state.json"))

# Durée max avant de considérer l'état comme périmé (30 minutes)
STATE_MAX_AGE_SECONDS = int(os.getenv("STREAM_STATE_MAX_AGE", "1800"))


def save_state(channel: dict):
    """Sauvegarder l'état du stream en cours dans un fichier JSON."""
    state = {
        "channel": channel,
        "timestamp": time.time(),
    }
    try:
        with open(STATE_FILE, 'w', encoding='utf-8') as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
        logger.debug(f"Etat du stream sauvegarde: {channel.get('name', '?')}")
    except Exception as e:
        logger.warning(f"Impossible de sauvegarder l'etat du stream: {e}")


def load_state() -> dict | None:
    """Charger l'état précédent. Retourne le channel dict ou None si périmé/absent."""
    if not os.path.exists(STATE_FILE):
        return None

    try:
        with open(STATE_FILE, 'r', encoding='utf-8') as f:
            state = json.load(f)

        timestamp = state.get("timestamp", 0)
        age = time.time() - timestamp

        if age > STATE_MAX_AGE_SECONDS:
            logger.info(f"Etat precedent trop ancien ({int(age)}s > {STATE_MAX_AGE_SECONDS}s), ignore")
            clear_state()
            return None

        channel = state.get("channel")
        if channel and channel.get("url"):
            logger.info(f"Etat precedent trouve: {channel.get('name', '?')} (age: {int(age)}s)")
            return channel

        return None

    except (json.JSONDecodeError, KeyError) as e:
        logger.warning(f"Fichier d'etat corrompu, suppression: {e}")
        clear_state()
        return None


def clear_state():
    """Supprimer le fichier d'état (stream arrêté)."""
    try:
        if os.path.exists(STATE_FILE):
            os.remove(STATE_FILE)
            logger.debug("Fichier d'etat supprime")
    except Exception as e:
        logger.warning(f"Impossible de supprimer le fichier d'etat: {e}")
