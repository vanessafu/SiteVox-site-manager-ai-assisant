"""SQLite-Ablage. Dokumente als JSON mit wenigen indizierten Spalten – bewusst schlicht."""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Optional

from . import settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects   (id TEXT PRIMARY KEY, doc TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS activities (project_id TEXT, id TEXT, doc TEXT NOT NULL, PRIMARY KEY(project_id, id));
CREATE TABLE IF NOT EXISTS progress   (project_id TEXT, activity_id TEXT, date TEXT, qty REAL,
                                       evidence_id TEXT, PRIMARY KEY(project_id, activity_id, date));
CREATE TABLE IF NOT EXISTS staffing   (project_id TEXT, date TEXT, crew TEXT, present INTEGER, planned INTEGER,
                                       evidence_id TEXT, PRIMARY KEY(project_id, date, crew));
CREATE TABLE IF NOT EXISTS captures   (id TEXT PRIMARY KEY, project_id TEXT, date TEXT, kind TEXT,
                                       captured_at TEXT, status TEXT, doc TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS evidence   (id TEXT PRIMARY KEY, project_id TEXT, capture_id TEXT, doc TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS events     (id TEXT PRIMARY KEY, project_id TEXT, date TEXT, doc TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS letters    (id TEXT PRIMARY KEY, project_id TEXT, event_id TEXT, doc TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS emails     (id TEXT PRIMARY KEY, project_id TEXT, received_at TEXT, doc TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS documents  (id TEXT PRIMARY KEY, project_id TEXT, doc TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS weather    (project_id TEXT, date TEXT, doc TEXT NOT NULL, PRIMARY KEY(project_id, date));
CREATE TABLE IF NOT EXISTS audit      (id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, actor TEXT, entity TEXT,
                                       entity_id TEXT, action TEXT, before TEXT, after TEXT, note TEXT);
CREATE TABLE IF NOT EXISTS counters   (name TEXT PRIMARY KEY, value INTEGER);
CREATE INDEX IF NOT EXISTS ix_captures_pd ON captures(project_id, date);
CREATE INDEX IF NOT EXISTS ix_events_pd ON events(project_id, date);
"""

_local = threading.local()


def connect(path: Optional[Path] = None) -> sqlite3.Connection:
    path = Path(path or settings.db_path())
    key = str(path)
    conns = getattr(_local, "conns", None)
    if conns is None:
        conns = _local.conns = {}
    if key not in conns:
        path.parent.mkdir(parents=True, exist_ok=True)
        c = sqlite3.connect(path, check_same_thread=False)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        c.executescript(SCHEMA)
        conns[key] = c
    return conns[key]


def reset(path: Optional[Path] = None) -> None:
    path = Path(path or settings.db_path())
    conns = getattr(_local, "conns", {})
    if str(path) in conns:
        conns.pop(str(path)).close()
    for suffix in ("", "-wal", "-shm"):
        Path(str(path) + suffix).unlink(missing_ok=True)


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def next_id(prefix: str, width: int = 3) -> str:
    c = connect()
    cur = c.execute("SELECT value FROM counters WHERE name=?", (prefix,)).fetchone()
    v = (cur["value"] if cur else 0) + 1
    c.execute("INSERT OR REPLACE INTO counters(name, value) VALUES(?,?)", (prefix, v))
    c.commit()
    return f"{prefix}{v:0{width}d}"


def _dump(doc: Any) -> str:
    if hasattr(doc, "model_dump"):
        doc = doc.model_dump(mode="json")
    return json.dumps(doc, ensure_ascii=False)


# ---------------------------------------------------------------------------- generic
def put(table: str, doc: Any, **cols: Any) -> None:
    c = connect()
    names = list(cols) + ["doc"]
    values = list(cols.values()) + [_dump(doc)]
    c.execute(
        f"INSERT OR REPLACE INTO {table}({','.join(names)}) VALUES({','.join('?' * len(names))})", values
    )
    c.commit()


def get(table: str, id_: str) -> Optional[dict]:
    row = connect().execute(f"SELECT doc FROM {table} WHERE id=?", (id_,)).fetchone()
    return json.loads(row["doc"]) if row else None


def query(table: str, where: str = "1=1", params: Iterable[Any] = (), order: str = "") -> list[dict]:
    sql = f"SELECT doc FROM {table} WHERE {where}" + (f" ORDER BY {order}" if order else "")
    return [json.loads(r["doc"]) for r in connect().execute(sql, tuple(params)).fetchall()]


# ---------------------------------------------------------------------------- typed helpers
def save_project(p: dict) -> None:
    put("projects", p, id=p["id"])


def list_projects() -> list[dict]:
    return query("projects", order="id")


def save_activity(project_id: str, a: dict) -> None:
    put("activities", a, project_id=project_id, id=a["id"])


def activities(project_id: str) -> list[dict]:
    return query("activities", "project_id=?", (project_id,), order="id")


def save_progress(project_id: str, activity_id: str, date: str, qty: float, evidence_id: str | None) -> None:
    c = connect()
    c.execute(
        "INSERT OR REPLACE INTO progress VALUES(?,?,?,?,?)", (project_id, activity_id, date, qty, evidence_id)
    )
    c.commit()


def progress(project_id: str) -> list[dict]:
    rows = connect().execute(
        "SELECT activity_id, date, qty, evidence_id FROM progress WHERE project_id=? ORDER BY date", (project_id,)
    )
    return [dict(r) for r in rows.fetchall()]


def save_staffing(project_id: str, date: str, crew: str, present: int, planned: int, evidence_id: str | None):
    c = connect()
    c.execute(
        "INSERT OR REPLACE INTO staffing VALUES(?,?,?,?,?,?)", (project_id, date, crew, present, planned, evidence_id)
    )
    c.commit()


def staffing(project_id: str, date: str) -> list[dict]:
    rows = connect().execute("SELECT * FROM staffing WHERE project_id=? AND date=?", (project_id, date))
    return [dict(r) for r in rows.fetchall()]


def save_capture(cap: dict) -> None:
    put("captures", cap, id=cap["capture_id"], project_id=cap["project_id"], date=cap["date"],
        kind=cap["kind"], captured_at=cap["captured_at"], status=cap.get("status", "new"))


def captures(project_id: str, date: str | None = None) -> list[dict]:
    if date:
        return query("captures", "project_id=? AND date=?", (project_id, date), order="captured_at")
    return query("captures", "project_id=?", (project_id,), order="captured_at")


def save_evidence(ev: Any) -> None:
    d = ev.model_dump(mode="json") if hasattr(ev, "model_dump") else ev
    put("evidence", d, id=d["evidence_id"], project_id=d["project_id"], capture_id=d.get("capture_id"))


def evidence(evidence_id: str) -> Optional[dict]:
    return get("evidence", evidence_id)


def evidence_many(ids: Iterable[str]) -> list[dict]:
    out = []
    for i in ids:
        e = evidence(i)
        if e:
            out.append(e)
    return out


def project_evidence(project_id: str) -> list[dict]:
    return query("evidence", "project_id=?", (project_id,), order="id")


def save_event(ev: Any) -> None:
    d = ev.model_dump(mode="json") if hasattr(ev, "model_dump") else ev
    put("events", d, id=d["event_id"], project_id=d["project_id"], date=d["date"])


def events(project_id: str, date: str | None = None) -> list[dict]:
    if date:
        return query("events", "project_id=? AND date=?", (project_id, date), order="id")
    return query("events", "project_id=?", (project_id,), order="id")


def save_letter(l: Any) -> None:
    d = l.model_dump(mode="json") if hasattr(l, "model_dump") else l
    put("letters", d, id=d["letter_id"], project_id=d["project_id"], event_id=d["event_id"])


def letters(project_id: str) -> list[dict]:
    return query("letters", "project_id=?", (project_id,), order="id")


def save_email(m: dict) -> None:
    put("emails", m, id=m["message_id"], project_id=m["project_id"], received_at=m["received_at"])


def emails(project_id: str) -> list[dict]:
    return query("emails", "project_id=?", (project_id,), order="received_at DESC")


def save_document(d: dict) -> None:
    put("documents", d, id=d["doc_id"], project_id=d["project_id"])


def documents(project_id: str | None = None) -> list[dict]:
    if project_id:
        return query("documents", "project_id=? OR project_id='_legal'", (project_id,), order="id")
    return query("documents", order="id")


def save_weather(project_id: str, date: str, w: dict) -> None:
    put("weather", w, project_id=project_id, date=date)


def weather(project_id: str, date: str) -> Optional[dict]:
    row = connect().execute("SELECT doc FROM weather WHERE project_id=? AND date=?", (project_id, date)).fetchone()
    return json.loads(row["doc"]) if row else None


def audit(actor: str, entity: str, entity_id: str, action: str, before: Any = None, after: Any = None,
          note: str = "") -> None:
    c = connect()
    c.execute(
        "INSERT INTO audit(ts, actor, entity, entity_id, action, before, after, note) VALUES(?,?,?,?,?,?,?,?)",
        (now_iso(), actor, entity, entity_id, action,
         json.dumps(before, ensure_ascii=False) if before is not None else None,
         json.dumps(after, ensure_ascii=False) if after is not None else None, note),
    )
    c.commit()


def audit_log(entity_id: str | None = None) -> list[dict]:
    c = connect()
    if entity_id:
        rows = c.execute("SELECT * FROM audit WHERE entity_id=? ORDER BY id DESC", (entity_id,))
    else:
        rows = c.execute("SELECT * FROM audit ORDER BY id DESC LIMIT 500")
    out = []
    for r in rows.fetchall():
        d = dict(r)
        for k in ("before", "after"):
            if d[k]:
                d[k] = json.loads(d[k])
        out.append(d)
    return out


# ---------------------------------------------------------------------------- delete / raw
def delete(table: str, id_: str) -> None:
    c = connect()
    c.execute(f"DELETE FROM {table} WHERE id=?", (id_,))
    c.commit()


def execute(sql: str, params: Iterable[Any] = ()) -> int:
    c = connect()
    cur = c.execute(sql, tuple(params))
    c.commit()
    return cur.rowcount


def evidence_by_capture(capture_id: str) -> list[dict]:
    return query("evidence", "capture_id=?", (capture_id,), order="id")


def delete_activity(project_id: str, activity_id: str) -> None:
    execute("DELETE FROM activities WHERE project_id=? AND id=?", (project_id, activity_id))
    execute("DELETE FROM progress WHERE project_id=? AND activity_id=?", (project_id, activity_id))
