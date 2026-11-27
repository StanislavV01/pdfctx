"""Incremental indexing of PDF files and folders."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from .embed import Embedder
from .outline import build_outline
from .parse import ocr, parse_pdf
from .store import BlockRow, DocumentRow, SectionRow, Store
from .units import make_units

# Bump whenever parsing, outline or unit building changes, so existing indexes are rebuilt.
INDEX_VERSION = 2


def tokens(text: str) -> int:
    return math.ceil(len(text) / 4)


@dataclass
class IndexOptions:
    contextual: bool = True
    table_rows: bool = True
    embedder: Embedder | None = None

    def digest(self) -> str:
        key = {
            "contextual": self.contextual,
            "table_rows": self.table_rows,
            "embedder": self.embedder.name if self.embedder else None,
            # A scan indexed without OCR is re-indexed once tesseract is installed.
            "ocr": ocr.available(),
            "v": INDEX_VERSION,
        }
        return hashlib.sha256(json.dumps(key, sort_keys=True).encode()).hexdigest()[:16]


@dataclass
class IndexReport:
    added: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    problems: list[tuple[str, str]] = field(default_factory=list)


def doc_id_for(path: Path) -> str:
    return hashlib.sha256(str(path.resolve()).encode()).hexdigest()[:12]


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def expand(paths: list[Path]) -> list[Path]:
    """PDF files under the given paths (recursively), skipping hidden folders and .pdfctx."""
    out: list[Path] = []
    for p in map(Path, paths):
        if p.is_dir():
            for f in sorted(p.rglob("*")):
                rel = f.relative_to(p).parts
                if (
                    f.is_file()
                    and f.suffix.lower() == ".pdf"
                    and not any(x.startswith(".") for x in rel[:-1])
                ):
                    out.append(f)
        elif p.is_file():
            out.append(p)
    return out


def index_file(store: Store, path: Path, options: IndexOptions, sha: str | None = None) -> DocumentRow:
    path = Path(path)
    doc_id = doc_id_for(path)
    parsed = parse_pdf(path)
    now = datetime.now(UTC).isoformat(timespec="seconds")
    row = DocumentRow(
        id=doc_id,
        path=str(path.resolve()),
        sha256=sha or _sha256(path),
        options_hash=options.digest(),
        title=parsed.title,
        pages=parsed.pages,
        status=parsed.status,
        error=parsed.error,
        indexed_at=now,
    )
    sections, assign = build_outline(parsed)
    section_rows = [
        SectionRow(
            id=f"{doc_id}:s{s.idx}",
            doc_id=doc_id,
            idx=s.idx,
            parent_id=f"{doc_id}:s{s.parent}" if s.parent is not None else None,
            level=s.level,
            title=s.title,
            page=s.page,
        )
        for s in sections
    ]
    block_rows = [
        BlockRow(
            id=f"{doc_id}:b{i}",
            doc_id=doc_id,
            idx=i,
            section_id=f"{doc_id}:s{assign[i]}" if assign[i] is not None else None,
            kind=b.kind,
            page=b.page,
            bbox=b.bbox,
            text=b.text,
            header=b.header,
            rows=b.rows,
            caption=b.caption,
            lead_in=b.lead_in,
            tokens=tokens(b.text),
        )
        for i, b in enumerate(parsed.blocks)
    ]
    units = make_units(parsed, sections, assign, contextual=options.contextual, table_rows=options.table_rows)
    unit_rows = [
        (f"{doc_id}:u{n}", f"{doc_id}:b{u.block_idx}", u.kind, u.text, u.context, u.page)
        for n, u in enumerate(units)
    ]
    vectors = None
    if options.embedder is not None and unit_rows:
        vectors = options.embedder.embed([f"{u[4]}\n{u[3]}".strip() for u in unit_rows])
    store.upsert_document(row)
    store.replace_contents(doc_id, section_rows, block_rows, unit_rows, vectors)
    return row


def index_paths(store: Store, paths: list[Path], options: IndexOptions | None = None) -> IndexReport:
    options = options or IndexOptions()
    report = IndexReport()
    files = expand(paths)
    seen: set[str] = set()
    for f in files:
        resolved = str(f.resolve())
        seen.add(resolved)
        existing = store.document_by_path(resolved)
        sha = _sha256(f)
        if existing and existing.sha256 == sha and existing.options_hash == options.digest():
            report.unchanged.append(str(f))
            continue
        row = index_file(store, f, options, sha)
        (report.updated if existing else report.added).append(str(f))
        if row.status != "ok":
            report.problems.append((str(f), f"{row.status}: {row.error}" if row.error else row.status))
    # Drop documents that were indexed from these roots but whose files are gone.
    roots = [Path(p).resolve() for p in paths]
    for doc in store.list_documents():
        if doc.path in seen:
            continue
        doc_path = Path(doc.path)
        under = any(doc_path == r or r in doc_path.parents for r in roots)
        if under and not doc_path.exists():
            store.delete_document(doc.id)
            report.removed.append(doc.path)
    return report
