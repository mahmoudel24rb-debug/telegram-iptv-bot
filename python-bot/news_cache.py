"""
BingeBear TV - Cache des messages news deja transferes
Double deduplication :
  1. Par (channel_id, message_id) : evite de retraiter le meme message source
  2. Par hash de contenu          : evite les doublons entre plusieurs canaux sources

Migration automatique depuis l'ancien format (dict plat {message_id: timestamp}).
"""

import json
import os
import time
import re
import hashlib
import logging

logger = logging.getLogger('bingebear')

# Chemin du fichier de cache
CACHE_FILE = os.getenv("NEWS_CACHE_FILE", os.path.join(os.path.dirname(__file__), "news_cache.json"))

# Nombre max d'entrees par index (double car on a maintenant 2 sources potentielles)
CACHE_MAX_SIZE = 1000

# Duree de vie des entrees (7 jours)
CACHE_TTL_SECONDS = 7 * 24 * 3600


def normalize_text_for_hash(text: str) -> str:
    """
    Normalise un texte pour comparaison de contenu entre canaux.
    Supprime URLs, ponctuation, casse, espaces multiples, et mots de bruit recurrents.
    """
    if not text:
        return ""
    t = text.lower()
    # Retirer URLs (souvent les seuls trucs qui changent entre 2 reposts)
    t = re.sub(r'https?://\S+', '', t)
    # Retirer ponctuation
    t = re.sub(r'[^\w\s]', ' ', t)
    # Retirer mots de bruit frequents
    noise = [
        'dear users', 'dear reseller', 'dear resellers',
        'team bingebeartv', 'bingebeartv', 'bingebear tv', 'bingebear',
    ]
    for n in noise:
        t = t.replace(n, '')
    # Whitespace multiples
    t = re.sub(r'\s+', ' ', t).strip()
    return t


def compute_content_hash(text: str) -> str:
    """
    Calcule un hash court du texte normalise.
    Retourne '' si le texte normalise fait moins de 20 caracteres
    (en dessous de ce seuil, le hash n'est pas fiable — trop de faux positifs).
    """
    norm = normalize_text_for_hash(text)
    if len(norm) < 20:
        return ""
    return hashlib.md5(norm.encode('utf-8')).hexdigest()[:16]


class NewsCache:
    """Cache persistant a double index."""

    def __init__(self):
        self._by_source = {}  # {"channel_id:msg_id": timestamp}
        self._by_hash = {}    # {"hash": timestamp}
        self._load()

    def _load(self):
        """Charger le cache depuis le fichier JSON, avec migration auto si ancien format."""
        if not os.path.exists(CACHE_FILE):
            return

        try:
            with open(CACHE_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)

            now = time.time()

            # Migration depuis l'ancien format (dict plat {message_id: timestamp})
            if isinstance(data, dict) and "by_source" not in data and "by_hash" not in data:
                logger.info("Migration du cache news vers le nouveau format a double index")
                self._by_source = {
                    f"legacy:{mid}": ts for mid, ts in data.items()
                    if now - ts < CACHE_TTL_SECONDS
                }
                self._by_hash = {}
                self._save()
                return

            # Nouveau format
            self._by_source = {
                k: v for k, v in data.get("by_source", {}).items()
                if now - v < CACHE_TTL_SECONDS
            }
            self._by_hash = {
                k: v for k, v in data.get("by_hash", {}).items()
                if now - v < CACHE_TTL_SECONDS
            }
            logger.debug(
                f"Cache news charge : {len(self._by_source)} sources, {len(self._by_hash)} hashs"
            )
        except (json.JSONDecodeError, IOError) as e:
            logger.warning(f"Cache news corrompu, reinitialisation : {e}")
            self._by_source = {}
            self._by_hash = {}

    def _save(self):
        """Sauvegarder le cache dans le fichier JSON."""
        try:
            with open(CACHE_FILE, 'w', encoding='utf-8') as f:
                json.dump({
                    "by_source": self._by_source,
                    "by_hash": self._by_hash,
                }, f)
        except IOError as e:
            logger.warning(f"Impossible de sauvegarder le cache news : {e}")

    def _trim(self, d: dict) -> dict:
        """Limite la taille d'un index aux N entrees les plus recentes."""
        if len(d) <= CACHE_MAX_SIZE:
            return d
        sorted_items = sorted(d.items(), key=lambda x: x[1])
        return dict(sorted_items[-CACHE_MAX_SIZE:])

    # ========== Index 1 : par message source (channel_id, msg_id) ==========

    def is_source_seen(self, channel_id: int, message_id: int) -> bool:
        """Vrai si ce message d'origine a deja ete vu."""
        return f"{channel_id}:{message_id}" in self._by_source

    def mark_source_seen(self, channel_id: int, message_id: int):
        """Marque un message source comme vu et persiste."""
        self._by_source[f"{channel_id}:{message_id}"] = time.time()
        self._by_source = self._trim(self._by_source)
        self._save()

    # ========== Index 2 : par hash de contenu ==========

    def is_content_seen(self, content_hash: str) -> bool:
        """
        Vrai si ce contenu a deja ete envoye.
        Hash vide → toujours False (pas de dedup pour textes trop courts ou vides).
        """
        if not content_hash:
            return False
        return content_hash in self._by_hash

    def mark_content_seen(self, content_hash: str):
        """Marque un contenu comme envoye et persiste. No-op si hash vide."""
        if not content_hash:
            return
        self._by_hash[content_hash] = time.time()
        self._by_hash = self._trim(self._by_hash)
        self._save()

    # ========== Compatibilite avec l'ancien code (DEPRECATED) ==========

    def is_forwarded(self, message_id: int) -> bool:
        """DEPRECATED : utiliser is_source_seen(channel_id, message_id) a la place."""
        return f"legacy:{message_id}" in self._by_source

    def mark_forwarded(self, message_id: int):
        """DEPRECATED : utiliser mark_source_seen(channel_id, message_id) a la place."""
        self._by_source[f"legacy:{message_id}"] = time.time()
        self._by_source = self._trim(self._by_source)
        self._save()
