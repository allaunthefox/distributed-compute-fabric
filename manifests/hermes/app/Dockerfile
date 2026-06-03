# Dockerfile for Hermes Orchestrator
# Multi-stage build for smaller final image
#
# Build: docker build -t hermes-orchestrator:latest -f app/Dockerfile .
# Run: docker run -p 8000:8000 -e CODER_MODEL_URL=http://coder-model:80 hermes-orchestrator

# =============================================================================
# Stage 1: Build Python dependencies
# =============================================================================
FROM python:3.11-slim as builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY app/requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir --user -r requirements.txt

# =============================================================================
# Stage 2: Final runtime image
# =============================================================================
FROM python:3.11-slim

WORKDIR /app

# Copy Python packages from builder
COPY --from=builder /root/.local /root/.local
COPY --from=builder /app /app

# Make sure scripts in .local are usable
ENV PATH=/root/.local/bin:$PATH

# Copy application code
COPY app/orchestrator.py .
COPY app/requirements.txt .

# Create non-root user for security
RUN useradd --create-home --shell /bin/bash hermes && \
    chown -R hermes:hermes /app
USER hermes

# Environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HERMES_PORT=8000 \
    ORCHESTRATOR_ENABLED=true \
    CODER_MODEL_URL=http://coder-model.services.svc.cluster.local

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import httpx; httpx.get('http://localhost:8000/health', timeout=5).raise_for_status()" || exit 1

# Run the application
CMD ["python", "orchestrator.py"]
