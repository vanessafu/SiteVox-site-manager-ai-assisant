"""PDF-Text mit Spalten (CPU, pdfplumber): Wörter nach Koordinaten zu Zeilen und Zellen gruppieren.

Ergebnis je Seite: Text, in dem Tabellenzellen durch Tabulator getrennt sind; mehrzeilige Zellen werden in die
Zelle der Zeile darüber gezogen. Die Wissensbasis stellt Tab-Zeilen als Tabelle dar, Extraktoren lesen Spalten.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

CELL_GAP = 7.0  # pt Abstand zwischen Wörtern, ab dem eine neue Zelle beginnt
SAME_LINE = 3.0  # pt Toleranz für „gleiche Zeile“
CONT_FACTOR = 1.45  # Zeilenabstand < 1,45 × Schrifthöhe → Fortsetzung der Zelle darüber
COL_TOL = 4.0  # pt Toleranz beim Zuordnen einer Fortsetzungszeile zu einer Spalte


def available() -> bool:
    try:
        import pdfplumber  # type: ignore  # noqa: F401
    except ImportError:
        return False
    return True


def _lines(words: list[dict]) -> list[dict[str, Any]]:
    rows: list[list[dict]] = []
    for w in sorted(words, key=lambda w: (round(w["top"]), w["x0"])):
        if rows and abs(rows[-1][0]["top"] - w["top"]) < SAME_LINE:
            rows[-1].append(w)
        else:
            rows.append([w])
    out = []
    for r in rows:
        r.sort(key=lambda w: w["x0"])
        cells = [{"x0": r[0]["x0"], "x1": r[0]["x1"], "text": r[0]["text"]}]
        for a, b in zip(r, r[1:]):
            if b["x0"] - a["x1"] > CELL_GAP:
                cells.append({"x0": b["x0"], "x1": b["x1"], "text": b["text"]})
            else:
                cells[-1]["text"] += " " + b["text"]
                cells[-1]["x1"] = b["x1"]
        out.append({"top": r[0]["top"], "h": max(w["bottom"] - w["top"] for w in r), "cells": cells})
    return out


def page_text(words: list[dict]) -> str:
    lines = _lines(words)
    merged: list[dict] = []
    for ln in lines:
        prev = merged[-1] if merged else None
        if prev and len(prev["cells"]) > 1 and len(ln["cells"]) < len(prev["cells"]) \
                and ln["top"] - prev["last_top"] < CONT_FACTOR * max(ln["h"], prev["h"]):
            cols = [c["x0"] for c in prev["cells"]]
            mids = [(c["x0"] + c["x1"]) / 2 for c in prev["cells"]]
            ok = True
            targets = []
            for c in ln["cells"]:
                # Spalte, in deren Bereich die Fortsetzung beginnt (rechtsbündige Zellen beginnen weiter rechts)
                mid = (c["x0"] + c["x1"]) / 2
                j = min(range(len(mids)), key=lambda i: abs(mids[i] - mid)) if c["x0"] >= cols[0] - COL_TOL else None
                if j is None or (j == 0 and abs(cols[0] - c["x0"]) > COL_TOL) or any(t[0] == j for t in targets):
                    ok = False
                    break
                targets.append((j, c["text"]))
            if ok:
                for j, txt in targets:
                    prev["cells"][j]["text"] += " " + txt
                prev["last_top"], prev["h"] = ln["top"], max(prev["h"], ln["h"])
                continue
        merged.append({**ln, "cells": [dict(c) for c in ln["cells"]], "last_top": ln["top"]})
    return "\n".join("\t".join(c["text"] for c in m["cells"]) for m in merged)


def pages(path: Path) -> Optional[list[dict]]:
    """Seiten mit spaltenerhaltendem Text oder None, wenn pdfplumber fehlt."""
    if not available():
        return None
    import pdfplumber  # type: ignore

    out = []
    with pdfplumber.open(str(path)) as pdf:
        for i, pg in enumerate(pdf.pages, start=1):
            out.append({"page": i, "text": page_text(pg.extract_words(x_tolerance=1.5)).strip()})
    return out
