"""PDF / Word / Scans → Text je Seite + Tabellen (Docling, inkl. OCR und Tabellenerkennung).

Für .txt/.md (Demo) wird der Text direkt übernommen; Seitenumbrüche über Zeilen "--- Seite N ---".
"""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from .. import settings

PAGE_RE = re.compile(r"^-{3}\s*Seite\s+(\d+)\s*-{3}\s*$", re.M)


def _plain(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    parts = PAGE_RE.split(text)
    pages: list[dict] = []
    if len(parts) == 1:
        pages = [{"page": 1, "text": text.strip()}]
    else:
        if parts[0].strip():
            pages.append({"page": 1, "text": parts[0].strip()})
        for i in range(1, len(parts), 2):
            pages.append({"page": int(parts[i]), "text": parts[i + 1].strip()})
    tables = []
    for p in pages:
        rows = [l for l in p["text"].splitlines() if l.strip().startswith("|")]
        if len(rows) >= 2:
            cells = [[c.strip() for c in r.strip().strip("|").split("|")] for r in rows
                     if not set(r.replace("|", "").strip()) <= set("-: ")]
            tables.append({"page": p["page"], "header": cells[0], "rows": cells[1:]})
    return {"pages": pages, "tables": tables, "markdown": text, "backend": "plain"}


@lru_cache(maxsize=1)
def _converter():
    from docling.datamodel.base_models import InputFormat  # type: ignore
    from docling.datamodel.pipeline_options import PdfPipelineOptions  # type: ignore
    from docling.document_converter import DocumentConverter, PdfFormatOption  # type: ignore

    c = settings.models()["documents"]
    opts = PdfPipelineOptions(do_ocr=c.get("do_ocr", True), do_table_structure=c.get("do_table_structure", True))
    return DocumentConverter(format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=opts)})


def _docling(path: Path) -> dict[str, Any]:
    res = _converter().convert(str(path))
    doc = res.document
    by_page: dict[int, list[str]] = {}
    for item in doc.texts:
        page = item.prov[0].page_no if getattr(item, "prov", None) else 1
        by_page.setdefault(page, []).append(item.text)
    tables = []
    for t in doc.tables:
        df = t.export_to_dataframe()
        page = t.prov[0].page_no if getattr(t, "prov", None) else 1
        tables.append({"page": page, "header": [str(c) for c in df.columns],
                       "rows": df.astype(str).values.tolist()})
    pages = [{"page": p, "text": "\n".join(lines)} for p, lines in sorted(by_page.items())]
    return {"pages": pages, "tables": tables, "markdown": doc.export_to_markdown(), "backend": "docling"}


def parse(path: Path) -> dict[str, Any]:
    path = Path(path)
    if path.suffix.lower() in {".txt", ".md"} or settings.models()["documents"]["backend"] == "plain":
        return _plain(path)
    try:
        return _docling(path)
    except ImportError:
        # Demo-Rechner ohne Docling: Datei wird abgelegt, Text erst im GPU-Modus extrahiert
        note = f"[{path.name}: Textextraktion erfordert Docling (requirements-gpu.txt)]"
        return {"pages": [{"page": 1, "text": note}], "tables": [], "markdown": note, "backend": "none"}
