# Solstice agent service (Google ADK + FastAPI). Build context = repo root:
#   docker build -f agent-service/Dockerfile -t solstice/agent-service .
# The same image runs the API (default) or the one-shot migration job (`solstice-migrate`).

# --- build: resolve the locked dependency set with uv ----------------------------
FROM python:3.13-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.11.32 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/agent-service/.venv
WORKDIR /app/agent-service
COPY agent-service/pyproject.toml agent-service/uv.lock agent-service/.python-version ./
RUN uv sync --frozen --no-dev --no-install-project
COPY agent-service/src ./src
RUN uv sync --frozen --no-dev --no-editable

# --- runtime ------------------------------------------------------------------------
FROM python:3.13-slim
RUN groupadd --system --gid 10001 solstice \
 && useradd --system --uid 10001 --gid solstice --home /app --shell /usr/sbin/nologin solstice
WORKDIR /app
COPY --from=build --chown=solstice:solstice /app/agent-service/.venv /app/agent-service/.venv
# Agent configuration, schema migrations and the sample data export ship inside the image.
COPY --chown=solstice:solstice agents /app/agents
COPY --chown=solstice:solstice db/migrations /app/db/migrations
COPY --chown=solstice:solstice solstice-data /app/solstice-data
ENV PATH=/app/agent-service/.venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    SOLSTICE_PROMPTS_DIR=/app/agents \
    SOLSTICE_MIGRATIONS_DIR=/app/db/migrations \
    SOLSTICE_DATA_DIR=/app/solstice-data
USER solstice
EXPOSE 8080
HEALTHCHECK --interval=15s --timeout=5s --start-period=60s --retries=5 \
  CMD ["python", "-c", "import sys,urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=4).status == 200 else 1)"]
CMD ["solstice-api"]
