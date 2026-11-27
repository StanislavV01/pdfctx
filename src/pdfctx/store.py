"""SQLite storage: documents, sections, blocks, retrieval units (FTS5), vectors and the audit log."""

from __future__ import annotations

import json
import sqlite3
import struct
import threading
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from .errors import NotFound

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
  id TEXT PRIMARY KEY, path TEXT UNIQUE NOT NULL, sha256 TEXT, options_hash TEXT,
  title TEXT, pages INTEGER, status TEXT, error TEXT, indexed_at TEXT
);
CREATE TABLE IF NOT EXISTS sections (
  id TEXT PRIMARY KEY, doc_id TEXT NOT NULL, idx INTEGER, parent_id TEXT, level INTEGER,
  title TEXT, page INTEGER
);
CREATE INDEX IF NOT EXISTS sections_doc ON sections(doc_id, idx);
CREATE TABLE IF NOT EXISTS blocks (
  id TEXT PRIMARY KEY, doc_id TEXT NOT NULL, idx INTEGER, section_id TEXT, kind TEXT, page INTEGER,
  bbox TEXT, text TEXT, header TEXT, rows TEXT, caption TEXT, lead_in TEXT, tokens INTEGER
);
CREATE INDEX IF NOT EXISTS blocks_doc ON blocks(doc_id, idx);
CREATE INDEX IF NOT EXISTS blocks_section ON blocks(section_id);
CREATE TABLE IF NOT EXISTS units (
  rowid INTEGER PRIMARY KEY, id TEXT UNIQUE NOT NULL, doc_id TEXT NOT NULL, block_id TEXT NOT NULL,
  kind TEXT, text TEXT, context TEXT, page INTEGER
);
CREATE INDEX IF NOT EXISTS units_doc ON units(doc_id);
CREATE VIRTUAL TABLE IF NOT EXISTS units_fts USING fts5(
  context, text, tokenize = 'unicode61 remove_diacritics 2'
);
CREATE TABLE IF NOT EXISTS vectors (unit_rowid INTEGER PRIMARY KEY, data BLOB NOT NULL);
CREATE TABLE IF NOT EXISTS audit (
  id INTEGER PRIMARY KEY, ts TEXT, client TEXT, tool TEXT, args TEXT, block_ids TEXT, doc_ids TEXT
);
"""


@dataclass
class DocumentRow:
    id: str
    path: str
    sha256: str
    options_hash: str
    title: str
    pages: int
    status: str
    error: str | None
    indexed_at: str


@dataclass
class SectionRow:
    id: str
    doc_id: str
    idx: int
    parent_id: str | None
    level: int
    title: str
    page: int


@dataclass
class BlockRow:
    id: str
    doc_id: str
    idx: int
    section_id: str | None
    kind: str
    page: int
    bbox: tuple[float, float, float, float]
    text: str
    header: list[str] | None
    rows: list[list[str]] | None
    caption: str
    lead_in: str
    tokens: int


@dataclass
class UnitRow:
    rowid: int
    id: str
    doc_id: str
    block_id: str
    kind: str
    text: str
    context: str
    page: int


@dataclass
class AuditRow:
    id: int
    ts: str
    client: str
    tool: str
    args: dict
    block_ids: list[str]
    doc_ids: list[str]


def pack_vector(v: list[float]) -> bytes:
    return struct.pack(f"<{len(v)}f", *v)


def unpack_vector(b: bytes) -> list[float]:
    return list(struct.unpack(f"<{len(b) // 4}f", b))


class Store:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()  # one writer at a time
        # One connection per thread. A single connection shared by the server's worker threads lets one
        # request read another's half-finished results (and sqlite3 raises "API misuse"); WAL lets the
        # per-thread connections read committed data while a write is in progress.
        self._local = threading.local()
        self._conns: list[sqlite3.Connection] = []
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript(SCHEMA)

    @property
    def db(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None, timeout=30)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA synchronous=NORMAL")
            self._local.conn = conn
            with self._lock:
                self._conns.append(conn)
        return conn

    def close(self) -> None:
        with self._lock:
            for conn in self._conns:
                conn.close()
            self._conns.clear()
        self._local = threading.local()

    # -- writes -------------------------------------------------------------------------------

    def upsert_document(self, doc: DocumentRow) -> None:
        with self._lock:
            self.db.execute(
                "INSERT INTO documents VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET "
                "path=excluded.path, sha256=excluded.sha256, options_hash=excluded.options_hash, "
                "title=excluded.title, pages=excluded.pages, status=excluded.status, "
                "error=excluded.error, indexed_at=excluded.indexed_at",
                (
                    doc.id,
                    doc.path,
                    doc.sha256,
                    doc.options_hash,
                    doc.title,
                    doc.pages,
                    doc.status,
                    doc.error,
                    doc.indexed_at,
                ),
            )

    def _delete_contents(self, doc_id: str) -> None:
        self.db.execute(
            "DELETE FROM units_fts WHERE rowid IN (SELECT rowid FROM units WHERE doc_id=?)", (doc_id,)
        )
        self.db.execute(
            "DELETE FROM vectors WHERE unit_rowid IN (SELECT rowid FROM units WHERE doc_id=?)", (doc_id,)
        )
        for table in ("units", "blocks", "sections"):
            self.db.execute(f"DELETE FROM {table} WHERE doc_id=?", (doc_id,))

    def replace_contents(
        self,
        doc_id: str,
        sections: list[SectionRow],
        blocks: list[BlockRow],
        units: list[tuple[str, str, str, str, str, int]],  # id, block_id, kind, text, context, page
        vectors: list[list[float]] | None = None,
    ) -> None:
        """Atomically replace everything stored for a document."""
        with self._lock:
            self.db.execute("BEGIN")
            try:
                self._delete_contents(doc_id)
                self.db.executemany(
                    "INSERT INTO sections VALUES (?,?,?,?,?,?,?)",
                    [(s.id, s.doc_id, s.idx, s.parent_id, s.level, s.title, s.page) for s in sections],
                )
                self.db.executemany(
                    "INSERT INTO blocks VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    [
                        (
                            b.id,
                            b.doc_id,
                            b.idx,
                            b.section_id,
                            b.kind,
                            b.page,
                            json.dumps(b.bbox),
                            b.text,
                            json.dumps(b.header) if b.header is not None else None,
                            json.dumps(b.rows) if b.rows is not None else None,
                            b.caption,
                            b.lead_in,
                            b.tokens,
                        )
                        for b in blocks
                    ],
                )
                for n, (uid, block_id, kind, text, context, page) in enumerate(units):
                    cur = self.db.execute(
                        "INSERT INTO units (id, doc_id, block_id, kind, text, context, page) "
                        "VALUES (?,?,?,?,?,?,?)",
                        (uid, doc_id, block_id, kind, text, context, page),
                    )
                    rowid = cur.lastrowid
                    self.db.execute(
                        "INSERT INTO units_fts (rowid, context, text) VALUES (?,?,?)", (rowid, context, text)
                    )
                    if vectors is not None:
                        self.db.execute("INSERT INTO vectors VALUES (?,?)", (rowid, pack_vector(vectors[n])))
                self.db.execute("COMMIT")
            except Exception:
                self.db.execute("ROLLBACK")
                raise

    def delete_document(self, doc_id: str) -> None:
        with self._lock:
            self.db.execute("BEGIN")
            self._delete_contents(doc_id)
            self.db.execute("DELETE FROM documents WHERE id=?", (doc_id,))
            self.db.execute("COMMIT")

    def append_audit(
        self, ts: str, client: str, tool: str, args: dict, block_ids: list[str], doc_ids: list[str]
    ) -> None:
        with self._lock:
            self.db.execute(
                "INSERT INTO audit (ts, client, tool, args, block_ids, doc_ids) VALUES (?,?,?,?,?,?)",
                (
                    ts,
                    client,
                    tool,
                    json.dumps(args, sort_keys=True),
                    json.dumps(block_ids),
                    json.dumps(doc_ids),
                ),
            )

    # -- reads --------------------------------------------------------------------------------

    def _one(self, sql: str, args: tuple, what: str, key: str):
        row = self.db.execute(sql, args).fetchone()
        if row is None:
            raise NotFound(f"unknown {what} '{key}'")
        return row

    @staticmethod
    def _doc(r) -> DocumentRow:
        return DocumentRow(**dict(r))

    @staticmethod
    def _section(r) -> SectionRow:
        return SectionRow(**dict(r))

    @staticmethod
    def _block(r) -> BlockRow:
        d = dict(r)
        d["bbox"] = tuple(json.loads(d["bbox"]))
        d["header"] = json.loads(d["header"]) if d["header"] else None
        d["rows"] = json.loads(d["rows"]) if d["rows"] else None
        return BlockRow(**d)

    @staticmethod
    def _unit(r) -> UnitRow:
        return UnitRow(**dict(r))

    def list_documents(self) -> list[DocumentRow]:
        return [self._doc(r) for r in self.db.execute("SELECT * FROM documents ORDER BY path")]

    def get_document(self, doc_id: str) -> DocumentRow:
        return self._doc(self._one("SELECT * FROM documents WHERE id=?", (doc_id,), "document", doc_id))

    def document_by_path(self, path: str) -> DocumentRow | None:
        r = self.db.execute("SELECT * FROM documents WHERE path=?", (path,)).fetchone()
        return self._doc(r) if r else None

    def sections_for(self, doc_id: str) -> list[SectionRow]:
        return [
            self._section(r)
            for r in self.db.execute("SELECT * FROM sections WHERE doc_id=? ORDER BY idx", (doc_id,))
        ]

    def get_section(self, section_id: str) -> SectionRow:
        return self._section(
            self._one("SELECT * FROM sections WHERE id=?", (section_id,), "section", section_id)
        )

    def blocks_for(self, doc_id: str) -> list[BlockRow]:
        return [
            self._block(r)
            for r in self.db.execute("SELECT * FROM blocks WHERE doc_id=? ORDER BY idx", (doc_id,))
        ]

    def blocks_in_sections(self, section_ids: Iterable[str]) -> list[BlockRow]:
        ids = list(section_ids)
        if not ids:
            return []
        q = ",".join("?" * len(ids))
        rows = self.db.execute(f"SELECT * FROM blocks WHERE section_id IN ({q}) ORDER BY doc_id, idx", ids)
        return [self._block(r) for r in rows]

    def get_block(self, block_id: str) -> BlockRow:
        return self._block(self._one("SELECT * FROM blocks WHERE id=?", (block_id,), "block", block_id))

    def blocks_by_ids(self, ids: Iterable[str]) -> dict[str, BlockRow]:
        ids = list(ids)
        if not ids:
            return {}
        q = ",".join("?" * len(ids))
        return {
            r["id"]: self._block(r) for r in self.db.execute(f"SELECT * FROM blocks WHERE id IN ({q})", ids)
        }

    def get_unit(self, unit_id: str) -> UnitRow:
        return self._unit(self._one("SELECT * FROM units WHERE id=?", (unit_id,), "unit", unit_id))

    def units_by_rowid(self, rowids: Iterable[int]) -> dict[int, UnitRow]:
        ids = list(rowids)
        if not ids:
            return {}
        q = ",".join("?" * len(ids))
        return {
            r["rowid"]: self._unit(r)
            for r in self.db.execute(f"SELECT * FROM units WHERE rowid IN ({q})", ids)
        }

    def vectors_for(self, doc_ids: list[str] | None) -> list[tuple[int, list[float]]]:
        if doc_ids is None:
            rows = self.db.execute("SELECT unit_rowid, data FROM vectors")
        else:
            q = ",".join("?" * len(doc_ids))
            rows = self.db.execute(
                "SELECT v.unit_rowid, v.data FROM vectors v JOIN units u ON u.rowid=v.unit_rowid "
                f"WHERE u.doc_id IN ({q})",
                doc_ids,
            )
        return [(r[0], unpack_vector(r[1])) for r in rows]

    def audit(self, limit: int = 50) -> list[AuditRow]:
        rows = self.db.execute("SELECT * FROM audit ORDER BY id DESC LIMIT ?", (limit,))
        return [
            AuditRow(
                r["id"],
                r["ts"],
                r["client"],
                r["tool"],
                json.loads(r["args"]),
                json.loads(r["block_ids"]),
                json.loads(r["doc_ids"]),
            )
            for r in rows
        ]
