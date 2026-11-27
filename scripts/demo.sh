#!/usr/bin/env bash
# Local demo: installs pdfctx in .venv, indexes a folder of PDFs, starts the API and the web UI.
#   ./scripts/demo.sh                 # downloads 3M's 2018 10-K into demo-docs/ and uses that
#   ./scripts/demo.sh ~/Documents/x   # your own folder of PDFs
# Stop with Ctrl+C. Needs Python 3.11+ and Node 20+.
set -euo pipefail
cd "$(dirname "$0")/.."

PY=${PYTHON:-python3}
if ! "$PY" -c 'import sys; sys.exit(sys.version_info < (3, 11))' 2>/dev/null; then
  echo "pdfctx needs Python 3.11+ ($PY is $("$PY" -V 2>&1))."
  echo "Install one (brew install python@3.12) and run: PYTHON=python3.12 $0 ${1:-}"
  exit 1
fi
command -v npm >/dev/null || { echo "npm not found: install Node 20+ (brew install node)"; exit 1; }

[ -d .venv ] || "$PY" -m venv .venv
# shellcheck disable=SC1091
. .venv/bin/activate
echo "==> installing pdfctx"
pip install -q --upgrade pip
pip install -q -e ".[dev]"

DOCS=${1:-demo-docs}
if [ "$DOCS" = demo-docs ] && [ ! -f demo-docs/3M_2018_10K.pdf ]; then
  echo "==> downloading 3M's 2018 10-K (FinanceBench)"
  mkdir -p demo-docs
  curl -sSfL -o demo-docs/3M_2018_10K.pdf \
    https://raw.githubusercontent.com/patronus-ai/financebench/cc39aeb4afdf33909ee1412188bf89035950c2eb/pdfs/3M_2018_10K.pdf
fi

echo "==> indexing $DOCS"
pdfctx index "$DOCS"

echo "==> installing the web UI"
(cd web && { [ -d node_modules ] || npm install --no-audit --no-fund; })

echo "==> starting the API on http://127.0.0.1:8000"
PDFCTX_WEB_ORIGIN=http://localhost:3000 pdfctx serve-http "$DOCS" --uploads .uploads &
API_PID=$!
trap 'kill $API_PID 2>/dev/null || true' EXIT INT TERM
for _ in $(seq 1 60); do curl -sf http://127.0.0.1:8000/healthz >/dev/null && break; sleep 1; done

echo
echo "==> open http://localhost:3000/app  (search: purchases of property plant and equipment 2018; or the Metrics tab)"
echo
cd web && NEXT_PUBLIC_PDFCTX_API=http://127.0.0.1:8000 npm run dev
