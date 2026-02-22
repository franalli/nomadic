Run both curl test suites against the local backend and produce a backend issue report.

## Prerequisites Check

Before running, verify the backend is up:

```bash
curl -s http://localhost:8000/health | python3 -c "import sys,json; d=json.load(sys.stdin); print('Backend UP:', d.get('status'))" 2>/dev/null || echo "ERROR: Backend not running — start it with: cd backend && python start.py --prod"
```

If the backend is not running, stop and tell the user to start it first.

## Run Both Suites Sequentially

Run the suites one after another (they share the session rate limit budget):

```bash
echo "=== BASIC SUITE ===" && bash backend/tests/run_curl_flows.sh 2>&1 | tee /tmp/curl_flows_basic.txt; echo ""
echo "=== EXTENDED SUITE ===" && bash backend/tests/run_curl_flows_extended.sh 2>&1 | tee /tmp/curl_flows_extended.txt
```

If you run suites repeatedly in the same hour, set a higher session budget in `backend/.env`:

```bash
MAX_SESSIONS_PER_IP_HOUR=100
```

## Parse Results and Produce Report

After both suites complete, read `/tmp/curl_flows_basic.txt` and `/tmp/curl_flows_extended.txt` and produce a structured report:

```
## Curl E2E Test Report

### Basic Suite (Flows 1–6)
| Flow | Description | Result | Failures |
|------|-------------|--------|----------|
| 1    | Diving in Bali (Tier 1) | ✅/❌ | ... |
| 2    | Yoga + Cooking (Tier 2) | ✅/❌ | ... |
| 3    | Mixed diving + yoga     | ✅/❌ | ... |
| 4    | Origin detection (2-turn) | ✅/❌ | ... |
| 5    | Settings change mid-flow | ✅/❌ | ... |
| 6    | Bare destination ("Bali") | ✅/❌ | ... |

### Extended Suite (Flows 7–12)
| Flow | Description | Result | Failures |
|------|-------------|--------|----------|
| 7    | Google Places cascade    | ✅/❌/⏭ | ... |
| 8    | Input gate rejection     | ✅/❌ | ... |
| 9    | Inline itinerary S3      | ✅/❌ | ... |
| 10   | Cache survival (L2)      | ✅/❌ | ... |
| 11   | Constraint violation     | ✅/❌ | ... |
| 12   | Constraint resolution    | ✅/❌ | ... |

### Summary
- Total passed: N
- Total failed: N
- Skipped: N

### Issues to Fix in Backend

For each ✗ check, list:
1. **[Flow N — Check name]**: What failed, expected vs actual value.
   - Likely cause: (what backend code is probably responsible)
   - File to investigate: (e.g., `backend/app/planner/nodes/constraint_guard.py`)

If all checks pass: "No issues found — all checks green."
```

## Teardown

After both suites complete (regardless of results), kill the backend:

```bash
lsof -i :8000 -t 2>/dev/null | xargs kill 2>/dev/null || true
echo "Backend stopped."
```

## Rules

- Run both suites regardless of failures — do not abort on first failure.
- Flow 7 skips are expected when `USE_GOOGLE_PLACES_PROVIDER` is not set — mark as ⏭ not ❌.
- Do NOT modify any source files. This command is read-only.
- Do NOT retry failed checks — report them as-is.
- The "Issues to Fix" section must reference specific backend files/functions, not vague descriptions.
