"""L'invio dei rapporti per email, con la libreria standard (smtplib): niente dipendenze.

SMTPS implicito sulla 465 (`ssl=True`) o STARTTLS sulla 587. Un messaggio per destinatario: nessuno
vede gli indirizzi degli altri. Il rapporto è HTML semplice (tabelle, niente immagini remote, che i
client di posta bloccano) con una versione testuale e un allegato Excel.
"""
from __future__ import annotations

import html
import smtplib
import ssl as ssl_
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formataddr, make_msgid
from typing import Dict, List, Optional, Sequence, Tuple


@dataclass(frozen=True)
class ConfigSmtp:
    host: str
    porta: int = 465
    utente: str = ""
    password: str = ""
    mittente: str = ""
    nome_mittente: str = ""
    ssl: bool = True
    timeout: float = 30.0

    @property
    def configurato(self) -> bool:
        return bool(self.host and self.mittente)


def componi(
    config: ConfigSmtp, destinatario: str, oggetto: str, testo: str, html_: str,
    allegati: Sequence[Tuple[str, bytes, str]] = (),
) -> EmailMessage:
    m = EmailMessage()
    m["From"] = formataddr((config.nome_mittente, config.mittente)) if config.nome_mittente else config.mittente
    m["To"] = destinatario
    m["Subject"] = oggetto
    m["Message-ID"] = make_msgid(domain=config.mittente.split("@")[-1] or None)
    m.set_content(testo)
    m.add_alternative(html_, subtype="html")
    for nome, dati, tipo in allegati:
        principale, _, secondario = tipo.partition("/")
        m.add_attachment(dati, maintype=principale, subtype=secondario, filename=nome)
    return m


def invia(config: ConfigSmtp, messaggi: Sequence[EmailMessage]) -> Dict[str, str]:
    """Invia i messaggi con una connessione sola. Restituisce destinatario → "ok" o l'errore."""
    esiti: Dict[str, str] = {}
    contesto = ssl_.create_default_context()
    if config.ssl:
        server = smtplib.SMTP_SSL(config.host, config.porta, timeout=config.timeout, context=contesto)
    else:
        server = smtplib.SMTP(config.host, config.porta, timeout=config.timeout)
    with server:
        if not config.ssl:
            server.starttls(context=contesto)
        if config.utente:
            server.login(config.utente, config.password)
        for m in messaggi:
            try:
                server.send_message(m)
                esiti[m["To"]] = "ok"
            except smtplib.SMTPException as errore:
                esiti[m["To"]] = str(errore)[:300]
    return esiti


# ---- un rapporto semplice ---------------------------------------------------------------------


def tabella_html(titolo: str, intestazioni: List[str], righe: List[List[str]]) -> str:
    cella = 'style="padding:6px 10px;border-bottom:1px solid #ddd;text-align:{}"'
    testa = "".join(f"<th {cella.format('left' if i == 0 else 'right')}>{html.escape(h)}</th>" for i, h in enumerate(intestazioni))
    corpo = "".join(
        "<tr>" + "".join(f"<td {cella.format('left' if i == 0 else 'right')}>{html.escape(str(v))}</td>" for i, v in enumerate(r)) + "</tr>"
        for r in righe
    )
    return (f'<h2 style="font-size:16px;margin:24px 0 8px">{html.escape(titolo)}</h2>'
            f'<table style="border-collapse:collapse;font-size:14px;width:100%;max-width:640px">'
            f"<thead><tr>{testa}</tr></thead><tbody>{corpo}</tbody></table>")


def pagina_html(titolo: str, sottotitolo: str, blocchi: List[str], piede: Optional[str] = None) -> str:
    return (
        '<!doctype html><html><body style="margin:0;padding:16px;font-family:Arial,Helvetica,sans-serif;'
        'color:#1c1530;background:#ffffff;line-height:1.5">'
        f'<h1 style="font-size:20px;margin:0 0 4px">{html.escape(titolo)}</h1>'
        f'<p style="margin:0 0 16px;color:#4f4570">{html.escape(sottotitolo)}</p>'
        + "".join(blocchi)
        + (f'<p style="margin-top:24px;font-size:12px;color:#635a80">{piede}</p>' if piede else "")
        + "</body></html>"
    )
