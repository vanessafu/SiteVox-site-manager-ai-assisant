"""Outlook-ENTWURF – niemals senden.

Zwei Wege:
  1. .eml mit Header "X-Unsent: 1": Outlook öffnet die Datei als ungesendeten Entwurf; die Bauleitung
     prüft und klickt selbst auf "Senden". (Funktioniert ohne Azure-App-Registrierung – Demo-tauglich.)
  2. Microsoft Graph: POST /me/messages legt einen Entwurf im Ordner "Entwürfe" an.
     Benötigte Berechtigung: Mail.ReadWrite (delegiert). Mail.Send wird bewusst NICHT angefordert –
     damit garantiert das Berechtigungsmodell selbst, dass die KI nichts versenden kann.
"""
from __future__ import annotations

import mimetypes
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from pathlib import Path
from typing import Any

from .. import DISCLAIMER, settings

GRAPH_SCOPES = ["Mail.ReadWrite"]  # absichtlich ohne Mail.Send


def _body(letter: dict) -> str:
    project = settings.project_cfg(letter["project_id"])
    subj = next(s["text"] for s in letter["rendered"] if s["key"] == "betreff")
    return (f"Sehr geehrte Damen und Herren,\n\nanbei erhalten Sie vorab per E-Mail unser Schreiben "
            f"„{subj}“ zum Bauvorhaben {project['title']} (Vertrag Nr. {project['contract_no']}). "
            f"Das Original folgt auf dem vereinbarten Zustellweg.\n\nMit freundlichen Grüßen\n"
            f"{settings.baseline()['company']['signer']}\n{settings.baseline()['company']['name']}\n\n"
            f"[Interner Hinweis, vor dem Senden löschen: {DISCLAIMER}]")


def write_eml_draft(letter: dict, attachment: Path, extra: list[Path] | None = None) -> Path:
    msg = EmailMessage()
    msg["X-Unsent"] = "1"
    from ..drafting.composer import recipient_email

    msg["To"] = recipient_email(letter) or ""  # nur belegte/von der Bauleitung eingetragene Adresse
    msg["From"] = ""
    msg["Subject"] = next(s["text"] for s in letter["rendered"] if s["key"] == "betreff")
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain="sitevox.local")
    msg.set_content(_body(letter))
    for p in [attachment, *(extra or [])]:
        if p and Path(p).exists():
            ctype = mimetypes.guess_type(str(p))[0] or "application/octet-stream"
            main, sub = ctype.split("/", 1)
            msg.add_attachment(Path(p).read_bytes(), maintype=main, subtype=sub, filename=Path(p).name)
    out = Path(attachment).with_suffix(".eml")
    out.write_bytes(bytes(msg))
    return out


def graph_create_draft(letter: dict, access_token: str, attachment: Path) -> dict[str, Any]:
    """Legt den Entwurf per Graph an (nur Mail.ReadWrite). Es gibt in SiteVox keinen Send-Aufruf."""
    import base64

    import httpx

    from ..drafting.composer import recipient_email

    payload = {
        "subject": next(s["text"] for s in letter["rendered"] if s["key"] == "betreff"),
        "body": {"contentType": "Text", "content": _body(letter)},
        "toRecipients": [{"emailAddress": {"address": a}} for a in [recipient_email(letter)] if a],
        "attachments": [{
            "@odata.type": "#microsoft.graph.fileAttachment", "name": Path(attachment).name,
            "contentBytes": base64.b64encode(Path(attachment).read_bytes()).decode(),
        }],
    }
    r = httpx.post("https://graph.microsoft.com/v1.0/me/messages", json=payload,
                   headers={"Authorization": f"Bearer {access_token}"}, timeout=30)
    r.raise_for_status()
    d = r.json()
    return {"id": d["id"], "webLink": d.get("webLink"), "isDraft": d.get("isDraft", True)}
