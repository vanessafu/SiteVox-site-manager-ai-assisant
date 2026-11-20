"""E-Mail-Eingang: Mock über einen Ordner exportierter .eml-Dateien (Graph-API später).

Zuordnung zum Projekt über Vertragsnummer / Projektname / bekannte Absender (deterministisch).
"""
from __future__ import annotations

import email
import re
from email import policy
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Optional

from .. import settings


def _body(msg) -> str:
    part = msg.get_body(preferencelist=("plain", "html"))
    if part is None:
        return ""
    text = part.get_content()
    if part.get_content_type() == "text/html":
        text = re.sub(r"<[^>]+>", " ", text)
    return text.strip()


def parse_eml(path: Path) -> dict[str, Any]:
    msg = email.message_from_bytes(Path(path).read_bytes(), policy=policy.default)
    received = parsedate_to_datetime(msg["Date"]).isoformat() if msg["Date"] else None
    attachments = [p.get_filename() for p in msg.iter_attachments() if p.get_filename()]
    return {
        "message_id": (msg["Message-ID"] or Path(path).stem).strip("<>"),
        "from": str(msg["From"] or ""),
        "to": str(msg["To"] or ""),
        "cc": str(msg["Cc"] or ""),
        "subject": str(msg["Subject"] or ""),
        "received_at": received,
        "body": _body(msg),
        "attachments": attachments,
        "file": str(path),
    }


def assign_project(mail: dict) -> Optional[str]:
    hay = " ".join([mail["subject"], mail["body"], mail["from"], mail["to"]]).lower()
    best, best_score = None, 0
    for p in settings.baseline()["projects"]:
        score = 0
        if p.get("contract_no") and p["contract_no"].lower() in hay:
            score += 3
        if p["name"].lower() in hay or p["id"].lower().replace("-", " ") in hay:
            score += 2
        emails = [p.get("client", {}).get("email", "")] + [x.get("email", "") for x in p.get("parties", [])]
        domains = {e.split("@")[-1] for e in emails if e}
        if any(d and d in mail["from"].lower() for d in domains):
            score += 1
        if score > best_score:
            best, best_score = p["id"], score
    return best


def scan_folder(folder: Path) -> list[dict]:
    return [parse_eml(p) for p in sorted(Path(folder).glob("*.eml"))]
