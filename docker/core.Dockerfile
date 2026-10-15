# syntax=docker/dockerfile:1.7
# JuStAI5 core: API, admin UI, audio/vision/AI engines and builtin plugins.

# ---------------------------------------------------------------- frontend build
FROM node:22.23.3-bookworm-slim AS frontend
WORKDIR /src/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# --------------------------------------------------------------- python deps
FROM python:3.12.12-slim-bookworm AS python-base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never UV_PROJECT_ENVIRONMENT=/app/.venv
RUN pip install --no-cache-dir uv==0.13.1
WORKDIR /app

FROM python-base AS builder
COPY pyproject.toml uv.lock ./
COPY sdk/python/pyproject.toml sdk/python/pyproject.toml
COPY backend/pyproject.toml backend/pyproject.toml
COPY sandbox/pyproject.toml sandbox/pyproject.toml
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --package justai-core --no-install-workspace
COPY sdk/python sdk/python
COPY backend backend
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --package justai-core --no-editable

# -------------------------------------------------------------------- models
FROM builder AS models
COPY scripts/fetch_models.py /tmp/fetch_models.py
RUN /app/.venv/bin/python /tmp/fetch_models.py /models

# ------------------------------------------------------------------- runtime
FROM python:3.12.12-slim-bookworm AS runtime
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg tini curl ca-certificates libgomp1 \
 && rm -rf /var/lib/apt/lists/* \
 && useradd --system --uid 10001 --create-home --home-dir /home/justai justai \
 && mkdir -p /data && chown justai:justai /data
ENV PATH=/app/.venv/bin:$PATH PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    JUSTAI_MODELS_DIR=/models JUSTAI_DATA_DIR=/data JUSTAI_BUILTIN_PLUGINS_DIR=/app/plugins \
    JUSTAI_STATIC_DIR=/app/static HF_HUB_OFFLINE=1 HF_HOME=/models/hf
COPY --from=builder /app/.venv /app/.venv
COPY --from=models --chown=10001:10001 /models /models
COPY plugins /app/plugins
COPY --from=frontend /src/frontend/dist /app/static
WORKDIR /app
USER justai
EXPOSE 8080
VOLUME ["/data"]
HEALTHCHECK --interval=30s --timeout=5s --start-period=90s --retries=3 \
  CMD curl -fs http://localhost:8080/api/health || exit 1
ENTRYPOINT ["tini", "--"]
CMD ["python", "-m", "justai.main"]
