#!/usr/bin/env bash
# ==============================================================================
# Aegis-Observe: SigNoz Alert Rule Exporter Script
# ==============================================================================
set -euo pipefail

SIGNOZ_API_URL="${SIGNOZ_API_URL:-http://localhost:8080}"
SIGNOZ_API_KEY="${SIGNOZ_API_KEY:-}"

HEADERS=()
if [ -n "${SIGNOZ_API_KEY}" ]; then
  HEADERS+=(-H "SIGNOZ-API-KEY: ${SIGNOZ_API_KEY}")
fi

echo "=== Exporting Configured SigNoz Alert Rules ==="
curl -s -X GET "${SIGNOZ_API_URL}/api/v1/rules" "${HEADERS[@]}" | python3 -m json.tool || curl -s -X GET "${SIGNOZ_API_URL}/api/v1/rules" "${HEADERS[@]}"
