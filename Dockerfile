FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PATH="/app/.venv/bin:$PATH"

RUN apt-get update && apt-get install -y --no-install-recommends \
    poppler-utils \
    libgomp1 \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.12.7 /uv /uvx /bin/

COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-dev --no-install-project

COPY src ./src
COPY data/documents/*.pdf ./data/documents/
COPY data/database/app.db data/database/schema.sql data/database/seed_data.sql ./data/database/
COPY config.py ingest.py qc_audit.py ./
COPY docker-entrypoint.sh /app/docker-entrypoint.sh

RUN uv sync --frozen --no-dev \
    && useradd --create-home --uid 10001 assistant \
    && mkdir -p /app/.cache/adan /home/assistant/.cache \
    && chown -R assistant:assistant /app /home/assistant \
    && chmod -R a-w /app/data \
    && chmod +x /app/docker-entrypoint.sh

USER assistant
EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=180s \
  CMD curl -sf http://localhost:8000/health || exit 1

ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["uvicorn", "adan.api:app", "--host", "0.0.0.0", "--port", "8000", "--loop", "asyncio"]
