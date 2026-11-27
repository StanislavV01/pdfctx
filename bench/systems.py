"""Systems under test. Each returns ranked passages (document, page, text) for a question."""

from __future__ import annotations

import sqlite3
from importlib import metadata
from pathlib import Path
from typing import Protocol

import pypdfium2 as pdfium

from bench.financebench import Passage
from pdfctx.embed import get_embedder, get_reranker
from pdfctx.indexer import IndexOptions, doc_id_for, index_paths
from pdfctx.search import SearchConfig, fts_query, search
from pdfctx.store import Store


class System(Protocol):
    name: str

    def prepare(self, pdfs: list[Path]) -> None: ...

    def retrieve(self, question: str, doc_name: str | None, k: int) -> list[Passage]: ...


class BaselinePage:
    """One passage per page, BM25 over the raw page text: what a naive page-level RAG does."""

    name = "baseline"

    def prepare(self, pdfs: list[Path]) -> None:
        self.db = sqlite3.connect(":memory:")
        self.db.execute(
            "CREATE VIRTUAL TABLE pages USING fts5("
            "doc UNINDEXED, page UNINDEXED, text, tokenize='unicode61 remove_diacritics 2')"
        )
        for path in pdfs:
            pdf = pdfium.PdfDocument(str(path))
            rows = [(path.stem, i + 1, pdf[i].get_textpage().get_text_range()) for i in range(len(pdf))]
            self.db.executemany("INSERT INTO pages VALUES (?,?,?)", rows)
            pdf.close()

    def retrieve(self, question: str, doc_name: str | None, k: int) -> list[Passage]:
        q = fts_query(question)
        if q is None:
            return []
        scope = " AND doc = ?" if doc_name else ""
        args = [q, doc_name] if doc_name else [q]
        rows = self.db.execute(
            f"SELECT doc, page, text FROM pages WHERE pages MATCH ?{scope} ORDER BY rank LIMIT {k}", args
        )
        return [Passage(d, p, t) for d, p, t in rows]


class PdfctxSystem:
    def __init__(
        self,
        name: str,
        options: IndexOptions,
        config: SearchConfig | None = None,
        reranker=None,
        index_dir: Path | None = None,
    ):
        self.name, self.options, self.config, self.reranker = (
            name,
            options,
            config or SearchConfig(),
            reranker,
        )
        self.index_dir = index_dir
        self.version = metadata.version("pdfctx") if _installed("pdfctx") else "dev"

    def prepare(self, pdfs: list[Path]) -> None:
        index_dir = self.index_dir or pdfs[0].parent.parent / "indexes"
        self.store = Store(Path(index_dir) / f"{self.options.digest()}.db")
        self.paths = {p.stem: p for p in pdfs}
        index_paths(self.store, pdfs, self.options)

    def retrieve(self, question: str, doc_name: str | None, k: int) -> list[Passage]:
        doc_ids = [doc_id_for(self.paths[doc_name])] if doc_name else None
        hits = search(
            self.store,
            question,
            doc_ids=doc_ids,
            k=k,
            config=self.config,
            embedder=self.options.embedder,
            reranker=self.reranker,
        )
        names = {doc_id_for(p): n for n, p in self.paths.items()}
        out = []
        for h in hits:
            block = self.store.get_block(h.block_id)
            if h.unit_kind == "row":
                unit = self.store.get_unit(h.unit_id)
                text = "\n".join(x for x in (block.caption, unit.text) if x)
            else:
                text = block.text
            out.append(Passage(names[h.doc_id], block.page, text))
        return out


class PdfMcpSystem:
    """jztan/pdf-mcp, queried through its own `pdf_search` tool function (doc scope)."""

    name = "pdf-mcp"

    def prepare(self, pdfs: list[Path]) -> None:
        from pdf_mcp.tools.search import pdf_search  # raises ImportError when not installed

        self._search = getattr(pdf_search, "fn", pdf_search)
        self.paths = {p.stem: p for p in pdfs}
        self.version = metadata.version("pdf-mcp")

    def retrieve(self, question: str, doc_name: str | None, k: int) -> list[Passage]:
        if doc_name is None:
            raise NotImplementedError("pdf-mcp is compared in doc scope only")
        res = self._search(path=str(self.paths[doc_name]), query=question, mode="auto", max_results=k)
        out = []
        for m in res.get("matches", [])[:k]:
            text = m.get("excerpt") or m.get("context") or m.get("text") or ""
            out.append(Passage(doc_name, int(m["page"]), text))
        return out


def _installed(dist: str) -> bool:
    try:
        metadata.version(dist)
        return True
    except metadata.PackageNotFoundError:
        return False


def make_system(name: str, bench_dir: Path) -> System:
    index_dir = bench_dir / "indexes"
    match name:
        case "baseline":
            return BaselinePage()
        case "pdf-mcp":
            return PdfMcpSystem()
        case "pdfctx-structure":
            return PdfctxSystem(name, IndexOptions(contextual=False, table_rows=False), index_dir=index_dir)
        case "pdfctx-context":
            return PdfctxSystem(name, IndexOptions(contextual=True, table_rows=False), index_dir=index_dir)
        case "pdfctx-tables":
            return PdfctxSystem(name, IndexOptions(contextual=True, table_rows=True), index_dir=index_dir)
        case "pdfctx-hybrid":
            opts = IndexOptions(embedder=get_embedder("fastembed"))
            return PdfctxSystem(name, opts, SearchConfig(vectors=True), index_dir=index_dir)
        case "pdfctx-rerank":
            opts = IndexOptions(embedder=get_embedder("fastembed"))
            return PdfctxSystem(
                name,
                opts,
                SearchConfig(vectors=True, rerank=True),
                reranker=get_reranker("fastembed"),
                index_dir=index_dir,
            )
    raise SystemExit(f"unknown system '{name}'")
