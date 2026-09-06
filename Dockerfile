# ── Yiriba SaaS Dockerfile ────────────────────────────────────────
FROM python:3.11-slim AS base

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps
# README.md est copié car hatchling l'exige pour générer les métadonnées
# (pyproject.toml déclare readme = "README.md").
COPY pyproject.toml README.md ./
RUN pip install --no-cache-dir ".[prod]"

# Copy source
COPY . .

# Create uploads dir
RUN mkdir -p /app/uploads

# Non-root user — /app doit lui appartenir pour créer yiriba.db et écrire les uploads
RUN adduser --disabled-password --gecos '' appuser \
    && chown -R appuser:appuser /app
USER appuser

# Healthcheck
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:5050/health')"

EXPOSE 5050

CMD ["gunicorn", "app.main:app", \
     "--worker-class", "uvicorn.workers.UvicornWorker", \
     "--workers", "4", \
     "--bind", "0.0.0.0:5050", \
     "--timeout", "120"]
