# pdfctx web demo

A Next.js UI over the pdfctx REST API: document list with upload, outline navigation, search and
`context_pack` side by side, and the page image with every cited block highlighted at its exact bounding box.

```bash
# terminal 1 — the API (CORS allowed for the web origin)
PDFCTX_WEB_ORIGIN=http://localhost:3000 pdfctx serve-http ~/Documents/reports --uploads ./uploads

# terminal 2 — the UI
cd web && npm install && NEXT_PUBLIC_PDFCTX_API=http://127.0.0.1:8000 npm run dev
```
