#!/usr/bin/env bash
# Stage 2 integration flows via curl against running backend.
# Usage: bash tests/run_curl_flows.sh

set -euo pipefail
API="http://localhost:8000/api/graph_plan/stream"
PASS=0
FAIL=0
TOTAL=6
COOKIE_JAR=$(mktemp)

# Get session + CSRF cookies (must use /api/document — /health skips session middleware)
curl -s -c "$COOKIE_JAR" http://localhost:8000/api/document > /dev/null
CSRF=$(grep csrf "$COOKIE_JAR" | awk '{print $NF}')
echo "Session established (csrf=${CSRF:0:8}...)"

post() {
  # SSE endpoint — capture full stream, extract the complete event's JSON payload
  local tmpfile
  tmpfile=$(mktemp)
  curl -s -X POST "$API" \
    -H "Content-Type: application/json" \
    -H "X-CSRF-Token: $CSRF" \
    -b "$COOKIE_JAR" \
    -c "$COOKIE_JAR" \
    -d "$1" \
    -o "$tmpfile"
  # Extract the complete event data (SSE format: "data: {json}")
  python3 -c "
import json, sys
with open('$tmpfile') as f:
    for line in f:
        if not line.startswith('data: '): continue
        raw = line[6:].strip()
        try:
            obj = json.loads(raw)
        except: continue
        if obj.get('type') == 'complete':
            print(json.dumps(obj.get('data', {})))
            break
" 2>/dev/null || echo '{}'
  rm -f "$tmpfile"
}

check() {
  local label="$1" expr="$2" val="$3"
  if echo "$val" | python3 -c "import sys,json; d=json.load(sys.stdin); $expr" 2>/dev/null; then
    echo "  ✓ $label"
  else
    echo "  ✗ $label"
    FAIL=$((FAIL+1))
    return 1
  fi
  return 0
}

# =============================================================================
echo ""
echo "═══ Flow 1: Diving in Bali (Tier 1 specialist) ═══"
R1=$(post '{"message":"I want to go diving in Bali for a week starting March 15"}')

echo "$R1" | python3 -c "
import sys,json
d=json.load(sys.stdin)
ss=d.get('session_state',{})
meta=ss.get('metadata',{})
ts=meta.get('trip_settings',{})
doc=d.get('document',{})
pvs=doc.get('plan_view_state','?')
secs=doc.get('strategy_sections',[])
print(f'  plan_view_state={pvs}')
print(f'  strategy_sections={len(secs)}')
print(f'  trip_settings.booking_types={ts.get(\"booking_types\",{})}')
for s in secs:
    ca=s.get('content_added',[])
    cb=s.get('content_blocks',[])
    match='✓' if ca==cb else '✗ MISMATCH'
    print(f'  section[{s.get(\"id\")}] content_added={len(ca)} content_blocks={len(cb)} {match}')
idc=doc.get('itinerary_day_cards')
print(f'  itinerary_day_cards={len(idc) if idc else None}')
"
F1_OK=true
check "trip_settings present" "
ss=d.get('session_state',{});meta=ss.get('metadata',{});ts=meta.get('trip_settings')
assert ts is not None, 'missing'
assert 'booking_types' in ts
assert 'flight_settings' in ts
assert 'hotel_settings' in ts
assert 'activity_settings' in ts
" "$R1" || F1_OK=false

check "legacy trip_inputs present" "
ss=d.get('session_state',{});meta=ss.get('metadata',{})
assert meta.get('trip_inputs') is not None
" "$R1" || F1_OK=false

check "strategy_sections > 0" "
doc=d.get('document',{})
assert len(doc.get('strategy_sections',[])) > 0
" "$R1" || F1_OK=false

check "content_blocks dual-written" "
doc=d.get('document',{})
for s in doc.get('strategy_sections',[]):
    ca=s.get('content_added',[])
    cb=s.get('content_blocks',[])
    if ca: assert ca==cb, f'{s.get(\"id\")}: mismatch'
" "$R1" || F1_OK=false

check "plan_view_state beyond S0" "
doc=d.get('document',{})
assert doc.get('plan_view_state','') != 'S0_BOOTSTRAP'
" "$R1" || F1_OK=false

$F1_OK && PASS=$((PASS+1)) && echo "  ══ Flow 1 PASS ══" || echo "  ══ Flow 1 FAIL ══"

# =============================================================================
echo ""
echo "═══ Flow 2: Yoga + Cooking in Bali (Tier 2) ═══"
R2=$(post '{"message":"yoga and cooking in Bali for 5 days starting April 1"}')

echo "$R2" | python3 -c "
import sys,json
d=json.load(sys.stdin)
doc=d.get('document',{})
secs=doc.get('strategy_sections',[])
pvs=doc.get('plan_view_state','?')
print(f'  plan_view_state={pvs}, sections={len(secs)}')
for s in secs:
    print(f'  section[{s.get(\"id\")}] type={s.get(\"specialist_type\")}')
"
F2_OK=true
check "trip_settings present" "
ss=d.get('session_state',{});meta=ss.get('metadata',{});ts=meta.get('trip_settings')
assert ts is not None
assert 'booking_types' in ts
" "$R2" || F2_OK=false

check "legacy trip_inputs present" "
ss=d.get('session_state',{});meta=ss.get('metadata',{})
assert meta.get('trip_inputs') is not None
" "$R2" || F2_OK=false

check "content_blocks dual-written" "
doc=d.get('document',{})
for s in doc.get('strategy_sections',[]):
    ca=s.get('content_added',[])
    cb=s.get('content_blocks',[])
    if ca: assert ca==cb
" "$R2" || F2_OK=false

$F2_OK && PASS=$((PASS+1)) && echo "  ══ Flow 2 PASS ══" || echo "  ══ Flow 2 FAIL ══"

# =============================================================================
echo ""
echo "═══ Flow 3: Mixed diving + yoga ═══"
R3=$(post '{"message":"diving and yoga in Bali for a week starting March 20"}')

echo "$R3" | python3 -c "
import sys,json
d=json.load(sys.stdin)
doc=d.get('document',{})
secs=doc.get('strategy_sections',[])
pvs=doc.get('plan_view_state','?')
print(f'  plan_view_state={pvs}, sections={len(secs)}')
for s in secs:
    print(f'  section[{s.get(\"id\")}] type={s.get(\"specialist_type\")}')
"
F3_OK=true
check "trip_settings present" "
ss=d.get('session_state',{});meta=ss.get('metadata',{});ts=meta.get('trip_settings')
assert ts is not None
assert 'booking_types' in ts
" "$R3" || F3_OK=false

check "content_blocks dual-written" "
doc=d.get('document',{})
for s in doc.get('strategy_sections',[]):
    ca=s.get('content_added',[])
    cb=s.get('content_blocks',[])
    if ca: assert ca==cb
" "$R3" || F3_OK=false

check "strategy_sections > 0" "
doc=d.get('document',{})
assert len(doc.get('strategy_sections',[])) > 0
" "$R3" || F3_OK=false

$F3_OK && PASS=$((PASS+1)) && echo "  ══ Flow 3 PASS ══" || echo "  ══ Flow 3 FAIL ══"

# =============================================================================
echo ""
echo "═══ Flow 4: Origin detection (2-turn) ═══"
R4A=$(post '{"message":"I want to go to Bali for a week starting March 15"}')

check "turn 1: trip_settings present" "
ss=d.get('session_state',{});meta=ss.get('metadata',{})
assert meta.get('trip_settings') is not None
" "$R4A" || true

SS4=$(echo "$R4A" | python3 -c "import sys,json; print(json.dumps(json.load(sys.stdin).get('session_state',{})))")

R4B=$(post "{\"message\":\"I'm flying from San Francisco\",\"session_state\":$SS4}")

echo "$R4B" | python3 -c "
import sys,json
d=json.load(sys.stdin)
ss=d.get('session_state',{})
meta=ss.get('metadata',{})
ts=meta.get('trip_settings',{})
ti=ss.get('trip_inputs',{})
print(f'  origin (trip_inputs)={ti.get(\"origin\",\"?\")}')
print(f'  flights={ts.get(\"booking_types\",{}).get(\"flights\",\"?\")}')
"

F4_OK=true
check "flights enabled after origin" "
ss=d.get('session_state',{});meta=ss.get('metadata',{});ts=meta.get('trip_settings',{})
flights=ts.get('booking_types',{}).get('flights','off')
assert flights != 'off', f'flights={flights}'
" "$R4B" || F4_OK=false

check "origin in trip_inputs" "
ss=d.get('session_state',{});ti=ss.get('trip_inputs',{})
o=ti.get('origin','').lower()
assert 'san francisco' in o or 'sfo' in o, f'origin={o}'
" "$R4B" || F4_OK=false

check "origin in metadata.trip_inputs" "
ss=d.get('session_state',{});meta=ss.get('metadata',{})
ti=meta.get('trip_inputs',{})
assert ti.get('origin',''), 'missing'
" "$R4B" || F4_OK=false

$F4_OK && PASS=$((PASS+1)) && echo "  ══ Flow 4 PASS ══" || echo "  ══ Flow 4 FAIL ══"

# =============================================================================
echo ""
echo "═══ Flow 5: Settings change mid-flow ═══"
R5A=$(post '{"message":"I want to go to Bali for a week starting March 15"}')
SS5=$(echo "$R5A" | python3 -c "import sys,json; print(json.dumps(json.load(sys.stdin).get('session_state',{})))")

R5B=$(post "{\"message\":\"5-star hotels only\",\"session_state\":$SS5}")

echo "$R5B" | python3 -c "
import sys,json
d=json.load(sys.stdin)
ss=d.get('session_state',{})
meta=ss.get('metadata',{})
ts=meta.get('trip_settings',{})
print(f'  min_stars={ts.get(\"hotel_settings\",{}).get(\"min_stars\",\"?\")}')
print(f'  booking_types={ts.get(\"booking_types\",{})}')
"

F5_OK=true
check "min_stars >= 4 after settings change" "
ss=d.get('session_state',{});meta=ss.get('metadata',{});ts=meta.get('trip_settings',{})
ms=ts.get('hotel_settings',{}).get('min_stars',0)
assert ms >= 4, f'min_stars={ms}'
" "$R5B" || F5_OK=false

$F5_OK && PASS=$((PASS+1)) && echo "  ══ Flow 5 PASS ══" || echo "  ══ Flow 5 FAIL ══"

# =============================================================================
echo ""
echo "═══ Flow 6: Bare destination — no errors ═══"
R6=$(post '{"message":"Bali"}')

echo "$R6" | python3 -c "
import sys,json
d=json.load(sys.stdin)
print(f'  error={d.get(\"error\")}')
print(f'  plan_view_state={d.get(\"document\",{}).get(\"plan_view_state\",\"?\")}')
"
F6_OK=true
check "no error field" "
assert d.get('error') is None, f'error={d.get(\"error\")}'
" "$R6" || F6_OK=false

check "valid JSON with document" "
assert 'document' in d, 'missing document key'
" "$R6" || F6_OK=false

$F6_OK && PASS=$((PASS+1)) && echo "  ══ Flow 6 PASS ══" || echo "  ══ Flow 6 FAIL ══"

# =============================================================================
echo ""
echo "═══════════════════════════════════════════"
echo "  Results: $PASS/$TOTAL passed, $FAIL checks failed"
echo "═══════════════════════════════════════════"

rm -f "$COOKIE_JAR"
[ "$PASS" -eq "$TOTAL" ] && exit 0 || exit 1
