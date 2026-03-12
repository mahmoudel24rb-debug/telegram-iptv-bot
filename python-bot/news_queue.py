"""
BingeBear TV - File d'attente pour l'envoi des news
Gere le rate-limiting Telegram (max ~30 msg/sec vers un canal)
"""

import asyncio
import logging
import time

logger = logging.getLogger('bingebear')

# Delai minimum entre deux envois (en secondes)
SEND_DELAY = 1.5


class NewsQueue:
    """File d'attente async pour envoyer les messages sans depasser le rate-limit."""

    def __init__(self):
        self._queue = asyncio.Queue()
        self._running = False
        self._last_send_time = 0

    async def start(self):
        """Demarrer le worker de la file d'attente."""
        if self._running:
            return
        self._running = True
        asyncio.create_task(self._worker())
        logger.debug("File d'attente news demarree")

    async def enqueue(self, send_func):
        """Ajouter une fonction d'envoi a la file.

        Args:
            send_func: Coroutine sans arguments qui effectue l'envoi
        """
        await self._queue.put(send_func)
        logger.debug(f"Message ajoute a la file ({self._queue.qsize()} en attente)")

    async def _worker(self):
        """Worker qui traite la file avec respect du rate-limit."""
        while self._running:
            try:
                send_func = await self._queue.get()

                # Respecter le delai minimum entre envois
                elapsed = time.time() - self._last_send_time
                if elapsed < SEND_DELAY:
                    await asyncio.sleep(SEND_DELAY - elapsed)

                try:
                    await send_func()
                    self._last_send_time = time.time()
                except Exception as e:
                    # En cas d'erreur rate-limit (429), attendre plus longtemps
                    if "429" in str(e) or "Too Many Requests" in str(e):
                        logger.warning(f"Rate-limit Telegram detecte, attente 30s...")
                        await asyncio.sleep(30)
                        # Re-essayer une fois
                        try:
                            await send_func()
                            self._last_send_time = time.time()
                        except Exception as retry_e:
                            logger.error(f"Echec apres retry rate-limit: {retry_e}")
                    else:
                        logger.error(f"Erreur envoi news depuis la file: {e}")

                self._queue.task_done()

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Erreur worker file news: {e}")
                await asyncio.sleep(1)
