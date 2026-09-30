from sqlalchemy import BigInteger, Column, MetaData, Table
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable

from lanterna import registra_tabelle
from lanterna.agente import analizza, e_bot
from lanterna.config import ConfigLanterna
from lanterna.geo import NESSUNO, luogo
from lanterna.impronta import identificativo_esteso, impronta
from lanterna.rete import ip_da_intestazioni
from lanterna.sorgenti import classifica, dominio, utm_da_url

IPHONE = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1"
)
ANDROID = (
    "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Mobile Safari/537.36"
)
EDGE = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36 Edg/126.0.0.0"
)
IPAD = "Mozilla/5.0 (iPad; CPU OS 17_5 like Mac OS X) AppleWebKit/605.1.15 Version/17.5 Mobile/15E148 Safari/604.1"


# ---- impronta ------------------------------------------------------------------------


def test_impronta_stabile_nello_stesso_giorno_e_diversa_col_sale():
    a = impronta("sale1", "sito", "1.2.3.4", IPHONE)
    assert a == impronta("sale1", "sito", "1.2.3.4", IPHONE)
    assert len(a) == 32
    assert a != impronta("sale2", "sito", "1.2.3.4", IPHONE)
    assert a != impronta("sale1", "altro", "1.2.3.4", IPHONE)
    assert a != impronta("sale1", "sito", "1.2.3.5", IPHONE)
    assert "1.2.3.4" not in a


def test_identificativo_esteso_richiede_segreto_e_id():
    assert identificativo_esteso("", "sito", "abc") is None
    assert identificativo_esteso("segreto", "sito", "") is None
    x = identificativo_esteso("segreto", "sito", "abc")
    assert x and len(x) == 64 and x == identificativo_esteso("segreto", "sito", "abc")
    assert x != identificativo_esteso("altro-segreto", "sito", "abc")


# ---- rete -------------------------------------------------------------------------------


def test_ip_preferisce_x_real_ip_poi_ultimo_inoltrato():
    assert ip_da_intestazioni({"x-real-ip": " 9.9.9.9 ", "x-forwarded-for": "1.1.1.1"}, "10.0.0.1") == "9.9.9.9"
    assert ip_da_intestazioni({"x-forwarded-for": "6.6.6.6, 2.2.2.2"}, "10.0.0.1") == "2.2.2.2"
    assert ip_da_intestazioni({}, "10.0.0.1") == "10.0.0.1"
    assert ip_da_intestazioni({}, None) is None


# ---- agente -----------------------------------------------------------------------------


def test_analisi_user_agent():
    assert analizza(IPHONE).__dict__ == {"dispositivo": "mobile", "browser": "Safari", "so": "iOS"}
    assert analizza(ANDROID).__dict__ == {"dispositivo": "mobile", "browser": "Chrome", "so": "Android"}
    assert analizza(EDGE).__dict__ == {"dispositivo": "desktop", "browser": "Edge", "so": "Windows"}
    assert analizza(IPAD).dispositivo == "tablet"


def test_bot():
    for ua in (
        "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
        "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; GPTBot/1.1)",
        "curl/8.4.0",
        "python-requests/2.32",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 HeadlessChrome/126.0 Safari/537.36",
        "",
    ):
        assert e_bot(ua), ua
    for ua in (IPHONE, ANDROID, EDGE, IPAD):
        assert not e_bot(ua), ua


# ---- sorgenti -----------------------------------------------------------------------------


def test_dominio_e_utm():
    assert dominio("https://www.Google.com/search?q=x") == "google.com"
    assert dominio(None) is None
    assert utm_da_url("https://tarots.chat/?utm_source=ig&utm_medium=paid_social&x=1") == {
        "utm_source": "ig",
        "utm_medium": "paid_social",
    }


def test_canali():
    c = lambda ref, utm=None: classifica(ref, utm or {}, "tarots.chat").canale  # noqa: E731
    assert c(None) == "diretto"
    assert c("https://tarots.chat/leggi") == "diretto"  # interno
    assert c("https://www.google.it/") == "ricerca"
    assert c("https://duckduckgo.com/") == "ricerca"
    assert c("https://l.instagram.com/") == "social"
    assert c("https://t.co/abc") == "social"
    assert c("https://chatgpt.com/") == "assistenti_ai"
    assert c("https://www.perplexity.ai/search") == "assistenti_ai"
    assert c("https://unblog.example.org/post") == "referral"
    assert c(None, {"utm_source": "google", "utm_medium": "cpc"}) == "ricerca_a_pagamento"
    assert c(None, {"utm_source": "facebook", "utm_medium": "paid"}) == "social_a_pagamento"
    assert c(None, {"utm_source": "newsletter", "utm_medium": "email"}) == "email"
    assert c(None, {"utm_source": "instagram"}) == "social"
    assert c(None, {"utm_campaign": "lancio"}) == "campagna"


def test_provenienza_conserva_utm_e_referrer():
    p = classifica("https://www.bing.com/", {"utm_campaign": " autunno ", "utm_term": ""}, "tarots.chat")
    assert p.referrer_dominio == "bing.com"
    assert p.utm_campagna == "autunno"
    assert p.utm_termine is None


# ---- geo e config ------------------------------------------------------------------------


def test_geo_senza_file_non_fallisce():
    assert luogo(None, "1.2.3.4") is NESSUNO
    assert luogo("/non/esiste.mmdb", "1.2.3.4") is NESSUNO


def test_percorsi_esclusi():
    cfg = ConfigLanterna(sito="t")
    assert cfg.escluso("/admin") and cfg.escluso("/admin/utenti")
    assert not cfg.escluso("/administrator") and not cfg.escluso("/")


# ---- schema -------------------------------------------------------------------------------


def test_schema_senza_ip_e_con_brin():
    metadata = MetaData()
    Table("users", metadata, Column("id", BigInteger, primary_key=True))
    t = registra_tabelle(metadata)
    colonne = {c.name for tab in metadata.tables.values() for c in tab.columns}
    assert not {"ip", "indirizzo", "user_agent", "email"} & colonne
    ddl = [str(CreateIndex(i).compile(dialect=postgresql.dialect())) for i in t.eventi.indexes]
    assert any("USING brin" in d for d in ddl)
    str(CreateTable(t.giornaliero).compile(dialect=postgresql.dialect()))
