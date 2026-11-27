#!/bin/bash
# End-to-end check of the built image, the way a customer uses it: sign in by email link, upload a filing,
# build a metrics table, call MCP with an API key. Usage: deploy/smoke.sh <image>
set -euo pipefail
IMG=${1:-pdfctx-cloud}
URL=http://localhost:8080
docker rm -f pdfctx-smoke >/dev/null 2>&1 || true
docker run -d --name pdfctx-smoke -p 8080:8080 \
  -e PDFCTX_PUBLIC_URL=$URL -e PDFCTX_WEB_ORIGIN=$URL -e PDFCTX_ALLOWED_HOSTS=127.0.0.1 "$IMG" >/dev/null
trap 'docker logs pdfctx-smoke 2>&1 | tail -n 40; docker rm -f pdfctx-smoke >/dev/null' EXIT
for _ in $(seq 1 60); do curl -sf $URL/api/healthz >/dev/null && break; sleep 2; done
curl -sf $URL/ | grep -q "Every number with its source row"
echo "ok: landing page"

J=(-H "content-type: application/json" -H "x-pdfctx: 1")
curl -sf "${J[@]}" -d '{"email":"smoke@example.com"}' $URL/api/auth/request >/dev/null
sleep 1
LINK=$(docker logs pdfctx-smoke 2>&1 | grep -o "$URL/api/auth/verify?token=[A-Za-z0-9_-]*" | tail -1)
[ -n "$LINK" ] || { echo "no sign-in link in the log"; exit 1; }
curl -s -c /tmp/jar -o /dev/null -w "%{http_code} %{redirect_url}\n" "$LINK" | grep -q "303 $URL/app"
curl -sf -b /tmp/jar $URL/api/me | grep -q '"email":"smoke@example.com"'
echo "ok: email sign-in"

PDF=${PDF:?set PDF to a small text PDF}
curl -sf -b /tmp/jar -H "x-pdfctx: 1" -H "content-type: application/pdf" -H "x-filename: report.pdf" \
  --data-binary @"$PDF" $URL/api/v1/documents | grep -q '"status":"ok"'
curl -sf -b /tmp/jar "${J[@]}" -d '{"metrics":["Total"],"years":[2025]}' $URL/api/v1/metrics | grep -q '"value":2000.0'
echo "ok: upload and metrics"

KEY=$(curl -sf -b /tmp/jar "${J[@]}" -d '{"name":"smoke"}' $URL/api/keys | python3 -c 'import sys,json;print(json.load(sys.stdin)["key"])')
curl -sf -H "authorization: Bearer $KEY" $URL/api/v1/documents | grep -q '"documents"'
code=$(curl -s -o /dev/null -w "%{http_code}" -H "authorization: Bearer pk_live_wrong" $URL/api/v1/documents)
[ "$code" = 401 ]
echo "ok: API keys"

INIT='{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"smoke","version":"1"}}}'
curl -sf -H "authorization: Bearer $KEY" -H "content-type: application/json" \
  -H "accept: application/json, text/event-stream" -d "$INIT" $URL/api/mcp | grep -q '"serverInfo"'
echo "ok: MCP over the proxy with an API key"
trap 'docker rm -f pdfctx-smoke >/dev/null' EXIT
echo "smoke test passed"
