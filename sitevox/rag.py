"""Wissensbasis (RAG): zwei Collections – Rechtsgrundlagen (VOB/B aktuelle Fassung) und Projektunterlagen
(Vertrag, LV, Planlieferliste, Protokolle; Filter project_id). Hybride Suche: BM25 + BGE-M3 dense (Chroma),
Rerank mit bge-reranker-v2-m3. Im Demo-Modus nur BM25 + lexikalische Abdeckung als Relevanzscore.

Wichtig: Normzitate in Schreiben stammen ausschließlich aus den Vorlagen. RAG dient dazu, dem Nutzer
die zugrunde liegenden Stellen zu zeigen und Vertrags-/LV-Belege zu finden (z. B. "Kernbohrung nicht im LV").
"""
from __future__ import annotations

import math
import re
from functools import lru_cache
from typing import Any, Optional

from . import settings, store

TOKEN_RE = re.compile(r"[a-zäöüß0-9]+", re.I)
STOP = set("der die das und oder in im am an zu zum zur mit von für auf ist sind ein eine einer eines den dem des "
           "nicht als bei wird werden so dass sich es auch nach".split())


def tokenize(text: str) -> list[str]:
    return [t for t in (m.group(0).lower() for m in TOKEN_RE.finditer(text)) if t not in STOP]


def chunk_document(doc: dict) -> list[dict]:
    """Rechtstexte: je Absatz (## Überschrift). Sonstiges: je Seite, ggf. in Fenster zerlegt."""
    cfg = settings.models()["rag"]
    chunks = []
    for page in doc["pages"]:
        text = page["text"]
        if doc.get("collection") == "legal":
            parts = re.split(r"(?m)^## ", text)
            for p in parts:
                if not p.strip():
                    continue
                title, _, body = p.partition("\n")
                chunks.append({"title": title.strip(), "text": body.strip(), "page": page["page"]})
            continue
        size, ov = cfg["chunk_chars"], cfg["chunk_overlap"]
        for i in range(0, max(len(text), 1), size - ov):
            piece = text[i:i + size]
            if piece.strip():
                chunks.append({"title": doc["title"], "text": piece, "page": page["page"]})
            if i + size >= len(text):
                break
    for i, c in enumerate(chunks):
        c.update(chunk_id=f"{doc['doc_id']}#{i}", doc_id=doc["doc_id"], doc_title=doc["title"],
                 project_id=doc["project_id"], collection=doc.get("collection", "project"))
    return chunks


class Index:
    def __init__(self):
        self.chunks: list[dict] = []
        self._bm25 = None
        self._dense = None

    def build(self) -> "Index":
        from rank_bm25 import BM25Okapi

        self.chunks = [c for d in store.documents() for c in chunk_document(d)]
        self._bm25 = BM25Okapi([tokenize(c["title"] + " " + c["text"]) for c in self.chunks]) if self.chunks else None
        if not settings.is_demo() and settings.models()["rag"]["backend"] == "chroma":
            self._dense = _Dense(self.chunks)
        return self

    def search(self, query: str, project_id: Optional[str] = None, collection: Optional[str] = None,
               k: Optional[int] = None) -> list[dict[str, Any]]:
        cfg = settings.models()["rag"]
        k = k or cfg["rerank_top_k"]
        if not self.chunks:
            return []
        q = tokenize(query)
        bm = self._bm25.get_scores(q) if self._bm25 else [0] * len(self.chunks)
        mx = max(bm) or 1.0
        scores = {i: s / mx for i, s in enumerate(bm)}
        if self._dense is not None:
            dense = self._dense.query(query, cfg["top_k"] * 3)
            a = cfg["hybrid_alpha"]
            scores = {i: (1 - a) * scores.get(i, 0) + a * dense.get(i, 0) for i in set(scores) | set(dense)}
        cand = [i for i in sorted(scores, key=scores.get, reverse=True)
                if (not project_id or self.chunks[i]["project_id"] in (project_id, "_legal"))
                and (not collection or self.chunks[i]["collection"] == collection)][: cfg["top_k"]]
        hits = []
        for i in cand:
            c = self.chunks[i]
            terms = set(q)
            cover = len(terms & set(tokenize(c["title"] + " " + c["text"]))) / max(len(terms), 1)
            hits.append({**c, "score": round(scores[i], 3), "relevance": round(cover, 3)})
        if self._dense is not None and hits:
            rr = _reranker().predict([(query, h["text"]) for h in hits])
            for h, s in zip(hits, rr):
                h["relevance"] = round(1 / (1 + math.exp(-float(s))), 3)
            hits.sort(key=lambda h: h["relevance"], reverse=True)
        else:
            hits.sort(key=lambda h: (h["relevance"], h["score"]), reverse=True)
        return [h for h in hits if h["score"] > 0 or h["relevance"] > 0][:k]


class _Dense:
    def __init__(self, chunks: list[dict]):
        import chromadb  # type: ignore
        from sentence_transformers import SentenceTransformer  # type: ignore

        cfg = settings.models()["rag"]
        self.model = SentenceTransformer(cfg["embedding_model"], device=settings.models()["runtime"]["device"])
        client = chromadb.PersistentClient(path=str(settings.ROOT / cfg["persist_dir"]))
        self.col = client.get_or_create_collection("sitevox_all", metadata={"hnsw:space": "cosine"})
        ids = [c["chunk_id"] for c in chunks]
        existing = set(self.col.get(ids=ids)["ids"]) if ids else set()
        new = [c for c in chunks if c["chunk_id"] not in existing]
        if new:
            emb = self.model.encode([c["text"] for c in new], normalize_embeddings=True).tolist()
            self.col.add(ids=[c["chunk_id"] for c in new], embeddings=emb, documents=[c["text"] for c in new],
                         metadatas=[{"project_id": c["project_id"], "collection": c["collection"]} for c in new])
        self.pos = {c["chunk_id"]: i for i, c in enumerate(chunks)}

    def query(self, text: str, n: int) -> dict[int, float]:
        emb = self.model.encode([text], normalize_embeddings=True).tolist()
        r = self.col.query(query_embeddings=emb, n_results=n)
        return {self.pos[i]: 1 - d for i, d in zip(r["ids"][0], r["distances"][0]) if i in self.pos}


@lru_cache(maxsize=1)
def _reranker():
    from sentence_transformers import CrossEncoder  # type: ignore

    return CrossEncoder(settings.models()["rag"]["reranker_model"])


_index: Optional[Index] = None


def index(rebuild: bool = False) -> Index:
    global _index
    if _index is None or rebuild:
        _index = Index().build()
    return _index


def best_sentence(text: str, query: str) -> str:
    """Aussagekräftigster Satz/Tabellenzeile eines Treffers (für das Belegzitat)."""
    q = set(tokenize(query))
    parts = [p.strip() for p in re.split(r"(?<=[.!?])\s+|\n+", text) if len(p.strip()) > 12]
    if not parts:
        return text[:300]
    return max(parts, key=lambda p: len(q & set(tokenize(p))) / (1 + 0.002 * len(p)))[:400]


def lv_contains(project_id: str, phrase: str, threshold: float = 0.6) -> dict[str, Any]:
    """Prüft deterministisch, ob eine Leistung im LV enthalten ist (Grundlage für 'Zusatzleistung')."""
    hits = [h for h in index().search(phrase, project_id=project_id, collection="project", k=5)
            if "lv" in h["doc_title"].lower() or "leistungsverzeichnis" in h["doc_title"].lower()]
    best = hits[0] if hits else None
    found = bool(best and best["relevance"] >= threshold)
    return {"found": found, "best": best, "relevance": best["relevance"] if best else 0.0}
