"""
dev_mode.py — Wrapper de preview pour les commandes admin.

Permet d'executer n'importe quelle commande qui post dans le canal
en redirigeant la sortie vers le DM de l'admin, sans modifier d'etat.
"""
import logging

logger = logging.getLogger(__name__)

DEV_PREFIX = "🧪 [DEV PREVIEW]\n\n"


class PreviewBot:
    """
    Wrapper autour d'un bot Telegram qui redirige les envois vers un DM admin.

    Intercepte:
      - send_message(chat_id=..., text=...)
      - send_photo(chat_id=..., photo=..., caption=...)

    Si chat_id correspond a NEWS_DEST_CHANNEL ou CHAT_ID -> redirige vers admin_id.
    Sinon -> passe au vrai bot.
    """

    def __init__(self, real_bot, admin_id: int, redirect_targets: set):
        self._bot = real_bot
        self._admin_id = admin_id
        self._targets = redirect_targets
        self.intercepted_count = 0

    def _should_redirect(self, chat_id) -> bool:
        """Verifie si ce chat_id est une cible a intercepter."""
        if chat_id in self._targets:
            return True
        if isinstance(chat_id, str):
            stripped = chat_id.lstrip("@").lower()
            return any(
                isinstance(t, str) and t.lstrip("@").lower() == stripped
                for t in self._targets
            )
        return False

    async def send_message(self, chat_id, text, **kwargs):
        if self._should_redirect(chat_id):
            self.intercepted_count += 1
            preview_text = f"{DEV_PREFIX}{text}"
            if len(preview_text) > 4096:
                preview_text = preview_text[:4090] + "\n[...]"
            return await self._bot.send_message(
                chat_id=self._admin_id,
                text=preview_text,
                **kwargs
            )
        return await self._bot.send_message(chat_id=chat_id, text=text, **kwargs)

    async def send_photo(self, chat_id, photo, caption=None, **kwargs):
        if self._should_redirect(chat_id):
            self.intercepted_count += 1
            preview_caption = f"{DEV_PREFIX}{caption or ''}"
            if len(preview_caption) > 1024:
                preview_caption = preview_caption[:1018] + "\n[...]"
            return await self._bot.send_photo(
                chat_id=self._admin_id,
                photo=photo,
                caption=preview_caption,
                **kwargs
            )
        return await self._bot.send_photo(
            chat_id=chat_id, photo=photo, caption=caption, **kwargs
        )

    def __getattr__(self, name):
        return getattr(self._bot, name)


class DevContext:
    """
    Wrapper minimal autour de context pour remplacer context.bot par PreviewBot
    tout en gardant tout le reste intact.
    """
    def __init__(self, real_context, preview_bot: PreviewBot):
        self._ctx = real_context
        self.bot = preview_bot

    def __getattr__(self, name):
        return getattr(self._ctx, name)
