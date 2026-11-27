# pdfctx Cloud: the API (FastAPI + MCP) and the Next.js web app in one image, behind one port.
# Next serves the site on $PORT and forwards /api/* to the API on 127.0.0.1:8000.

FROM node:22-slim AS web
WORKDIR /web
COPY web/package.json ./
RUN npm install --no-audit --no-fund
COPY web/ ./
ENV NEXT_PUBLIC_PDFCTX_MODE=cloud NEXT_TELEMETRY_DISABLED=1
RUN npm run build

FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends tesseract-ocr curl \
    && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y --no-install-recommends nodejs && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install --no-cache-dir ".[embed]"
COPY --from=web /web /web
COPY deploy/start.sh /start.sh
ENV PDFCTX_DATA=/data PORT=8080 PDFCTX_BACKEND=http://127.0.0.1:8000 NEXT_TELEMETRY_DISABLED=1
EXPOSE 8080
CMD ["/start.sh"]
