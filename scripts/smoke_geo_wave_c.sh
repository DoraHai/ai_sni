#!/usr/bin/env bash
# Wave C / B3 HTTP smoke: visibility insights, publishing channels, evidence stats.
# Usage:
#   API_KEY=geo-demo-local-key TENANT_ID=1 BASE=http://127.0.0.1:8011 bash scripts/smoke_geo_wave_c.sh

set -euo pipefail
BASE="${BASE:-http://127.0.0.1:8011}"
API_KEY="${API_KEY:?set API_KEY}"
TENANT_ID="${TENANT_ID:?set TENANT_ID}"
AUTH_H="X-API-Key: ${API_KEY}"
CT="Content-Type: application/json"

json_get() {
  python3 -c "import json,sys; d=json.load(sys.stdin); print($1)"
}

echo "== health =="
curl -fsS -H "$AUTH_H" "$BASE/health/geo"
echo
curl -fsS -H "$AUTH_H" "$BASE/api/v1/geo/content-health"
echo

echo "== list prompts (need brand_missing) =="
PROMPTS=$(curl -fsS -H "$AUTH_H" "$BASE/api/v1/geo/prompts?tenant_id=${TENANT_ID}&tag=brand_missing")
PID=$(python3 -c "import json,sys; items=json.load(sys.stdin).get('items') or []; assert items, 'no brand_missing prompts'; print(items[0]['id'])" <<<"$PROMPTS")
echo "prompt_id=$PID"

echo "== create answer snapshot with Wave C fields =="
SNAP=$(curl -fsS -H "$AUTH_H" -H "$CT" \
  -d "{\"tenant_id\":${TENANT_ID},\"prompt_id\":${PID},\"engine\":\"chatgpt\",\"raw_text\":\"推荐可看 Tableau、PowerBI，也有人提到 GrowthSniper 获客平台在 B2B 场景不错。\",\"mentions_brand\":true,\"competitors\":[\"Tableau\",\"PowerBI\"],\"brand_position\":\"mentioned\",\"sentiment\":\"positive\",\"note\":\"smoke-wave-c\"}" \
  "$BASE/api/v1/geo/answer-snapshots")
SID=$(python3 -c "import json,sys; d=json.load(sys.stdin); assert d['competitors']==['Tableau','PowerBI']; assert d['brand_position']=='mentioned'; assert d['sentiment']=='positive'; print(d['id'])" <<<"$SNAP")
echo "snapshot_id=$SID"

echo "== competitor insights =="
COMP=$(curl -fsS -H "$AUTH_H" "$BASE/api/v1/geo/competitor-insights?tenant_id=${TENANT_ID}")
python3 -c "import json,sys; items=json.load(sys.stdin)['items']; names={i['name'] for i in items}; assert 'Tableau' in names and 'PowerBI' in names, items; print('competitors ok', len(items))" <<<"$COMP"

echo "== evaluation insights =="
EVAL=$(curl -fsS -H "$AUTH_H" "$BASE/api/v1/geo/evaluation-insights?tenant_id=${TENANT_ID}")
python3 -c "import json,sys; d=json.load(sys.stdin); assert d['total']>=1; assert d['sentiment_counts']['positive']>=1; assert d['position_counts']['mentioned']>=1; print('evaluation ok', d['sentiment_counts'], d['position_counts'])" <<<"$EVAL"

echo "== content-stats visibility fields =="
STATS=$(curl -fsS -H "$AUTH_H" "$BASE/api/v1/geo/content-stats?tenant_id=${TENANT_ID}")
python3 -c "import json,sys; d=json.load(sys.stdin); assert d.get('visibility_mention_rate') is not None; assert d.get('visibility_engines_covered',0)>=1; assert d.get('snapshots_with_competitors',0)>=1; print('stats', {k:d.get(k) for k in ['snapshots','snapshots_mention_brand','visibility_mention_rate','visibility_engines_covered','snapshots_with_competitors','prompts_brand_missing','prompts_need_recheck']})" <<<"$STATS"

echo "== brand_missing cleared after mention =="
AFTER=$(curl -fsS -H "$AUTH_H" "$BASE/api/v1/geo/prompts?tenant_id=${TENANT_ID}")
python3 -c "import json,sys; items=json.load(sys.stdin)['items']; p=next(i for i in items if i['id']==${PID}); tags=p.get('tags') or []; assert 'brand_missing' not in tags, tags; print('tags after mention', tags)" <<<"$AFTER"

echo "== toggle mentions_brand false restores brand_missing =="
curl -fsS -H "$AUTH_H" -H "$CT" \
  -d '{"mentions_brand":false,"brand_position":"absent","sentiment":"neutral"}' \
  -X PATCH "$BASE/api/v1/geo/answer-snapshots/${SID}?tenant_id=${TENANT_ID}" >/dev/null
AFTER2=$(curl -fsS -H "$AUTH_H" "$BASE/api/v1/geo/prompts?tenant_id=${TENANT_ID}")
python3 -c "import json,sys; items=json.load(sys.stdin)['items']; p=next(i for i in items if i['id']==${PID}); tags=p.get('tags') or []; assert 'brand_missing' in tags, tags; print('tags after absent', tags)" <<<"$AFTER2"

echo "== restore mention for clean demo state =="
curl -fsS -H "$AUTH_H" -H "$CT" \
  -d '{"mentions_brand":true,"brand_position":"mentioned","sentiment":"positive"}' \
  -X PATCH "$BASE/api/v1/geo/answer-snapshots/${SID}?tenant_id=${TENANT_ID}" >/dev/null

echo "== AI settings get =="
curl -fsS -H "$AUTH_H" "$BASE/api/v1/geo/ai-settings?tenant_id=${TENANT_ID}" | python3 -c "import json,sys; d=json.load(sys.stdin); assert 'presets' in d and 'effective' in d; print('ai-settings ok', d.get('provider'), d['effective'])"

echo "== publishing channels bootstrap =="
CH=$(curl -fsS -H "$AUTH_H" "$BASE/api/v1/geo/publishing-channels?tenant_id=${TENANT_ID}")
python3 -c "import json,sys; items=json.load(sys.stdin)['items']; assert len(items)>=5, items; types={i.get('channel_type') or i.get('type') for i in items}; print('channels', len(items), sorted(types)[:8])" <<<"$CH"
CID=$(python3 -c "import json,sys; items=json.load(sys.stdin)['items']; print(items[0]['id'])" <<<"$CH")

echo "== create channel account (credentials encrypted, not echoed) =="
ACC=$(curl -fsS -H "$AUTH_H" -H "$CT" \
  -d "{\"tenant_id\":${TENANT_ID},\"channel_id\":${CID},\"display_name\":\"smoke-account\",\"auth_type\":\"api_key\",\"credentials\":{\"token\":\"secret-smoke-token\"}}" \
  "$BASE/api/v1/geo/channel-accounts")
python3 -c "import json,sys; d=json.load(sys.stdin); assert d.get('has_credentials') is True; assert 'token' not in json.dumps(d); print('account ok', d.get('id'), 'has_credentials', d.get('has_credentials'))" <<<"$ACC"

echo "== probe without AI key expects 503 =="
CODE=$(curl -sS -o /tmp/probe_body.json -w '%{http_code}' -H "$AUTH_H" -H "$CT" \
  -d "{\"tenant_id\":${TENANT_ID},\"prompt_id\":${PID}}" \
  "$BASE/api/v1/geo/answer-snapshots/probe")
python3 -c "import sys; code=int(sys.argv[1]); assert code==503, code; print('probe degraded ok', code)" "$CODE"
cat /tmp/probe_body.json; echo

echo "== tracking engines =="
curl -fsS -H "$AUTH_H" "$BASE/api/v1/geo/tracking-engines?tenant_id=${TENANT_ID}" | python3 -c "import json,sys; items=json.load(sys.stdin)['items']; assert items; print('engines', len(items))"

echo "OK wave-c smoke"
