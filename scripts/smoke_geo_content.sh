#!/usr/bin/env bash
# Smoke GEO content APIs. Requires API key + tenant.
# Usage:
#   API_KEY=xxx TENANT_ID=1 BASE=http://127.0.0.1:8000 bash scripts/smoke_geo_content.sh

set -euo pipefail
BASE="${BASE:-http://127.0.0.1:8000}"
API_KEY="${API_KEY:?set API_KEY}"
TENANT_ID="${TENANT_ID:?set TENANT_ID}"
AUTH=("X-API-Key: ${API_KEY}")

echo "== health =="
curl -fsS -H "${AUTH[0]}" "$BASE/api/v1/geo/content-health"
echo

echo "== create prompt =="
PROMPT=$(curl -fsS -H "${AUTH[0]}" -H "Content-Type: application/json" \
  -d "{\"tenant_id\":${TENANT_ID},\"question\":\"烟雾测试：数据分析平台哪个好用\",\"priority\":99,\"tags\":[\"demo\"],\"source\":\"manual\"}" \
  "$BASE/api/v1/geo/prompts")
echo "$PROMPT"
PID=$(python -c "import json,sys; print(json.load(sys.stdin)['id'])" <<<"$PROMPT")

echo "== create 3 facts =="
FACT_IDS=()
for i in 1 2 3; do
  F=$(curl -fsS -H "${AUTH[0]}" -H "Content-Type: application/json" \
    -d "{\"tenant_id\":${TENANT_ID},\"title\":\"事实${i}\",\"statement\":\"烟雾测试事实陈述 ${i}\",\"source_name\":\"seed-${i}\",\"trust_level\":\"needs_review\"}" \
    "$BASE/api/v1/geo/facts")
  FID=$(python -c "import json,sys; print(json.load(sys.stdin)['id'])" <<<"$F")
  FACT_IDS+=("$FID")
done
echo "facts: ${FACT_IDS[*]}"

echo "== create task =="
TASK=$(curl -fsS -H "${AUTH[0]}" -H "Content-Type: application/json" \
  -d "{\"tenant_id\":${TENANT_ID},\"prompt_id\":${PID},\"fact_ids\":[${FACT_IDS[0]},${FACT_IDS[1]},${FACT_IDS[2]}],\"target_channels\":[\"website\",\"zhihu\"]}" \
  "$BASE/api/v1/geo/content-tasks")
TID=$(python -c "import json,sys; print(json.load(sys.stdin)['id'])" <<<"$TASK")
echo "task=$TID"

echo "== generate =="
curl -fsS -H "${AUTH[0]}" -X POST "$BASE/api/v1/geo/content-tasks/${TID}/generate?tenant_id=${TENANT_ID}" | python -m json.tool | head -n 40

echo "== variants =="
curl -fsS -H "${AUTH[0]}" -H "Content-Type: application/json" \
  -d '{"channels":["website","zhihu"]}' \
  -X POST "$BASE/api/v1/geo/content-tasks/${TID}/variants?tenant_id=${TENANT_ID}" >/dev/null

echo "== publish =="
curl -fsS -H "${AUTH[0]}" -H "Content-Type: application/json" \
  -d "{\"tenant_id\":${TENANT_ID},\"channel\":\"zhihu\",\"published_url\":\"https://example.com/geo-smoke/${TID}\",\"note\":\"smoke\"}" \
  -X POST "$BASE/api/v1/geo/content-tasks/${TID}/publications" | python -c "import json,sys; d=json.load(sys.stdin); print(d['status'], d.get('publications'))"

echo "OK"
