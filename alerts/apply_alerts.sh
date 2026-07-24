#!/usr/bin/env bash
# ==============================================================================
# Aegis-Observe: SigNoz Alert Rule Importer Script
# ==============================================================================
set -euo pipefail

SIGNOZ_API_URL="${SIGNOZ_API_URL:-http://localhost:8080}"
SIGNOZ_API_KEY="${SIGNOZ_API_KEY:-}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ALERT_FILES=("${SCRIPT_DIR}/llm_token_usage.json" "${SCRIPT_DIR}/fraud_api_504.json")

echo "=== Aegis-Observe: Applying SigNoz Alert Rules ==="
echo "Target API Endpoint: ${SIGNOZ_API_URL}/api/v1/rules"

HEADERS=(-H "Content-Type: application/json")
if [ -n "${SIGNOZ_API_KEY}" ]; then
  HEADERS+=(-H "SIGNOZ-API-KEY: ${SIGNOZ_API_KEY}")
fi

FAILED=0

for ALERT_FILE in "${ALERT_FILES[@]}"; do
  if [ ! -f "${ALERT_FILE}" ]; then
    echo "❌ Error: Alert file ${ALERT_FILE} not found."
    FAILED=1
    continue
  fi

  ALERT_NAME=$(python3 -c "import json; data=json.load(open('${ALERT_FILE}')); print(data.get('alert') or data.get('alertName') or 'SigNoz Alert')" 2>/dev/null || echo "SigNoz Alert")
  echo "Applying alert rule: '${ALERT_NAME}'..."

  RESPONSE=$(curl -s -w "\nHTTP_STATUS:%{http_code}" -X POST "${SIGNOZ_API_URL}/api/v1/rules" \
    "${HEADERS[@]}" \
    -d @"${ALERT_FILE}" || true)

  HTTP_STATUS=$(echo "${RESPONSE}" | grep "HTTP_STATUS" | cut -d':' -f2)
  BODY=$(echo "${RESPONSE}" | grep -v "HTTP_STATUS")

  if [ "${HTTP_STATUS}" = "200" ] || [ "${HTTP_STATUS}" = "201" ]; then
    echo "✅ Successfully applied '${ALERT_NAME}' via SigNoz API."
  else
    echo "❌ Error: Failed to apply '${ALERT_NAME}' via SigNoz API (HTTP ${HTTP_STATUS})."
    echo "API Error Output: ${BODY}"
    FAILED=1
  fi
done

if [ "${FAILED}" -ne 0 ]; then
  echo "❌ Alert rule application failed."
  exit 1
fi

echo "=== All alert rules applied successfully via SigNoz API ==="
