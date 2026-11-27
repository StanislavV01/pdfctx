# pdfctx Cloud v0.2 — plan

Spec: `docs/superpowers/specs/2026-11-27-pdfctx-cloud-design.md`. TDD throughout; every commit goes through
the seaworthy gate (`/home/claude/pdfc.sh`). Commits are by Stanislav only.

## Tasks

1. **OCR** — `parse/ocr.py` (tesseract TSV → `Word`s; 300 dpi render under `PDFIUM_LOCK`; timeout), wired
   into `parse_pdf` for empty pages; `ParsedDoc.ocr_pages`; CI installs `tesseract-ocr`.
   Tests: image-only PDF from `pdfgen.make_image_only` becomes searchable; bbox is on the page; skipped without
   tesseract.
2. **Metrics** — `metrics.py`: synonyms, number and unit parsing, year columns from row units, best-row choice,
   `Library.extract_metrics`, MCP tool `extract_metrics`, REST `POST /v1/metrics` (+ `?format=csv`), audit.
   Tests: number parsing table, the synthetic report's table, and golden 3M 2018 capex (the PDF comes from the
   bench cache; the test is skipped if absent).
3. **Accounts** — `cloud/accounts.py` (SQLite: users, workspaces, sessions, magic tokens, api keys, usage),
   `cloud/mail.py` (Resend over urllib; log fallback). Tests: token single-use and expiry, key hashing, usage
   by month.
4. **Tenants + cloud app** — `cloud/app.py`: `create_cloud_app(data_dir)`; auth routes (`/auth/request`,
   `/auth/verify`, `/auth/logout`, `/me`); workspace routes under `/app/v1/*` that reuse the REST handlers on
   the caller's `Library`; API keys; MCP per workspace with a bearer key; limits on upload; CSRF header.
   Tests: tenant isolation (user B cannot read A's documents by id), key auth, limit refusal (402).
5. **Billing** — `cloud/billing.py`: plans, Checkout session creation (urllib), webhook verification and plan
   updates. Tests: valid and invalid signatures, replay outside tolerance, plan change, unknown events ignored.
6. **Accuracy** — read the benchmark run; if hybrid/rerank beat lexical, make the cloud default
   `PDFCTX_EMBED=fastembed`; README/CHANGELOG with the numbers either way.
7. **Web** — landing (`/`), pricing, sign-in, `/app` (documents, upload, viewer moved under `/app/d/[id]`),
   `/app/metrics` (metric picker, years, table with clickable citations, CSV), `/app/keys`. The local demo keeps
   working through `NEXT_PUBLIC_PDFCTX_MODE=local`.
8. **Ship-ready** — `Dockerfile` (python:3.12-slim + tesseract + the built web as a static export or a separate
   node stage), `fly.toml`, `docs/DEPLOY.md`; `pdfctx serve-cloud` CLI. No deploy.
9. **E2E + review** — the CI screenshot job runs the cloud flow (dev magic link from the log); an independent
   review of the branch; fixes; README section "pdfctx Cloud".
