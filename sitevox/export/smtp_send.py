"""Freigegebenes Schreiben per E-Mail an den AG senden – über das im Projekt gebundene Postfach (SMTP).

Sicherheitsrahmen (bewusst eng):
  * Nur Schreiben im Status „Geprüft“ (= von einem Menschen freigegeben) und nur nach ausdrücklicher Bestätigung
    im Sendedialog (eigener API-Aufruf). Die Freigabe selbst sendet nie.
  * Empfänger ausschließlich aus dem Feld „E-Mail Empfänger (AG)“ (belegt bzw. von der Bauleitung eingetragen).
  * Passwort nur im Arbeitsspeicher (wie beim Abruf); ohne entsperrtes Postfach kein Versand.
  * Gesendete Nachricht wird als .eml abgelegt und im Audit-Log festgehalten.
"""
from __future__ import annotations

import mimetypes
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid
from pathlib import Path
from typing import Any, Callable, Optional

from .. import settings
from ..understand import imap_mail

SMTP_PRESETS = {  # Anbieter → (Server, Port, Sicherheit)
    "gmail": ("smtp.gmail.com", 465, "ssl"),
    "gmx": ("mail.gmx.net", 465, "ssl"),
    "webde": ("smtp.web.de", 587, "starttls"),
    "tonline": ("securesmtp.t-online.de", 465, "ssl"),
    "ionos": ("smtp.ionos.de", 465, "ssl"),
}


def smtp_settings(acc: dict) -> tuple[str, int, str]:
    if acc.get("smtp_host"):
        port = int(acc.get("smtp_port") or 465)
        return acc["smtp_host"], port, acc.get("smtp_security") or ("ssl" if port == 465 else "starttls")
    if acc.get("provider") in SMTP_PRESETS:
        return SMTP_PRESETS[acc["provider"]]
    host = acc.get("imap_host") or ""
    host = "smtp." + host.split(".", 1)[1] if host.startswith("imap.") else host  # imap.firma.de → smtp.firma.de
    return host, 465, "ssl"


def subject(letter: dict) -> str:
    return next(s["text"] for s in letter["rendered"] if s["key"] == "betreff")


def body(letter: dict) -> str:
    """Begleittext der E-Mail (ohne internen Hinweis – der steht nur im Outlook-Entwurf)."""
    project = settings.project_cfg(letter["project_id"])
    company = settings.baseline()["company"]
    return (f"Sehr geehrte Damen und Herren,\n\nanbei erhalten Sie vorab per E-Mail unser Schreiben "
            f"„{subject(letter)}“ zum Bauvorhaben {project['title']} (Vertrag Nr. {project['contract_no']}). "
            f"Das Original folgt auf dem vereinbarten Zustellweg.\n\nMit freundlichen Grüßen\n"
            f"{company['signer']}\n{company['name']}")


def attachments(letter: dict) -> list[Path]:
    """Das Schreiben selbst: PDF, sonst DOCX (PDF nur mit LibreOffice auf dem Server)."""
    ex = letter.get("exports") or {}
    for k in ("pdf", "docx"):
        if ex.get(k) and Path(ex[k]).exists():
            return [Path(ex[k])]
    return []


def build(letter: dict, sender: str, to: str, cc: list[str]) -> EmailMessage:
    company = settings.baseline()["company"]
    msg = EmailMessage()
    msg["From"] = formataddr((company.get("signer", "").split(",")[0].strip() or company["name"], sender))
    msg["To"] = to
    if cc:
        msg["Cc"] = ", ".join(cc)
    msg["Subject"] = subject(letter)
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain=sender.split("@", 1)[1])
    msg["Disposition-Notification-To"] = sender  # Lesebestätigung anfordern (Nachweis, nicht garantiert)
    msg.set_content(body(letter))
    for p in attachments(letter):
        ctype = mimetypes.guess_type(str(p))[0] or "application/octet-stream"
        main, sub = ctype.split("/", 1)
        msg.add_attachment(p.read_bytes(), maintype=main, subtype=sub, filename=p.name)
    return msg


def transmit(acc: dict, password: str, msg: EmailMessage) -> None:
    host, port, sec = smtp_settings(acc)
    if not host:
        raise imap_mail.MailError("SMTP-Server des Postfachs unbekannt")
    user = acc.get("username") or acc["address"]
    ctx = ssl.create_default_context()
    try:
        if sec == "ssl":
            with smtplib.SMTP_SSL(host, port, context=ctx, timeout=30) as s:
                s.login(user, password)
                s.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=30) as s:
                s.starttls(context=ctx)
                s.login(user, password)
                s.send_message(msg)
    except smtplib.SMTPAuthenticationError as e:
        raise imap_mail.MailError("SMTP-Anmeldung abgelehnt – App-Passwort / SMTP-Freigabe beim Anbieter prüfen") from e
    except smtplib.SMTPRecipientsRefused as e:
        raise imap_mail.MailError(f"Empfänger abgelehnt: {', '.join(e.recipients)}") from e
    except (OSError, smtplib.SMTPException) as e:
        raise imap_mail.MailError(f"Versand über {host}:{port} fehlgeschlagen ({e})") from e


def send(letter: dict, acc: dict, to: str, cc: list[str],
         transport: Optional[Callable[[dict, str, EmailMessage], None]] = None) -> dict[str, Any]:
    password = imap_mail.secret(acc["account_id"])
    if not password:
        raise imap_mail.MailError("Postfach gesperrt – bitte zuerst mit Passwort entsperren")
    msg = build(letter, acc["address"], to, cc)
    (transport or transmit)(acc, password, msg)
    ex = letter.get("exports") or {}
    base = Path(ex.get("docx") or ex.get("eml") or ".")
    out = base.with_name(base.stem + "_gesendet.eml")
    out.write_bytes(bytes(msg))
    return {"from": acc["address"], "to": to, "cc": cc, "subject": msg["Subject"], "message_id": msg["Message-ID"],
            "attachments": [p.name for p in attachments(letter)], "eml": str(out)}
