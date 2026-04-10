"""
BingeBear TV - Retry logic avec backoff exponentiel
Pour les appels réseau (API IPTV, Telegram, etc.)
"""

import asyncio
import functools
import logging
import requests

logger = logging.getLogger('bingebear')


async def retry_async(func, max_retries=3, base_delay=1, description='operation'):
    """Retry exponentiel pour les opérations async.

    Args:
        func: Callable async sans arguments (utiliser lambda ou functools.partial)
        max_retries: Nombre max de tentatives
        base_delay: Délai initial en secondes (doublé à chaque retry)
        description: Description pour les logs
    """
    for attempt in range(max_retries):
        try:
            return await func()
        except Exception as e:
            if attempt == max_retries - 1:
                logger.error(f"[RETRY] {description} echoue apres {max_retries} tentatives: {e}")
                raise
            delay = base_delay * (2 ** attempt)
            logger.warning(f"[RETRY] {description} tentative {attempt + 1}/{max_retries} echouee, retry dans {delay}s: {e}")
            await asyncio.sleep(delay)


def retry_sync(func, max_retries=3, base_delay=1, description='operation'):
    """Retry exponentiel pour les opérations synchrones (ex: requests.get).

    Args:
        func: Callable sync sans arguments
        max_retries: Nombre max de tentatives
        base_delay: Délai initial en secondes
        description: Description pour les logs
    """
    import time
    for attempt in range(max_retries):
        try:
            return func()
        except Exception as e:
            if attempt == max_retries - 1:
                logger.error(f"[RETRY] {description} echoue apres {max_retries} tentatives: {e}")
                raise
            delay = base_delay * (2 ** attempt)
            logger.warning(f"[RETRY] {description} tentative {attempt + 1}/{max_retries} echouee, retry dans {delay}s: {e}")
            time.sleep(delay)
