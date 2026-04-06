# ──────────────────────────────────────────────────────────────
# WeatherRouter — Docker image
# Multi-stage build for a slim production image.
# ──────────────────────────────────────────────────────────────

# ── Stage 1: Install Python dependencies ──────────────────────
FROM python:3.12-slim AS builder

WORKDIR /build

COPY backend/requirements.txt .

RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ── Stage 2: Production image ─────────────────────────────────
FROM python:3.12-slim

LABEL maintainer="WeatherRouter"
LABEL description="Weather-aware route planning for the Nordic countries"

# Copy installed packages from builder stage
COPY --from=builder /install /usr/local

# Create a non-root user
RUN groupadd --gid 1000 appuser \
    && useradd --uid 1000 --gid 1000 --create-home appuser

WORKDIR /app

# Copy application code
COPY backend/ ./backend/
COPY frontend/ ./frontend/
COPY run.py .

# Own everything by the non-root user
RUN chown -R appuser:appuser /app

USER appuser

# Default configuration (can be overridden at runtime with -e or --env-file)
ENV HOST=0.0.0.0
ENV PORT=8000
ENV ROUTING_PROVIDER=osrm
ENV WEATHER_PROVIDER=open_meteo

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/providers')" || exit 1

# In production we disable reload and run with a single explicit command
CMD ["python", "-m", "uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
