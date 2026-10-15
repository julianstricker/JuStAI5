# syntax=docker/dockerfile:1.7
# Isolated runner for untrusted plugins and generated tools.
FROM python:3.12.12-slim-bookworm AS builder
ENV UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1 UV_PYTHON_DOWNLOADS=never UV_PROJECT_ENVIRONMENT=/app/.venv
RUN pip install --no-cache-dir uv==0.13.1
WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY sdk/python/pyproject.toml sdk/python/pyproject.toml
COPY backend/pyproject.toml backend/pyproject.toml
COPY sandbox/pyproject.toml sandbox/pyproject.toml
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --package justai-sandbox --no-install-workspace
COPY sdk/python sdk/python
COPY sandbox sandbox
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --package justai-sandbox --no-editable

FROM python:3.12.12-slim-bookworm
RUN useradd --system --uid 10002 --no-create-home sandbox
COPY --from=builder /app/.venv /app/.venv
ENV PATH=/app/.venv/bin:$PATH PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    SANDBOX_WORK_DIR=/tmp SANDBOX_CORE_URL=http://core:8080
USER sandbox
EXPOSE 8090
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request;urllib.request.urlopen('http://localhost:8090/health')"
CMD ["python", "-m", "justai_sandbox.server"]
