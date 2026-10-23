#!/usr/bin/env bash
set -eo pipefail

echo "======================================================================"
echo " [STARTUP] CloudScale Assistant Initializing"
echo "======================================================================"

# Check for host proxy bridge (for environments requiring proxy for external APIs)
if python -c "import socket; s = socket.socket(); s.settimeout(1); s.connect(('host.docker.internal', 10809)); s.close()" 2>/dev/null; then
    echo "[STARTUP] Detected host proxy bridge on host.docker.internal:10809, enabling proxy..."
    export HTTP_PROXY="http://host.docker.internal:10809"
    export HTTPS_PROXY="http://host.docker.internal:10809"
    export http_proxy="http://host.docker.internal:10809"
    export https_proxy="http://host.docker.internal:10809"
    export NO_PROXY="localhost,127.0.0.1,qdrant"
    export no_proxy="localhost,127.0.0.1,qdrant"
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

python ingest.py

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
