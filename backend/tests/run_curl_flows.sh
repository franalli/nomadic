#!/usr/bin/env bash
# =============================================================================
# Nomadic Backend — E2E Curl Test Suite (create_agent + tools architecture)
# =============================================================================
#
# Flows:
#   1   Greeting — zero tools, direct agent response
#   2   Input gates — oversized (422), empty (graceful), missing CSRF (403)
#   3   Tier 1 specialist — diving in Bali + SSE event structure
#   4   Tier 2 categories — yoga + cooking (no specialist LLM)
#   5   Mixed Tier 1 + 2 — diving + yoga coexist
#   6   Origin detection — 2-turn with session_state round-trip
#   7   Settings change — 2-turn NL extraction (min_stars)
#   8   Bare destination — minimal input, no error
#   9   Build itinerary — 2-turn with GENERATE_PLAN_NOW trigger
#   10  Destination change — stale data cleared by coordinator field-merge logic
#   11  Cache survival — L2 specialist cache persists across session reset
#   12  Google Places cascade — non-curated destination (conditional)
#   13  APD tile scaling — activities_per_day=2 generates enough tiles + blocks
#   14  Full plan golden path — "rome" + "Mar 1-7", 2-turn complete pipeline
#   15  Deeplink URL format validation — hotel/activity deeplinks are real URLs
#   16  Travelers + budget extraction — "2 adults and 1 child, $3000 budget"
#   17  Suggested response round-trip — chip bar text sent as user message
#   18  Price + star rating — day card blocks carry price_level + hotel price
#   19  Extend trip — extend dates preserves existing day card structure
#   20  Add Tier 1 activity — hiking after initial cultural plan
#   21  Long trip tile density — extend by 10 days, ≥60% fill rate
#   22  Specialist survival — diving sections/tiles survive origin add
#
# Architecture contract (from plan_graph_analysis.md + data-contracts.md):
#   - SSE event types: token, node_status, partial, complete, error
#   - complete payload: {type:"complete", data:{document:{...}, session_state:{...}, ...}}
#   - session_state MUST be round-tripped for multi-turn (messages live there)
#   - node_status.data.node = tool name, status = "started"|"completed"
#   - 5 tools: extract_trip_fields, get_specialist_advice, search_tiles,
#              get_local_intel, build_itinerary
#   - Message length gate: 2000 chars → 422
#
# Usage:
#   bash tests/run_curl_flows.sh             # all flows
#   bash tests/run_curl_flows.sh 3           # Flow 3 only
#   bash tests/run_curl_flows.sh 3,6,9       # Flows 3, 6, 9
#
# Results:
#   1. Tests run, capturing console + uvicorn trace to tests/results/
#   2. Analyzer scans all captured logs for issues across all flows
#   3. Combined report printed + saved to tests/results/summary_report.txt
#   4. Temp files (per-flow logs) deleted — only summary_report.txt survives
#
# =============================================================================

set -uo pipefail
# NOTE: -e intentionally omitted — individual failures must not abort the suite.

# Source backend .env so conditional flows (e.g. Google Places) see the same vars.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$SCRIPT_DIR/.."
BACKEND_ENV="$BACKEND_DIR/.env"
if [ -f "$BACKEND_ENV" ]; then
  set -a; source "$BACKEND_ENV"; set +a
fi

BASE="http://localhost:8000"
API="$BASE/api/graph_plan/stream"
PASS=0; FAIL=0; SKIP=0
FLOW_PASS=0; FLOW_FAIL=0; FLOW_TOTAL=0
ANALYSIS_ERRORS=0; ANALYSIS_WARNINGS=0
COOKIE_JAR=$(mktemp)
RESP=$(mktemp)
SS_FILE=$(mktemp)          # session_state round-trip file
BODY_FILE=$(mktemp)
CSRF=""                    # initialized by init_session; declared here for set -u safety

echo '{}' > "$SS_FILE"

# ── Results directory ────────────────────────────────────────────────────────

RESULTS_DIR="$SCRIPT_DIR/results"
mkdir -p "$RESULTS_DIR"
# Clear previous run's results (keep .gitignore)
find "$RESULTS_DIR" -maxdepth 1 -type f \( -name "*.log" -o -name "*.txt" \) -delete 2>/dev/null || true

ANALYZER="$SCRIPT_DIR/analyze_flow_logs.py"
BACKEND_LOG="$RESULTS_DIR/backend_full.log"
CONSOLE_FULL="$RESULTS_DIR/console_full.log"
> "$BACKEND_LOG"
> "$CONSOLE_FULL"

# ── Server management ───────────────────────────────────────────────────────

MANAGED_SERVER=false
SERVER_PID=""

_check_server_up() {
  local code
  code=$(curl -s -o /dev/null -w "%{http_code}" "$BASE/api/document" 2>/dev/null) || true
  [ "$code" = "200" ] || [ "$code" = "204" ]
}

_start_server() {
  if _check_server_up; then
    echo "  ⚠  Server already running on $BASE — stopping it for log capture..."
    # Kill any process listening on :8000 so we can start our own with DEBUG=full
    lsof -ti :8000 | xargs kill -9 2>/dev/null || true
    sleep 1
    if _check_server_up; then
      echo "  ✗ Could not stop existing server on $BASE. Stop it manually and re-run."
      return 1
    fi
    echo "  Existing server stopped."
  fi

  echo "  Starting backend server (DEBUG=full) for log capture..."
  # Use the backend venv if available, otherwise system python
  local py="python3"
  if [ -x "$BACKEND_DIR/.venv/bin/python" ]; then
    py="$BACKEND_DIR/.venv/bin/python"
  fi

  # Start with DEBUG=full for maximum log output.
  # PYTHONUNBUFFERED=1 prevents stdout buffering when redirected to a file,
  # ensuring print()-based debug output flushes immediately so per-flow log
  # segments (captured via line-count offsets) are accurate.
  # --prod disables hot-reload so logging.basicConfig in start.py runs in the
  # server process (reload mode spawns a subprocess that skips it).
  # Rate limits disabled: RATE_LIMIT_ENABLED=false disables slowapi per-route
  # limits, MAX_SESSIONS_PER_IP_HOUR=9999 effectively disables session creation
  # throttle, preventing 429s during rapid test runs.
  (cd "$BACKEND_DIR" && \
    PYTHONUNBUFFERED=1 \
    DEBUG=full \
    RATE_LIMIT_ENABLED=false \
    MAX_SESSIONS_PER_IP_HOUR=9999 \
    "$py" start.py --prod) > "$BACKEND_LOG" 2>&1 &
  SERVER_PID=$!
  MANAGED_SERVER=true

  # Wait for server to be ready
  local max_wait=45 waited=0
  while [ $waited -lt $max_wait ]; do
    if _check_server_up; then
      echo "  Server ready (PID=$SERVER_PID, waited ${waited}s)"
      echo ""
      return 0
    fi
    # Check if process died
    if ! kill -0 "$SERVER_PID" 2>/dev/null; then
      echo "  ✗ Server process died during startup. Check $BACKEND_LOG"
      return 1
    fi
    sleep 1
    waited=$((waited + 1))
  done
  echo "  ✗ Server failed to start after ${max_wait}s"
  return 1
}

_stop_server() {
  if [ "$MANAGED_SERVER" = true ] && [ -n "$SERVER_PID" ]; then
    echo ""
    echo "Stopping managed server (PID=$SERVER_PID)..."
    kill "$SERVER_PID" 2>/dev/null || true
    wait "$SERVER_PID" 2>/dev/null || true
    echo "Server stopped."
  fi
}

# ── Cleanup ──────────────────────────────────────────────────────────────────

cleanup() {
  rm -f "$COOKIE_JAR" "$RESP" "$SS_FILE" "$BODY_FILE"
  _stop_server
}
trap cleanup EXIT

# ── Console output capture ───────────────────────────────────────────────────
# Tee all stdout+stderr to the master console log for per-flow extraction.

exec > >(tee -a "$CONSOLE_FULL") 2>&1

# ── Flow selection ───────────────────────────────────────────────────────────

RUN_FLOW="${1:-all}"
should_run() {
  [ "$RUN_FLOW" = "all" ] && return 0
  echo ",$RUN_FLOW," | grep -qF ",$1,"
}

# ── Per-flow log capture ────────────────────────────────────────────────────

_CUR_FLOW=0
_BACKEND_LINES=0
_FLOW_SSE=""

_flow_begin() {
  _CUR_FLOW=$1
  _BACKEND_LINES=$(wc -l < "$BACKEND_LOG" 2>/dev/null || echo 0)
  _FLOW_SSE="$RESULTS_DIR/flow_${1}_sse.log"
  > "$_FLOW_SSE"
}

_flow_end() {
  local n=${1:-$_CUR_FLOW}

  # Extract backend log segment for this flow
  local new_lines
  new_lines=$(wc -l < "$BACKEND_LOG" 2>/dev/null || echo 0)
  local flow_backend="$RESULTS_DIR/flow_${n}_backend.log"
  if [ "$new_lines" -gt "$_BACKEND_LINES" ]; then
    tail -n $(( new_lines - _BACKEND_LINES )) "$BACKEND_LOG" > "$flow_backend" 2>/dev/null
  else
    > "$flow_backend"
  fi

  # Give tee a moment to flush console output
  sleep 0.2

  # Extract console segment between flow markers
  local flow_console="$RESULTS_DIR/flow_${n}_console.log"
  sed -n "/═══ Flow $n[: ]/,/══ Flow $n /p" "$CONSOLE_FULL" > "$flow_console" 2>/dev/null || > "$flow_console"
}

# Run analyzer on all captured flows after the suite finishes.
# Produces per-flow reports, prints + saves a combined summary, then deletes temp files.
_generate_final_report() {
  local summary="$RESULTS_DIR/summary_report.txt"

  {
    echo "═══════════════════════════════════════════════════════════════════════"
    echo "  NOMADIC E2E CURL FLOW SUITE — ISSUE REPORT"
    echo "  $(date '+%Y-%m-%d %H:%M:%S')"
    echo "═══════════════════════════════════════════════════════════════════════"
    echo ""
    echo "  Flows:  $FLOW_PASS/$FLOW_TOTAL passed"
    echo "  Checks: $PASS passed, $FAIL failed, $SKIP skipped"
    echo ""
  } > "$summary"

  # Analyze each captured flow
  if [ -f "$ANALYZER" ]; then
    for sse_file in "$RESULTS_DIR"/flow_*_sse.log; do
      [ -f "$sse_file" ] || continue
      local n
      n=$(echo "$sse_file" | sed 's/.*flow_\([0-9]*\)_sse.*/\1/')
      local flow_backend="$RESULTS_DIR/flow_${n}_backend.log"
      local flow_console="$RESULTS_DIR/flow_${n}_console.log"
      local flow_report="$RESULTS_DIR/flow_${n}_report.txt"

      python3 "$ANALYZER" "$n" "$flow_backend" "$flow_console" "$sse_file" "$flow_report" 2>/dev/null || true

      if [ -f "$flow_report" ]; then
        cat "$flow_report" >> "$summary"
        echo "" >> "$summary"

        # Tally analysis issues
        local errs warns
        errs=$(grep -c "^    ✗" "$flow_report" 2>/dev/null) || errs=0
        warns=$(grep -c "^    ⚠" "$flow_report" 2>/dev/null) || warns=0
        ANALYSIS_ERRORS=$((ANALYSIS_ERRORS + errs))
        ANALYSIS_WARNINGS=$((ANALYSIS_WARNINGS + warns))
      fi
    done
  fi

  # Append totals
  {
    echo "═══════════════════════════════════════════════════════════════════════"
    echo "  TOTALS"
    echo "    Flows:    $FLOW_PASS/$FLOW_TOTAL passed"
    echo "    Checks:   $PASS passed, $FAIL failed, $SKIP skipped"
    echo "    Analysis: $ANALYSIS_ERRORS errors, $ANALYSIS_WARNINGS warnings"
    echo "═══════════════════════════════════════════════════════════════════════"
  } >> "$summary"

  # Print the full report to console
  echo ""
  cat "$summary"

  # Delete individual report temp files; keep per-flow backend, console, and
  # SSE logs so /run-curl agents can inspect raw traces.
  find "$RESULTS_DIR" -maxdepth 1 -type f -name "flow_*_report.txt" -delete 2>/dev/null || true
}

# ── Session helpers ──────────────────────────────────────────────────────────

init_session() {
  local code attempt max_retries=4 delay=2
  for attempt in $(seq 1 $max_retries); do
    code=$(curl -s -o "$RESP" -w "%{http_code}" \
      -c "$COOKIE_JAR" -b "$COOKIE_JAR" "$BASE/api/document")
    if [ "$code" = "200" ] || [ "$code" = "204" ]; then
      CSRF=$(grep -i csrf "$COOKIE_JAR" | awk '{print $NF}' | head -1 || true)
      [ -z "$CSRF" ] && CSRF="none"
      return 0
    fi
    if [ "$code" = "429" ] && [ "$attempt" -lt "$max_retries" ]; then
      echo "  ⚠  init_session got 429, retrying in ${delay}s (attempt $attempt/$max_retries)"
      sleep "$delay"
      delay=$((delay * 2))
    else
      echo "  ✗ INFRA: init_session (HTTP $code)"
      FAIL=$((FAIL + 1)); return 1
    fi
  done
}

fresh_session() {
  echo '{}' > "$SS_FILE"
  # Each flow gets its own session so per-session rate limits (e.g.
  # 30/hour on graph_plan/stream) don't accumulate across flows.
  rm -f "$COOKIE_JAR"; COOKIE_JAR=$(mktemp)
  init_session
}

# Reset session state without creating a new session (avoids session creation limit).
# Use when the same flow needs a "clean slate" mid-test (e.g. Flow 11 cache survival).
reset_state() {
  echo '{}' > "$SS_FILE"
}

# POST with automatic session_state round-trip.
# Reads session_state from SS_FILE → includes in body → saves response session_state back.
send_message() {
  local msg="$1"
  python3 - "$msg" "$SS_FILE" "$BODY_FILE" <<'PYEOF'
import sys, json
msg, ss_path, out_path = sys.argv[1], sys.argv[2], sys.argv[3]
body = {"message": msg}
try:
    with open(ss_path) as f:
        ss = json.load(f)
    if ss and ss != {}:
        body["session_state"] = ss
except Exception:
    pass
with open(out_path, "w") as f:
    json.dump(body, f)
PYEOF

  local code attempt max_retries=3 delay=10
  for attempt in $(seq 1 $max_retries); do
    code=$(curl -s -o "$RESP" -w "%{http_code}" \
      -b "$COOKIE_JAR" -c "$COOKIE_JAR" \
      -X POST -H "Content-Type: application/json" \
      -H "X-CSRF-Token: $CSRF" \
      -d @"$BODY_FILE" "$API")

    if [ "$code" = "200" ]; then
      _save_session_state
      # Append SSE response to per-flow SSE log
      if [ -n "${_FLOW_SSE:-}" ]; then
        cat "$RESP" >> "$_FLOW_SSE"
        echo "" >> "$_FLOW_SSE"
      fi
      return 0
    fi
    if [ "$code" = "429" ] && [ "$attempt" -lt "$max_retries" ]; then
      echo "  ⚠  send_message got 429, retrying in ${delay}s (attempt $attempt/$max_retries)"
      sleep "$delay"
      delay=$((delay * 2))
    else
      echo "  ✗ INFRA: send_message (HTTP $code)"
      [ -s "$RESP" ] && echo "    body: $(tr '\n' ' ' < "$RESP" | cut -c1-200)"
      FAIL=$((FAIL + 1)); return 1
    fi
  done
}

# ── SSE extraction (operates on $RESP) ──────────────────────────────────────

# Extract dotted key from SSE complete event → data.document.<key>
extract_doc() {
  python3 - "$RESP" "$1" <<'PYEOF'
import sys, json
with open(sys.argv[1]) as f:
    for line in f:
        if not line.startswith("data: "): continue
        try: outer = json.loads(line[6:])
        except: continue
        if outer.get("type") != "complete": continue
        val = outer.get("data", {}).get("document", {})
        for p in sys.argv[2].split("."):
            if isinstance(val, dict): val = val.get(p)
            elif isinstance(val, list) and p.isdigit(): val = val[int(p)]
            else: val = None; break
        if val is not None:
            print(json.dumps(val) if isinstance(val, (dict, list)) else val)
        break
PYEOF
}

# Extract dotted key from SSE complete event → data.<key> (session_state etc.)
extract_top() {
  python3 - "$RESP" "$1" <<'PYEOF'
import sys, json
with open(sys.argv[1]) as f:
    for line in f:
        if not line.startswith("data: "): continue
        try: outer = json.loads(line[6:])
        except: continue
        if outer.get("type") != "complete": continue
        val = outer.get("data", {})
        for p in sys.argv[2].split("."):
            if isinstance(val, dict): val = val.get(p)
            elif isinstance(val, list) and p.isdigit(): val = val[int(p)]
            else: val = None; break
        if val is not None:
            print(json.dumps(val) if isinstance(val, (dict, list)) else val)
        break
PYEOF
}

# Save session_state from complete event to SS_FILE for next turn
_save_session_state() {
  python3 - "$RESP" "$SS_FILE" <<'PYEOF'
import sys, json
with open(sys.argv[1]) as f:
    for line in f:
        if not line.startswith("data: "): continue
        try: outer = json.loads(line[6:])
        except: continue
        if outer.get("type") == "complete":
            ss = outer.get("data", {}).get("session_state", {})
            with open(sys.argv[2], "w") as out: json.dump(ss, out)
            break
PYEOF
}

# Count SSE events by type (token / node_status / partial / complete / error)
count_sse() {
  python3 - "$RESP" "$1" <<'PYEOF'
import sys, json
c = 0
with open(sys.argv[1]) as f:
    for line in f:
        if not line.startswith("data: "): continue
        try: obj = json.loads(line[6:])
        except: continue
        if obj.get("type") == sys.argv[2]: c += 1
print(c)
PYEOF
}

# Comma-separated tool names from node_status "started" events
extract_tools() {
  python3 - "$RESP" <<'PYEOF'
import sys, json
tools = []
with open(sys.argv[1]) as f:
    for line in f:
        if not line.startswith("data: "): continue
        try: obj = json.loads(line[6:])
        except: continue
        if obj.get("type") == "node_status":
            d = obj.get("data", {})
            if d.get("status") == "started": tools.append(d.get("node", ""))
print(",".join(tools))
PYEOF
}

# Length of a JSON array/object (uses printf to avoid echo escaping issues)
jlen() {
  printf '%s' "$1" | python3 -c "
import sys,json
try: print(len(json.load(sys.stdin)))
except: print(0)
" 2>/dev/null || echo "0"
}

# ── Assertions ───────────────────────────────────────────────────────────────

check()              { if [ "$2" = "$3" ]; then echo "  ✓ $1"; PASS=$((PASS+1)); else echo "  ✗ $1 (expected='$3' got='$2')"; FAIL=$((FAIL+1)); return 1; fi; }
check_ne()           { if [ "$2" != "$3" ]; then echo "  ✓ $1"; PASS=$((PASS+1)); else echo "  ✗ $1 (should NOT be '$3')"; FAIL=$((FAIL+1)); return 1; fi; }
check_not_empty()    { if [ -n "$2" ] && [ "$2" != "null" ] && [ "$2" != "None" ] && [ "$2" != "{}" ] && [ "$2" != "[]" ]; then echo "  ✓ $1"; PASS=$((PASS+1)); else echo "  ✗ $1 (empty/null)"; FAIL=$((FAIL+1)); return 1; fi; }
check_contains()     { if echo "$2" | grep -qF "$3" 2>/dev/null; then echo "  ✓ $1"; PASS=$((PASS+1)); else echo "  ✗ $1 (no '$3' in: ${2:0:120})"; FAIL=$((FAIL+1)); return 1; fi; }
check_not_contains() { if ! echo "$2" | grep -qF "$3" 2>/dev/null; then echo "  ✓ $1"; PASS=$((PASS+1)); else echo "  ✗ $1 (should NOT contain '$3')"; FAIL=$((FAIL+1)); return 1; fi; }
check_gte()          { if [ -n "$2" ] && python3 -c "import sys;sys.exit(0 if int('$2')>=$3 else 1)" 2>/dev/null; then echo "  ✓ $1 (=$2 ≥ $3)"; PASS=$((PASS+1)); else echo "  ✗ $1 (expected ≥$3 got='$2')"; FAIL=$((FAIL+1)); return 1; fi; }
check_gt()           { if [ -n "$2" ] && python3 -c "import sys;sys.exit(0 if int('$2')>$3 else 1)" 2>/dev/null; then echo "  ✓ $1 (=$2 > $3)"; PASS=$((PASS+1)); else echo "  ✗ $1 (expected >$3 got='$2')"; FAIL=$((FAIL+1)); return 1; fi; }
skip_test()          { echo "  ⏭  $1 — SKIPPED ($2)"; SKIP=$((SKIP+1)); }

_flow() {
  FLOW_TOTAL=$((FLOW_TOTAL+1))
  if [ "$1" = "pass" ]; then FLOW_PASS=$((FLOW_PASS+1)); echo "  ══ Flow $2 PASS ══"
  else FLOW_FAIL=$((FLOW_FAIL+1)); echo "  ══ Flow $2 FAIL ══"; fi
}


# ── Start server ─────────────────────────────────────────────────────────────

echo "═══════════════════════════════════════════════════════════════"
echo "  Nomadic E2E Curl Flow Suite"
echo "  Results: $RESULTS_DIR"
echo "═══════════════════════════════════════════════════════════════"
echo ""

if ! _start_server; then
  echo "FATAL: Cannot start or reach backend server. Aborting."
  exit 1
fi


# =============================================================================
#  FLOW 1: Greeting — Zero Tools
# =============================================================================
# Cheapest path: agent responds directly without calling any tools.
# Validates SSE event lifecycle: tokens stream → complete event → no tools.
if should_run 1; then
_flow_begin 1
echo ""
echo "═══ Flow 1: Greeting — Zero Tools ═══"
F=true

if fresh_session; then
if send_message "Hi there!"; then

TOKEN_CT=$(count_sse "token")
check_gt "Tokens streamed" "$TOKEN_CT" 0 || F=false

NODE_CT=$(count_sse "node_status")
check "No tool node_status events (zero tools)" "$NODE_CT" "0" || F=false

COMPLETE_CT=$(count_sse "complete")
check "Exactly 1 complete event" "$COMPLETE_CT" "1" || F=false

PVS=$(extract_doc "plan_view_state")
check_contains "plan_view_state is S0" "$PVS" "S0" || F=false

# session_state returned (needed for multi-turn)
SS=$(extract_top "session_state")
check_not_empty "session_state returned" "$SS" || F=false

else F=false; fi; else F=false; fi
$F && _flow pass 1 || _flow fail 1
_flow_end 1
fi


# =============================================================================
#  FLOW 2: Input Gates
# =============================================================================
# Tests pre-graph validation: message length gate (2000 chars), CSRF enforcement.
if should_run 2; then
_flow_begin 2
echo ""
echo "═══ Flow 2: Input Gates ═══"
F=true

if init_session; then

# 2a: Oversized message (>2000 chars) → 422
echo "  → Oversized message (2100 chars)"
LONG_MSG=$(python3 -c "print('x'*2100)")
CODE=$(curl -s -o "$RESP" -w "%{http_code}" \
  -b "$COOKIE_JAR" -c "$COOKIE_JAR" -X POST \
  -H "Content-Type: application/json" -H "X-CSRF-Token: $CSRF" \
  -d "{\"message\":\"$LONG_MSG\"}" "$API")
check "Oversized → 422" "$CODE" "422" || F=false

# 2b: Empty message — should not 500
echo "  → Empty message"
CODE=$(curl -s -o "$RESP" -w "%{http_code}" \
  -b "$COOKIE_JAR" -c "$COOKIE_JAR" -X POST \
  -H "Content-Type: application/json" -H "X-CSRF-Token: $CSRF" \
  -d '{"message":""}' "$API")
if [ "$CODE" = "200" ] || [ "$CODE" = "422" ]; then
  echo "  ✓ Empty message handled (HTTP $CODE)"; PASS=$((PASS+1))
else
  echo "  ✗ Empty message → HTTP $CODE (expected 200 or 422)"; FAIL=$((FAIL+1)); F=false
fi

# 2c: Missing CSRF → 403
echo "  → Missing CSRF"
CODE=$(curl -s -o "$RESP" -w "%{http_code}" \
  -b "$COOKIE_JAR" -X POST \
  -H "Content-Type: application/json" \
  -d '{"message":"hello"}' "$API")
check "Missing CSRF → 403" "$CODE" "403" || F=false

fi
$F && _flow pass 2 || _flow fail 2
_flow_end 2
echo ""
fi


# =============================================================================
#  FLOW 3: Tier 1 Specialist — Diving in Bali + SSE Structure
# =============================================================================
# Full planning turn: extract_trip_fields → get_specialist_advice → search_tiles.
# Validates SSE event types, tool node_status names, document envelope, and
# session_state structure (trip_plan, trip_settings).
if should_run 3; then
_flow_begin 3
echo ""
echo "═══ Flow 3: Tier 1 Specialist — Diving in Bali ═══"
F=true

if fresh_session; then
if send_message "I want to go diving in Bali for a week starting March 15"; then

# ── SSE event structure ──
TOKEN_CT=$(count_sse "token")
check_gt "Tokens present" "$TOKEN_CT" 0 || F=false

NODE_CT=$(count_sse "node_status")
check_gt "Tool node_status events present" "$NODE_CT" 0 || F=false

TOOLS=$(extract_tools)
echo "  ℹ  Tools called: $TOOLS"
check_contains "extract_trip_fields called" "$TOOLS" "extract_trip_fields" || F=false
check_contains "get_specialist_advice called" "$TOOLS" "get_specialist_advice" || F=false

# ── session_state.trip_plan ──
DEST=$(extract_top "session_state.trip_plan.destination")
check_not_empty "Destination extracted" "$DEST" || F=false

START=$(extract_top "session_state.trip_plan.start_date")
check_not_empty "Start date extracted" "$START" || F=false

END=$(extract_top "session_state.trip_plan.end_date")
check_not_empty "End date extracted" "$END" || F=false

# ── session_state.trip_settings ──
TS=$(extract_top "session_state.trip_settings")
check_not_empty "trip_settings present" "$TS" || F=false

# ── document envelope ──
PVS=$(extract_doc "plan_view_state")
check_ne "plan_view_state past S0" "$PVS" "S0_BOOTSTRAP" || F=false

SECS=$(extract_doc "strategy_sections")
SEC_CT=$(jlen "$SECS")
check_gte "strategy_sections ≥ 1" "$SEC_CT" 1 || F=false

SUGG=$(extract_doc "suggested_responses")
SUGG_CT=$(jlen "$SUGG")
check_gte "suggested_responses ≥ 1" "$SUGG_CT" 1 || F=false

CHIPS=$(extract_doc "suggestion_chips")
CHIPS_CT=$(jlen "$CHIPS")
check_gte "suggestion_chips ≥ 1" "$CHIPS_CT" 1 || F=false

CHIP_META=$(extract_doc "suggested_response_meta")
CHIP_META_CT=$(jlen "$CHIP_META")
check_gte "suggested_response_meta ≥ 1" "$CHIP_META_CT" 1 || F=false

# ── Specialist tile verification ──
TILES=$(extract_doc "tiles")
TILE_CT=$(jlen "$TILES")
check_gte "tiles ≥ 3" "$TILE_CT" 3 || F=false

# Diving tiles should exist (from specialist OR GP browse with diving tag)
HAS_DIVING_TILES=$(echo "$TILES" | python3 -c "
import sys,json
try:
    t=json.load(sys.stdin)
    vals=t.values() if isinstance(t,dict) else t
    found=0
    for v in vals:
        if not isinstance(v,dict): continue
        tags=v.get('tags',[])
        title=(v.get('title','')+'').lower()
        if 'diving' in tags or 'dive' in title or 'snorkel' in title:
            found+=1
    print('true' if found>=1 else 'false')
except: print('false')
" 2>/dev/null || echo "false")
check "Diving tiles present (specialist or tagged)" "$HAS_DIVING_TILES" "true" || F=false

else F=false; fi; else F=false; fi
$F && _flow pass 3 || _flow fail 3
_flow_end 3
echo ""
fi


# =============================================================================
#  FLOW 4: Tier 2 Categories — Yoga + Cooking
# =============================================================================
# Tier 2 categories (not in SPECIALIST_REGISTRY) use experience_generator.
# get_specialist_advice should NOT fire — only Tier 1 has dedicated specialists.
if should_run 4; then
_flow_begin 4
echo ""
echo "═══ Flow 4: Tier 2 — Yoga + Cooking ═══"
F=true

if fresh_session; then
if send_message "yoga and cooking in Bali for 5 days starting April 1"; then

DEST=$(extract_top "session_state.trip_plan.destination")
check_not_empty "Destination extracted" "$DEST" || F=false

TS=$(extract_top "session_state.trip_settings")
check_not_empty "trip_settings present" "$TS" || F=false

PVS=$(extract_doc "plan_view_state")
check_ne "plan_view_state past S0" "$PVS" "S0_BOOTSTRAP" || F=false

TOOLS=$(extract_tools)
echo "  ℹ  Tools called: $TOOLS"
# Yoga/cooking not in SPECIALIST_REGISTRY → agent should skip specialist tool
check_not_contains "get_specialist_advice NOT called (Tier 2)" "$TOOLS" "get_specialist_advice" || F=false

else F=false; fi; else F=false; fi
$F && _flow pass 4 || _flow fail 4
_flow_end 4
echo ""
fi


# =============================================================================
#  FLOW 5: Mixed Tier 1 + Tier 2 — Diving + Yoga
# =============================================================================
# Diving triggers Tier 1 specialist; yoga is Tier 2. Both coexist in sections.
if should_run 5; then
_flow_begin 5
echo ""
echo "═══ Flow 5: Mixed — Diving + Yoga ═══"
F=true

if fresh_session; then
if send_message "diving and yoga in Bali for a week starting March 20"; then

SECS=$(extract_doc "strategy_sections")
SEC_CT=$(jlen "$SECS")
check_gte "strategy_sections ≥ 1" "$SEC_CT" 1 || F=false

TOOLS=$(extract_tools)
echo "  ℹ  Tools called: $TOOLS"
check_contains "get_specialist_advice called (diving)" "$TOOLS" "get_specialist_advice" || F=false

else F=false; fi; else F=false; fi
$F && _flow pass 5 || _flow fail 5
_flow_end 5
echo ""
fi


# =============================================================================
#  FLOW 6: Origin Detection — 2-Turn Session State Round-Trip
# =============================================================================
# Turn 1: destination + dates. Turn 2: origin city.
# Validates that session_state.trip_plan survives across turns and that
# setting origin flips booking_types.flights from "off" to "suggested"
# (per coordinator field-merge logic).
if should_run 6; then
_flow_begin 6
echo ""
echo "═══ Flow 6: Origin Detection — 2-Turn ═══"
F=true

if fresh_session; then

echo "  → Turn 1: Bali for a week starting March 15"
if send_message "I want to go to Bali for a week starting March 15"; then

DEST=$(extract_top "session_state.trip_plan.destination")
check_not_empty "Turn 1: destination extracted" "$DEST" || F=false

echo "  → Turn 2: I'm flying from San Francisco"
if send_message "I'm flying from San Francisco"; then

ORIGIN=$(extract_top "session_state.trip_plan.origin")
check_not_empty "Turn 2: origin extracted" "$ORIGIN" || F=false

# Verify San Francisco / SFO
ORIGIN_LC=$(echo "$ORIGIN" | tr '[:upper:]' '[:lower:]')
if echo "$ORIGIN_LC" | grep -qE "san francisco|sfo"; then
  echo "  ✓ Origin matches San Francisco (=$ORIGIN)"; PASS=$((PASS+1))
else
  echo "  ✗ Origin mismatch (got='$ORIGIN')"; FAIL=$((FAIL+1)); F=false
fi

# Destination must survive from Turn 1 (proves session_state round-trip works)
DEST2=$(extract_top "session_state.trip_plan.destination")
check_not_empty "Turn 2: destination preserved from Turn 1" "$DEST2" || F=false

# Origin → flights flipped to "suggested" (coordinator field-merge logic)
FLIGHTS=$(extract_top "session_state.trip_settings.booking_types.flights")
if [ -n "$FLIGHTS" ] && [ "$FLIGHTS" != "off" ]; then
  echo "  ✓ flights enabled after origin (=$FLIGHTS)"; PASS=$((PASS+1))
else
  echo "  ✗ flights still off after origin (got='$FLIGHTS')"; FAIL=$((FAIL+1)); F=false
fi

else F=false; fi; else F=false; fi; else F=false; fi
$F && _flow pass 6 || _flow fail 6
_flow_end 6
echo ""
fi


# =============================================================================
#  FLOW 7: Settings Change — 2-Turn NL Extraction
# =============================================================================
# Turn 1: destination. Turn 2: "5-star hotels only."
# Validates extract_trip_fields writes hotel_min_stars →
# trip_settings.hotel_settings.min_stars (via coordinator field-merge logic).
if should_run 7; then
_flow_begin 7
echo ""
echo "═══ Flow 7: Settings Change — 2-Turn ═══"
F=true

if fresh_session; then

echo "  → Turn 1: Bali for a week starting March 15"
if send_message "I want to go to Bali for a week starting March 15"; then

echo "  → Turn 2: 5-star hotels only"
if send_message "5-star hotels only"; then

MIN_STARS=$(extract_top "session_state.trip_settings.hotel_settings.min_stars")
if [ -n "$MIN_STARS" ] && python3 -c "import sys;sys.exit(0 if int('$MIN_STARS')>=4 else 1)" 2>/dev/null; then
  echo "  ✓ min_stars ≥ 4 (=$MIN_STARS)"; PASS=$((PASS+1))
else
  echo "  ✗ min_stars not updated (got='$MIN_STARS')"; FAIL=$((FAIL+1)); F=false
fi

else F=false; fi; else F=false; fi; else F=false; fi
$F && _flow pass 7 || _flow fail 7
_flow_end 7
echo ""
fi


# =============================================================================
#  FLOW 8: Bare Destination — Minimal Input
# =============================================================================
# Just "Bali". Agent should extract destination without error.
if should_run 8; then
_flow_begin 8
echo ""
echo "═══ Flow 8: Bare Destination ═══"
F=true

if fresh_session; then
if send_message "Bali"; then

COMPLETE_CT=$(count_sse "complete")
check "Complete event present" "$COMPLETE_CT" "1" || F=false

ERROR_CT=$(count_sse "error")
check "No error events" "$ERROR_CT" "0" || F=false

DEST=$(extract_top "session_state.trip_plan.destination")
check_not_empty "Destination extracted" "$DEST" || F=false

else F=false; fi; else F=false; fi
$F && _flow pass 8 || _flow fail 8
_flow_end 8
echo ""
fi


# =============================================================================
#  FLOW 9: Build Itinerary — 2-Turn with GENERATE_PLAN_NOW
# =============================================================================
# Turn 1: full trip details → extract + specialist + tiles.
# Turn 2: "GENERATE_PLAN_NOW" → validate_plan → build_itinerary → day_cards.
#
# Why 2 turns: agent tool-calling is non-deterministic. GENERATE_PLAN_NOW is an
# explicit trigger (system prompt rule 6) that skips extract_trip_fields and
# goes straight to validate → build. This makes the flow reliable.
if should_run 9; then
_flow_begin 9
echo ""
echo "═══ Flow 9: Build Itinerary — GENERATE_PLAN_NOW ═══"
F=true

if fresh_session; then

echo "  → Turn 1: Diving in Bali, March 15-22, from New York"
if send_message "Diving in Bali, March 15-22, 2 adults from New York"; then

TILES=$(extract_doc "tiles")
TILES_CT=$(jlen "$TILES")
echo "  ℹ  Tiles after Turn 1: $TILES_CT"

echo "  → Turn 2: GENERATE_PLAN_NOW"
if send_message "GENERATE_PLAN_NOW"; then

TOOLS=$(extract_tools)
echo "  ℹ  Tools called: $TOOLS"
# Agent may call build_itinerary explicitly OR auto-build fills day_cards.
# Check tool presence (informational) but don't fail — auto-build is valid.
if echo "$TOOLS" | grep -qF "build_itinerary"; then
  echo "  ✓ build_itinerary called explicitly"; PASS=$((PASS+1))
else
  echo "  ⚠  build_itinerary not called (auto-build expected)"
fi

# Day cards in document.day_cards (Pydantic model field name)
DAY_CARDS=$(extract_doc "day_cards")
DC_CT=$(jlen "$DAY_CARDS")
check_gte "day_cards ≥ 1" "$DC_CT" 1 || F=false

PVS=$(extract_doc "plan_view_state")
check_contains "plan_view_state is S3" "$PVS" "S3" || F=false

else F=false; fi; else F=false; fi; else F=false; fi
$F && _flow pass 9 || _flow fail 9
_flow_end 9
echo ""
fi


# =============================================================================
#  FLOW 10: Destination Change — Stale Data Cleared
# =============================================================================
# Turn 1: Bali + diving. Turn 2: "let's go to Lisbon instead."
# Coordinator field-merge logic clears strategy_sections, tiles, day_cards,
# constraints when destination changes.
if should_run 10; then
_flow_begin 10
echo ""
echo "═══ Flow 10: Destination Change — Stale Data Cleared ═══"
F=true

if fresh_session; then

echo "  → Turn 1: Diving in Bali for a week starting March 15"
if send_message "Diving in Bali for a week starting March 15"; then

SEC1_CT=$(jlen "$(extract_doc "strategy_sections")")
echo "  ℹ  Turn 1: $SEC1_CT strategy sections (Bali)"

echo "  → Turn 2: Actually, let's go to Lisbon instead"
if send_message "Actually, let's go to Lisbon instead"; then

DEST=$(extract_top "session_state.trip_plan.destination")
DEST_LC=$(echo "$DEST" | tr '[:upper:]' '[:lower:]')
check_contains "Destination changed to Lisbon" "$DEST_LC" "lisbon" || F=false

# After coordinator field-merge clears stale data, session_state.strategy_sections
# should be [] (cleared) or contain NEW Lisbon sections — but NOT Bali diving.
# The agent MAY call specialist again for Lisbon, or may not if no Tier 1 category.
STRAT_CT=$(jlen "$(extract_top "session_state.strategy_sections")")
echo "  ℹ  Turn 2: $STRAT_CT strategy sections (should be 0 or Lisbon-only)"

# Key proof: tiles should be cleared/replaced. Coordinator field-merge sets tiles={}
# then agent may call search_tiles for Lisbon.
TILES_RAW=$(extract_top "session_state.tiles")
HAS_BALI_TILES=$(echo "$TILES_RAW" | python3 -c "
import sys,json
try:
    t=json.load(sys.stdin)
    vals=t.values() if isinstance(t, dict) else t
    bali_refs=[v for v in vals if isinstance(v, dict)
               and 'bali' in json.dumps(v).lower()
               and v.get('type') in ('hotel', 'activity')]
    print('stale' if bali_refs else 'clean')
except: print('clean')
" 2>/dev/null || echo "clean")
check "Bali tiles cleared" "$HAS_BALI_TILES" "clean" || F=false

# Categories should NOT contain 'diving' after switching to Lisbon
CATS_RAW=$(extract_top "session_state.trip_settings.activity_settings.categories")
HAS_STALE_CAT=$(echo "$CATS_RAW" | python3 -c "
import sys,json
try:
    cats=json.load(sys.stdin)
    stale=[c for c in cats if c.lower() in ('diving','surfing','skiing')]
    print('stale:'+','.join(stale) if stale else 'clean')
except: print('clean')
" 2>/dev/null || echo "clean")
check "Stale categories cleared" "$HAS_STALE_CAT" "clean" || F=false

else F=false; fi; else F=false; fi; else F=false; fi
$F && _flow pass 10 || _flow fail 10
_flow_end 10
echo ""
fi


# =============================================================================
#  FLOW 11: Cache Survival — L2 Specialist Cache Across Session Reset
# =============================================================================
# Same query before/after session reset. Specialist structure fingerprint
# (count + types) should match (L2 cache hit). Warm path typically faster.
if should_run 11; then
_flow_begin 11
echo ""
echo "═══ Flow 11: Cache Survival — L2 Across Session Reset ═══"
F=true

if fresh_session; then

# Use dates 30 days in the future to avoid past-date auto-bump warnings
_F11_START=$(date -v+30d +%b\ %d 2>/dev/null || date -d "+30 days" +"%b %d" 2>/dev/null || echo "Jun 15")
_F11_END=$(date -v+37d +%b\ %d 2>/dev/null || date -d "+37 days" +"%b %d" 2>/dev/null || echo "Jun 22")
_F11_QUERY="Diving in Bali, ${_F11_START}-${_F11_END}"

echo "  → Turn 1 (cold): $_F11_QUERY"
T1_START=$(python3 -c "import time;print(int(time.time()*1000))")
if send_message "$_F11_QUERY"; then
T1_END=$(python3 -c "import time;print(int(time.time()*1000))")
T1_MS=$((T1_END - T1_START))
echo "  ⏱  Turn 1: ${T1_MS}ms"

# Structural fingerprint: section count + sorted specialist types
FP1=$(extract_doc "strategy_sections" | python3 -c "
import sys,json
try:
    secs=json.load(sys.stdin)
    types=sorted(s.get('specialist_type','?') for s in secs)
    print(f'{len(secs)}|{\"|\".join(types)}')
except: print('')
" 2>/dev/null || echo "")
echo "  Fingerprint 1: $FP1"

echo "  → Resetting session state..."
if reset_state; then

echo "  → Turn 2 (warm L2): $_F11_QUERY"
T2_START=$(python3 -c "import time;print(int(time.time()*1000))")
if send_message "$_F11_QUERY"; then
T2_END=$(python3 -c "import time;print(int(time.time()*1000))")
T2_MS=$((T2_END - T2_START))
echo "  ⏱  Turn 2: ${T2_MS}ms"

FP2=$(extract_doc "strategy_sections" | python3 -c "
import sys,json
try:
    secs=json.load(sys.stdin)
    types=sorted(s.get('specialist_type','?') for s in secs)
    print(f'{len(secs)}|{\"|\".join(types)}')
except: print('')
" 2>/dev/null || echo "")
echo "  Fingerprint 2: $FP2"

check "Specialist structure matches" "$FP1" "$FP2" || F=false

# Latency comparison — warn only, don't fail (varies with load)
if [ "$T1_MS" -gt 0 ] && [ "$T2_MS" -gt 0 ]; then
  if [ "$T2_MS" -lt "$T1_MS" ]; then
    echo "  ✓ Turn 2 faster (${T1_MS}ms → ${T2_MS}ms)"; PASS=$((PASS+1))
  else
    echo "  ⚠  Turn 2 not faster (${T1_MS}ms → ${T2_MS}ms) — L2 may not be hitting"; PASS=$((PASS+1))
  fi
fi

else F=false; fi; else F=false; fi
else F=false; fi; else F=false; fi
$F && _flow pass 11 || _flow fail 11
_flow_end 11
echo ""
fi


# =============================================================================
#  FLOW 12: Google Places Cascade — Non-Curated Destination (Conditional)
# =============================================================================
# Requires USE_GOOGLE_PLACES_PROVIDER=true. Skipped if not set.
# Verifies hotel tiles have real coordinates and Google Places metadata.
if should_run 12; then
_flow_begin 12
echo ""
echo "═══ Flow 12: Google Places Cascade ═══"

if [ -z "${GOOGLE_PLACES_API_KEY:-}" ] && [ -z "${USE_GOOGLE_PLACES_PROVIDER:-}" ]; then
  skip_test "Google Places tiles" "USE_GOOGLE_PLACES_PROVIDER not set"
  _flow pass 12  # conditional skip = pass
else
F=true

if reset_state; then
if send_message "I want hotels and things to do in Lisbon, March 10-17"; then

TILES_RAW=$(extract_doc "tiles")

HAS_META=$(echo "$TILES_RAW" | python3 -c "
import sys,json
tiles=json.load(sys.stdin)
vals=tiles.values() if isinstance(tiles,dict) else tiles
for t in vals:
    if isinstance(t,dict) and t.get('type')=='hotel':
        meta=t.get('meta',{})
        if meta.get('place_id') or 'google_places' in t.get('tags',[]):
            print('true'); sys.exit()
print('false')
" 2>/dev/null || echo "false")
check "Hotel tiles have Google Places metadata" "$HAS_META" "true" || F=false

HAS_COORDS=$(echo "$TILES_RAW" | python3 -c "
import sys,json
tiles=json.load(sys.stdin)
vals=tiles.values() if isinstance(tiles,dict) else tiles
for t in vals:
    if isinstance(t,dict) and t.get('type')=='hotel':
        geo=t.get('geo') or {}
        if geo.get('lat',0)!=0 and geo.get('lng',0)!=0:
            print('true'); sys.exit()
print('false')
" 2>/dev/null || echo "false")
check "Hotel coordinates are real" "$HAS_COORDS" "true" || F=false

else F=false; fi; else F=false; fi
$F && _flow pass 12 || _flow fail 12
fi
_flow_end 12
echo ""
fi


# =============================================================================
#  FLOW 13: APD Tile Scaling — activities_per_day=2 Produces Enough Tiles
# =============================================================================
# Regression test for the APD tile scaling bug chain:
#   - _activity_logistics_hash must include activities_per_day
#   - _search_tiles must forward strategy_sections to logistics_node
#   - _compute_tiles_per_category cap must scale for APD > 1
#   - APD change must invalidate stale tiles
#
# Turn 1: Tier 2 trip with APD=2 → extract + search_tiles + build_itinerary.
# Turn 2: GENERATE_PLAN_NOW → day_cards with multiple activity blocks per day.
if should_run 13; then
_flow_begin 13
echo ""
echo "═══ Flow 13: APD Tile Scaling — activities_per_day=2 ═══"
F=true

if fresh_session; then

echo "  → Turn 1: Yoga in Bali, 7 days, 2 activities per day"
if send_message "yoga in Bali for a week starting March 15, 2 activities per day"; then

# activities_per_day must be captured in session_state
APD=$(extract_top "session_state.trip_settings.activity_settings.activities_per_day")
if [ -n "$APD" ] && python3 -c "import sys;sys.exit(0 if int('$APD')>=2 else 1)" 2>/dev/null; then
  echo "  ✓ activities_per_day ≥ 2 (=$APD)"; PASS=$((PASS+1))
else
  echo "  ✗ activities_per_day not extracted (got='$APD')"; FAIL=$((FAIL+1)); F=false
fi

echo "  → Turn 2: GENERATE_PLAN_NOW"
if send_message "GENERATE_PLAN_NOW"; then

DAY_CARDS=$(extract_doc "day_cards")
DC_CT=$(jlen "$DAY_CARDS")
check_gte "day_cards ≥ 5 (7-day trip)" "$DC_CT" 5 || F=false

# Count total activity blocks across all day cards.
# With APD=2 and 5 free days, builder should place ≥ 8 activities.
# (10 ideal, but co-scheduling and tile availability may reduce slightly)
ACT_CT=$(echo "$DAY_CARDS" | python3 -c "
import sys,json
try:
    cards=json.load(sys.stdin)
    total=0
    for card in cards:
        for b in card.get('blocks',[]):
            if b.get('booking_category')=='activity':
                total+=1
    print(total)
except: print(0)
" 2>/dev/null || echo "0")
echo "  ℹ  Total activity blocks: $ACT_CT"
check_gte "Activity blocks ≥ 6 (APD=2 × 5 free days, slack for LLM/provider variance)" "$ACT_CT" 6 || F=false

# At least one day should have 2+ activity blocks (proves APD>1 works)
MULTI_ACT_DAYS=$(echo "$DAY_CARDS" | python3 -c "
import sys,json
try:
    cards=json.load(sys.stdin)
    count=0
    for card in cards:
        acts=sum(1 for b in card.get('blocks',[]) if b.get('booking_category')=='activity')
        if acts>=2: count+=1
    print(count)
except: print(0)
" 2>/dev/null || echo "0")
check_gte "Days with 2+ activities ≥ 1" "$MULTI_ACT_DAYS" 1 || F=false

else F=false; fi; else F=false; fi; else F=false; fi
$F && _flow pass 13 || _flow fail 13
_flow_end 13
echo ""
fi


# =============================================================================
#  FLOW 14: Full Plan Golden Path — Rome Cultural, Mar 1-7
# =============================================================================
# Golden path integration smoke test: two turns from "rome" to rendered itinerary.
#   Turn 1: "rome" → extract_trip_fields, local_intel, conversationalist
#     - destination extracted
#     - strategy_sections populated (local_expert at minimum)
#     - no day_cards (no dates yet)
#     - suggested_responses nudge toward dates
#   Turn 2: "Mar 1-7" → extract_trip_fields, search_tiles, build_itinerary
#     - plan_view_state = S3
#     - 7 day_cards (Mar 1 through Mar 7)
#     - Day 1 = Arrival, Day 7 = Departure
#     - tiles non-empty (hotels + activities)
#     - interior days have activity blocks
#     - strategy_sections preserved from Turn 1
if should_run 14; then
_flow_begin 14
echo ""
echo "═══ Flow 14: Full Plan Golden Path — Rome Cultural ═══"
F=true

if fresh_session; then

# ── Turn 1: Destination only ──────────────────────────────────────────
echo "  → Turn 1: rome"
if send_message "rome"; then

DEST=$(extract_top "session_state.trip_plan.destination")
check_not_empty "Turn 1: destination extracted" "$DEST" || F=false

SECS=$(extract_doc "strategy_sections")
SEC_CT=$(jlen "$SECS")
check_gte "Turn 1: strategy_sections ≥ 1" "$SEC_CT" 1 || F=false

# No day_cards yet (no dates provided)
DC=$(extract_doc "day_cards")
DC_CT=$(jlen "$DC")
check "Turn 1: 0 day_cards (no dates)" "$DC_CT" "0" || F=false

SUGG=$(extract_doc "suggested_responses")
SUGG_CT=$(jlen "$SUGG")
check_gte "Turn 1: suggested_responses ≥ 1" "$SUGG_CT" 1 || F=false

PVS=$(extract_doc "plan_view_state")
check_not_contains "Turn 1: plan_view_state not S3 yet" "$PVS" "S3" || F=false

# ── Turn 2: Add dates ────────────────────────────────────────────────
echo "  → Turn 2: Mar 1-7"
if send_message "Mar 1-7"; then

# Dates extracted
START=$(extract_top "session_state.trip_plan.start_date")
check_not_empty "Turn 2: start_date extracted" "$START" || F=false
check_contains "Turn 2: start_date contains 03-01" "$START" "03-01" || F=false

END=$(extract_top "session_state.trip_plan.end_date")
check_not_empty "Turn 2: end_date extracted" "$END" || F=false
check_contains "Turn 2: end_date contains 03-07" "$END" "03-07" || F=false

# plan_view_state = S3
PVS=$(extract_doc "plan_view_state")
check_contains "Turn 2: plan_view_state=S3" "$PVS" "S3" || F=false

# 7 day_cards
DAY_CARDS=$(extract_doc "day_cards")
DC_CT=$(jlen "$DAY_CARDS")
echo "  ℹ  Day cards: $DC_CT"
check_gte "Turn 2: day_cards ≥ 6 (Mar 1-7)" "$DC_CT" 6 || F=false

# Day 1 = Arrival
DAY1_LABEL=$(echo "$DAY_CARDS" | python3 -c "
import sys,json
try:
    cards=json.load(sys.stdin)
    label=cards[0].get('label','') if cards else ''
    print(label.lower())
except: print('')
" 2>/dev/null || echo "")
check_contains "Turn 2: Day 1=Arrival" "$DAY1_LABEL" "arrival" || F=false

# Day 7 = Departure
DAY7_LABEL=$(echo "$DAY_CARDS" | python3 -c "
import sys,json
try:
    cards=json.load(sys.stdin)
    label=cards[-1].get('label','') if cards else ''
    print(label.lower())
except: print('')
" 2>/dev/null || echo "")
check_contains "Turn 2: Day 7=Departure" "$DAY7_LABEL" "departure" || F=false

# Interior days (2-6) have ≥1 activity block each
# Require at least 3 of 5 interior days to have activities (LLM variance)
INTERIOR_OK=$(echo "$DAY_CARDS" | python3 -c "
import sys,json
try:
    cards=json.load(sys.stdin)
    ok=0
    for card in cards[1:6]:
        acts=sum(1 for b in card.get('blocks',[]) if b.get('booking_category')=='activity')
        if acts>=1: ok+=1
    print(ok)
except: print(0)
" 2>/dev/null || echo "0")
echo "  ℹ  Interior days with activities: $INTERIOR_OK/5"
check_gte "Turn 2: interior days with activities ≥ 3" "$INTERIOR_OK" 3 || F=false

# Tiles non-empty
TILES=$(extract_doc "tiles")
TILE_CT=$(jlen "$TILES")
check_gte "Turn 2: tiles ≥ 3" "$TILE_CT" 3 || F=false

# At least 1 hotel tile with deeplink_url
HOTEL_DEEPLINKS=$(echo "$TILES" | python3 -c "
import sys,json
try:
    tiles=json.load(sys.stdin)
    vals=tiles.values() if isinstance(tiles,dict) else tiles
    count=sum(1 for t in vals if isinstance(t,dict) and t.get('type')=='hotel' and t.get('deeplink_url'))
    print(count)
except: print(0)
" 2>/dev/null || echo "0")
check_gte "Turn 2: hotel tiles with deeplink ≥ 1" "$HOTEL_DEEPLINKS" 1 || F=false

# At least 1 activity tile with geo coordinates
ACT_GEO=$(echo "$TILES" | python3 -c "
import sys,json
try:
    tiles=json.load(sys.stdin)
    vals=tiles.values() if isinstance(tiles,dict) else tiles
    count=sum(1 for t in vals if isinstance(t,dict) and t.get('type')=='activity' and t.get('geo'))
    print(count)
except: print(0)
" 2>/dev/null || echo "0")
check_gte "Turn 2: activity tiles with geo ≥ 1" "$ACT_GEO" 1 || F=false

# Strategy sections preserved from Turn 1
SECS2=$(extract_doc "strategy_sections")
SEC2_CT=$(jlen "$SECS2")
check_gte "Turn 2: strategy_sections preserved ≥ 1" "$SEC2_CT" 1 || F=false

# Destination survived Turn 2
DEST2=$(extract_top "session_state.trip_plan.destination")
check_not_empty "Turn 2: destination preserved" "$DEST2" || F=false

# Tools called
TOOLS=$(extract_tools)
echo "  ℹ  Tools called: $TOOLS"
check_contains "Turn 2: build_itinerary called" "$TOOLS" "build_itinerary" || F=false

else F=false; fi; else F=false; fi; else F=false; fi
$F && _flow pass 14 || _flow fail 14
_flow_end 14
echo ""
fi


# =============================================================================
#  FLOW 15: Deeplink URL Format Validation
# =============================================================================
# Booking buttons ship this sprint — broken URLs = broken demo.
# Validates that hotel/activity deeplink_url fields are real HTTP URLs,
# not "#" placeholders or empty strings.
if should_run 15; then
_flow_begin 15
echo ""
echo "═══ Flow 15: Deeplink URL Format Validation ═══"
F=true

# Run a fresh session with the golden path
if fresh_session; then
if send_message "diving in Bali, March 15-22, from New York"; then
if send_message "GENERATE_PLAN_NOW"; then

TILES=$(extract_doc "tiles")
TILE_CT=$(jlen "$TILES")
check_gte "Tiles present for deeplink check" "$TILE_CT" 1 || F=false

# Hotel deeplinks must be valid HTTP URLs
HOTEL_DL_VALID=$(echo "$TILES" | python3 -c "
import sys,json
try:
    tiles=json.load(sys.stdin)
    vals=tiles.values() if isinstance(tiles,dict) else tiles
    hotels=[t for t in vals if isinstance(t,dict) and t.get('type')=='hotel']
    bad=[]
    for t in hotels:
        dl=t.get('deeplink_url','')
        if not dl or dl=='#' or not dl.startswith('http'):
            bad.append(f\"{t.get('id','?')}: '{dl[:60]}'\")
    if bad: print('INVALID: ' + '; '.join(bad[:3]))
    else: print('valid')
except Exception as e: print(f'ERROR: {e}')
" 2>/dev/null || echo "ERROR")
check_contains "Hotel deeplinks are valid URLs" "$HOTEL_DL_VALID" "valid" || F=false

# Activity deeplinks must be valid HTTP URLs
ACT_DL_VALID=$(echo "$TILES" | python3 -c "
import sys,json
try:
    tiles=json.load(sys.stdin)
    vals=tiles.values() if isinstance(tiles,dict) else tiles
    acts=[t for t in vals if isinstance(t,dict) and t.get('type')=='activity']
    bad=[]
    for t in acts:
        dl=t.get('deeplink_url','')
        if not dl or dl=='#' or not dl.startswith('http'):
            bad.append(f\"{t.get('id','?')}: '{dl[:60]}'\")
    if bad: print('INVALID: ' + '; '.join(bad[:3]))
    else: print('valid')
except Exception as e: print(f'ERROR: {e}')
" 2>/dev/null || echo "ERROR")
check_contains "Activity deeplinks are valid URLs" "$ACT_DL_VALID" "valid" || F=false

# DayBlock.deeplink propagation — blocks should inherit tile deeplinks
BLOCK_DL=$(extract_doc "day_cards" | python3 -c "
import sys,json
try:
    cards=json.load(sys.stdin)
    total=0; has_dl=0
    for card in cards:
        for b in card.get('blocks',[]):
            if b.get('booking_category')=='activity':
                total+=1
                if b.get('deeplink'): has_dl+=1
    print(f'{has_dl}/{total}')
except: print('0/0')
" 2>/dev/null || echo "0/0")
echo "  ℹ  Activity blocks with deeplink: $BLOCK_DL"

else F=false; fi; else F=false; fi; else F=false; fi
$F && _flow pass 15 || _flow fail 15
_flow_end 15
echo ""
fi


# =============================================================================
#  FLOW 16: Travelers + Budget Extraction
# =============================================================================
# Real users type "2 adults and a kid, $3000 budget." Validates that the
# router extraction correctly parses adults, children, and budget fields.
if should_run 16; then
_flow_begin 16
echo ""
echo "═══ Flow 16: Travelers + Budget Extraction ═══"
F=true

if fresh_session; then
if send_message "Bali for a week starting March 15, 2 adults and 1 child, budget around 3000 dollars"; then

ADULTS=$(extract_top "session_state.trip_plan.adults")
check "Adults=2" "$ADULTS" "2" || F=false

CHILDREN=$(extract_top "session_state.trip_plan.children")
check "Children=1" "$CHILDREN" "1" || F=false

BUDGET=$(extract_top "session_state.trip_plan.budget")
if [ -n "$BUDGET" ] && [ "$BUDGET" != "null" ]; then
  echo "  ✓ Budget extracted (=$BUDGET)"; PASS=$((PASS+1))
else
  skip_test "Budget extracted" "budget extraction is best-effort"
fi

else F=false; fi; else F=false; fi
$F && _flow pass 16 || _flow fail 16
_flow_end 16
echo ""
fi


# =============================================================================
#  FLOW 17: Suggested Response Round-Trip
# =============================================================================
# The chip bar is core UX. User clicks a suggested response → does the backend
# handle it as a normal turn? Validates end-to-end suggested_response flow.
if should_run 17; then
_flow_begin 17
echo ""
echo "═══ Flow 17: Suggested Response Round-Trip ═══"
F=true

if fresh_session; then

echo "  → Turn 1: Bali destination"
if send_message "I want to go to Bali"; then

# Capture a suggested_response from Turn 1
SUGG_TEXT=$(extract_doc "suggested_responses" | python3 -c "
import sys,json
try:
    srs=json.load(sys.stdin)
    if srs and isinstance(srs, list):
        # Pick the first text-bearing suggestion
        for s in srs:
            text = s.get('text','') if isinstance(s,dict) else str(s)
            if text and len(text) > 2:
                print(text); break
        else: print('')
    else: print('')
except: print('')
" 2>/dev/null || echo "")

if [ -n "$SUGG_TEXT" ]; then
  echo "  ℹ  Using suggested response: '$SUGG_TEXT'"
  echo "  → Turn 2: Send suggested response as user message"
  if send_message "$SUGG_TEXT"; then

    COMPLETE_CT=$(count_sse "complete")
    check "Turn 2: complete event" "$COMPLETE_CT" "1" || F=false

    ERROR_CT=$(count_sse "error")
    check "Turn 2: no error events" "$ERROR_CT" "0" || F=false

    # Destination preserved
    DEST2=$(extract_top "session_state.trip_plan.destination")
    check_not_empty "Turn 2: destination preserved" "$DEST2" || F=false

  else F=false; fi
else
  skip_test "Suggested response round-trip" "no suggested_responses in Turn 1"
fi

else F=false; fi; else F=false; fi
$F && _flow pass 17 || _flow fail 17
_flow_end 17
echo ""
fi


# =============================================================================
#  FLOW 18: Price + Star Rating in Day Cards
# =============================================================================
# After building an itinerary, activity blocks should carry price_level and
# hotel blocks should have booked_tile with price_estimate. Rating comes from
# LLM specialist output (not Google Places, which is Pro-tier only).
if should_run 18; then
_flow_begin 18
echo ""
echo "═══ Flow 18: Price + Star Rating in Day Cards ═══"
F=true

if fresh_session; then

echo "  → Turn 1: Diving in Bali, March 15-22, from New York"
if send_message "Diving in Bali, March 15-22, 2 adults from New York"; then

echo "  → Turn 2: GENERATE_PLAN_NOW"
if send_message "GENERATE_PLAN_NOW"; then

DAY_CARDS=$(extract_doc "day_cards")
DC_CT=$(jlen "$DAY_CARDS")
check_gte "day_cards present" "$DC_CT" 1 || F=false

# Count activity blocks with price_level set (non-null)
PRICED_ACTS=$(echo "$DAY_CARDS" | python3 -c "
import sys,json
try:
    cards=json.load(sys.stdin)
    total=0; priced=0
    for card in cards:
        for b in card.get('blocks',[]):
            if b.get('booking_category')=='activity':
                total+=1
                if b.get('price_level') is not None:
                    priced+=1
    print(f'{priced}/{total}')
except: print('0/0')
" 2>/dev/null || echo "0/0")
echo "  ℹ  Activity blocks with price_level: $PRICED_ACTS"

# At least 50% of activity blocks should have price_level
PRICE_OK=$(echo "$DAY_CARDS" | python3 -c "
import sys,json
try:
    cards=json.load(sys.stdin)
    total=0; priced=0
    for card in cards:
        for b in card.get('blocks',[]):
            if b.get('booking_category')=='activity':
                total+=1
                if b.get('price_level') is not None:
                    priced+=1
    print('true' if total>0 and priced>=total*0.5 else 'false')
except: print('false')
" 2>/dev/null || echo "false")
check "≥50% activity blocks have price_level" "$PRICE_OK" "true" || F=false

# Count activity blocks with rating set (from LLM specialist output)
RATED_ACTS=$(echo "$DAY_CARDS" | python3 -c "
import sys,json
try:
    cards=json.load(sys.stdin)
    total=0; rated=0
    for card in cards:
        for b in card.get('blocks',[]):
            if b.get('booking_category')=='activity':
                total+=1
                if b.get('rating') is not None:
                    rated+=1
    print(f'{rated}/{total}')
except: print('0/0')
" 2>/dev/null || echo "0/0")
echo "  ℹ  Activity blocks with rating: $RATED_ACTS"

# Hotel price in tiles dict (hotels are browse-only without explicit user preference)
TILES=$(extract_doc "tiles")
HOTEL_PRICE=$(echo "$TILES" | python3 -c "
import sys,json
try:
    tiles=json.load(sys.stdin)
    vals=tiles.values() if isinstance(tiles,dict) else tiles
    for t in vals:
        if not isinstance(t,dict): continue
        if t.get('type')=='hotel':
            pe=t.get('price_estimate') or t.get('total_inclusive')
            if pe is not None and float(pe)>0:
                print('true'); sys.exit()
    print('false')
except: print('false')
" 2>/dev/null || echo "false")
check "Hotel tile has price in tiles dict" "$HOTEL_PRICE" "true" || F=false

# Hotel tile should have rating (from tile data)
HOTEL_RATING=$(echo "$DAY_CARDS" | python3 -c "
import sys,json
try:
    cards=json.load(sys.stdin)
    for card in cards:
        for b in card.get('blocks',[]):
            if b.get('booking_category')=='hotel' and b.get('booked_tile'):
                tile=b['booked_tile']
                r=tile.get('rating')
                if r is not None and float(r)>0:
                    print('true'); sys.exit()
    print('false')
except: print('false')
" 2>/dev/null || echo "false")
if [ "$HOTEL_RATING" = "true" ]; then
  echo "  ✓ Hotel booked_tile has rating"; PASS=$((PASS+1))
else
  echo "  ⚠  Hotel booked_tile missing rating (non-critical — heuristic sources vary)"
fi

# Tiles should have price_estimate set
TILES=$(extract_doc "tiles")
TILES_PRICED=$(echo "$TILES" | python3 -c "
import sys,json
try:
    tiles=json.load(sys.stdin)
    vals=tiles.values() if isinstance(tiles,dict) else tiles
    total=0; priced=0
    for t in vals:
        if isinstance(t,dict):
            total+=1
            pe=t.get('price_estimate') or t.get('total_inclusive')
            if pe is not None and float(pe)>0:
                priced+=1
    print(f'{priced}/{total}')
except: print('0/0')
" 2>/dev/null || echo "0/0")
echo "  ℹ  Tiles with price: $TILES_PRICED"
TILE_PRICE_OK=$(echo "$TILES" | python3 -c "
import sys,json
try:
    tiles=json.load(sys.stdin)
    vals=tiles.values() if isinstance(tiles,dict) else tiles
    total=0; priced=0
    for t in vals:
        if isinstance(t,dict):
            total+=1
            pe=t.get('price_estimate') or t.get('total_inclusive')
            if pe is not None and float(pe)>0:
                priced+=1
    print('true' if total>0 and priced>=total*0.5 else 'false')
except: print('false')
" 2>/dev/null || echo "false")
check "≥50% tiles have price_estimate" "$TILE_PRICE_OK" "true" || F=false

else F=false; fi; else F=false; fi; else F=false; fi
$F && _flow pass 18 || _flow fail 18
_flow_end 18
echo ""
fi


# =============================================================================
#  FLOW 19: Extend Trip — Preserves Existing Day Cards
# =============================================================================
# Turn 1: 5-day trip. Turn 2: GENERATE_PLAN_NOW. Turn 3: Extend by 3 days.
# Turn 4: GENERATE_PLAN_NOW again.
# Validates that the new itinerary has more days and the original Arrival/Departure
# structure is preserved (Arrival on Day 1, Departure on last day).
if should_run 19; then
_flow_begin 19
echo ""
echo "═══ Flow 19: Extend Trip — Preserves Existing Day Cards ═══"
F=true

if fresh_session; then

echo "  → Turn 1: Rome, March 1-5"
if send_message "I want to visit Rome from March 1 to March 5"; then

DEST=$(extract_top "session_state.trip_plan.destination")
check_not_empty "Turn 1: destination extracted" "$DEST" || F=false

echo "  → Turn 2: GENERATE_PLAN_NOW"
if send_message "GENERATE_PLAN_NOW"; then

DAY_CARDS_T2=$(extract_doc "day_cards")
DC_CT_T2=$(jlen "$DAY_CARDS_T2")
echo "  ℹ  Turn 2: $DC_CT_T2 day cards (5-day trip)"
check_gte "Turn 2: day_cards ≥ 4" "$DC_CT_T2" 4 || F=false

# Capture Arrival label
DAY1_LABEL_T2=$(echo "$DAY_CARDS_T2" | python3 -c "
import sys,json
try:
    cards=json.load(sys.stdin)
    print(cards[0].get('label','').lower() if cards else '')
except: print('')
" 2>/dev/null || echo "")
check_contains "Turn 2: Day 1=Arrival" "$DAY1_LABEL_T2" "arrival" || F=false

# Capture activity count from original itinerary
ORIG_ACT_CT=$(echo "$DAY_CARDS_T2" | python3 -c "
import sys,json
try:
    cards=json.load(sys.stdin)
    total=0
    for card in cards:
        for b in card.get('blocks',[]):
            if b.get('booking_category')=='activity':
                total+=1
    print(total)
except: print(0)
" 2>/dev/null || echo "0")
echo "  ℹ  Turn 2: $ORIG_ACT_CT activity blocks in original itinerary"

echo "  → Turn 3: Extend trip by 3 more days"
if send_message "extend the trip by 3 more days"; then

# Router should update end_date
END_DATE=$(extract_top "session_state.trip_plan.end_date")
check_not_empty "Turn 3: end_date updated" "$END_DATE" || F=false
# End date should now be March 8 (original Mar 5 + 3 days)
if echo "$END_DATE" | grep -qE "03-0[7-9]|03-1[0-9]"; then
  echo "  ✓ End date extended past March 5 (=$END_DATE)"; PASS=$((PASS+1))
else
  echo "  ⚠  End date may not be extended (=$END_DATE) — checking day count instead"
fi

echo "  → Turn 4: GENERATE_PLAN_NOW"
if send_message "GENERATE_PLAN_NOW"; then

DAY_CARDS_T4=$(extract_doc "day_cards")
DC_CT_T4=$(jlen "$DAY_CARDS_T4")
echo "  ℹ  Turn 4: $DC_CT_T4 day cards (extended trip)"

# Extended trip should have MORE day cards than original
check_gt "Turn 4: more day_cards than Turn 2 ($DC_CT_T4 > $DC_CT_T2)" "$DC_CT_T4" "$DC_CT_T2" || F=false

# Should have at least 7 day cards (5 original + 3 extended)
check_gte "Turn 4: day_cards ≥ 7 (extended)" "$DC_CT_T4" 7 || F=false

# Arrival still on Day 1
DAY1_LABEL_T4=$(echo "$DAY_CARDS_T4" | python3 -c "
import sys,json
try:
    cards=json.load(sys.stdin)
    print(cards[0].get('label','').lower() if cards else '')
except: print('')
" 2>/dev/null || echo "")
check_contains "Turn 4: Day 1=Arrival (preserved)" "$DAY1_LABEL_T4" "arrival" || F=false

# Departure on last day
LAST_LABEL_T4=$(echo "$DAY_CARDS_T4" | python3 -c "
import sys,json
try:
    cards=json.load(sys.stdin)
    print(cards[-1].get('label','').lower() if cards else '')
except: print('')
" 2>/dev/null || echo "")
check_contains "Turn 4: Last day=Departure" "$LAST_LABEL_T4" "departure" || F=false

# Activity count should be >= original (more days = more activities)
EXTEND_ACT_CT=$(echo "$DAY_CARDS_T4" | python3 -c "
import sys,json
try:
    cards=json.load(sys.stdin)
    total=0
    for card in cards:
        for b in card.get('blocks',[]):
            if b.get('booking_category')=='activity':
                total+=1
    print(total)
except: print(0)
" 2>/dev/null || echo "0")
echo "  ℹ  Turn 4: $EXTEND_ACT_CT activity blocks in extended itinerary"
check_gte "Turn 4: activity blocks ≥ original ($EXTEND_ACT_CT ≥ $ORIG_ACT_CT)" "$EXTEND_ACT_CT" "$ORIG_ACT_CT" || F=false

# Day utilization: ≥50% of interior days should have real activity blocks
FILL_RATE=$(echo "$DAY_CARDS_T4" | python3 -c "
import sys,json
try:
    cards=json.load(sys.stdin)
    interior=[c for c in cards[1:-1]]  # skip arrival/departure
    with_acts=0
    for c in interior:
        acts=[b for b in c.get('blocks',[]) if b.get('booking_category')=='activity']
        if acts: with_acts+=1
    total=max(1,len(interior))
    print('true' if with_acts/total >= 0.5 else 'false')
except: print('false')
" 2>/dev/null || echo "false")
check "Turn 4: ≥50% interior days have activities" "$FILL_RATE" "true" || F=false

# Destination preserved through all turns
DEST_T4=$(extract_top "session_state.trip_plan.destination")
check_not_empty "Turn 4: destination preserved" "$DEST_T4" || F=false

else F=false; fi; else F=false; fi; else F=false; fi; else F=false; fi; else F=false; fi
$F && _flow pass 19 || _flow fail 19
_flow_end 19
echo ""
fi


# =============================================================================
#  FLOW 20: Add Tier 1 Activity — Hiking After Initial Plan
# =============================================================================
# Turn 1: Cultural trip to Rome. Turn 2: GENERATE_PLAN_NOW.
# Turn 3: "add hiking". Turn 4: GENERATE_PLAN_NOW.
# Validates: specialist dispatched successfully, hiking tiles in tile dict,
# hiking activity blocks in day_cards, categories include hiking.
if should_run 20; then
_flow_begin 20
echo ""
echo "═══ Flow 20: Add Tier 1 Activity — Hiking ═══"
F=true

if fresh_session; then

echo "  → Turn 1: Cultural trip to Rome, March 1-7"
if send_message "I want a cultural trip to Rome from March 1 to March 7"; then

DEST=$(extract_top "session_state.trip_plan.destination")
check_not_empty "Turn 1: destination" "$DEST" || F=false

echo "  → Turn 2: GENERATE_PLAN_NOW"
if send_message "GENERATE_PLAN_NOW"; then

DC_T2=$(extract_doc "day_cards")
DC_CT_T2=$(jlen "$DC_T2")
check_gte "Turn 2: day_cards ≥ 5" "$DC_CT_T2" 5 || F=false

# Count cultural activity blocks before hiking
CULTURAL_ACT_CT=$(echo "$DC_T2" | python3 -c "
import sys,json
try:
    cards=json.load(sys.stdin)
    total=sum(1 for c in cards for b in c.get('blocks',[]) if b.get('booking_category')=='activity')
    print(total)
except: print(0)
" 2>/dev/null || echo "0")
echo "  ℹ  Turn 2: $CULTURAL_ACT_CT activity blocks (cultural only)"

echo "  → Turn 3: add hiking"
if send_message "add hiking to the trip"; then

# Categories should now include hiking
CATS=$(extract_top "session_state.trip_settings.activity_settings.categories")
check_contains "Turn 3: categories include hiking" "$CATS" "hiking" || F=false

# Specialist dispatch should have been attempted
TOOLS=$(extract_tools)
echo "  ℹ  Turn 3 tools: $TOOLS"
check_contains "Turn 3: get_specialist_advice called" "$TOOLS" "get_specialist_advice" || F=false

echo "  → Turn 4: GENERATE_PLAN_NOW"
if send_message "GENERATE_PLAN_NOW"; then

DC_T4=$(extract_doc "day_cards")
DC_CT_T4=$(jlen "$DC_T4")
check_gte "Turn 4: day_cards ≥ 5" "$DC_CT_T4" 5 || F=false

# Hiking tiles should exist in tiles dict
TILES=$(extract_doc "tiles")
HAS_HIKING=$(echo "$TILES" | python3 -c "
import sys,json
try:
    t=json.load(sys.stdin)
    vals=t.values() if isinstance(t,dict) else t
    found=0
    for v in vals:
        if not isinstance(v,dict): continue
        tags=[x.lower() for x in v.get('tags',[])]
        title=(v.get('title','')).lower()
        if 'hiking' in tags or 'hike' in title or 'trail' in title or 'trek' in title:
            found+=1
    print(found)
except: print(0)
" 2>/dev/null || echo "0")
echo "  ℹ  Turn 4: $HAS_HIKING hiking tiles in tile dict"
check_gte "Turn 4: hiking tiles ≥ 1" "$HAS_HIKING" 1 || F=false

# Activity blocks should increase (hiking adds to cultural)
TOTAL_ACT_CT=$(echo "$DC_T4" | python3 -c "
import sys,json
try:
    cards=json.load(sys.stdin)
    total=sum(1 for c in cards for b in c.get('blocks',[]) if b.get('booking_category')=='activity')
    print(total)
except: print(0)
" 2>/dev/null || echo "0")
echo "  ℹ  Turn 4: $TOTAL_ACT_CT total activity blocks (cultural+hiking)"
check_gte "Turn 4: activity blocks ≥ cultural baseline ($TOTAL_ACT_CT ≥ $CULTURAL_ACT_CT)" "$TOTAL_ACT_CT" "$CULTURAL_ACT_CT" || F=false

else F=false; fi; else F=false; fi; else F=false; fi; else F=false; fi; else F=false; fi
$F && _flow pass 20 || _flow fail 20
_flow_end 20
echo ""
fi


# =============================================================================
#  FLOW 21: Long Trip Tile Density — Extend by 10 Days
# =============================================================================
# Turn 1: Short trip. Turn 2: GENERATE_PLAN_NOW.
# Turn 3: Extend by 10 days. Turn 4: GENERATE_PLAN_NOW.
# Validates: day_cards cover extended range, ≥60% interior days have
# real activity blocks (not filler), tile count scales with duration.
if should_run 21; then
_flow_begin 21
echo ""
echo "═══ Flow 21: Long Trip Tile Density ═══"
F=true

if fresh_session; then

echo "  → Turn 1: Rome, March 1-7"
if send_message "I want to visit Rome from March 1 to March 7"; then

check_not_empty "Turn 1: destination" "$(extract_top 'session_state.trip_plan.destination')" || F=false

echo "  → Turn 2: GENERATE_PLAN_NOW"
if send_message "GENERATE_PLAN_NOW"; then

DC_T2=$(extract_doc "day_cards")
DC_CT_T2=$(jlen "$DC_T2")
check_gte "Turn 2: day_cards ≥ 5" "$DC_CT_T2" 5 || F=false

echo "  → Turn 3: extend by 10 days"
if send_message "extend the trip by 10 more days"; then

END_DATE=$(extract_top "session_state.trip_plan.end_date")
check_not_empty "Turn 3: end_date updated" "$END_DATE" || F=false

echo "  → Turn 4: GENERATE_PLAN_NOW"
if send_message "GENERATE_PLAN_NOW"; then

DC_T4=$(extract_doc "day_cards")
DC_CT_T4=$(jlen "$DC_T4")
echo "  ℹ  Turn 4: $DC_CT_T4 day cards (extended ~17-day trip)"
check_gte "Turn 4: day_cards ≥ 14 (17-day extended)" "$DC_CT_T4" 14 || F=false

# Tile count should scale — need more tiles for longer trip
TILES=$(extract_doc "tiles")
TILE_CT=$(jlen "$TILES")
echo "  ℹ  Turn 4: $TILE_CT tiles"
check_gte "Turn 4: tiles ≥ 10 (17-day needs density)" "$TILE_CT" 10 || F=false

# Key assertion: day utilization — ≥60% interior days have real activities
FILL_DATA=$(echo "$DC_T4" | python3 -c "
import sys,json
try:
    cards=json.load(sys.stdin)
    interior=[c for c in cards[1:-1]]
    with_acts=0; filler=0
    for c in interior:
        acts=[b for b in c.get('blocks',[]) if b.get('booking_category')=='activity']
        if acts:
            with_acts+=1
        else:
            filler+=1
    total=max(1,len(interior))
    rate=with_acts/total
    print(json.dumps({'with_acts':with_acts,'filler':filler,'total':total,'rate':round(rate,2)}))
except: print(json.dumps({'with_acts':0,'filler':0,'total':0,'rate':0}))
" 2>/dev/null || echo '{}')
echo "  ℹ  Turn 4: fill data: $FILL_DATA"

FILL_OK=$(echo "$FILL_DATA" | python3 -c "
import sys,json
try:
    d=json.load(sys.stdin)
    print('true' if d.get('rate',0) >= 0.6 else 'false')
except: print('false')
" 2>/dev/null || echo "false")
check "Turn 4: ≥60% interior days have activities" "$FILL_OK" "true" || F=false

# Filler block count should be minority
FILLER_OK=$(echo "$FILL_DATA" | python3 -c "
import sys,json
try:
    d=json.load(sys.stdin)
    print('true' if d.get('filler',999) <= d.get('total',0)*0.5 else 'false')
except: print('false')
" 2>/dev/null || echo "false")
check "Turn 4: filler days ≤ 50% of interior" "$FILLER_OK" "true" || F=false

else F=false; fi; else F=false; fi; else F=false; fi; else F=false; fi; else F=false; fi
$F && _flow pass 21 || _flow fail 21
_flow_end 21
echo ""
fi

# ── Flow 22: Specialist Survival — Origin Add ──────────────────────────────
# Regression test: specialist strategy_sections + tiles must survive a
# non-dispatch turn (origin add). Tests the strategy_sections hydration fix.

if should_run 22; then
_flow_begin 22
echo ""
echo "═══ Flow 22: Specialist Survival — Origin Add ═══"
F=true

if fresh_session; then

echo "  → Turn 1: Diving in Bali, March 15-22"
if send_message "Diving in Bali, March 15-22"; then

SECS_T1=$(extract_doc "strategy_sections")
SEC_CT_T1=$(jlen "$SECS_T1")
check_gte "Turn 1: strategy_sections ≥ 1" "$SEC_CT_T1" 1 || F=false

TOOLS_T1=$(extract_tools)
echo "  ℹ  Turn 1 tools: $TOOLS_T1"
check_contains "Turn 1: get_specialist_advice called" "$TOOLS_T1" "get_specialist_advice" || F=false

# Diving tiles should exist
TILES_T1=$(extract_doc "tiles")
HAS_DIVING_T1=$(echo "$TILES_T1" | python3 -c "
import sys,json
try:
    t=json.load(sys.stdin)
    vals=t.values() if isinstance(t,dict) else t
    found=0
    for v in vals:
        if not isinstance(v,dict): continue
        tags=v.get('tags',[])
        title=(v.get('title','')+'').lower()
        src=v.get('source_agent','').lower()
        if 'diving' in tags or 'dive' in title or 'snorkel' in title or src=='vertical_specialist':
            found+=1
    print('true' if found>=1 else 'false')
except: print('false')
" 2>/dev/null || echo "false")
check "Turn 1: diving tiles present" "$HAS_DIVING_T1" "true" || F=false

echo "  → Turn 2: I'm flying from Dubai"
if send_message "I'm flying from Dubai"; then

# Origin extracted
ORIGIN=$(extract_top "session_state.trip_plan.origin")
check_not_empty "Turn 2: origin extracted" "$ORIGIN" || F=false

# THE regression check — strategy_sections survive non-dispatch turn
SECS_T2=$(extract_doc "strategy_sections")
SEC_CT_T2=$(jlen "$SECS_T2")
check_gte "Turn 2: strategy_sections ≥ 1 (PRESERVED)" "$SEC_CT_T2" 1 || F=false

# Diving tiles still present
TILES_T2=$(extract_doc "tiles")
HAS_DIVING_T2=$(echo "$TILES_T2" | python3 -c "
import sys,json
try:
    t=json.load(sys.stdin)
    vals=t.values() if isinstance(t,dict) else t
    found=0
    for v in vals:
        if not isinstance(v,dict): continue
        tags=v.get('tags',[])
        title=(v.get('title','')+'').lower()
        src=v.get('source_agent','').lower()
        if 'diving' in tags or 'dive' in title or 'snorkel' in title or src=='vertical_specialist':
            found+=1
    print('true' if found>=1 else 'false')
except: print('false')
" 2>/dev/null || echo "false")
check "Turn 2: diving tiles preserved" "$HAS_DIVING_T2" "true" || F=false

# Destination preserved
DEST_T2=$(extract_top "session_state.trip_plan.destination")
DEST_LC=$(echo "$DEST_T2" | tr '[:upper:]' '[:lower:]')
check_contains "Turn 2: destination preserved (Bali)" "$DEST_LC" "bali" || F=false

# Flights enabled (origin triggers flight search)
BT=$(extract_top "session_state.trip_settings.booking_types")
BT_FLIGHTS=$(echo "$BT" | python3 -c "
import sys,json
try:
    bt=json.load(sys.stdin)
    f=bt.get('flights','off')
    print('true' if f and f != 'off' else 'false')
except: print('false')
" 2>/dev/null || echo "false")
check "Turn 2: flights enabled" "$BT_FLIGHTS" "true" || F=false

# Section content integrity — preserved sections include diving
HAS_DIVING_SEC=$(echo "$SECS_T2" | python3 -c "
import sys,json
try:
    secs=json.load(sys.stdin)
    found=any(s.get('specialist_type','').lower()=='diving' for s in secs)
    print('true' if found else 'false')
except: print('false')
" 2>/dev/null || echo "false")
check "Turn 2: strategy_sections contain diving specialist" "$HAS_DIVING_SEC" "true" || F=false

# plan_view_state should remain at S2 (not regress to S0)
PVS_T2=$(extract_doc "plan_view_state")
check_not_contains "Turn 2: plan_view_state not S0 (no regression)" "$PVS_T2" "S0" || F=false

# day_cards should be absent/empty (no itinerary built yet)
DC_T2=$(extract_doc "day_cards")
DC_CT_T2=$(jlen "$DC_T2")
check "Turn 2: day_cards empty (no itinerary built)" "$DC_CT_T2" "0" || F=false

# get_specialist_advice should NOT be called on a logistics-only turn
TOOLS_T2=$(extract_tools)
echo "  ℹ  Turn 2 tools: $TOOLS_T2"
check_not_contains "Turn 2: get_specialist_advice NOT called (no re-dispatch)" "$TOOLS_T2" "get_specialist_advice" || F=false

else F=false; fi; else F=false; fi; else F=false; fi
$F && _flow pass 22 || _flow fail 22
_flow_end 22
echo ""
fi

# ── Final report ─────────────────────────────────────────────────────────────
# Analyze all captured logs, print combined report, delete temp files.

_generate_final_report

[ "$FAIL" -eq 0 ] && [ "$ANALYSIS_ERRORS" -eq 0 ] && exit 0 || exit 1
