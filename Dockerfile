# ═══════════════════════════════════════════════════════════════
# CodEdu — Production Dockerfile
# ═══════════════════════════════════════════════════════════════
# Security: runs as non-root user (appuser, UID 1001)
# Minimal image: python:3.11-slim with only required packages
# Includes /usr/bin/time for memory measurement in sandbox

FROM python:3.11-slim AS base

# ── System packages ───────────────────────────────────────────
# time: for /usr/bin/time memory measurement
# No extra shells or utilities to reduce attack surface
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        time \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# ── Create non-root user ─────────────────────────────────────
RUN groupadd -r appgroup && \
    useradd -r -g appgroup -d /app -s /usr/sbin/nologin -u 1001 appuser

# ── Application directory ─────────────────────────────────────
WORKDIR /app

# ── Install Python dependencies ──────────────────────────────
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# ── Copy application code ─────────────────────────────────────
COPY app/ ./app/
COPY public/ ./public/
COPY data/ ./data/

# ── Create temp directory for code evaluation ─────────────────
RUN mkdir -p /tmp/codedu && \
    chown appuser:appgroup /tmp/codedu && \
    chmod 700 /tmp/codedu

# ── Set file ownership ───────────────────────────────────────
RUN chown -R appuser:appgroup /app

# ── Switch to non-root user ──────────────────────────────────
USER appuser

# ── Expose port ──────────────────────────────────────────────
EXPOSE 8080

# ── Health check ─────────────────────────────────────────────
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python3 -c "import socket; s=socket.socket(); s.settimeout(3); s.connect(('127.0.0.1',8080)); s.send(b'GET /health HTTP/1.1\r\nHost: localhost\r\n\r\n'); d=s.recv(1024); s.close(); exit(0 if b'200' in d else 1)"

# ── Start server ─────────────────────────────────────────────
CMD ["python3", "-m", "app.main"]
