FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
RUN apt-get update && apt-get install -y --no-install-recommends poppler-utils libgomp1 \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir uv==0.12.7
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
COPY data/documents/*.pdf ./data/documents/
COPY data/database/app.db data/database/schema.sql data/database/seed_data.sql ./data/database/
RUN uv sync --frozen --no-dev \
    && useradd --create-home --uid 10001 assistant \
    && mkdir -p /app/.cache/adan \
    && chown -R assistant:assistant /app/.cache \
    && chmod -R a-w /app/data
USER assistant
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=180s \
  CMD ["/app/.venv/bin/python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/health', timeout=4)"]
CMD ["/app/.venv/bin/uvicorn", "adan.api:app", "--host", "0.0.0.0", "--port", "8000", "--loop", "asyncio"]
