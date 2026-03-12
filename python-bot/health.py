"""
BingeBear TV - Health Check HTTP
Endpoint /health pour le monitoring et le watchdog systemd
"""

import time
import logging
from aiohttp import web

logger = logging.getLogger('bingebear')


class HealthCheck:
    """Mini serveur HTTP pour exposer l'état du bot."""

    def __init__(self):
        self.bot_started = time.time()
        self.last_stream_activity = None
        self.is_streaming = False
        self.last_news_forwarded = None

    async def handle(self, request):
        """Retourne l'état du bot en JSON."""
        uptime = int(time.time() - self.bot_started)
        status = {
            'status': 'ok',
            'uptime_seconds': uptime,
            'is_streaming': self.is_streaming,
            'last_stream_activity': self.last_stream_activity,
            'last_news_forwarded': self.last_news_forwarded,
        }
        return web.json_response(status)

    async def start(self, port=8080):
        """Démarrer le serveur HTTP sur le port spécifié."""
        app = web.Application()
        app.router.add_get('/health', self.handle)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, '0.0.0.0', port)
        await site.start()
        logger.info(f"Health check HTTP demarre sur http://0.0.0.0:{port}/health")
