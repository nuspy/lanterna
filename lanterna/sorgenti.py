"""Da referrer e parametri UTM al canale di acquisizione.

Il raggruppamento segue a grandi linee i «canali predefiniti» di GA4, con due differenze pensate
per un sito piccolo: gli assistenti AI (ChatGPT, Perplexity, Claude, Gemini, Copilot) sono un
canale a sé, perché oggi sono una fonte di traffico da guardare separatamente; e un UTM con un mezzo
sconosciuto resta «campagna» invece di sparire in «altro».
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Mapping, Optional
from urllib.parse import parse_qs, urlsplit

CANALI = (
    "diretto",
    "ricerca",
    "ricerca_a_pagamento",
    "social",
    "social_a_pagamento",
    "assistenti_ai",
    "email",
    "referral",
    "affiliati",
    "display",
    "campagna",
)

_RICERCA = re.compile(
    r"(^|\.)(google|bing|yahoo|duckduckgo|ecosia|qwant|yandex|baidu|naver|seznam|startpage|brave|"
    r"search\.aol|ask|sogou|so\.com|yep)\.",
)
_SOCIAL = re.compile(
    r"(^|\.)(facebook|fb|instagram|t\.co|twitter|x\.com|linkedin|lnkd\.in|pinterest|reddit|tiktok|"
    r"youtube|youtu\.be|threads|bsky|mastodon|tumblr|snapchat|telegram|t\.me|whatsapp|wa\.me|"
    r"vk|weibo|quora|discord|messenger)(\.|$)",
)
_AI = re.compile(
    r"(^|\.)(chatgpt\.com|chat\.openai\.com|openai\.com|perplexity\.ai|claude\.ai|gemini\.google\.com|"
    r"bard\.google\.com|copilot\.microsoft\.com|you\.com|phind\.com|meta\.ai|deepseek\.com|"
    r"chat\.mistral\.ai|grok\.com)$",
)
_EMAIL = re.compile(r"(^|\.)(mail\.google|outlook\.live|mail\.yahoo|webmail|mail\.)")

_MEZZI_PAGATI = {"cpc", "ppc", "paid", "paidsearch", "paid_search", "cpm", "cpv", "cpa", "paid-social", "paid_social", "paidsocial"}


@dataclass(frozen=True)
class Provenienza:
    canale: str
    referrer_dominio: Optional[str] = None
    utm_sorgente: Optional[str] = None
    utm_mezzo: Optional[str] = None
    utm_campagna: Optional[str] = None
    utm_contenuto: Optional[str] = None
    utm_termine: Optional[str] = None


def dominio(url: Optional[str]) -> Optional[str]:
    if not url:
        return None
    try:
        host = urlsplit(url if "//" in url else f"//{url}").hostname
    except ValueError:
        return None
    if not host:
        return None
    host = host.lower()
    return host[4:] if host.startswith("www.") else host


def utm_da_url(url: Optional[str]) -> dict:
    """I parametri utm_* di un indirizzo, se ci sono."""
    if not url:
        return {}
    try:
        query = parse_qs(urlsplit(url).query)
    except ValueError:
        return {}
    return {k: v[0] for k, v in query.items() if k.startswith("utm_") and v and v[0]}


def _pulito(valore: Optional[str]) -> Optional[str]:
    if valore is None:
        return None
    valore = str(valore).strip()[:200]
    return valore or None


def _interno(host: str, sito: str) -> bool:
    sito = (sito or "").lower().removeprefix("www.")
    return bool(sito) and (host == sito or host.endswith("." + sito))


def classifica(referrer: Optional[str], utm: Mapping[str, str], dominio_sito: str = "") -> Provenienza:
    host = dominio(referrer)
    if host and _interno(host, dominio_sito):
        host = None  # un referrer interno non è una provenienza
    sorgente = _pulito(utm.get("utm_source"))
    mezzo = _pulito(utm.get("utm_medium"))
    campagna = _pulito(utm.get("utm_campaign"))
    m = (mezzo or "").lower()
    s = (sorgente or "").lower()

    if mezzo or sorgente or campagna:
        pagato = m in _MEZZI_PAGATI or m.startswith("paid") or m.endswith("cpc")
        social_sorgente = bool(_SOCIAL.search(s + ".")) or m in {"social", "social-network", "social-media", "sm"}
        if m in {"email", "e-mail", "e_mail", "newsletter"}:
            canale = "email"
        elif m in {"affiliate", "affiliati", "affiliazione"}:
            canale = "affiliati"
        elif m in {"display", "banner", "cpm", "interstitial", "expandable"}:
            canale = "display"
        elif pagato and social_sorgente:
            canale = "social_a_pagamento"
        elif pagato:
            canale = "ricerca_a_pagamento"
        elif social_sorgente:
            canale = "social"
        elif m in {"organic"}:
            canale = "ricerca"
        elif m in {"referral"}:
            canale = "referral"
        else:
            canale = "campagna"
    elif host is None:
        canale = "diretto"
    elif _AI.search(host):
        canale = "assistenti_ai"
    elif _RICERCA.search(host):
        canale = "ricerca"
    elif _SOCIAL.search(host):
        canale = "social"
    elif _EMAIL.search(host):
        canale = "email"
    else:
        canale = "referral"

    return Provenienza(
        canale=canale,
        referrer_dominio=host[:255] if host else None,
        utm_sorgente=sorgente,
        utm_mezzo=mezzo,
        utm_campagna=campagna,
        utm_contenuto=_pulito(utm.get("utm_content")),
        utm_termine=_pulito(utm.get("utm_term")),
    )
