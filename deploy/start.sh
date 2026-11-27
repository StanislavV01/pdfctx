#!/bin/bash
# Starts the API and the web app; exits (so the platform restarts the machine) if either stops.
set -e
: "${PDFCTX_PUBLIC_URL:?set PDFCTX_PUBLIC_URL to the public https URL}"
: "${PDFCTX_ALLOWED_HOSTS:=127.0.0.1}"
export PDFCTX_ALLOWED_HOSTS
pdfctx serve-cloud --data "$PDFCTX_DATA" --public-url "$PDFCTX_PUBLIC_URL" --host 127.0.0.1 --port 8000 &
API=$!
cd /web && npx next start -p "$PORT" -H 0.0.0.0 &
WEB=$!
wait -n "$API" "$WEB" 2>/dev/null || wait "$API"
exit 1
