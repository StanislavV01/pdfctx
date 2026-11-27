# pdfctx: design

**Status:** approved direction, v0.1 scope · **Date:** 2026-11-27 · **Author:** Stanislav

## 1. Problem

Agents read PDFs badly. Chunk-and-embed RAG hands an agent five disconnected fragments: it loses the
document's structure (which section is this, what came before), mangles tables, and gives citations
nobody can check. Businesses add a second problem: they cannot see or control what an agent read.

## 2. Product

pdfctx gives agents **structured, verifiable, accountable** access to PDFs.

- **Structured.** A document is a tree of sections with paragraphs and tables, not a bag of chunks.
  The agent can look at the outline and read a section the way a person would.
- **Verifiable.** Every block carries its file, page and bounding box. Any answer can be traced to
  a highlighted rectangle on a page.
- **Accountable.** Every tool call is written to an append-only audit log: who asked, what for,
  and which blocks were returned.

One Python package, three ways to run it (only the first is v0.1):

| Mode | Who | Where data lives | Version |
|---|---|---|---|
| Local CLI + stdio MCP | individuals, Claude Desktop / Cursor | user's machine | **v0.1** |
| HTTP server (FastAPI REST + streamable-HTTP MCP) | demo, teams | our host (demo) or the client's | v0.1 (server code), v0.2 (hosted demo) |
| Team features (collections, per-agent tokens, roles, SSO) | companies | client's cloud (Docker) | v0.3 |

## 3. v0.1 scope

In scope:

1. Parse text-layer PDFs into blocks: headings, paragraphs, tables (as rows), with page + bbox.
2. Remove running headers/footers and page numbers.
3. Build a section tree: from PDF bookmarks when present, otherwise from heading heuristics.
4. Index a folder or files into one SQLite database; re-index only changed files (content hash);
   drop deleted files.
5. Search: BM25 via SQLite FTS5 by default (no keys, no model download). Optional dense vectors
   through a pluggable embedder (`pdfctx[embed]` → fastembed bge-small); hybrid via reciprocal
   rank fusion.
6. Agent tools (identical over MCP and REST):
   - `list_documents()`
   - `outline(doc_id, max_depth=3)`
   - `read_section(section_id, max_tokens=2000)` (section ids embed the document id)
   - `search(query, doc_ids=None, k=8)`
   - `get_table(table_id, format="markdown"|"csv")`
   - `cite(block_id)` → file, page, bbox, exact text
   - `context_pack(query, budget_tokens=4000, doc_ids=None)` → deduplicated blocks in document
     order, grouped under their section headings, each with a citation, fitting the budget.
7. Audit log of every tool call (SQLite table) and `pdfctx audit` to read it.
8. CLI: `index`, `serve` (stdio MCP), `serve-http` (FastAPI + MCP at `/mcp`), `search`, `outline`,
   `audit`.
9. FastAPI REST mirroring the tools, plus `POST /documents` upload with limits.

Out of scope for v0.1: OCR/scanned PDFs (detected and reported as "no text layer"), DOCX/XLSX,
auth and multi-tenant collections, the benchmark (v0.2), hosted deployment (v0.2), GUI app.

## 4. Architecture

```
pdfctx/
  parse/      PDF -> ParsedDoc (blocks with page, bbox, font stats, tables)
  outline     ParsedDoc -> Section tree, block -> section assignment
  store       SQLite: documents, sections, blocks, blocks_fts (FTS5), vectors, audit
  search      FTS5 BM25 + optional embedder, RRF fusion
  context     read_section, cite, context_pack (token budgeting)
  library     the one façade every interface calls; writes the audit log
  mcp_server  MCPServer (mcp 2.x) tools over stdio / streamable HTTP
  api         FastAPI app
  cli         argparse entry point
```

`Library` is the only API the interfaces use, so MCP, REST and CLI cannot drift apart.

### Data model

- `Document(id, path, sha256, title, pages, indexed_at, status, error)` — `id` is a short stable
  hash of the absolute path; `status` ∈ `ok | no_text | encrypted | failed`.
- `Section(id, doc_id, parent_id, level, title, page, order)` — `id` = `{doc_id}:s{n}`.
- `Block(id, doc_id, section_id, kind, page, bbox, order, text, tokens)` — `kind` ∈
  `heading | paragraph | table`; `id` = `{doc_id}:b{n}`; tables also keep `rows` (JSON).
- `bbox` is `(x0, top, x1, bottom)` in PDF points, top-left origin (pdfplumber convention).

### Key decisions

- **SQLite + FTS5** gives BM25 for free, one file per index, nothing to run. Tokenizer
  `unicode61 remove_diacritics 2` so Polish/Ukrainian text matches without diacritics.
- **User queries never reach FTS5 syntax.** Queries are reduced to word tokens and combined with
  `OR`, so quotes, hyphens, `AND`, `NEAR`, `*` and `:` cannot raise errors or change semantics.
- **Token estimate** = `ceil(len(text) / 4)`; documented as an estimate (no tokenizer dependency).
- **Headings**: a line is a heading candidate if its font size is ≥ 1.15× the document's body
  size (the most common size by character count), or it is bold and short (≤ 12 words) and
  standalone, or it matches a numbering pattern (`1.`, `1.2`, `Article 5`, `§ 3`). Heading levels
  are ranked by font size, then by numbering depth.
- **Headers/footers**: lines in the top or bottom 8% of the page whose normalized text (digits
  replaced by `#`) repeats on ≥ 50% of pages (min 3 pages) are dropped.
- **Tables**: `pdfplumber.Page.find_tables()`; words inside a table bbox are excluded from
  paragraphs; a table is kept only if it has ≥ 2 rows and ≥ 2 columns.
- **Reading order**: blocks sorted by page, then column (detected by x-gaps ≥ 15% page width),
  then top.
- **Audit**: `(ts, client, tool, args_json, block_ids_json, doc_ids_json)`; append-only; the
  library never updates or deletes rows.

## 5. Interfaces

- `pdfctx index PATH... [--db FILE]` — default DB `<first dir>/.pdfctx/index.db`, or
  `./.pdfctx/index.db` for files.
- `pdfctx serve PATH... [--db]` — index then serve MCP over stdio; files changed since the
  last call are re-indexed lazily at the start of each tool call (mtime check, then hash).
- `pdfctx serve-http PATH... [--host 127.0.0.1] [--port 8000]` — FastAPI with REST under `/v1`
  and MCP streamable HTTP at `/mcp`.
- REST: `GET /v1/documents`, `GET /v1/documents/{id}/outline`, `GET /v1/sections/{id}`,
  `GET /v1/search?q=&k=`, `GET /v1/tables/{id}?format=`, `GET /v1/blocks/{id}/cite`,
  `POST /v1/context`, `POST /v1/documents` (multipart upload; max 20 MB, max 300 pages,
  PDF magic bytes required), `GET /healthz`.
- Errors: tools return clear messages (`unknown section 'x'`, `document is encrypted`), never
  stack traces.

## 6. Quality bar

- Python ≥ 3.11; dependencies: `pdfplumber`, `pypdf`, `mcp>=2.3,<3`, `fastapi`, `uvicorn`.
  Optional extra `embed`: `fastembed`. Dev: `pytest`, `reportlab`, `ruff`, `httpx`.
- Tests generate their PDFs with reportlab (deterministic headings, bookmarks, tables,
  headers/footers, two columns, Polish text) and also run on real PDFs vendored from
  pdfplumber's test-suite (MIT).
- CI: ruff + pytest on Python 3.11 and 3.13, Ubuntu and macOS.
- Commits: Conventional Commits, author `Stanislav <83041246+StanislavV01@users.noreply.github.com>`,
  no trailers.

## 7. Later

- v0.2: benchmark (chunk-RAG vs navigation on a fixed QA set; retrieval recall@k, answer
  citation precision), hosted demo with preloaded documents, Dockerfile.
- v0.3: collections, per-agent tokens, role filters applied inside `Library`, audit export.
