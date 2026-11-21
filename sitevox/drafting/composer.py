"""Briefentwurf: Vorlage als Gerüst (Jinja2), LLM (Qwen3-8B) füllt NUR Sachverhalt + Auswirkungen.

Ablauf
  1. Belege des Ereignisses + berechnete Fakten der Engine (eigener Beleg "Terminplan-Berechnung")
     werden nummeriert: E-01, E-02, ...
  2. LLM schreibt Sätze, jeder mit Beleg-IDs (Schema DraftBody, keine Normzitate erlaubt)
  3. Vorlage rendert Betreff, Bezug, Einleitung, Forderung, Vorbehalt, Gruß – Normzitate nur hier
  4. Faktenprüfung (verify.py) → rote Stellen sperren den Export bis zur manuellen Bestätigung
  5. Felder mit Konfidenz → Review-Queue
Die KI versendet nichts; Status bleibt "Entwurf" bis die Bauleitung freigibt.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from .. import confidence as conf
from .. import llm, rag, settings, store, verify
from ..engine import deviation
from ..prompts import DRAFT_USER, draft_system
from ..schemas import DraftBody, DraftSentence, Letter, LetterField, labels

TEMPLATES = Path(__file__).parent / "templates"
_env = Environment(loader=FileSystemLoader(TEMPLATES), undefined=StrictUndefined, keep_trailing_newline=False)
SECTION_TITLES = {"sachverhalt": "Sachverhalt", "auswirkungen": "Auswirkungen"}
SECTION_TITLES_EN = {"sachverhalt": "Facts", "auswirkungen": "Effects"}
CHECKLIST = {
    "recipient_is_client": "Empfänger ist der Auftraggeber bzw. dessen bevollmächtigter Vertreter",
    "contract_no": "Vertragsnummer korrekt",
    "facts_complete": "Tatsachen, Ursache und voraussichtliche Auswirkungen sind benannt",
    "delivery_proof": "Zustellweg mit Nachweis festgelegt (E-Mail vorab + Einschreiben/Bote)",
}
DELIVERY_DEFAULT = "E-Mail vorab an bevollmächtigten Vertreter, Original per Einschreiben mit Rückschein"
DELIVERY_DEFAULT_EN = "E-mail in advance to the authorised representative, original by registered mail with return receipt"
MONTHS_EN = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
             "November", "December"]
WEEKDAYS = {"de": ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"],
            "en": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]}


_TITLE_EN = [("Sprachmemo", "Voice memo"), ("Foto", "Photo"), ("Notiz", "Note"), ("Dokument", "Document"),
             ("Mail", "E-mail")]


def _title(d: dict, lang: str) -> str:
    """Beleg-Titel (beim Erfassen auf Deutsch angelegt) für englische Schreiben übersetzen."""
    t = d.get("title", "")
    if lang == "en":
        for de, en in _TITLE_EN:
            if t.startswith(de + " "):
                return en + t[len(de):]
    return t


def _lang(letter: dict) -> str:
    return (letter.get("sections", {}).get("meta") or {}).get("language", "de")


def _date(iso: str, lang: str = "de") -> str:
    """de: 20.11.2026 · en: 20 November 2026 (beide Formen erkennt verify)."""
    d = date.fromisoformat(iso[:10])
    return f"{d.day} {MONTHS_EN[d.month - 1]} {d.year}" if lang == "en" else d.strftime("%d.%m.%Y")


def _dt(iso: str, lang: str = "de") -> str:
    dt = datetime.fromisoformat(iso)
    return f"{_date(iso, 'en')}, {dt:%H:%M}" if lang == "en" else dt.strftime("%d.%m.%Y, %H:%M Uhr")


def _de_date(iso: str) -> str:
    return date.fromisoformat(iso[:10]).strftime("%d.%m.%Y")


def _de_dt(iso: str) -> str:
    dt = datetime.fromisoformat(iso)
    return dt.strftime("%d.%m.%Y, %H:%M Uhr")


def _safe_de_dt(v: Any, lang: str = "de") -> str:
    try:
        return _dt(str(v), lang)
    except (ValueError, TypeError):
        return str(v or "")


def _fmt(x: float, lang: str = "de") -> str:
    return f"{x:g}" if lang == "en" else f"{x:g}".replace(".", ",")


# ----------------------------------------------------------------------------- engine facts
def engine_facts(event: dict, analysis: dict, lang: str = "de") -> tuple[list[str], str]:
    en = lang == "en"
    D = lambda iso: _date(iso, lang)  # noqa: E731
    F = lambda x: _fmt(x, lang)  # noqa: E731
    rows = {r["id"]: r for r in analysis["activities"]}
    lines = [f"Programme calculation (as of {D(analysis['date'])}, forecast at current rate):" if en else
             f"Terminplan-Berechnung (Stand {D(analysis['date'])}, Prognose bei aktuellem Tempo):"]
    for aid in event["activity_ids"]:
        r = rows.get(aid)
        if not r:
            continue
        if r["today"]["soll"]:
            pct = round(100 * r["today"]["ratio"]) if r["today"]["ratio"] is not None else 0
            lines.append(
                f"Daily output {r['name']} on {D(analysis['date'])}: {F(r['today']['ist'])} {r['unit']} of "
                f"{F(r['today']['soll'])} {r['unit']} daily target ({pct} %)." if en else
                f"Tagesleistung {r['name']} am {D(analysis['date'])}: {F(r['today']['ist'])} "
                f"{r['unit']} von {F(r['today']['soll'])} {r['unit']} Tagessoll ({pct} %).")
        crit = (" (critical path)" if en else " (kritischer Pfad)") if r["critical"] else ""
        lines.append(
            f"{r['name']}: planned finish {D(r['planned_finish'])}, forecast finish {D(r['forecast_finish'])}, "
            f"delay {r['delay_days']} working days{crit}." if en else
            f"{r['name']}: geplantes Ende {D(r['planned_finish'])}, prognostiziertes Ende "
            f"{D(r['forecast_finish'])}, Verzug {r['delay_days']} Arbeitstage{crit}.")
    for ch in analysis["impact"]:
        if ch["root"] in event["activity_ids"]:
            for aid, r in rows.items():
                if r["delay_days"] > 0 and aid not in event["activity_ids"] and r["kind"] != "milestone" and \
                        r["name"] in ch["text"]:
                    lines.append(
                        f"Subsequent activity {r['name']}: planned {D(r['planned_start'])} to "
                        f"{D(r['planned_finish'])}, forecast {D(r['forecast_start'])} to {D(r['forecast_finish'])}."
                        if en else
                        f"Folgevorgang {r['name']}: geplant {D(r['planned_start'])} bis "
                        f"{D(r['planned_finish'])}, prognostiziert {D(r['forecast_start'])} "
                        f"bis {D(r['forecast_finish'])}.")
            for m in analysis["milestones"]:
                if m["overrun_days"] > 0 and m["name"] in ch["text"]:
                    lines.append(
                        f"{m['name']} on {D(m['date'])}: forecast {D(m['forecast'])}, exceeded by "
                        f"{m['overrun_days']} working days." if en else
                        f"{m['name']} am {D(m['date'])}: Prognose {D(m['forecast'])}, "
                        f"Überschreitung um {m['overrun_days']} Arbeitstage.")
    if event.get("blocked_until"):
        d = date.fromisoformat(event["blocked_until"])
        wd = WEEKDAYS["en" if en else "de"][d.weekday()]
        lines.append(f"Blocked until probably {wd}, {D(event['blocked_until'])} (according to evidence)." if en else
                     f"Blockade bis voraussichtlich {wd}, {D(event['blocked_until'])} (laut Beleg).")
    if event["type"] == "additional_work" and event["attrs"].get("not_in_lv"):
        lines.append("Comparison with the bill of quantities: no matching item." if en else
                     "Abgleich Leistungsverzeichnis: keine passende Position vorhanden.")
    return lines, "\n".join(lines)


# ----------------------------------------------------------------------------- LLM body
def _fallback_body(ev_list: list[tuple[str, dict]], engine_ref: str, facts: list[str], lang: str = "de") -> DraftBody:
    sv = []
    for ref, d in ev_list:
        if d["source"] in ("engine", "contract", "weather") or not verify.counts_as_evidence(d):
            continue  # KI-Beobachtungen sind kein Beleg → nicht als Sachverhalt zitieren
        when = _dt(d["captured_at"], lang) if d.get("captured_at") else ""
        q = re.sub(r"\s+", " ", d.get("quote", "")).strip().rstrip(".")
        if q:
            sv.append(DraftSentence(text=f"{_title(d, lang)} ({when}): “{q}”." if lang == "en" else
                                    f"{d['title']} ({when}): „{q}“.", evidence=[ref]))
    aw = [DraftSentence(text=f, evidence=[engine_ref]) for f in facts[1:]] or \
         [DraftSentence(text="The effects on the construction schedule are currently being determined." if lang == "en"
                        else "Die Auswirkungen auf den Bauablauf werden derzeit ermittelt.", evidence=[engine_ref])]
    return DraftBody(sachverhalt=sv[:5] or [DraftSentence(text="See enclosures." if lang == "en" else "Siehe Anlagen.",
                                                          evidence=[engine_ref])],
                     auswirkungen=aw[:5])


def _ev_line(ref: str, d: dict, lang: str = "de") -> str:
    head = (f"[{ref}] {_title(d, lang)} ({d['source']}{', ' + _dt(d['captured_at'], lang) if d.get('captured_at') else ''}"
            f"{', S. ' + str(d['page']) if d.get('page') else ''})")
    if verify.is_ai_observation(d) and not verify.counts_as_evidence(d):
        head += " [KI-Beobachtung, KEIN Beleg – nicht als Tatsache darstellen]"
    elif d["source"] == "photo":
        head += " [Fotodatei – Anlage]"
    return f"{head}: {d.get('quote') or d.get('full_text', '')[:400]}"


def _llm_body(event: dict, kind: str, ev_list: list[tuple[str, dict]], engine_ref: str, facts: list[str],
              lang: str = "de") -> DraftBody:
    ev_labels, kind_labels = labels(lang)
    ev_txt = "\n".join(_ev_line(ref, d, lang) for ref, d in ev_list)
    msgs = [{"role": "system", "content": draft_system(lang)},
            {"role": "user", "content": DRAFT_USER.format(
                kind_label=kind_labels[kind], event_label=ev_labels[event["type"]],
                description=event["description"], engine_id=engine_ref, facts="\n".join(facts), evidence=ev_txt)}]
    fx = f"draft_{event['type']}_{event['date']}" + ("_en" if lang == "en" else "")  # Demo: dt. Fixture nur für de
    return llm.get("drafter").structured(DraftBody, msgs, n=1, fixture=(event["project_id"], fx),
                                         fallback=lambda: _fallback_body(ev_list, engine_ref, facts, lang))[0]


# ----------------------------------------------------------------------------- render
def render(letter: dict) -> list[dict[str, Any]]:
    """Rendert die Vorlage mit aktuellen Feldwerten; LLM-Sätze werden an [[...]] eingesetzt."""
    project = settings.project_cfg(letter["project_id"])
    lang = _lang(letter)
    f = {k: v["value"] for k, v in letter["fields"].items()}
    ctx = {
        "project": project, "company": settings.baseline()["company"], "f": f,
        "event_label": letter["sections"]["meta"]["event_label"],
        "contract_date": _date(project["contract_date"], lang),
        "start_de": _safe_de_dt(f.get("event_start"), lang),
    }
    text = _env.get_template(f"{letter['kind']}{'.en' if lang == 'en' else ''}.j2").render(**ctx)
    titles = SECTION_TITLES_EN if lang == "en" else SECTION_TITLES
    out = []
    for block in re.split(r"(?m)^### ", text):
        if not block.strip():
            continue
        key, _, body = block.partition("\n")
        key = key.strip()
        if body.strip() in ("[[SACHVERHALT]]", "[[AUSWIRKUNGEN]]"):
            out.append({"key": key, "title": titles[key], "sentences": letter["sections"]["llm"][key]})
        else:
            out.append({"key": key, "text": body.strip()})
    return out


def _evidence_docs(letter: dict) -> dict[str, dict]:
    return {eid: store.evidence(eid) or {} for eid in letter["evidence_map"].values()}


def reverify(letter: dict) -> dict:
    prev = {(i["section"], i["sentence"], i["kind"], i["value"]): i for i in letter.get("issues", [])}
    issues = verify.verify_sentences(letter["sections"]["llm"], letter["evidence_map"], _evidence_docs(letter))
    for i in issues:
        p = prev.get((i.section, i.sentence, i.kind, i.value))
        if p and p["status"] == "confirmed" and i.status in ("unverified", "needs_confirmation"):
            i.status = "confirmed"
            i.message = p.get("message", "")
    letter["issues"] = [i.model_dump() for i in issues]
    letter["rendered"] = render(letter)
    return letter


# ----------------------------------------------------------------------------- create
def _field(key: str, label: str, value: Any, c: dict | float, evidence_ids: list[str], note: str = "") -> LetterField:
    v = c if isinstance(c, (int, float)) else c["value"]
    return LetterField(key=key, label=label, value=value, confidence=v, evidence_ids=evidence_ids,
                       importance=conf.importance(key), note=note)


def create_letter(event_id: str, actor: str = "ai", kind: Optional[str] = None, language: str = "de") -> dict:
    """language (de|en) = UI-Sprache: Vorlage, KI-Sätze und Datumsformat; Zitate aus Belegen bleiben im Original."""
    from ..pipeline import new_evidence  # zirkulären Import vermeiden

    event = store.get("events", event_id)
    if event is None:
        raise KeyError(event_id)
    kind = kind or event["recommended_document"]["kind"]
    if kind not in ("behinderungsanzeige", "mehrkostenankuendigung", "nachtragsankuendigung", "bedenkenanzeige"):
        raise ValueError(f"Für {kind} wird kein Schreiben an den AG erstellt (nur Bautagebuch/intern).")
    pid = event["project_id"]
    project = settings.project_cfg(pid)
    analysis = deviation.analyze(pid, date.fromisoformat(event["date"]))
    lang = settings.output_language(language)
    ev_labels, kind_labels = labels(lang)
    facts, facts_text = engine_facts(event, analysis, lang)
    eng = new_evidence(project_id=pid, source="engine",
                       title="Programme calculation (SiteVox engine)" if lang == "en" else
                       "Terminplan-Berechnung (SiteVox-Engine)",
                       quote=facts_text, full_text=facts_text, captured_at=analysis["date"] + "T17:00:00")

    # Beleg-Nummerierung E-01 ...: Kernbelege, Stammdaten, Engine; danach Foto-Ableitungen
    # (Ausschnitte, Detailfoto, KI-Beobachtungen) – so bleibt die Nummerierung der Kernbelege stabil.
    def _derived(eid: str) -> bool:
        d = store.evidence(eid) or {}
        return d.get("source") == "ai_vision" or (d.get("meta") or {}).get("role") in ("crop", "detail")

    core = [i for i in event["evidence"] if not _derived(i)]
    derived = [i for i in event["evidence"] if _derived(i)]
    ev_ids = core + derived
    master = [e for e in store.project_evidence(pid) if e["source"] == "contract" and e["meta"].get("master")]
    legal_hits = rag.index().search(event["recommended_document"]["basis"] or kind, collection="legal", k=1)
    evidence_map: dict[str, str] = {}
    for i, eid in enumerate(core + [m["evidence_id"] for m in master] + [eng.evidence_id] + derived, start=1):
        evidence_map[f"E-{i:02d}"] = eid
    inv = {v: k for k, v in evidence_map.items()}
    engine_ref = inv[eng.evidence_id]
    ev_list = [(inv[eid], store.evidence(eid)) for eid in ev_ids if store.evidence(eid)] + [
        (engine_ref, eng.model_dump())]
    body = _llm_body(event, kind, ev_list, engine_ref, facts, lang)

    ec = event["confidence"]["fields"]
    client = project["client"]
    master_ids = [m["evidence_id"] for m in master]
    legal_rel = legal_hits[0]["relevance"] if legal_hits else None
    fields = {
        "recipient": _field("recipient", "Empfänger",
                            f"{client['name']}, {'attn.' if lang == 'en' else 'z. Hd.'} {client['representative']} "
                            f"({client['representative_role']})",
                            conf.combine(n_evidence=len(master_ids), consistency=1.0, rule_ok=True), master_ids,
                            "aus Vertragsstammdaten"),
        "contract_no": _field("contract_no", "Vertragsnummer", project["contract_no"],
                              conf.combine(n_evidence=len(master_ids), consistency=1.0, rule_ok=True), master_ids),
        "event_start": _field("event_start", "Beginn des Ereignisses", event["start"], ec.get("start", 0.0),
                              event["attrs"].get("field_stats", {}).get("start", {}).get("evidence", ev_ids)),
        "cause": _field("cause", "Ursache", event["cause"], ec.get("cause", 0.0), ev_ids),
        "sphere": _field("sphere", "Risikosphäre (Vorschlag)", event["sphere"], ec.get("sphere", 0.0), ev_ids,
                         event.get("sphere_rule", "")),
        "affected_activities": _field("affected_activities", "Betroffene Vorgänge", event["affected_activities"],
                                      ec.get("affected_activities", 0.0), ev_ids),
        "impact_estimate_days": _field("impact_estimate_days", "Voraussichtliche Auswirkung (AT)",
                                       event["impact_estimate_days"]["value"],
                                       event["impact_estimate_days"]["confidence"], [eng.evidence_id],
                                       "berechnet von der Engine; Eingangsgrößen aus Belegen"),
        "legal_basis": _field("legal_basis", "Rechtsgrundlage (aus Vorlage)", event["recommended_document"]["basis"]
                              if kind == event["recommended_document"]["kind"] else kind,
                              conf.combine(n_evidence=1 if legal_hits else 0, retrieval=legal_rel, consistency=1.0,
                                           rule_ok=not event["warnings"] or None),
                              [], "Normzitat ausschließlich aus Vorlage"),
        "delivery_method": _field("delivery_method", "Zustellweg", DELIVERY_DEFAULT_EN if lang == "en" else
                                  DELIVERY_DEFAULT, 0.6, [],
                                  "Firmenstandard – bitte bestätigen"),
    }
    if event["impact_estimate_days"]["value"] is None:
        fields.pop("impact_estimate_days")  # z. B. Mehrkosten ohne Terminwirkung
    now = store.now_iso()
    lid = store.next_id("DOC-", 3)
    letter = Letter(
        letter_id=lid, project_id=pid, event_id=event_id, kind=kind, fields=fields,
        sections={"llm": {"sachverhalt": [s.model_dump() for s in body.sachverhalt],
                          "auswirkungen": [s.model_dump() for s in body.auswirkungen]},
                  "meta": {"event_label": ev_labels[event["type"]], "kind_label": kind_labels[kind], "language": lang}},
        evidence_map=evidence_map, checklist={k: False for k in CHECKLIST}, created_at=now, updated_at=now,
    ).model_dump(mode="json")
    letter = reverify(letter)
    letter["legal_refs"] = [{"title": h["title"], "text": h["text"], "doc": h["doc_title"]} for h in legal_hits]
    store.save_letter(letter)
    event["letter_id"], event["status"] = lid, "draft"
    store.save_event(event)
    store.audit(actor, "letter", lid, "create", after={"event": event_id, "kind": kind,
                                                       "issues": len(verify.blocking(letter["issues"]))})
    return letter


# ----------------------------------------------------------------------------- human actions
def field_action(letter_id: str, key: str, action: str, actor: str, value: Any = None) -> dict:
    letter = store.get("letters", letter_id)
    if letter["status"] != "Entwurf":
        raise ValueError("Nur Entwürfe sind bearbeitbar")
    f = letter["fields"][key]
    before = {"value": f["value"], "status": f["status"]}
    if action == "accept":
        f["status"] = "accepted"
    elif action == "edit":
        f["value"], f["status"], f["confidence"] = value, "edited", 1.0
    elif action == "reject":
        f["status"] = "rejected"
    else:
        raise ValueError(action)
    letter["updated_at"] = store.now_iso()
    letter = reverify(letter)
    store.save_letter(letter)
    store.audit(actor, "letter", letter_id, f"field_{action}", before={key: before},
                after={key: {"value": f["value"], "status": f["status"]}})
    return letter


def accept_all_fields(letter_id: str, actor: str) -> dict:
    """Alle noch offenen Felder übernehmen (bearbeitete/verworfene bleiben unverändert). Ein Audit-Eintrag.
    Ersetzt NICHT die Faktenprüfung (rote Werte) und die Checkliste – die bleiben bewusste Einzelentscheidungen."""
    letter = store.get("letters", letter_id)
    if letter["status"] != "Entwurf":
        raise ValueError("Nur Entwürfe sind bearbeitbar")
    keys = [k for k, f in letter["fields"].items() if f["status"] == "pending"]
    for k in keys:
        letter["fields"][k]["status"] = "accepted"
    if keys:
        letter["updated_at"] = store.now_iso()
        letter = reverify(letter)
        store.save_letter(letter)
        store.audit(actor, "letter", letter_id, "field_accept_all",
                    after={k: {"value": letter["fields"][k]["value"], "status": "accepted"} for k in keys})
    return letter


def edit_sentence(letter_id: str, section: str, idx: int, text: str, actor: str,
                  evidence: Optional[list[str]] = None) -> dict:
    letter = store.get("letters", letter_id)
    s = letter["sections"]["llm"][section][idx]
    before = dict(s)
    s["text"] = text
    if evidence is not None:
        s["evidence"] = evidence
    s["edited"] = True
    letter["updated_at"] = store.now_iso()
    letter = reverify(letter)
    store.save_letter(letter)
    store.audit(actor, "letter", letter_id, "edit_sentence", before=before, after=s)
    return letter


def confirm_issue(letter_id: str, issue_id: str, actor: str, note: str = "") -> dict:
    letter = store.get("letters", letter_id)
    for i in letter["issues"]:
        if i["issue_id"] == issue_id:
            i["status"], i["message"] = "confirmed", f"manuell bestätigt: {note}".strip()
            store.audit(actor, "letter", letter_id, "confirm_fact", after=i, note=note)
    store.save_letter(letter)
    return letter


def set_checklist(letter_id: str, key: str, value: bool, actor: str) -> dict:
    letter = store.get("letters", letter_id)
    letter["checklist"][key] = bool(value)
    store.save_letter(letter)
    store.audit(actor, "letter", letter_id, "checklist", after={key: bool(value)})
    return letter


def release_blockers(letter: dict) -> list[str]:
    b = []
    for i in verify.blocking(letter["issues"]):
        where = f"({i['section']} Satz {i['sentence'] + 1})"
        b.append(f"KI-Beobachtung bestätigen: {i['value']} {where}" if i["status"] == "needs_confirmation"
                 else f"Nicht belegt: {i['kind']} „{i['value']}“ {where}")
    for k, f in letter["fields"].items():
        if f["status"] == "pending" and conf.band(f["confidence"]) == "red":
            b.append(f"Feld „{f['label']}“ unsicher – bitte übernehmen, bearbeiten oder verwerfen")
        if f["status"] == "rejected" and k in ("recipient", "contract_no", "legal_basis"):
            b.append(f"Pflichtfeld „{f['label']}“ verworfen")
    for k, ok in letter["checklist"].items():
        if not ok:
            b.append(f"Checkliste: {CHECKLIST[k]}")
    return b


def release(letter_id: str, actor: str) -> dict:
    """Freigeben = menschliche Entscheidung. Erzeugt Exporte, versendet NICHTS."""
    from ..export import docx_export, outlook

    letter = store.get("letters", letter_id)
    blockers = release_blockers(letter)
    if blockers:
        raise PermissionError("; ".join(blockers))
    letter = reverify(letter)
    letter["status"], letter["released_at"], letter["released_by"] = "Geprüft", store.now_iso(), actor
    paths = docx_export.letter_docx(letter)
    letter["exports"] = paths
    letter["exports"]["eml"] = str(outlook.write_eml_draft(letter, Path(paths["docx"])))
    store.save_letter(letter)
    ev = store.get("events", letter["event_id"])
    ev["status"] = "released"
    store.save_event(ev)
    store.audit(actor, "letter", letter_id, "release", after={"exports": letter["exports"]})
    return letter


def mark_sent(letter_id: str, actor: str, method: str, sent_at: Optional[str] = None) -> dict:
    """Nur die Bauleitung markiert als versendet – nachdem sie selbst in Outlook auf Senden geklickt hat."""
    letter = store.get("letters", letter_id)
    if letter["status"] != "Geprüft":
        raise ValueError("Nur freigegebene Schreiben können als versendet markiert werden")
    letter["status"], letter["sent_at"] = "Versendet", sent_at or store.now_iso()
    letter["sent_method"] = method
    store.save_letter(letter)
    ev = store.get("events", letter["event_id"])
    ev["status"], ev["sent_at"] = "sent", letter["sent_at"]
    store.save_event(ev)
    store.audit(actor, "letter", letter_id, "mark_sent", after={"method": method, "sent_at": letter["sent_at"]})
    return letter


def revoke(letter_id: str, actor: str, note: str) -> dict:
    """Eine Stufe zurück (menschliche Korrektur, mit Begründung im Audit-Log):
    Versendet → Geprüft (Versand-Markierung zurücknehmen), Geprüft → Entwurf (Freigabe zurückziehen),
    Verworfen → Entwurf (wiederherstellen, danach normal prüfen und freigeben).
    Feldentscheidungen und Checkliste bleiben erhalten; die erneute Freigabe prüft alle Blocker wieder."""
    if not note.strip():
        raise ValueError("Begründung erforderlich")
    letter = store.get("letters", letter_id)
    ev = store.get("events", letter["event_id"])
    before = {"status": letter["status"]}
    if letter["status"] == "Versendet":
        letter["status"], letter["sent_at"], letter["sent_method"] = "Geprüft", None, None
        ev["status"], ev["sent_at"] = "released", None
        action = "revoke_sent"
    elif letter["status"] == "Geprüft":
        letter["status"], letter["released_at"], letter["released_by"] = "Entwurf", None, None
        letter["exports"] = {}  # Downloads gesperrt; neue Freigabe erzeugt die Dateien neu
        ev["status"] = "draft"
        action = "revoke_release"
    elif letter["status"] == "Verworfen":
        letter["status"] = "Entwurf"
        ev["status"] = "draft"
        action = "restore"
    else:
        raise ValueError("Nur freigegebene, versendete oder verworfene Schreiben können zurückgenommen werden")
    letter["updated_at"] = store.now_iso()
    store.save_letter(letter)
    store.save_event(ev)
    store.audit(actor, "letter", letter_id, action, before=before, after={"status": letter["status"]}, note=note)
    return letter


def reject_letter(letter_id: str, actor: str, note: str = "") -> dict:
    letter = store.get("letters", letter_id)
    letter["status"] = "Verworfen"
    store.save_letter(letter)
    store.audit(actor, "letter", letter_id, "reject", note=note)
    return letter


def review_queue(letter: dict) -> list[dict]:
    """Unsicherste Stellen zuerst: (1 − Konfidenz) × Wichtigkeit; rote Faktenprüfung immer oben."""
    q = []
    for i in letter["issues"]:
        if i["status"] in ("unverified", "needs_confirmation"):
            red = i["status"] == "unverified"
            q.append({"type": "fact", "id": i["issue_id"],
                      "label": f"{i['kind']}: {i['value']}" if red else f"KI-Beobachtung: {i['value']}",
                      "section": i["section"], "sentence": i["sentence"], "priority": 2.0 if red else 1.8,
                      "band": "red" if red else "yellow", "message": i["message"]})
    for k, f in letter["fields"].items():
        if f["status"] == "pending":
            q.append({"type": "field", "id": k, "label": f["label"], "priority": conf.priority(f["confidence"], k),
                      "band": conf.band(f["confidence"]), "confidence": f["confidence"]})
    return sorted(q, key=lambda x: -x["priority"])
