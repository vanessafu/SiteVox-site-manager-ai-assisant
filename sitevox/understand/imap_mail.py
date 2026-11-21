"""Postfach-Anbindung per IMAP (Gmail, GMX, WEB.DE, T-Online, IONOS, eigener Server …).

- Nur lesend: Nachrichten werden mit BODY.PEEK[] geholt (bleiben im Postfach ungelesen).
- Das Passwort (empfohlen: App-Passwort) wird NICHT gespeichert, sondern nur im Arbeitsspeicher
  des Backends gehalten; nach einem Neustart muss es erneut eingegeben werden.
- Microsoft 365 / Outlook.com erlauben kein IMAP mit Passwort mehr → dort Microsoft Graph (OAuth,
  Mail.Read) – in Vorbereitung.
"""
from __future__ import annotations

import imaplib
import re
import ssl
from datetime import date, timedelta
from typing import Any

PRESETS: dict[str, dict[str, Any]] = {
    "gmail": {"label": "Gmail", "imap_host": "imap.gmail.com", "imap_port": 993,
              "hint": "Google-Konto → Sicherheit → App-Passwörter (2-Faktor muss aktiv sein)"},
    "gmx": {"label": "GMX", "imap_host": "imap.gmx.net", "imap_port": 993,
            "hint": "In GMX unter E-Mail → Einstellungen → POP3/IMAP Abruf zuerst IMAP erlauben"},
    "webde": {"label": "WEB.DE", "imap_host": "imap.web.de", "imap_port": 993,
              "hint": "In WEB.DE unter Einstellungen → POP3/IMAP Abruf zuerst IMAP erlauben"},
    "tonline": {"label": "T-Online", "imap_host": "secureimap.t-online.de", "imap_port": 993,
                "hint": "Eigenes E-Mail-Passwort aus dem Kundencenter verwenden"},
    "ionos": {"label": "IONOS", "imap_host": "imap.ionos.de", "imap_port": 993, "hint": ""},
    "imap": {"label": "Anderer IMAP-Server", "imap_host": "", "imap_port": 993,
             "hint": "Serverdaten beim E-Mail-Anbieter / der IT erfragen"},
    "microsoft": {"label": "Microsoft 365 / Outlook", "imap_host": "outlook.office365.com", "imap_port": 993,
                  "hint": "Microsoft erlaubt IMAP nur noch mit OAuth – Anbindung über Microsoft Graph folgt",
                  "disabled": True},
}

_secrets: dict[str, str] = {}  # account_id → Passwort (nur im Arbeitsspeicher)


class MailError(Exception):
    pass


def remember(account_id: str, password: str) -> None:
    _secrets[account_id] = password


def forget(account_id: str) -> None:
    _secrets.pop(account_id, None)


def has_secret(account_id: str) -> bool:
    return account_id in _secrets


def _connect(acc: dict, password: str) -> imaplib.IMAP4:
    host, port = acc["imap_host"], int(acc.get("imap_port") or 993)
    if not host:
        raise MailError("IMAP-Server fehlt")
    try:
        if acc.get("security", "ssl") == "ssl":
            m = imaplib.IMAP4_SSL(host, port, ssl_context=ssl.create_default_context(), timeout=20)
        else:
            m = imaplib.IMAP4(host, port, timeout=20)
            m.starttls(ssl_context=ssl.create_default_context())
    except (OSError, imaplib.IMAP4.error) as e:
        raise MailError(f"Server {host}:{port} nicht erreichbar ({e})") from e
    try:
        m.login(acc.get("username") or acc["address"], password)
    except imaplib.IMAP4.error as e:
        raise MailError("Anmeldung abgelehnt – Benutzername/App-Passwort prüfen bzw. IMAP beim Anbieter freischalten") from e
    return m


def _select(m: imaplib.IMAP4, folder: str) -> int:
    typ, data = m.select(f'"{folder}"' if " " in folder else folder, readonly=True)
    if typ != "OK":
        raise MailError(f"Ordner „{folder}“ nicht gefunden")
    return int(data[0] or 0)


def test(acc: dict, password: str) -> dict[str, Any]:
    m = _connect(acc, password)
    try:
        n = _select(m, acc.get("folder") or "INBOX")
        return {"ok": True, "messages": n}
    finally:
        try:
            m.logout()
        except Exception:  # noqa: BLE001
            pass


def fetch(acc: dict, password: str, since_days: int = 14, limit: int = 50) -> list[bytes]:
    """Rohnachrichten (RFC 822) der letzten `since_days` Tage, neueste zuerst, höchstens `limit`."""
    m = _connect(acc, password)
    try:
        _select(m, acc.get("folder") or "INBOX")
        since = (date.today() - timedelta(days=since_days)).strftime("%d-%b-%Y")
        typ, data = m.search(None, "SINCE", since)
        if typ != "OK":
            raise MailError("Suche im Postfach fehlgeschlagen")
        ids = data[0].split()[-limit:][::-1]
        out = []
        for i in ids:
            typ, msg = m.fetch(i, "(BODY.PEEK[])")
            if typ == "OK":
                raw = next((p[1] for p in msg if isinstance(p, tuple)), None)
                if raw:
                    out.append(raw)
        return out
    finally:
        try:
            m.logout()
        except Exception:  # noqa: BLE001
            pass


def safe_name(message_id: str) -> str:
    return re.sub(r"[^\w.-]+", "_", message_id)[:80] or "mail"
