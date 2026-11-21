#!/usr/bin/env python3
"""Fehlerinjektion für sitevox/verify.py – fast kostenlos viele Testfälle aus wenigen echten Schreiben.

Nimmt die Sätze vorhandener Entwürfe (DB) samt Belegen und erzeugt je Satz gezielt Fehler:
  number   – Zahl ändern (14 → 15)            time     – Uhrzeit verschieben (07:30 → 08:30)
  date     – Datum verschieben (18.11. → 21.11.)  entity – Firmen-/Personenname tauschen
  legal    – Normzitat in KI-Text einfügen     uncited  – Beleg-IDs entfernen
  bad_cite – nicht existierende Beleg-ID      added_claim – zusätzlicher Satz mit unbelegter Zahl
Schwere Fälle (by design schwer für einen String-Abgleich – zeigen die Grenzen ehrlich):
  hard_number_swap – Zahl durch eine Zahl ersetzen, die in einem ANDEREN Beleg vorkommt
  hard_entity_swap – Name durch einen anderen bekannten Namen aus den Belegen ersetzen (falsche Zuordnung)
  hard_negation    – Aussage verneinen / Verneinung entfernen
Gemessen: Erkennungsrate je Fehlerart (neue „unverified“-Meldung im veränderten Satz) und
Fehlalarme auf den unveränderten Originalen.

  python -m evaluation.eval_verify --project BV-RIEM --out outputs/eval/verify
"""
from __future__ import annotations

import argparse
import copy
import json
import random
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evaluation import metrics as M  # noqa: E402
from sitevox import store, verify  # noqa: E402

# erwartete Meldungsart je Fehler (zählt als „aus dem richtigen Grund erkannt“)
EXPECT = {"number": "number", "time": "time", "date": "date", "entity": "entity", "legal": "legal_ref",
          "uncited": "uncited", "bad_cite": "citation", "added_claim": "number",
          "hard_number_swap": "number", "hard_entity_swap": "entity", "hard_negation": None}
FAKE_ENTITIES = ["Ingenieurbüro Hartmann", "Kowalski Bau GmbH", "Herr Yılmaz", "Frau Nowak"]


def _key(i) -> tuple:
    return (i.section, i.sentence, i.kind, i.value)


def perturbations(text: str, hay: dict, rng: random.Random) -> list[tuple[str, str]]:
    """[(fehlerart, neuer_text)] – nur Werte, die in KEINEM Beleg vorkommen (sonst wäre der Fehler unsichtbar)."""
    out = []
    stripped = verify._strip_dates_times(verify._numwords_to_digits(text))
    nums = [m for m in verify.NUM_RE.finditer(stripped)]
    if nums:
        m = rng.choice(nums)
        old = m.group(1)
        base = float(old.replace(",", "."))
        for k in (1, 2, 3, 7, 11):
            new = f"{base + k:g}".replace(".", ",")
            if verify._norm_num(new) not in hay["numbers"] and re.search(rf"(?<![\d.,]){re.escape(old)}(?![\d])", text):
                out.append(("number", re.sub(rf"(?<![\d.,]){re.escape(old)}(?![\d])", new, text, count=1)))
                break
    tm = re.search(r"\b(\d{1,2}):(\d{2})\b", text)
    if tm:
        for dh in (1, 2, 3):
            h = (int(tm.group(1)) + dh) % 24
            if h * 60 + int(tm.group(2)) not in hay["times"]:
                out.append(("time", text[:tm.start()] + f"{h:02d}:{tm.group(2)}" + text[tm.end():]))
                break
    dm = re.search(r"\b(\d{1,2})\.(\d{1,2})\.(\d{4})?", text)
    if dm:
        for dd in (3, 5, 9):
            d = (int(dm.group(1)) + dd - 1) % 28 + 1
            if not verify._date_ok((d, int(dm.group(2)), None), hay):
                out.append(("date", text[:dm.start()] + f"{d:02d}.{dm.group(2)}." + (dm.group(3) or "")
                            + text[dm.end():]))
                break
    ents = sorted(verify._entities_in(text), key=len, reverse=True)
    if ents:
        fake = next(f for f in FAKE_ENTITIES if f.lower() not in hay["text"])
        out.append(("entity", text.replace(ents[0], fake, 1)))
    out.append(("legal", text.rstrip(".") + " gemäß § 6 Abs. 1 VOB/B."))
    # --- schwere Fälle
    own = verify._numbers_in(text)
    other = sorted(hay["numbers"] - own, key=lambda x: (len(x), x))
    if nums and other:
        old = nums[0].group(1)
        new = other[rng.randrange(len(other))].replace(".", ",")
        pat = rf"(?<![\d.,]){re.escape(old)}(?![\d])"
        if re.search(pat, text):
            out.append(("hard_number_swap", re.sub(pat, new, text, count=1)))
    known = [e for e in verify.known_entities() if e.lower() in hay["text"]]
    if ents:
        alt = [e for e in known if e.lower() not in text.lower()]
        if alt:
            out.append(("hard_entity_swap", text.replace(ents[0], alt[0], 1)))
    neg = re.search(r"\b(nicht|kein|keine|keinen)\s", text)
    if neg:
        out.append(("hard_negation", text[:neg.start()] + text[neg.end():]))
    else:
        v = re.search(r"\b(ist|sind|war|waren|wurde|wurden|lag|lagen|hat|haben)\b", text)
        if v:
            out.append(("hard_negation", text[:v.end()] + " nicht" + text[v.end():]))
    return out


def run_letter(letter: dict, rng: random.Random) -> tuple[list[dict], dict]:
    sections = letter["sections"]["llm"]
    emap = letter["evidence_map"]
    docs = {eid: store.evidence(eid) or {} for eid in emap.values()}
    hay = verify._haystack([verify._ev_text(d) for d in docs.values()])
    clean = verify.verify_sentences(sections, emap, docs)
    clean_keys = {_key(i) for i in clean if i.status == "unverified"}
    checked = len(clean)
    base = {"letter_id": letter["letter_id"], "clean_checked": checked, "clean_flagged": len(clean_keys)}
    cases = []

    def check(kind: str, sec: str, idx: int, new_sections: dict, scenario: str):
        issues = verify.verify_sentences(new_sections, emap, docs)
        new = [i for i in issues if i.status == "unverified" and i.section == sec and i.sentence == idx
               and _key(i) not in clean_keys]
        cases.append({"id": f"{letter['letter_id']}:{sec}:{idx}:{kind}", "scenario_id": letter["letter_id"],
                      "kind": kind, "hard": kind.startswith("hard_"), "detected": bool(new),
                      "flag_kinds": sorted({i.kind for i in new}),
                      "right_reason": bool(new) and (EXPECT.get(kind) is None or EXPECT[kind] in {i.kind for i in new}),
                      "sentence": new_sections[sec][idx]["text"] if idx < len(new_sections[sec]) else "",
                      "scenario": scenario})

    for sec, sents in sections.items():
        for idx, s in enumerate(sents):
            for kind, new_text in perturbations(s["text"], hay, rng):
                ns = copy.deepcopy(sections)
                ns[sec][idx]["text"] = new_text
                check(kind, sec, idx, ns, "modify")
            ns = copy.deepcopy(sections)
            ns[sec][idx]["evidence"] = []
            ns[sec][idx]["text"] = verify.CITE_RE.sub("", s["text"])
            check("uncited", sec, idx, ns, "modify")
            ns = copy.deepcopy(sections)
            ns[sec][idx]["evidence"] = ["E-99"]
            check("bad_cite", sec, idx, ns, "modify")
        n = next(k for k in range(7, 500) if verify._norm_num(str(k)) not in hay["numbers"])
        ns = copy.deepcopy(sections)
        ns[sec].append({"text": f"Zusätzlich standen {n} Mitarbeiter ohne Arbeit auf der Baustelle.",
                        "evidence": [sents[0]["evidence"][0]] if sents and sents[0].get("evidence") else []})
        check("added_claim", sec, len(ns[sec]) - 1, ns, "append")
    return cases, base


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", default="BV-RIEM")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", required=True, type=Path)
    a = ap.parse_args()
    letters = store.letters(a.project)
    if not letters:
        sys.exit("Keine Entwürfe in der DB – zuerst scripts/seed_demo.py bzw. echte Entwürfe erzeugen.")
    rng = random.Random(a.seed)
    cases, bases = [], []
    for letter in letters:
        c, b = run_letter(letter, rng)
        cases += c
        bases.append(b)
    a.out.mkdir(parents=True, exist_ok=True)
    with open(a.out / "items.jsonl", "w", encoding="utf-8") as f:
        for c in cases:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    s = {"n_cases": len(cases), "n_letters": len(letters),
         "detection_standard": M.cluster_bootstrap([c for c in cases if not c["hard"]], M.mean_of("detected")),
         "detection_hard": M.cluster_bootstrap([c for c in cases if c["hard"]], M.mean_of("detected")),
         "by_kind": {k[0]: M.cluster_bootstrap(v, M.mean_of("detected")) | {
                         "n": len(v), "right_reason": sum(c["right_reason"] for c in v) / len(v)}
                     for k, v in M.group_by(cases, "kind").items()},
         "false_alarms_on_clean": {"flagged": sum(b["clean_flagged"] for b in bases),
                                   "checked": sum(b["clean_checked"] for b in bases)},
         "missed_examples": [c for c in cases if not c["detected"]][:20]}
    (a.out / "summary.json").write_text(json.dumps(s, ensure_ascii=False, indent=1), encoding="utf-8")
    fa = s["false_alarms_on_clean"]
    md = ["# verify.py – Fehlerinjektion", "", f"{len(cases)} Fälle aus {len(letters)} Entwürfen "
          "(KI über Entwürfe gebootstrapt – bei wenigen Entwürfen sehr breit)", "",
          "| Fehlerart | n | Erkannt ↑ | davon richtige Meldungsart |", "|---|---|---|---|",
          f"| **Standard gesamt** | {sum(not c['hard'] for c in cases)} | {M.fmt_ci(s['detection_standard'])} | |",
          f"| **Schwer gesamt** | {sum(c['hard'] for c in cases)} | {M.fmt_ci(s['detection_hard'])} | |"]
    md += [f"| {k} | {v['n']} | {M.fmt_ci(v)} | {100 * v['right_reason']:.0f} % |" for k, v in s["by_kind"].items()]
    md += ["", f"Fehlalarme auf unveränderten Entwürfen: {fa['flagged']} von {fa['checked']} geprüften Fakten"]
    if s["missed_examples"]:
        md += ["", "Nicht erkannt (Auszug):"] + [f"- `{c['kind']}`: {c['sentence'][:140]}" for c in s["missed_examples"][:8]]
    (a.out / "summary.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print("\n".join(md))


if __name__ == "__main__":
    main()
