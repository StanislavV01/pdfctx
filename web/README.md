# pdfctx web

One Next.js app, two modes:

- **local** (default): the open-source server on your machine. No accounts. `../scripts/demo.sh` starts both.
- **cloud** (`NEXT_PUBLIC_PDFCTX_MODE=cloud`): pdfctx Cloud. Landing, pricing, email sign-in, the workspace
  app, API keys. The browser calls `/api/*` on the same origin. Next forwards that to the cloud server
  (`PDFCTX_BACKEND`), so the session cookie stays first-party and there is no CORS.

Pages: `/` landing · `/pricing` · `/signin` · `/app` documents and upload · `/app/d/[id]` viewer (outline,
search, `context_pack`, cited boxes on the page) · `/app/metrics` metrics table with source links and CSV ·
`/app/keys` API keys and agent setup · `/app/audit` every tool call.

```bash
# local
PDFCTX_WEB_ORIGIN=http://localhost:3000 pdfctx serve-http ~/Documents/reports --uploads ~/pdfctx-uploads
cd web && npm install && npm run dev                                   # http://localhost:3000/app

# cloud, on your machine (the sign-in link is printed in the server log when RESEND_API_KEY is unset)
pdfctx serve-cloud --data ./cloud-data --public-url http://localhost:3000
cd web && NEXT_PUBLIC_PDFCTX_MODE=cloud npm run dev                    # http://localhost:3000
```
