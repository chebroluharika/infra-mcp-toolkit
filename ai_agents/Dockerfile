# Dockerfile for AI Agents Streamlit App - Multi-stage Optimized Build
# QE Agentic Dashboard - AI Assistant Interface
# Optimized for smaller image size with multi-stage build
#
# Build context: Project root (to include mcp_servers and backend services)
# Usage: docker build -f ai_agents/Dockerfile -t qe-dashboard-streamlit .

# Stage 1: Build stage - Install dependencies with build tools
FROM python:3.11-slim AS builder

WORKDIR /build

# Install build dependencies for faiss and other packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first (better layer caching)
COPY ai_agents/requirements.txt .

# Create virtual environment and install dependencies
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
RUN pip install --no-cache-dir --no-compile pip==24.0 && \
    pip install --no-cache-dir --no-compile -r requirements.txt && \
    # Trim unused heavy Google Cloud packages pulled in by google-adk \
    pip uninstall -y \
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

# Copy virtual environment from builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Create non-root user for security
RUN groupadd -r appuser && useradd -r -g appuser -u 1001 appuser

# Copy AI agents application code
COPY ai_agents/ .

# Copy MCP servers (needed for agent tools)
COPY mcp_servers/ /app/mcp_servers/
ENV MCP_SERVERS_DIR=/app/mcp_servers

# Copy Streamlit config
COPY ai_agents/.streamlit /app/.streamlit

# Copy backend services needed by github_agent and testrail_agent
# (they import from backend/services/ and backend/utilities/ for FAISS tools)
COPY backend/services/ /backend/services/
COPY backend/utilities/ /backend/utilities/
COPY backend/config.py /backend/config.py

# Create empty .env at container root (ai_agents/config.py resolves .env relative to project root;
# in Docker, env vars come from docker-compose, so we just need the file to exist)
RUN touch /.env

# Create data directory for vector stores and set permissions
RUN mkdir -p /app/data /app/.streamlit /backend/data && \
    chown -R appuser:appuser /app && \
    chown -R appuser:appuser /backend

# Remove unnecessary files to reduce image size (single layer)
RUN find /opt/venv -type d -name '__pycache__' -exec rm -rf {} + 2>/dev/null || true && \
    find /opt/venv -type f -name '*.pyc' -delete 2>/dev/null || true && \
    find /opt/venv -type f -name '*.pyo' -delete 2>/dev/null || true && \
    find /opt/venv -type d -name 'tests' -exec rm -rf {} + 2>/dev/null || true && \
    find /opt/venv -type d -name 'test' -exec rm -rf {} + 2>/dev/null || true && \
    find /opt/venv -type f -name '*.dist-info/RECORD' -delete 2>/dev/null || true && \
    find . -type d -name '__pycache__' -exec rm -rf {} + 2>/dev/null || true && \
    find . -type f -name '*.pyc' -delete 2>/dev/null || true && \
    rm -rf /app/docs /app/*.md 2>/dev/null || true

# Switch to non-root user
USER appuser

# Expose Streamlit port
EXPOSE 8501

# Performance: Enable fast startup mode for Docker
ENV STREAMLIT_FAST_STARTUP=true

# Health check (increased start-period for cold starts)
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8501/_stcore/health')" || exit 1

# Run Streamlit with performance flags
CMD ["streamlit", "run", "streamlit_app.py", \
     "--server.port=8501", \
     "--server.address=0.0.0.0", \
     "--server.headless=true", \
     "--server.fileWatcherType=none", \
     "--server.runOnSave=false"]
