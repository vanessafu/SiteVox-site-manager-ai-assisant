"""PDF / Word / Scans → Text je Seite + Tabellen (Docling, inkl. OCR und Tabellenerkennung).

Für .txt/.md (Demo) wird der Text direkt übernommen; Seitenumbrüche über Zeilen "--- Seite N ---".
"""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from .. import settings
from . import gaeb_io, ocr

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


def _pdf_light(path: Path) -> tuple[list[dict], list[dict]]:
    """PDF ohne Docling: Textebene (pypdf); Seiten ohne Text (Scan) → OCR der eingebetteten Bilder."""
    from pypdf import PdfReader  # type: ignore

    pages = []
    for i, pg in enumerate(PdfReader(str(path)).pages, start=1):
        text = (pg.extract_text() or "").strip()
        if len(text) < 20 and ocr.enabled():
            try:
                text = "\n".join(t for t in (ocr.image_text(im.data) for im in pg.images) if t) or text
            except Exception:  # noqa: BLE001
                pass
        pages.append({"page": i, "text": text})
    return pages, []


def _docx_light(path: Path) -> tuple[list[dict], list[dict]]:
    import docx  # type: ignore

    d = docx.Document(str(path))
    lines = [p.text for p in d.paragraphs if p.text.strip()]
    tables = []
    for t in d.tables:
        rows = [[c.text.strip() for c in r.cells] for r in t.rows]
        if rows:
            tables.append({"page": 1, "header": rows[0], "rows": rows[1:]})
            lines += [" | ".join(r) for r in rows]
    return [{"page": 1, "text": "\n".join(lines)}], tables


def _light(path: Path) -> dict[str, Any]:
    """Leichter Parser ohne GPU/Docling: PDF-Textebene, Word, Bilder per OCR (CPU)."""
    suf = path.suffix.lower()
    if suf == ".pdf":
        pages, tables = _pdf_light(path)
    elif suf == ".docx":
        pages, tables = _docx_light(path)
    elif suf in ocr.IMAGE_SUFFIXES:
        pages, tables = [{"page": 1, "text": ocr.image_text(path)}], []
    else:
        raise ValueError(suf)
    if not any(p["text"].strip() for p in pages):
        raise ValueError("kein Text erkannt")
    md = "\n\n".join(f"--- Seite {p['page']} ---\n{p['text']}" for p in pages)
    return {"pages": pages, "tables": tables, "markdown": md, "backend": "light"}


def parse(path: Path) -> dict[str, Any]:
    path = Path(path)
    if gaeb_io.is_gaeb(path):  # LV-Austauschformat: strukturiert einlesen (Positionen, Mengen, Einheiten)
        try:
            return gaeb_io.parse(path)
        except Exception as e:  # noqa: BLE001
            note = f"[{path.name}: GAEB-Datei konnte nicht gelesen werden – {str(e)[:200]}]"
            return {"pages": [{"page": 1, "text": note}], "tables": [], "markdown": note, "backend": "none"}
    if path.suffix.lower() in {".txt", ".md"} or settings.models()["documents"]["backend"] == "plain":
        return _plain(path)
    try:
        return _docling(path)
    except ImportError:
        pass
    # Demo-Rechner ohne Docling: pypdf / python-docx / OCR auf der CPU
    try:
        return _light(path)
    except Exception:  # noqa: BLE001
        note = f"[{path.name}: kein Text extrahierbar – für Scans/komplexe Layouts Docling installieren (requirements-gpu.txt)]"
        return {"pages": [{"page": 1, "text": note}], "tables": [], "markdown": note, "backend": "none"}
