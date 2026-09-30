"""Dal user agent a tre categorie grossolane (dispositivo, browser, sistema) e al filtro dei bot.

Volutamente povero: il user agent completo non si conserva, e per decidere dove investire servono
«mobile o desktop», «Safari o Chrome», non la versione di build. Niente librerie esterne.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

_BOT = re.compile(
    r"bot\b|bot/|crawl|spider|slurp|mediapartners|facebookexternalhit|facebookcatalog|embedly|"
    r"headless|lighthouse|pagespeed|pingdom|uptime|monitor|preview|scanner|validator|"
    r"python-requests|python-urllib|aiohttp|httpx|curl/|wget/|go-http-client|java/|okhttp|"
    r"node-fetch|axios/|libwww|scrapy|phantomjs|puppeteer|playwright|selenium|"
    r"gptbot|chatgpt-user|oai-searchbot|claudebot|claude-web|anthropic-ai|perplexitybot|"
    r"bytespider|ccbot|amazonbot|applebot|yandex|baiduspider|duckduckbot|petalbot|semrush|ahrefs|mj12",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Agente:
    dispositivo: str  # mobile | tablet | desktop
    browser: str
    so: str


def e_bot(ua: str) -> bool:
    return not ua or bool(_BOT.search(ua))


def _so(ua: str) -> str:
    if re.search(r"iPhone|iPad|iPod", ua):
        return "iOS"
    if "Android" in ua:
        return "Android"
    if "CrOS" in ua:
        return "ChromeOS"
    if "Windows" in ua:
        return "Windows"
    if "Macintosh" in ua or "Mac OS X" in ua:
        return "macOS"
    if "Linux" in ua:
        return "Linux"
    return "altro"


def _browser(ua: str) -> str:
    if "Edg/" in ua or "EdgA/" in ua or "EdgiOS/" in ua:
        return "Edge"
    if "OPR/" in ua or "Opera" in ua:
        return "Opera"
    if "SamsungBrowser/" in ua:
        return "Samsung Internet"
    if "Firefox/" in ua or "FxiOS/" in ua:
        return "Firefox"
    if "CriOS/" in ua or ("Chrome/" in ua and "Chromium" not in ua):
        return "Chrome"
    if "Safari/" in ua and "Version/" in ua:
        return "Safari"
    return "altro"


def _dispositivo(ua: str) -> str:
    if "iPad" in ua or "Tablet" in ua or ("Android" in ua and "Mobile" not in ua):
        return "tablet"
    if "Mobi" in ua or "iPhone" in ua or "iPod" in ua:
        return "mobile"
    return "desktop"


def analizza(ua: str) -> Agente:
    ua = ua or ""
    return Agente(dispositivo=_dispositivo(ua), browser=_browser(ua), so=_so(ua))
