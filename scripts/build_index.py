#!/usr/bin/env python3
"""(Re-)Indexiert die Wissensbasis: Rechtsgrundlagen (data/knowledge) + Projektunterlagen.

Neue Projektdokumente (PDF/DOCX/Scans) werden mit Docling geparst:
  python scripts/build_index.py --project BV-RIEM --add data/raw/LV_Ausbau.pdf --kind lv
Im GPU-Modus werden BGE-M3-Embeddings in Chroma persistiert; sonst nur BM25.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sitevox import rag, store  # noqa: E402
from sitevox.understand import documents  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", default="BV-RIEM")
    ap.add_argument("--add", nargs="*", default=[])
    ap.add_argument("--kind", default="dokument")
    ap.add_argument("--query", default=None, help="Testsuche nach dem Indexieren")
    a = ap.parse_args()
    for f in a.add:
        p = Path(f)
        parsed = documents.parse(p)
        store.save_document({"doc_id": f"DOC-{p.stem}", "project_id": a.project, "title": p.stem, "file": str(p),
                             "kind": a.kind, "collection": "project", "pages": parsed["pages"],
                             "tables": parsed["tables"]})
        print(f"+ {p.name}: {len(parsed['pages'])} Seiten, {len(parsed['tables'])} Tabellen ({parsed['backend']})")
    idx = rag.index(rebuild=True)
    print(f"{len(idx.chunks)} Chunks indexiert")
    if a.query:
        for h in idx.search(a.query, project_id=a.project):
            print(f"  {h['relevance']:.2f}  {h['doc_title']} S.{h['page']}: {h['title']}")


if __name__ == "__main__":
    main()
