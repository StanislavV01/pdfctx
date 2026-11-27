# pdfctx Cloud for finance — design

Date: 2026-11-27 · Status: agreed scope, building

## Who pays and for what

Finance analysts, small funds, and people doing due diligence. They upload filings (10-K, 10-Q, annual reports,
including scanned ones). They need two things. First, cited answers their agent can use (MCP / API). Second, a
**metrics table**: "revenue, capex, net income for 2021–2023" across many filings, where every value links to its
page and row. The table is what they would otherwise copy by hand, so it is the paid feature.

Positioning: "Every number with its source row. Your agent reads filings through pdfctx and cites the line it used."

## Scope of iteration 1

| # | Feature | Done when |
|---|---|---|
| A | **Accuracy**: dense + rerank as the cloud default | turned on only if the FinanceBench run shows a gain; the README states the result either way |
| B | **OCR** for pages without a text layer | a scanned PDF becomes searchable with bboxes; no new Python dependency (tesseract binary, optional) |
| C | **Metrics extraction** `extract_metrics(metrics, years, doc_ids)` | returns value + unit + page + bbox + the row text per cell; CSV export; FinanceBench-derived golden test |
| D | **Accounts and workspaces** | sign up by email magic link; every workspace has its own index file; API keys for agents; MCP over HTTP with a bearer key |
| E | **Plans and billing** | Free / Pro / Team page limits enforced on upload; Stripe Checkout + signed webhook through stdlib `urllib`/`hmac` (no SDK) |
| F | **Landing + pricing + app** | Next.js: landing, pricing, sign-in, the existing viewer per workspace, a metrics page with CSV download |
| G | **Ship-ready, not shipped** | Dockerfile (tesseract included), env-var config, one `fly.toml`; deploying waits for an explicit go |

Out of scope: SSO, team roles, document sharing between workspaces, hosted LLM answers.

## Architecture

```
browser (Next.js) ──cookie session──▶ FastAPI /app/v1/*  ┐
agent (MCP/REST) ──Bearer api key────▶ FastAPI /w/{ws}/mcp ┤─▶ Tenants ─▶ Library(ws) ─▶ data/ws/<id>/index.db
Stripe ──signed webhook──────────────▶ /billing/webhook    ┘        accounts.db (users, workspaces, keys, usage)
```

- **Tenancy.** One `Library` per workspace, opened lazily and kept in an LRU cache, with the index at
  `DATA_DIR/ws/<id>/index.db` and uploads under `DATA_DIR/ws/<id>/files/`. Separate files are simpler than
  row-level tenancy and safer: a query bug cannot cross tenants. `accounts.db` holds users, workspaces, API keys
  (only sha256 is stored), magic-link tokens (sha256, 15 min, single use), sessions, and usage (pages per month).
- **Auth.** Magic link by email through the Resend HTTP API (`RESEND_API_KEY`); with no key the link is logged
  (dev). Session: an HttpOnly, SameSite=Lax, Secure (on https) cookie holding a random token whose hash is stored.
  State-changing routes require the custom header `x-pdfctx: 1` as CSRF defence (a cross-site form cannot set it).
  API keys look like `pk_live_…`, are shown once and revocable.
- **Limits.** Free 50 pages total, Pro 2,000 pages/month, Team 10,000 pages/month. Upload checks the limit
  before indexing. The webhook sets the plan from `checkout.session.completed` and `customer.subscription.*`.
- **OCR.** `parse/ocr.py`: when a page has no text and `tesseract` is on PATH, render it at 300 dpi with pdfium,
  run `tesseract … tsv`, and turn the words (with confidence ≥ 50) into the same `Word` objects as the text layer.
  So columns, tables, headings and citations work unchanged. `ParsedDoc` gains `ocr_pages`. The status is
  `ok` if any page has text.
- **Metrics.** `metrics.py`, deterministic with no LLM. For each metric, search table-row units (synonyms
  expand the query: capex → "purchases of property, plant and equipment", …). Keep rows whose label matches a
  synonym. Read the cells by header year. Parse numbers (parentheses mean negative, `—` means none, units from
  the caption or lead-in such as "(Millions)"). Pick the best row per (metric, year, doc) by label match, then by
  a primary statement over notes. Every cell carries a citation, and gaps stay empty, never guessed.
- **Accuracy.** `SearchConfig` stays lexical by default locally. The cloud enables `vectors`/`rerank` with
  fastembed when `PDFCTX_EMBED=fastembed`, and only if the benchmark run supports it.

## Security notes

- Every workspace route resolves the workspace from the session or key, never from a client-supplied id
  alone (the id in the URL must belong to the caller).
- Webhook: verify `Stripe-Signature` (HMAC-SHA256 over `t.payload`) with a 5-minute tolerance, using a
  constant-time compare.
- The existing host/origin guard stays. In the cloud, `PDFCTX_ALLOWED_HOSTS` and `PDFCTX_WEB_ORIGIN` are required.
- Uploads keep the existing limits. Rendering and OCR run under the pdfium lock and a 60 s timeout per page.

## Testing

Unit tests for each module. Billing webhook tests use real signatures computed in the test. OCR tests are
skipped when tesseract is missing, and CI installs it. A metrics golden test uses the synthetic report plus 3M
2018 capex = 1,577 (the CI web job already downloads that filing). E2E: the CI screenshot job is extended to
sign-in → upload → metrics.
