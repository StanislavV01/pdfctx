# pdfctx: design

**Status:** approved, v0.1 scope · **Date:** 2026-11-27 · **Author:** Stanislav

## 1. Problem

Agents read PDFs badly. Chunk-and-embed RAG hands an agent a few disconnected fragments: it loses
the document's structure, mangles tables and gives citations nobody can check. Long, table-heavy
documents (annual reports, contracts, manuals) are where this hurts most.

Good open-source PDF MCP servers already exist. The strongest, `jztan/pdf-mcp`, does hybrid search,
TOC, tables, OCR and folder search. pdfctx only matters if it **retrieves better and costs the agent
fewer tokens, measured on a public benchmark**.

## 2. Goal

A PDF retrieval engine and MCP/REST server for agents that beats a page-level baseline and
`pdf-mcp` on FinanceBench evidence-page recall at equal or lower returned tokens, and publishes
the numbers.

## 3. Benchmark (built first)

- **Data:** FinanceBench open set — 150 questions over 84 SEC filings, each with evidence page
  numbers. PDFs and questions are downloaded by the benchmark script from
  `github.com/patronus-ai/financebench` (CC BY-NC 4.0) and never committed here.
- **Task:** for each question retrieve passages from its own document (doc-scoped, the FinanceBench
  setting) and, as a harder variant, from the whole 84-document corpus.
- **Metrics (no LLM, no keys):**
  - `page_recall@k`, k ∈ {1, 3, 5, 10}: hit when any of the top-k passages lies on an evidence page
    (and, corpus-wide, in the right document).
  - `MRR@10` with the same hit definition.
  - `tokens@5`: mean estimated tokens of the top-5 passages — what the agent pays to read them.
  - p50 query latency.
- **Optional end-to-end:** with an API key, answer from the top-k context and grade with an LLM
  judge against the gold answer. Not part of CI.
- **Systems:** (1) `baseline-page`: one passage per page, BM25; (2) pdfctx ablations adding one
  technique at a time (§4); (3) `pdf-mcp` from PyPI, queried through its own search over the same
  files and scored by the same metric, version pinned in the results file.
- **Output:** `bench/results/<system>.json` and a markdown table the README embeds.

## 4. Retrieval techniques (each one measured)

1. **Structure-aware units.** Headings, paragraphs and tables with page + bbox; running headers,
   footers and page numbers removed; section tree from bookmarks or heading heuristics.
2. **Contextual indexing.** Each unit is indexed with a prefix of document title + section path
   (e.g. `3M 2018 10-K › Item 8 › Consolidated Statement of Cash Flows`). The prefix is used for
   retrieval only, never shown as body text.
3. **Table-first indexing.** Tables are indexed whole (lead-in sentence + header row) and row by
   row, each row rendered with its column headers
   (`Purchases of PP&E | 2018: (1,577) | 2017: (1,373)`), so a line-item question hits that row.
4. **Hybrid + rerank.** BM25 (SQLite FTS5) + optional dense vectors (`fastembed`, bge-small) fused
   with reciprocal rank fusion; optional ONNX cross-encoder rerank of the top 30. Without extras
   everything still works on BM25.
5. **Token-efficient answers.** `context_pack` returns matching rows with their table header and
   surrounding section, deduplicated, in document order, within a token budget.

## 5. Product surface

Seven tools, identical over MCP (stdio and streamable HTTP), FastAPI REST and the CLI:
`list_documents`, `outline(doc_id, max_depth)`, `read_section(section_id, max_tokens)`,
`search(query, doc_ids, k)`, `get_table(table_id, format)`, `cite(block_id)` (file, page, bbox,
exact text), `context_pack(query, budget_tokens, doc_ids)`.

Every tool call is appended to an audit log (client, tool, returned blocks); `pdfctx audit` prints
it — the base for v0.3 team features.

CLI: `pdfctx index`, `serve` (stdio MCP), `serve-http` (REST at `/v1`, MCP at `/mcp`), `search`,
`outline`, `audit`. One SQLite file per index, incremental by content hash.

Out of scope for v0.1: OCR/scanned PDFs (reported as `no_text`), DOCX, auth, multi-tenant
collections, hosted demo.

## 6. Architecture

```
src/pdfctx/
  parse/      lines, blocks, tables, pdf.parse_pdf -> ParsedDoc
  outline.py  section tree + block assignment
  units.py    retrieval units (block, table, table_row) + context prefix
  store.py    SQLite: documents, sections, blocks, units, units_fts (FTS5), vectors, audit
  indexer.py  incremental indexing of files/folders
  embed.py    Embedder/Reranker protocols; Hash, FastEmbed implementations
  search.py   BM25 / vector / RRF / rerank pipeline, configurable for ablations
  context.py  read_section, cite, context_pack
  library.py  façade used by every interface; writes the audit log
  mcp_server.py, api.py, cli.py
bench/
  financebench.py, systems.py, results/
```

Decisions:

- SQLite FTS5, tokenizer `unicode61 remove_diacritics 2`; user text is reduced to word tokens and
  OR-ed, so it never reaches FTS5 syntax.
- Token estimate = `ceil(len(text) / 4)` everywhere, including when scoring `pdf-mcp`.
- Pages are 1-based in pdfctx. FinanceBench `evidence_page_num` is 0-based; the benchmark converts
  it once and a test pins the conversion against known evidence text.

## 7. Quality bar

- Python ≥ 3.11. Runtime deps: `pdfplumber`, `pypdf`, `mcp>=2.3,<3`, `fastapi`, `uvicorn`. Extra
  `embed` = `fastembed`. Dev: `pytest`, `reportlab`, `ruff`, `httpx`.
- Unit tests on reportlab-generated PDFs plus two MIT-licensed PDFs from pdfplumber's tests.
- CI: ruff + pytest on 3.11/3.13 × Ubuntu/macOS; a manual workflow runs the full benchmark with
  extras and `pdf-mcp`.
- Commits: Conventional Commits, author `Stanislav <83041246+StanislavV01@users.noreply.github.com>`,
  no trailers.
