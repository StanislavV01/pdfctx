<div align="center">

# 📑 pdfctx

**PDF retrieval for AI agents that finds the right page more often and costs 10× fewer tokens.**

pdfctx turns PDFs into a section tree of paragraphs and tables with page + bounding box on every block, and
gives agents (Claude, Cursor, any MCP client) tools to navigate, search, cite and pack context. It reads
borderless SEC-style tables row by row, and it logs every read.

![Python](https://img.shields.io/badge/python-3.11+-3776AB?style=flat&logo=python&logoColor=white)
![MCP](https://img.shields.io/badge/MCP-SDK_2.3-6366F1?style=flat)
![FastAPI](https://img.shields.io/badge/FastAPI-REST-009688?style=flat&logo=fastapi&logoColor=white)
![Local-first](https://img.shields.io/badge/local--first-no_API_keys-22C55E?style=flat)
[![CI](https://github.com/StanislavV01/pdfctx/actions/workflows/ci.yml/badge.svg)](https://github.com/StanislavV01/pdfctx/actions)

</div>

---

## Results: FinanceBench

[FinanceBench](https://github.com/patronus-ai/financebench) (open set) has 150 questions about 84 SEC filings
(10-K, 10-Q, 8-K, earnings releases), and each question is labeled with its evidence pages. Below, each system
retrieves 10 passages from the question's filing, and we measure whether an evidence page is among them. No LLM
is involved and nothing is graded by a model.

| system | R@1 | R@3 | R@5 | R@10 | MRR@10 | tokens for top-5 |
|---|---|---|---|---|---|---|
| page-level BM25 (what most "chat with PDF" tools do) | 0.147 | 0.233 | 0.360 | 0.507 | 0.230 | 4,615 |
| pdfctx: structure | 0.160 | 0.267 | 0.333 | 0.453 | 0.237 | 586 |
| pdfctx: + section context | 0.160 | 0.267 | 0.353 | 0.500 | 0.242 | 572 |
| **pdfctx: + table rows (default)** | **0.167** | **0.313** | **0.393** | **0.567** | **0.270** | **461** |

**pdfctx is ahead of the page baseline on every metric while handing the agent 10× fewer tokens.** Every
change was kept or reverted based on these numbers. The log in
[`bench/results/CHANGELOG.md`](bench/results/CHANGELOG.md) includes what did not work: summed page boosts lost
to boilerplate, and document routing hurt corpus search. Defaults are rounded, not fitted to the 150 questions.

Structure alone does not beat the baseline at R@5–10; the gain comes from table rows.

The scores are low on purpose: FinanceBench is hard. Questions like *"what is 3M's FY2018 capital
expenditure?"* do not say *"Purchases of property, plant and equipment"*, the line item that holds the answer.
Lexical search cannot close that gap alone. The next rows are dense vectors and a cross-encoder reranker,
which run locally through `pdfctx[embed]`, plus [`jztan/pdf-mcp`](https://github.com/jztan/pdf-mcp) scored
the same way. They run in the [Benchmark workflow](.github/workflows/bench.yml) and will be added here from
its artifact.

Corpus scope (search all 84 filings): R@10 0.200 vs 0.187 for the baseline at 12× fewer tokens, but rank-1 is
lower (0.073 vs 0.093). Finding the right filing among 84 similar ones is the open problem
([details](bench/results/CHANGELOG.md#corpus-scope-no-tuning-was-done-here)).

## Why it works

- **Structure, not chunks.** PDFium (via pypdfium2) gives every character a box. pdfctx rebuilds words, lines,
  columns and paragraphs, and drops running headers, footers and page numbers, including the ones HTML-to-PDF
  converters print mid-page. Headings and bookmarks become a section tree.
- **Tables without borders.** SEC filings draw tables with whitespace only, and ruling-line detectors find
  nothing in them. pdfctx finds tables from text alignment: a label plus right-aligned numeric cells, with year
  and caption lines above. Each **row** is indexed with its headers and caption:
  `Consolidated Statement of Cash Flows · (Millions) › Purchases of PP&E | 2018: (1,577) | 2017: (1,373)`.
- **Page-aware ranking.** One result per page, a bounded boost for pages with several matches, and the most
  specific match (a row rather than the whole table). This is how small units beat whole pages on recall while
  staying cheap.
- **Everything local by default.** BM25 lives in SQLite FTS5 and the whole index is one file. Dense vectors
  and reranking are optional, either local (fastembed, ONNX on CPU) or through OpenAI / Voyage / Cohere keys.

## Tools for agents

| Tool | What it returns |
|---|---|
| `list_documents` | indexed PDFs with status (`ok`, `no_text`, `encrypted`, `failed`) |
| `outline(doc_id)` | the section tree with ids and pages |
| `read_section(section_id, max_tokens)` | a whole section, sub-sections included, in reading order |
| `search(query, doc_ids, k)` | paragraphs, tables or single table rows, with page, bbox and section path |
| `get_table(table_id, format)` | a full table as markdown or CSV, with its caption |
| `cite(block_id)` | file, page, bounding box and the verbatim text, so the user can verify |
| `context_pack(query, budget_tokens)` | the best evidence within a token budget, deduplicated and in document order |

All tools are read-only (`readOnlyHint`). Errors come back as readable tool errors. Every call is appended to an
audit log: which client, which tool, which blocks it received.

```text
$ pdfctx audit --db 10k/.pdfctx/index.db
2026-11-27T01:18:23.062+00:00  claude     search     {"doc_ids": null, "k": 3, "query": "purchases of property plant and equipment 2018"}  → 3 block(s)
2026-11-27T01:18:23.063+00:00  claude     get_table  {"format": "markdown", "table_id": "d34948841326:b797"}  → 1 block(s)
```

## Quick start

```bash
pip install "git+https://github.com/StanislavV01/pdfctx"     # PyPI release coming
pdfctx index ~/Documents/contracts
pdfctx search "termination notice period" --db ~/Documents/contracts/.pdfctx/index.db
```

**Claude Code**

```bash
claude mcp add pdfctx -- uvx --from git+https://github.com/StanislavV01/pdfctx pdfctx serve ~/Documents/contracts
```

**Claude Desktop / Cursor**

```json
{
  "mcpServers": {
    "pdfctx": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/StanislavV01/pdfctx", "pdfctx", "serve", "/Users/me/Documents/contracts"]
    }
  }
}
```

The folder is indexed on start, and files that are added, changed or deleted are re-indexed on the next tool
call.

**HTTP (REST + remote MCP)**

```bash
pdfctx serve-http ~/Documents/contracts --port 8000 --uploads ./uploads
curl "localhost:8000/v1/search?q=termination%20notice"
curl -X POST localhost:8000/v1/context -H 'content-type: application/json' \
     -d '{"query": "revenue by region 2024", "budget_tokens": 1500}'
# MCP clients connect to http://localhost:8000/mcp
```

Uploads (`POST /v1/documents`, raw PDF body) are off unless `--uploads` is set, and are limited to 20 MB and
300 pages. `GET /v1/documents/{id}/pages/{n}.png` renders a page so a UI can draw cited boxes on it.

**Better recall with local models** (first run downloads ~200 MB of ONNX models):

```bash
pip install "pdfctx[embed] @ git+https://github.com/StanislavV01/pdfctx"
pdfctx serve ~/Documents/contracts --embed fastembed --rerank fastembed
```

## Limits

- Text-layer PDFs only. Scanned pages are reported as `no_text`, and there is no OCR yet
  (pdf-mcp has it).
- Tables are detected from alignment. Unusual layouts can split or merge rows, and `get_table` always
  returns what was parsed, so it can be checked.
- Token counts are estimates (`len / 4`).
- Some HTML-to-PDF converters letter-space words in the text layer itself (`Busines s`). pdfctx keeps what
  the PDF says.

## Development

```bash
pip install -e ".[dev]" && pytest
python -m bench.financebench --systems baseline,pdfctx-tables --scope doc   # downloads FinanceBench (~160 MB)
```

The repository uses its own quality gate,
[seaworthy](https://github.com/StanislavV01/seaworthy): ruff and pytest must pass before every commit, and
test tampering is flagged.

## License

MIT. FinanceBench data (CC BY-NC 4.0) is downloaded at run time and not redistributed.
