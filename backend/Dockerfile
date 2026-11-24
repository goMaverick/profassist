
# Build stage
FROM python:3.12-slim AS builder

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
WORKDIR /app

# Install uv (pinned so the build is reproducible)
COPY --from=ghcr.io/astral-sh/uv:0.13.9 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy

# Install dependencies
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-install-project --no-dev

# Copy application
COPY . /app

# Install project
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# spaCy model Mem0 needs on its first write. Baked in at build time: mem0 calls
# spacy.cli.download when the model is missing, and that raises SystemExit, which
# used to take the ASGI worker down. The wheel matches spaCy 3.8.x from uv.lock.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --python /app/.venv/bin/python \
    https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.8.0/en_core_web_sm-3.8.0-py3-none-any.whl


# Runtime stage
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
WORKDIR /app

# Create the non-root user and the writable directories before copying, so the
# application tree can be copied with the right owner in one layer.
RUN adduser --disabled-password --gecos "" appuser && \
    mkdir -p /app/media /app/data /app/chroma_data /app/models_cache && \
    chown appuser:appuser /app/media /app/data /app/chroma_data /app/models_cache

# Copy the whole built tree (including .venv) with its final owner.
COPY --from=builder --chown=appuser:appuser /app /app

# Add venv to path
ENV PATH="/app/.venv/bin:$PATH"

USER appuser

EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import httpx; httpx.get('http://localhost:8000/api/v1/health')" || exit 1

CMD ["python", "-m", "cli.commands", "server", "run", "--host", "0.0.0.0", "--port", "8000"]
