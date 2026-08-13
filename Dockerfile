# Production Dockerfile for the IFSP Story app
# Backend and frontend run in the same container.
FROM node:20-bookworm-slim AS base

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 \
    python3-pip \
    python3-venv \
    build-essential \
    bash \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY package*.json ./
RUN npm ci --no-fund --no-audit

COPY webapp/requirements.txt ./webapp/requirements.txt
RUN python3 -m pip install --upgrade pip \
    && python3 -m pip install --no-cache-dir -r ./webapp/requirements.txt

COPY . .
RUN npm prune --omit=dev --no-fund --no-audit \
    && chmod +x ./start-services.sh ./healthcheck.sh

ENV NODE_ENV=production \
    PORT=3000 \
    PYTHONUNBUFFERED=1 \
    SEMANTIC_MODE=legacy \
    BACKEND_HOST=0.0.0.0 \
    BACKEND_PORT=8000

EXPOSE 3000 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=25s --retries=5 \
  CMD ./healthcheck.sh

CMD ["./start-services.sh"]
