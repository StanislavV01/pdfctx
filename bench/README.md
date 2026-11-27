# Benchmark: FinanceBench retrieval

[FinanceBench](https://github.com/patronus-ai/financebench) (open set) has 150 questions about 84
SEC filings. Each question is annotated with the page(s) that contain the evidence, so retrieval
quality can be measured without an LLM:

- `page_recall@k`: share of questions where an evidence page is in the top-k passages
- `mrr@10`: mean reciprocal rank of the first evidence page
- `tokens@5`: estimated tokens (`len/4`) of the top-5 passages, i.e. what an agent pays to read them
- `latency_p50_ms`: median query time

Doc scope (the FinanceBench setting) searches only the question's own filing; corpus scope searches all 84.

```bash
python -m bench.financebench --systems baseline,pdfctx-structure,pdfctx-context,pdfctx-tables --scope doc
pip install "pdfctx[embed]" pdf-mcp && python -m bench.financebench --systems pdfctx-hybrid,pdfctx-rerank,pdf-mcp
```

The data (CC BY-NC 4.0) is downloaded at a pinned commit into `~/.cache/pdfctx-bench` and never committed.
Results land in `bench/results/{scope}-{system}.json` with per-question ranks for miss analysis.

| system | what it is |
|---|---|
| `baseline` | one passage per page, BM25 over raw page text |
| `pdfctx-structure` | headings/paragraphs/tables as units, BM25 |
| `pdfctx-context` | + document title and section path indexed with every unit |
| `pdfctx-tables` | + every table row indexed with its column headers and caption |
| `pdfctx-hybrid` | + local dense vectors (bge-small), RRF |
| `pdfctx-rerank` | + local cross-encoder rerank of the top 30 |
| `pdf-mcp` | jztan/pdf-mcp `pdf_search` (mode auto, hybrid), same questions and scoring |
