"""
articles_feed.py — Recuperation et formatage des articles WordPress pour Telegram.

Source: API REST WordPress de bingebear.tv
Output: messages Telegram formates avec image, titre, extrait, lien.
"""
import os
import re
import json
import time
import logging
import asyncio
from typing import Optional
from datetime import datetime, timedelta
from html import unescape

import aiohttp

logger = logging.getLogger(__name__)

# Configuration depuis env
WP_API_BASE = os.getenv("WP_API_BASE", "https://bingebear.tv/wp-json/wp/v2")
WP_FEATURED_TAG_ID = os.getenv("WP_FEATURED_TAG_ID", "")
WP_EXCLUDE_TAG_ID = os.getenv("WP_EXCLUDE_TAG_ID", "")
ARTICLE_EXCERPT_MAX_CHARS = int(os.getenv("ARTICLE_EXCERPT_MAX_CHARS", "350"))
ARTICLE_CACHE_FILE = os.path.join(os.path.dirname(__file__), "articles_cache.json")
ARTICLE_CACHE_MAX_ENTRIES = 200
ARTICLE_CACHE_TTL_DAYS = 14
HTTP_TIMEOUT = 15


# ============================================================
# CACHE ANTI-DOUBLON
# ============================================================

def _load_cache() -> dict:
    if not os.path.exists(ARTICLE_CACHE_FILE):
        return {}
    try:
        with open(ARTICLE_CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"[ARTICLES] Cache illisible, recreation: {e}")
        return {}


def _save_cache(cache: dict):
    now = time.time()
    cutoff = now - (ARTICLE_CACHE_TTL_DAYS * 86400)
    cache = {k: v for k, v in cache.items() if v > cutoff}

    if len(cache) > ARTICLE_CACHE_MAX_ENTRIES:
        sorted_items = sorted(cache.items(), key=lambda x: x[1], reverse=True)
        cache = dict(sorted_items[:ARTICLE_CACHE_MAX_ENTRIES])

    try:
        with open(ARTICLE_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f)
    except Exception as e:
        logger.error(f"[ARTICLES] Erreur sauvegarde cache: {e}")


def is_article_seen(post_id: int) -> bool:
    cache = _load_cache()
    return str(post_id) in cache


def mark_article_seen(post_id: int):
    cache = _load_cache()
    cache[str(post_id)] = time.time()
    _save_cache(cache)


# ============================================================
# RECUPERATION VIA API REST
# ============================================================

async def _fetch_posts(params: dict) -> list:
    """Appel HTTP generique a l'API WP. Retourne liste de posts ou []."""
    url = f"{WP_API_BASE}/posts"
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=HTTP_TIMEOUT)) as session:
            async with session.get(url, params=params) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    logger.error(f"[ARTICLES] API WP statut {resp.status}: {body[:200]}")
                    return []
                return await resp.json()
    except asyncio.TimeoutError:
        logger.error(f"[ARTICLES] Timeout sur {url}")
        return []
    except Exception as e:
        logger.error(f"[ARTICLES] Erreur fetch: {e}")
        return []


async def fetch_latest_article() -> Optional[dict]:
    """Recupere le dernier article non encore envoye sur Telegram."""
    params = {
        "per_page": 10,
        "_embed": "true",
        "orderby": "date",
        "order": "desc",
        "status": "publish",
    }
    if WP_EXCLUDE_TAG_ID:
        params["tags_exclude"] = WP_EXCLUDE_TAG_ID

    posts = await _fetch_posts(params)
    for post in posts:
        if not is_article_seen(post["id"]):
            return post
    logger.info("[ARTICLES] Aucun article non vu trouve")
    return None


async def fetch_featured_article_today() -> Optional[dict]:
    """Recupere un article 'important' publie AUJOURD'HUI uniquement."""
    if not WP_FEATURED_TAG_ID:
        logger.debug("[ARTICLES] WP_FEATURED_TAG_ID non configure, pas de post du soir")
        return None

    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    params = {
        "per_page": 5,
        "_embed": "true",
        "orderby": "date",
        "order": "desc",
        "status": "publish",
        "tags": WP_FEATURED_TAG_ID,
        "after": today_start.isoformat(),
    }

    posts = await _fetch_posts(params)
    for post in posts:
        if not is_article_seen(post["id"]):
            return post
    return None


# ============================================================
# NETTOYAGE HTML / OXYGEN BUILDER
# ============================================================

def _strip_html(text: str) -> str:
    """Enleve les tags HTML et decode les entites."""
    text = re.sub(r"<[^>]+>", "", text)
    text = unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _escape_html(text: str) -> str:
    """Echappe les caracteres speciaux pour parse_mode=HTML."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def extract_intro_from_content(html_content: str, max_chars: int = None) -> str:
    """
    Extrait les premieres lignes propres du contenu HTML d'un article.
    Nettoie le CSS Oxygen Builder injecte dans content.rendered.
    """
    if not html_content:
        return ""

    if max_chars is None:
        max_chars = ARTICLE_EXCERPT_MAX_CHARS

    text = html_content

    # 1. Supprimer le CSS Oxygen
    text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE)
    # 2. Supprimer les scripts
    text = re.sub(r"<script[^>]*>.*?</script>", "", text, flags=re.DOTALL | re.IGNORECASE)
    # 3. Supprimer les commentaires HTML
    text = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)
    # 4. Strip toutes les balises HTML
    text = re.sub(r"<[^>]+>", " ", text)
    # 5. Decoder les entites HTML
    text = unescape(text)
    # 6. Normaliser les espaces
    text = re.sub(r"\s+", " ", text).strip()

    if len(text) <= max_chars:
        return text

    # 7. Tronquer proprement a la fin d'une phrase
    truncated = text[:max_chars]
    min_acceptable = int(max_chars * 0.6)
    last_sentence_end = max(
        truncated.rfind(". "),
        truncated.rfind("! "),
        truncated.rfind("? "),
    )

    if last_sentence_end >= min_acceptable:
        return truncated[:last_sentence_end + 1]

    last_space = truncated.rfind(" ")
    if last_space > min_acceptable:
        return truncated[:last_space] + "..."

    return truncated + "..."


# ============================================================
# GENERATION DU POST VIA CLAUDE API
# ============================================================

CLAUDE_INPUT_MAX_CHARS = 500
CLAUDE_OUTPUT_MAX_TOKENS = 250

CLAUDE_SYSTEM_PROMPT = """You are the editorial voice of BingeBear TV, an IPTV streaming service. Your job is to rewrite article intros into short, professional Telegram posts in a news/journal style.

Style guidelines:
- INFORMATIVE and FACTUAL — like a news brief, not marketing copy
- PROFESSIONAL tone — no excessive emojis, no hype, no "click here!" language
- 2-4 sentences maximum (around 250-350 characters total)
- Lead with the key information (inverted pyramid style)
- ENGLISH ONLY
- Do NOT include the title (it will be displayed separately)
- Do NOT include the link (it will be added separately)
- Do NOT add markdown or HTML formatting
- Do NOT start with phrases like "In this article" or "This post explains"
- Just write the news brief directly, ready to publish

Output: only the rewritten brief text, nothing else. No preamble, no explanation."""


async def generate_telegram_post_with_claude(title: str, intro: str) -> Optional[str]:
    """Demande a Claude de reecrire l'intro en post Telegram style news."""
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        logger.warning("[ARTICLES] ANTHROPIC_API_KEY absente, fallback sur intro brute")
        return None

    intro_truncated = intro[:CLAUDE_INPUT_MAX_CHARS]

    user_message = (
        f"Article title: {title}\n\n"
        f"Article intro:\n{intro_truncated}\n\n"
        f"Rewrite this as a professional news brief for our Telegram channel."
    )

    payload = {
        "model": "claude-sonnet-4-20250514",
        "max_tokens": CLAUDE_OUTPUT_MAX_TOKENS,
        "system": CLAUDE_SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": user_message}]
    }

    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json"
    }

    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as session:
            async with session.post(
                "https://api.anthropic.com/v1/messages",
                json=payload,
                headers=headers
            ) as resp:
                if resp.status != 200:
                    error_body = await resp.text()
                    logger.error(f"[ARTICLES] Claude API erreur {resp.status}: {error_body[:300]}")
                    return None

                data = await resp.json()
                content = data.get("content", [])
                if not content or not isinstance(content, list):
                    logger.error(f"[ARTICLES] Reponse Claude vide ou malformee")
                    return None

                generated = content[0].get("text", "").strip()
                if not generated:
                    logger.error("[ARTICLES] Texte genere par Claude vide")
                    return None

                logger.info(f"[ARTICLES] Claude a genere {len(generated)} chars (~$0.005 estime)")
                return generated

    except asyncio.TimeoutError:
        logger.error("[ARTICLES] Timeout sur appel Claude API")
        return None
    except Exception as e:
        logger.exception(f"[ARTICLES] Erreur appel Claude: {e}")
        return None


# ============================================================
# CONSTRUCTION DU MESSAGE FINAL
# ============================================================

async def build_morning_article_message(post: dict) -> tuple:
    """
    Construit le message Telegram a partir d'un post WP.
    Utilise parse_mode=HTML pour eviter les bugs Markdown.
    Returns: (text, photo_url)
    """
    title = _strip_html(post.get("title", {}).get("rendered", "Untitled"))

    # Extraction propre depuis content.rendered (nettoyage Oxygen)
    content_html = post.get("content", {}).get("rendered", "")
    intro = extract_intro_from_content(content_html, max_chars=CLAUDE_INPUT_MAX_CHARS)

    # Fallback : essayer l'excerpt
    if not intro:
        excerpt_raw = post.get("excerpt", {}).get("rendered", "")
        intro = _strip_html(excerpt_raw)

    if not intro:
        intro = "Read the full article on BingeBear TV."

    # Claude reecrit l'intro en style news
    brief = await generate_telegram_post_with_claude(title, intro)

    # Fallback si Claude indispo
    if not brief:
        logger.info("[ARTICLES] Fallback sur intro nettoyee (Claude indispo)")
        brief = intro[:ARTICLE_EXCERPT_MAX_CHARS]
        if len(intro) > ARTICLE_EXCERPT_MAX_CHARS:
            last_dot = brief.rfind(". ")
            if last_dot > ARTICLE_EXCERPT_MAX_CHARS * 0.6:
                brief = brief[:last_dot + 1]
            else:
                brief = brief.rsplit(" ", 1)[0] + "..."

    link = post.get("link", "")

    # Image a la une via _embedded
    photo_url = None
    embedded = post.get("_embedded", {})
    media = embedded.get("wp:featuredmedia", [])
    if media and isinstance(media, list) and len(media) > 0:
        photo_url = media[0].get("source_url")

    # Message final en HTML
    title_escaped = _escape_html(title)
    brief_escaped = _escape_html(brief)

    text = (
        f"\U0001f4f0 <b>{title_escaped}</b>\n\n"
        f"{brief_escaped}\n\n"
        f"\U0001f449 <a href=\"{link}\">Learn more</a>\n\n"
        f"<i>BingeBear TV — Daily Brief</i>"
    )

    return text, photo_url


async def build_evening_article_message(post: dict) -> tuple:
    """Variante pour le post du soir: meme structure, label different."""
    text, photo_url = await build_morning_article_message(post)
    text = text.replace(
        "<i>BingeBear TV — Daily Brief</i>",
        "<i>BingeBear TV — Featured Tonight</i>"
    )
    return text, photo_url
