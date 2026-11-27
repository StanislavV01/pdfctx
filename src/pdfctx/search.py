"""Retrieval pipeline: BM25 (FTS5) → optional dense vectors → RRF → optional rerank."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .embed import Embedder, Reranker
from .errors import PdfctxError
from .store import Store

_WORD = re.compile(r"\w+", re.UNICODE)
# Question words and fillers that only add noise to OR-queries.
STOPWORDS = frozenset(
    [
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "can",
        "could",
        "did",
        "do",
        "does",
        "for",
        "from",
        "give",
        "had",
        "has",
        "have",
        "how",
        "i",
        "if",
        "in",
        "into",
        "is",
        "it",
        "its",
        "me",
        "of",
        "on",
        "or",
        "our",
        "please",
        "response",
        "shown",
        "should",
        "than",
        "that",
        "the",
        "their",
        "them",
        "then",
        "there",
        "these",
        "this",
        "those",
        "to",
        "using",
        "was",
        "we",
        "were",
        "what",
        "when",
        "where",
        "which",
        "who",
        "why",
        "will",
        "with",
        "would",
        "you",
        "your",
        "relying",
        "details",
        "based",
        "question",
        "answer",
    ]
)


def fts_query(text: str) -> str | None:
    """Turn free text into a safe FTS5 query: quoted word tokens joined with OR. None if nothing remains."""
    words = [w for w in _WORD.findall(text.lower()) if w not in STOPWORDS]
    if not words:
        words = _WORD.findall(text.lower())
    seen: dict[str, None] = {}
    for w in words:
        seen.setdefault(w.replace('"', ""), None)
    terms = [f'"{w}"' for w in seen if w]
    return " OR ".join(terms) if terms else None


@dataclass
class SearchConfig:
    bm25: bool = True
    vectors: bool = False
    rerank: bool = False
    k_candidates: int = 50
    rerank_top: int = 30
    context_weight: float = 0.5
    heading_weight: float = 0.5


@dataclass
class Hit:
    unit_id: str
    block_id: str
    doc_id: str
    unit_kind: str
    score: float


def _scope_sql(doc_ids: list[str] | None) -> tuple[str, list[str]]:
    if doc_ids is None:
        return "", []
    return f" AND u.doc_id IN ({','.join('?' * len(doc_ids))})", list(doc_ids)


def _bm25(store: Store, query: str, doc_ids: list[str] | None, cfg: SearchConfig) -> list[int]:
    q = fts_query(query)
    if q is None or doc_ids == []:
        return []
    scope, args = _scope_sql(doc_ids)
    sql = (
        "SELECT u.rowid FROM units_fts JOIN units u ON u.rowid = units_fts.rowid "
        f"WHERE units_fts MATCH ?{scope} ORDER BY bm25(units_fts, ?, 1.0) LIMIT ?"
    )
    return [r[0] for r in store.db.execute(sql, [q, *args, cfg.context_weight, cfg.k_candidates])]


def _dense(
    store: Store, query: str, doc_ids: list[str] | None, cfg: SearchConfig, embedder: Embedder
) -> list[int]:
    if doc_ids == []:
        return []
    (qv,) = embedder.embed([query])
    rows = store.vectors_for(doc_ids)
    try:
        import numpy as np

        if not rows:
            return []
        ids = np.array([r[0] for r in rows])
        mat = np.array([r[1] for r in rows], dtype=np.float32)
        sims = mat @ np.array(qv, dtype=np.float32)
        top = np.argsort(-sims)[: cfg.k_candidates]
        return [int(ids[i]) for i in top]
    except ImportError:
        scored = sorted(rows, key=lambda r: -sum(a * b for a, b in zip(r[1], qv, strict=False)))
        return [r[0] for r in scored[: cfg.k_candidates]]


def search(
    store: Store,
    query: str,
    doc_ids: list[str] | None = None,
    k: int = 8,
    config: SearchConfig | None = None,
    embedder: Embedder | None = None,
    reranker: Reranker | None = None,
) -> list[Hit]:
    cfg = config or SearchConfig()
    if cfg.vectors and embedder is None:
        raise PdfctxError("vector search needs an embedder (index and search with the same one)")
    if cfg.rerank and reranker is None:
        raise PdfctxError("rerank needs a reranker")

    rankings: list[list[int]] = []
    if cfg.bm25:
        rankings.append(_bm25(store, query, doc_ids, cfg))
    if cfg.vectors and embedder is not None:
        rankings.append(_dense(store, query, doc_ids, cfg, embedder))

    fused: dict[int, float] = {}
    for ranking in rankings:
        for rank, rowid in enumerate(ranking):
            fused[rowid] = fused.get(rowid, 0.0) + 1.0 / (60 + rank)
    units = store.units_by_rowid(fused)
    blocks = store.blocks_by_ids({u.block_id for u in units.values()})
    for rowid, u in units.items():
        if blocks[u.block_id].kind == "heading":
            fused[rowid] *= cfg.heading_weight
    ordered = sorted(fused, key=lambda r: (-fused[r], r))

    if cfg.rerank and reranker is not None and ordered:
        top = ordered[: cfg.rerank_top]
        texts = [f"{units[r].context}\n{units[r].text}".strip() for r in top]
        scores = reranker.score(query, texts)
        reranked = [r for _, r in sorted(zip(scores, top, strict=True), key=lambda x: -x[0])]
        ordered = reranked + ordered[cfg.rerank_top :]
        for pos, r in enumerate(reranked):
            fused[r] = 1.0 / (1 + pos)

    hits: list[Hit] = []
    seen_blocks: set[str] = set()
    for r in ordered:
        u = units[r]
        if u.block_id in seen_blocks:
            continue
        seen_blocks.add(u.block_id)
        hits.append(Hit(u.id, u.block_id, u.doc_id, u.kind, round(fused[r], 6)))
        if len(hits) >= k:
            break
    return hits
