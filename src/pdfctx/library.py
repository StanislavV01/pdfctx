"""The façade every interface (MCP, REST, CLI) calls. Every tool call is written to the audit log."""

from __future__ import annotations

import csv
import io
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

from . import context as ctx
from .embed import Embedder, Reranker
from .errors import PdfctxError
from .indexer import IndexOptions, IndexReport, expand, index_paths
from .search import SearchConfig, search
from .store import Store


def _check(name: str, value: int, lo: int, hi: int) -> None:
    if not isinstance(value, int) or not lo <= value <= hi:
        raise PdfctxError(f"{name} must be an integer between {lo} and {hi}")


class Library:
    def __init__(
        self,
        db_path: Path | str,
        roots: list[Path] | None = None,
        options: IndexOptions | None = None,
        config: SearchConfig | None = None,
        reranker: Reranker | None = None,
        client: str = "local",
        refresh_interval: float = 2.0,
    ):
        self.store = Store(db_path)
        self.roots = [Path(r) for r in roots or []]
        self.options = options or IndexOptions()
        self.config = config or SearchConfig(
            vectors=self.options.embedder is not None, rerank=reranker is not None
        )
        self.reranker = reranker
        self.client = client
        self.refresh_interval = refresh_interval
        self._lock = threading.RLock()
        self._last_refresh = 0.0
        self._fingerprint: tuple | None = None
        if self.roots:
            self.refresh(force=True)

    @property
    def embedder(self) -> Embedder | None:
        return self.options.embedder

    def close(self) -> None:
        self.store.close()

    # -- indexing -----------------------------------------------------------------------------

    def refresh(self, force: bool = False) -> IndexReport | None:
        """Re-index roots when files were added, changed or removed (checked at most every interval)."""
        with self._lock:
            now = time.monotonic()
            if not force and now - self._last_refresh < self.refresh_interval:
                return None
            self._last_refresh = now
            files = expand(self.roots)
            fingerprint = tuple((str(f), f.stat().st_mtime_ns, f.stat().st_size) for f in files if f.exists())
            if not force and fingerprint == self._fingerprint:
                return None
            self._fingerprint = fingerprint
            return index_paths(self.store, self.roots, self.options)

    def index(self, paths: list[Path]) -> IndexReport:
        with self._lock:
            return index_paths(self.store, paths, self.options)

    def _audit(self, tool: str, args: dict, block_ids: list[str], doc_ids: list[str]) -> None:
        ts = datetime.now(UTC).isoformat(timespec="milliseconds")
        self.store.append_audit(ts, self.client, tool, args, block_ids, sorted(set(doc_ids)))

    # -- tools --------------------------------------------------------------------------------

    def list_documents(self) -> dict:
        self.refresh()
        docs = [
            {
                "id": d.id,
                "title": d.title,
                "file": d.path,
                "pages": d.pages,
                "status": d.status,
                **({"error": d.error} if d.error else {}),
            }
            for d in self.store.list_documents()
        ]
        self._audit("list_documents", {}, [], [d["id"] for d in docs])
        return {"documents": docs}

    def outline(self, doc_id: str, max_depth: int = 3) -> dict:
        self.refresh()
        _check("max_depth", max_depth, 1, 10)
        doc = self.store.get_document(doc_id)
        nodes = {
            s.id: {
                "id": s.id,
                "title": s.title,
                "level": s.level,
                "page": s.page,
                "children": [],
                "_parent": s.parent_id,
            }
            for s in self.store.sections_for(doc_id)
        }
        roots: list[dict] = []
        for node in nodes.values():
            parent = node.pop("_parent")
            (nodes[parent]["children"] if parent in nodes else roots).append(node)

        def prune(items: list[dict], depth: int) -> None:
            for it in items:
                if depth >= max_depth:
                    it["children"] = []
                else:
                    prune(it["children"], depth + 1)

        prune(roots, 1)
        self._audit("outline", {"doc_id": doc_id, "max_depth": max_depth}, [], [doc_id])
        return {"doc_id": doc.id, "title": doc.title, "pages": doc.pages, "sections": roots}

    def read_section(self, section_id: str, max_tokens: int = 2000) -> dict:
        self.refresh()
        _check("max_tokens", max_tokens, 100, 20000)
        out = ctx.render_section(self.store, section_id, max_tokens)
        self._audit(
            "read_section",
            {"section_id": section_id, "max_tokens": max_tokens},
            [b["block_id"] for b in out["blocks"]],
            [out["section"]["doc_id"]],
        )
        return out

    def _search(self, query: str, doc_ids: list[str] | None, k: int, per_page_cap: int | None = -1):
        if not isinstance(query, str) or not query.strip():
            raise PdfctxError("query must be a non-empty string")
        if doc_ids is not None:
            for d in doc_ids:
                self.store.get_document(d)
        return search(
            self.store,
            query,
            doc_ids=doc_ids,
            k=k,
            config=self.config,
            embedder=self.embedder,
            reranker=self.reranker,
        )

    def search(self, query: str, doc_ids: list[str] | None = None, k: int = 8) -> dict:
        self.refresh()
        _check("k", k, 1, 50)
        hits = self._search(query, doc_ids, k)
        blocks = self.store.blocks_by_ids(h.block_id for h in hits)
        results = []
        for h in hits:
            b = blocks[h.block_id]
            results.append(
                {
                    "block_id": b.id,
                    "unit_id": h.unit_id,
                    "doc_id": b.doc_id,
                    "kind": b.kind,
                    "match": h.unit_kind,
                    "page": b.page,
                    "bbox": list(b.bbox),
                    "section_path": ctx.section_path(self.store, b.section_id),
                    "text": ctx.hit_text(self.store, h, b),
                    "score": h.score,
                }
            )
        self._audit(
            "search",
            {"query": query, "doc_ids": doc_ids, "k": k},
            [r["block_id"] for r in results],
            [r["doc_id"] for r in results],
        )
        return {"query": query, "results": results}

    def get_table(self, table_id: str, format: str = "markdown") -> dict:
        self.refresh()
        if format not in ("markdown", "csv"):
            raise PdfctxError("format must be 'markdown' or 'csv'")
        b = self.store.get_block(table_id)
        if b.kind != "table":
            raise PdfctxError(f"block '{table_id}' is not a table")
        if format == "csv":
            buf = io.StringIO()
            w = csv.writer(buf, lineterminator="\n")
            w.writerow(["", *(b.header or [])])
            w.writerows(b.rows or [])
            table = buf.getvalue()
        else:
            table = b.text
        self._audit("get_table", {"table_id": table_id, "format": format}, [b.id], [b.doc_id])
        return {
            "table_id": b.id,
            "page": b.page,
            "caption": b.caption,
            "lead_in": b.lead_in,
            "format": format,
            "table": table,
        }

    def cite(self, block_id: str) -> dict:
        self.refresh()
        out = ctx.cite(self.store, block_id)
        self._audit("cite", {"block_id": block_id}, [block_id], [out["doc_id"]])
        return out

    def context_pack(self, query: str, budget_tokens: int = 4000, doc_ids: list[str] | None = None) -> dict:
        self.refresh()
        _check("budget_tokens", budget_tokens, 200, 50000)
        # A pack may use several blocks from one page (a table row and the paragraph explaining it).
        hits = self._search(query, doc_ids, k=50, per_page_cap=3)
        pack = ctx.context_pack(self.store, hits, budget_tokens)
        block_ids = [b["block_id"] for s in pack["sections"] for b in s["blocks"]]
        self._audit(
            "context_pack",
            {"query": query, "budget_tokens": budget_tokens, "doc_ids": doc_ids},
            block_ids,
            [s["doc_id"] for s in pack["sections"]],
        )
        return {"query": query, **pack}

    def audit(self, limit: int = 50) -> list[dict]:
        _check("limit", limit, 1, 10000)
        return [
            {
                "id": r.id,
                "ts": r.ts,
                "client": r.client,
                "tool": r.tool,
                "args": r.args,
                "block_ids": r.block_ids,
                "doc_ids": r.doc_ids,
            }
            for r in self.store.audit(limit)
        ]
