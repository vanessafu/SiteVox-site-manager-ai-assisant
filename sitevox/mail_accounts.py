"""Gebundene Postfächer je Projekt: anlegen (mit Verbindungstest), entfernen, synchronisieren.

Konten liegen im Projekt-Dokument (SQLite) unter "mail_accounts" – ohne Passwort.
Synchronisieren: neue Nachrichten holen → .eml ablegen → Projektzuordnung → normale E-Mail-Erfassung.
"""
from __future__ import annotations

import os
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional

from . import settings, store
from .understand import email_ingest, imap_mail

PUBLIC = ("account_id", "provider", "address", "username", "imap_host", "imap_port", "security", "folder",
          "since_days", "only_project", "created_at", "last_sync", "last_result", "smtp_host", "smtp_port")


AUTO_SYNC_MIN = float(os.environ.get("SITEVOX_MAIL_SYNC_MIN", "5"))  # 0 = kein automatischer Abruf (auch nicht nach Entsperren)
_locks: dict[str, threading.Lock] = {}
_auto = {"running": False, "next": None}


def _project(pid: str) -> dict:
    return store.get("projects", pid) or dict(settings.project_cfg(pid))


def _public(a: dict) -> dict:
    from .export.smtp_send import smtp_settings

    host, port, _ = smtp_settings(a)
    return {**{k: a.get(k) for k in PUBLIC}, "smtp_host": host, "smtp_port": port,
            "connected": imap_mail.has_secret(a["account_id"]),
            "auto_sync_min": AUTO_SYNC_MIN if _auto["running"] else None, "next_sync": _auto["next"]}


def accounts(pid: str) -> list[dict]:
    return [_public(a) for a in _project(pid).get("mail_accounts", [])]


def _get(pid: str, aid: str) -> dict:
    a = next((x for x in _project(pid).get("mail_accounts", []) if x["account_id"] == aid), None)
    if not a:
        raise KeyError(aid)
    return a


def _save(pid: str, accs: list[dict]) -> None:
    p = _project(pid)
    p["mail_accounts"] = accs
    store.save_project(p)


def add(pid: str, data: dict, actor: str, tester: Optional[Callable] = None) -> dict:
    provider = data.get("provider") or "imap"
    preset = imap_mail.PRESETS.get(provider, imap_mail.PRESETS["imap"])
    if preset.get("disabled"):
        raise imap_mail.MailError(preset["hint"])
    address = (data.get("address") or "").strip()
    password = "".join((data.get("password") or "").split())  # App-Passwörter werden mit Leerzeichen angezeigt
    if "@" not in address or not password:
        raise imap_mail.MailError("E-Mail-Adresse und Passwort angeben")
    acc = {
        "account_id": store.next_id("MAIL-", 3), "provider": provider, "address": address,
        "username": (data.get("username") or "").strip() or address,
        "imap_host": (data.get("imap_host") or preset["imap_host"]).strip(),
        "imap_port": int(data.get("imap_port") or preset["imap_port"]),
        "security": data.get("security") or "ssl", "folder": (data.get("folder") or "INBOX").strip(),
        "since_days": int(data.get("since_days") or 14), "only_project": bool(data.get("only_project", True)),
        "smtp_host": (data.get("smtp_host") or "").strip() or None,
        "smtp_port": int(data["smtp_port"]) if data.get("smtp_port") else None,
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"), "last_sync": None, "last_result": None,
    }
    info = (tester or imap_mail.test)(acc, password)  # wirft MailError mit verständlicher Meldung
    imap_mail.remember(acc["account_id"], password)
    _save(pid, [*_project(pid).get("mail_accounts", []), acc])
    store.audit(actor, "project", pid, "mail_account_add", after={"address": address, "host": acc["imap_host"]})
    return {**_public(acc), "messages": info.get("messages")}


def unlock(pid: str, aid: str, password: str, tester: Optional[Callable] = None) -> dict:
    acc = _get(pid, aid)
    password = "".join((password or "").split())
    (tester or imap_mail.test)(acc, password)
    imap_mail.remember(aid, password)
    return _public(acc)


def remove(pid: str, aid: str, actor: str) -> None:
    acc = _get(pid, aid)
    _save(pid, [a for a in _project(pid).get("mail_accounts", []) if a["account_id"] != aid])
    imap_mail.forget(aid)
    store.audit(actor, "project", pid, "mail_account_remove", before={"address": acc["address"]})


def sync(pid: str, aid: str, ingest: Callable[[Path, str], Any], actor: str,
         fetcher: Optional[Callable] = None) -> dict:
    """Holt neue Nachrichten und übergibt passende an `ingest(path, received_at)`. Gibt Zähler zurück.
    Manueller und automatischer Abruf desselben Kontos laufen nie gleichzeitig (Sperre je Konto)."""
    with _locks.setdefault(aid, threading.Lock()):
        try:
            return _sync(pid, aid, ingest, actor, fetcher)
        except imap_mail.MailError as e:
            _record(pid, aid, {"error": str(e)})
            raise


def _record(pid: str, aid: str, res: dict) -> None:
    accs = _project(pid).get("mail_accounts", [])
    for a in accs:
        if a["account_id"] == aid:
            a["last_sync"] = datetime.now().astimezone().isoformat(timespec="seconds")
            a["last_result"] = res
    _save(pid, accs)


def _sync(pid: str, aid: str, ingest: Callable[[Path, str], Any], actor: str,
          fetcher: Optional[Callable] = None) -> dict:
    acc = _get(pid, aid)
    password = imap_mail._secrets.get(aid)
    if password is None:
        raise PermissionError("Passwort erneut eingeben (wird aus Datenschutzgründen nicht gespeichert)")
    raws = (fetcher or imap_mail.fetch)(acc, password, acc.get("since_days", 14))
    folder = settings.data_dir() / pid / "mail"
    folder.mkdir(parents=True, exist_ok=True)
    res = {"fetched": len(raws), "new": 0, "duplicate": 0, "other_project": 0}
    for raw in raws:
        tmp = folder / "_incoming.eml"
        tmp.write_bytes(raw)
        mail = email_ingest.parse_eml(tmp)
        if store.get("emails", mail["message_id"]):
            res["duplicate"] += 1
            continue
        assigned = email_ingest.assign_project(mail)
        if acc.get("only_project", True) and assigned != pid:
            res["other_project"] += 1
            continue
        dest = folder / f"{imap_mail.safe_name(mail['message_id'])}.eml"
        tmp.replace(dest)
        received = mail["received_at"] or datetime.now().astimezone().isoformat(timespec="seconds")
        ingest(dest, received)
        res["new"] += 1
    (folder / "_incoming.eml").unlink(missing_ok=True)
    _record(pid, aid, res)
    store.audit(actor, "project", pid, "mail_sync", after={"account": acc["address"], **res})
    return res


# ---------------------------------------------------------------------------- automatischer Abruf
def sync_all(ingest_for: Callable[[str], Callable[[Path, str], Any]]) -> dict[str, Any]:
    """Alle entsperrten Postfächer aller Projekte abrufen (Fehler je Konto, nie für alle)."""
    out: dict[str, Any] = {}
    for p in store.list_projects():
        for a in p.get("mail_accounts", []):
            if not imap_mail.has_secret(a["account_id"]):
                continue
            try:
                out[a["account_id"]] = sync(p["id"], a["account_id"], ingest_for(p["id"]), "system (Auto-Abruf)")
            except Exception as e:  # noqa: BLE001 – ein defektes Konto darf die anderen nicht aufhalten
                out[a["account_id"]] = {"error": str(e)}
    return out


def start_auto_sync(ingest_for: Callable[[str], Callable[[Path, str], Any]]) -> bool:
    """Hintergrund-Thread: alle AUTO_SYNC_MIN Minuten sync_all. Gesperrte Postfächer (ohne Passwort) werden übersprungen."""
    if AUTO_SYNC_MIN <= 0 or _auto["running"]:
        return False
    _auto["running"] = True

    def loop() -> None:
        while True:
            _auto["next"] = datetime.fromtimestamp(time.time() + AUTO_SYNC_MIN * 60).astimezone().isoformat(timespec="seconds")
            time.sleep(AUTO_SYNC_MIN * 60)
            sync_all(ingest_for)

    threading.Thread(target=loop, name="mail-auto-sync", daemon=True).start()
    return True


def sync_soon(pid: str, aid: str, ingest: Callable[[Path, str], Any]) -> None:
    """Direkt nach Verbinden/Entsperren einmal abrufen, ohne die Anfrage aufzuhalten."""
    if AUTO_SYNC_MIN <= 0:  # automatischer Abruf ganz abgeschaltet
        return
    def run() -> None:
        try:
            sync(pid, aid, ingest, "system (Auto-Abruf)")
        except Exception:  # noqa: BLE001 – Fehler steht in last_result
            pass

    threading.Thread(target=run, name=f"mail-sync-{aid}", daemon=True).start()
