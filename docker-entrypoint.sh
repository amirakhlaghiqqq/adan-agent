#!/usr/bin/env bash
set -eo pipefail

echo "======================================================================"
echo " [STARTUP] CloudScale Assistant Initializing"
echo "======================================================================"

# Optional outbound proxy; ordinary installations connect directly.
if [ -n "${ADAN_PROXY_URL:-}" ]; then
    echo "[STARTUP] Using the configured outbound proxy."
    export HTTP_PROXY="$ADAN_PROXY_URL"
    export HTTPS_PROXY="$ADAN_PROXY_URL"
    export http_proxy="$ADAN_PROXY_URL"
    export https_proxy="$ADAN_PROXY_URL"
    export NO_PROXY="${NO_PROXY:+$NO_PROXY,}localhost,127.0.0.1,qdrant"
    export no_proxy="$NO_PROXY"
fi

# Target Qdrant endpoint
QDRANT_TARGET_URL="${QDRANT_URL:-http://qdrant:6333}"
echo "[STARTUP] Configured Qdrant endpoint: ${QDRANT_TARGET_URL}"

# a) Wait for Qdrant service to be reachable and ready
echo "[STARTUP] Polling Qdrant health check at ${QDRANT_TARGET_URL}/readyz..."
MAX_RETRIES=60
RETRY_INTERVAL=2
ATTEMPT=0

while true; do
    if curl -sf "${QDRANT_TARGET_URL}/readyz" >/dev/null 2>&1; then
        echo "[STARTUP] Qdrant service is online and healthy!"
        break
    fi
    ATTEMPT=$((ATTEMPT + 1))
    if [ "$ATTEMPT" -ge "$MAX_RETRIES" ]; then
        echo "[STARTUP] ERROR: Qdrant service did not become ready within $((MAX_RETRIES * RETRY_INTERVAL))s."
        exit 1
    fi
    echo "[STARTUP] Waiting for Qdrant... attempt ${ATTEMPT}/${MAX_RETRIES} (${RETRY_INTERVAL}s)"
    sleep "$RETRY_INTERVAL"
done

# b) Run ingestion & Quality Control audit
echo "======================================================================"
echo "[INGESTION] Starting automated PDF ingestion & Quality Control audit..."
echo "======================================================================"

python scripts/ingest.py --ensure

echo "======================================================================"
echo "[INGESTION] Completed successfully: All documents indexed and verified."
echo "======================================================================"

# c) Once ingestion is verified, start the server
if [ $# -gt 0 ]; then
    echo "[STARTUP] Executing server command: $@"
    exec "$@"
else
    echo "[STARTUP] Starting FastAPI server on 0.0.0.0:8000..."
    exec uvicorn adan.api:app --host 0.0.0.0 --port 8000 --loop asyncio
fi
