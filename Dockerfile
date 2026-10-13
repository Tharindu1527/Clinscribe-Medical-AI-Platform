# One Python code base for every ClinScribe service; services differ only by command (ADR-0003).
# Two images: `app` (default, every service) and `rag` (adds the CPU torch + encoder dependency
# group for guidelines-mcp, the only service that runs the retrieval models; Phase 3 task 3).
FROM python:3.11.17-slim AS deps

# uv pinned to the version that wrote uv.lock
COPY --from=ghcr.io/astral-sh/uv:0.6.4 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH"

WORKDIR /app

# Dependencies first, so code changes do not reinstall them
COPY pyproject.toml uv.lock .python-version ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-default-groups --no-install-project

# ---------------------------------------------------------------- rag image (guidelines-mcp)
FROM deps AS rag
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-default-groups --group rag --no-install-project
COPY . .
RUN useradd --system --uid 10001 --no-create-home app
USER app
EXPOSE 8010
CMD ["python", "-m", "mcp_servers.guidelines_mcp", "--http", "0.0.0.0:8010"]

# ---------------------------------------------------------------- app image (default target)
FROM deps AS app
COPY . .
RUN useradd --system --uid 10001 --no-create-home app
USER app
EXPOSE 8000 8001
CMD ["uvicorn", "apps.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
