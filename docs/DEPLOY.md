# Deploying pdfctx Cloud

Nothing here runs by itself; deploying is a deliberate step.

## What runs

One container (see `Dockerfile`):
- `pdfctx serve-cloud` on 127.0.0.1:8000. It handles accounts, one SQLite index per workspace under
  `/data/ws/<id>/`, REST at `/v1`, MCP at `/mcp`, and the Stripe webhook. `/data` must be a persistent volume.
- `next start` on `$PORT` (8080). It serves the site and forwards `/api/*` to the API, so the browser stays
  on one origin. Agents use `https://<host>/api/mcp` and `https://<host>/api/v1/…`.

## Configuration

| variable | required | what |
|---|---|---|
| `PDFCTX_PUBLIC_URL` | yes | `https://your-host`: sign-in links and Stripe redirects |
| `PDFCTX_ALLOWED_HOSTS` | yes | host names the API answers to. Behind the proxy that is `127.0.0.1`, plus the public host if the API is exposed |
| `PDFCTX_WEB_ORIGIN` | yes | `https://your-host`, so browser requests with that Origin pass the guard |
| `RESEND_API_KEY`, `PDFCTX_MAIL_FROM` | for real email | without them, sign-in links are only written to the log |
| `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET` | for billing | without them, checkout answers "billing is not configured" |
| `STRIPE_PRICE_PRO`, `STRIPE_PRICE_TEAM` | for billing | recurring monthly price ids ($29 / $99) |
| `PDFCTX_EMBED` | no | `fastembed` turns on dense vectors (more RAM and CPU; see the benchmark first) |

Stripe: add a webhook endpoint `https://<host>/api/billing/webhook` with the events
`checkout.session.completed`, `customer.subscription.created`, `customer.subscription.updated` and
`customer.subscription.deleted`.

## fly.io

```bash
fly launch --no-deploy --copy-config
fly volumes create pdfctx_data --size 10 --region fra
fly secrets set PDFCTX_PUBLIC_URL=https://pdfctx.fly.dev PDFCTX_WEB_ORIGIN=https://pdfctx.fly.dev \
  PDFCTX_ALLOWED_HOSTS=127.0.0.1 RESEND_API_KEY=… PDFCTX_MAIL_FROM="pdfctx <signin@yourdomain>" \
  STRIPE_SECRET_KEY=… STRIPE_WEBHOOK_SECRET=… STRIPE_PRICE_PRO=price_… STRIPE_PRICE_TEAM=price_…
fly deploy
```

## Before real customers

- Backups of `/data`: the accounts DB, the indexes and the uploaded files (for example a nightly `fly ssh`
  tar to object storage).
- Terms, a privacy policy and a DPA: customers upload confidential filings.
- One machine with one volume: SQLite needs a single writer. Scale up the machine before adding machines.
