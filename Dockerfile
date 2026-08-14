# Production Dockerfile for the IFSP Story application
# This deploys the real Python web UI plus the Node compatibility shell in one container.
FROM amr-registry-pre.caas.intel.com/if-pdh-ai-assist/ifspstory:latest

# Final image path used when this app is tagged and pushed to the Intel registry.
ARG APP_IMAGE=amr-registry-pre.caas.intel.com/if-pdh-ai-assist/ifspstory:latest
LABEL org.opencontainers.image.title="IFSP Story" \
      org.opencontainers.image.source="amr-registry-pre.caas.intel.com/if-pdh-ai-assist/ifspstory" \
      org.opencontainers.image.version="latest"

ENV http_proxy=http://proxy-dmz.intel.com:912 \
    https_proxy=http://proxy-dmz.intel.com:912 \
    no_proxy=localhost,127.0.0.0/8,10.0.0.0/8,.intel.com \
    HTTP_PROXY=http://proxy-dmz.intel.com:912 \
    HTTPS_PROXY=http://proxy-dmz.intel.com:912 \
    NO_PROXY=localhost,127.0.0.0/8,10.0.0.0/8,.intel.com \
    NODE_ENV=production \
    PORT=3000 \
    HOST=0.0.0.0 \
    PYTHONUNBUFFERED=1 \
    SEMANTIC_MODE=legacy \
    BACKEND_HOST=0.0.0.0 \
    BACKEND_PORT=8001 \
    PYTHON_BASE_URL=http://127.0.0.1:8001

WORKDIR /app

# Install system dependencies required by Python + Node runtime
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 \
    python3-pip \
    python3-venv \
    build-essential \
    bash \
    curl \
    procps \
    && rm -rf /var/lib/apt/lists/*

# Use the Intel package registry for Node dependencies when needed
RUN npm config set registry https://pixi.intel.com/

# Copy Node package metadata first for efficient dependency caching
COPY package*.json ./
RUN npm ci --no-fund --no-audit

# Install Python dependencies used by the actual IFSP planner app
COPY webapp/requirements.txt ./webapp/requirements.txt
RUN python3 -m pip install --upgrade pip \
    && python3 -m pip install --no-cache-dir -r ./webapp/requirements.txt

# Copy the rest of the project
COPY . .

# Ensure startup scripts are executable
RUN chmod +x ./start-services.sh ./healthcheck.sh

# Expose both the Node shell and the Python app UI
EXPOSE 3000 8001

# Healthcheck verifies the app is up and responding on both entry points.
HEALTHCHECK --interval=30s --timeout=10s --start-period=25s --retries=5 \
  CMD ["bash", "-lc", "curl -fsS http://127.0.0.1:8001/api/health >/dev/null && curl -fsS http://127.0.0.1:3000/api/health >/dev/null"]

CMD ["./start-services.sh"]
