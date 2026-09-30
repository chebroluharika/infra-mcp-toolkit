# Dockerfile for Backend - Multi-stage Optimized Build
# QE Agentic Dashboard - Python/FastAPI Backend
# Optimized for smaller image size with multi-stage build
#
# Build context: Project root (not backend folder)
# Usage: docker build -f backend/Dockerfile -t qe-dashboard-backend .

# Stage 1: Build stage - Install dependencies with build tools
FROM python:3.11-slim AS builder

WORKDIR /build

# Install build dependencies (single layer, cleaned immediately)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first (better layer caching)
COPY backend/requirements.txt .

# Create virtual environment and install dependencies
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Install public packages from PyPI
# Note: pylclient (internal Vault/Rancher client) is excluded — Rancher features
# require your own kubeconfig setup instead.
RUN pip install --no-cache-dir --no-compile pip==24.0 && \
    grep -v "pylclient" requirements.txt > requirements-public.txt && \
    pip install --no-cache-dir --no-compile -r requirements-public.txt

# Trim unused heavy Google Cloud packages pulled in by google-adk
# (google-adk depends on google-cloud-aiplatform which pulls the entire GCP SDK;
#  we only need ADK core, LiteLLM, and FAISS - not BigQuery, Spanner, Speech, etc.)
# Keep: opentelemetry-api, opentelemetry-sdk (required by ADK telemetry)
RUN pip uninstall -y \
    google-cloud-aiplatform google-cloud-bigquery google-cloud-bigquery-storage \
    google-cloud-bigtable google-cloud-discoveryengine google-cloud-spanner \
    google-cloud-speech google-cloud-pubsub google-cloud-monitoring \
    google-cloud-logging google-cloud-appengine-logging google-cloud-trace \
    sqlalchemy-spanner \
    opentelemetry-exporter-gcp-trace opentelemetry-exporter-gcp-monitoring \
    opentelemetry-exporter-gcp-logging opentelemetry-resourcedetector-gcp \
    opentelemetry-exporter-otlp-proto-common opentelemetry-exporter-otlp-proto-http \
    pyarrow 2>/dev/null || true

# Stage 2: Production stage - Minimal runtime image
FROM python:3.11-slim AS production

WORKDIR /app

# Install only runtime dependencies and clean up in the same layer
# gosu: for privilege drop in entrypoint
# (ghostscript/libgl removed - pymupdf handles PDF without them)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gosu \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Copy virtual environment from builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Create non-root user with a home directory (needed for ~/.kube/rancher kubeconfigs)
RUN groupadd -r appuser && useradd -r -g appuser -u 1001 -m -d /home/appuser appuser && \
    mkdir -p /home/appuser/.kube/rancher && \
    chown -R appuser:appuser /home/appuser

# Copy backend application code
COPY backend/ .

# Copy ai_agents (core, agents, config - needed by backend routers/services)
# backend/routers/{index,ai_chat} import from ai_agents/core/{runner,base}
# backend/services/{repo_indexer,testrail_indexer} import from ai_agents/core/{embeddings,vector_store}
# backend/routers/index.py imports escalation_analysis_agent, which uses github_agent and testrail_agent
COPY ai_agents/core/ /ai_agents/core/
COPY ai_agents/config.py /ai_agents/config.py
COPY ai_agents/__init__.py /ai_agents/__init__.py
COPY ai_agents/tfa_agent/ /ai_agents/tfa_agent/
COPY ai_agents/escalation_analysis_agent/ /ai_agents/escalation_analysis_agent/
COPY ai_agents/github_agent/ /ai_agents/github_agent/
COPY ai_agents/testrail_agent/ /ai_agents/testrail_agent/
COPY ai_agents/root_agent/ /ai_agents/root_agent/
COPY ai_agents/data/tfa_knowledge_base.json /ai_agents/data/tfa_knowledge_base.json

# Create empty .env at container root (ai_agents/config.py resolves .env relative to project root;
# in Docker, env vars come from docker-compose, so we just need the file to exist)
RUN touch /.env

# Copy data files to defaults directory (will be copied to volume on first run)
RUN mkdir -p /app/data-defaults && \
    cp -r /app/data/* /app/data-defaults/ 2>/dev/null || true

# Copy and setup entrypoint script
COPY backend/docker-entrypoint.sh /app/docker-entrypoint.sh
RUN chmod +x /app/docker-entrypoint.sh

# Create data directory and set permissions (single layer)
RUN mkdir -p /app/data && \
    chown -R appuser:appuser /app && \
    chown -R appuser:appuser /ai_agents

# Remove unnecessary files to reduce image size (single layer)
RUN find /opt/venv -type d -name '__pycache__' -exec rm -rf {} + 2>/dev/null || true && \
    find /opt/venv -type f -name '*.pyc' -delete 2>/dev/null || true && \
    find /opt/venv -type f -name '*.pyo' -delete 2>/dev/null || true && \
    find /opt/venv -type d -name 'tests' -exec rm -rf {} + 2>/dev/null || true && \
    find /opt/venv -type d -name 'test' -exec rm -rf {} + 2>/dev/null || true && \
    find /opt/venv -type f -name '*.dist-info/RECORD' -delete 2>/dev/null || true && \
    find . -type d -name '__pycache__' -exec rm -rf {} + 2>/dev/null || true && \
    find . -type f -name '*.pyc' -delete 2>/dev/null || true && \
    find /ai_agents -type d -name '__pycache__' -exec rm -rf {} + 2>/dev/null || true

# Expose port
EXPOSE 8000

# Health check using Python (no curl dependency needed)
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health')" || exit 1

# Set entrypoint to handle data initialization
ENTRYPOINT ["/app/docker-entrypoint.sh"]

# Run the application
# --limit-concurrency 50: cap in-flight requests to prevent overload under concurrent users
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--limit-concurrency", "50"]
