"""
BingeBear TV - Cache des messages news deja transferes
Evite les doublons apres un restart du bot
"""

import json
import os
import time
import logging

logger = logging.getLogger('bingebear')

# Chemin du fichier de cache
CACHE_FILE = os.getenv("NEWS_CACHE_FILE", os.path.join(os.path.dirname(__file__), "news_cache.json"))

# Nombre max de message_id a garder en cache
CACHE_MAX_SIZE = 500

# Duree de vie des entrees (7 jours)
CACHE_TTL_SECONDS = 7 * 24 * 3600


class NewsCache:
    """Cache persistant des message_id deja transferes."""

    def __init__(self):
        self._cache = {}  # {message_id_str: timestamp}
        self._load()

    def _load(self):
        """Charger le cache depuis le fichier JSON."""
        if not os.path.exists(CACHE_FILE):
            return

        try:
            with open(CACHE_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)

            now = time.time()
            # Filtrer les entrees perimees au chargement
            self._cache = {
                mid: ts for mid, ts in data.items()
                if now - ts < CACHE_TTL_SECONDS
            }
            logger.debug(f"Cache news charge: {len(self._cache)} entrees")
        except (json.JSONDecodeError, IOError) as e:
            logger.warning(f"Cache news corrompu, reinitialisation: {e}")
            self._cache = {}

    def _save(self):
        """Sauvegarder le cache dans le fichier JSON."""
        try:
            with open(CACHE_FILE, 'w', encoding='utf-8') as f:
                json.dump(self._cache, f)
        except IOError as e:
            logger.warning(f"Impossible de sauvegarder le cache news: {e}")

    def is_forwarded(self, message_id: int) -> bool:
        """Verifier si un message a deja ete transfere."""
        return str(message_id) in self._cache

    def mark_forwarded(self, message_id: int):
        """Marquer un message comme transfere."""
        self._cache[str(message_id)] = time.time()

        # Limiter la taille du cache (garder les plus recents)
        if len(self._cache) > CACHE_MAX_SIZE:
            sorted_items = sorted(self._cache.items(), key=lambda x: x[1])
            self._cache = dict(sorted_items[-CACHE_MAX_SIZE:])

        self._save()
