Run both curl test suites against the local backend and produce a backend issue report.

The test suite captures backend uvicorn trace logs, test console output, and SSE response data per flow. A regex analyzer runs first for deterministic checks, then LLM agents review the raw traces for semantic issues the regex can't catch.

## Flow

1. **Run all tests** — backend trace + console + SSE saved to `backend/tests/results/`
2. **Regex analyzer** — `analyze_flow_logs.py` scans for deterministic issues (tracebacks, step ordering, etc.)
3. **LLM agent review** — backend-specialist reviews backend traces, frontend-specialist reviews console + SSE
4. **Combined report** — merge regex + LLM findings into a single structured report

## Run Both Suites Sequentially

Rate limits are auto-disabled. The script kills any existing server on :8000 and starts its own with `DEBUG=full`.

```bash
echo "=== BASIC SUITE ===" && bash backend/tests/run_curl_flows.sh 2>&1; echo ""
echo "=== EXTENDED SUITE ===" && bash backend/tests/run_curl_flows_extended.sh 2>&1
```

## Parse Results and Produce Report

After both suites complete:

### Step 1: Read regex analyzer results

Read `backend/tests/results/summary_report.txt` for the per-flow breakdown.

### Step 2: Delegate LLM agent review (run in parallel)

Launch both agents concurrently. Each agent is read-only — no file modifications.

**Backend agent** — reviews ALL per-flow backend traces:

```
Read backend/tests/results/summary_report.txt for context on what the regex analyzer found.

Then read EVERY flow's backend trace: backend/tests/results/flow_N_backend.log (N=1..13).

For each flow, analyze the FULL trace for issues the regex can't catch. You understand
the coordinator architecture (classify → plan_turn → execute steps → build_envelope).
Look for:

- Tile coverage adequacy: Does `Tile scaling: trip=Nd, free=Nd, tiles/cat=N` make sense?
  Are there enough tiles to fill free days? (tiles_per_cat should be ≥ free_days × apd)
- Wasted LLM calls: Did a specialist or experience generator run but produce no useful output?
- Cache inefficiency: Same data fetched twice with different cache keys? Date-keyed caches
  causing misses when dates change but results would be identical?
- Enrichment gaps: `Enriched N/M` where N < M means some tiles lack real data
- Image quality: Unsplash placeholder fallbacks mean tiles show generic photos instead of
  destination-specific imagery. Check if GP enrichment photos should have been used instead.
- Constraint violations: Did the itinerary builder respect all constraints? Any conflicts?
- Step sequencing: Did steps execute in the right order? Any redundant steps?
- Error recovery: Did errors cascade or get properly contained?
- Cost waste: Unnecessary API calls, duplicate external requests, LLM retries that could
  have been avoided
- Local expert truncation: Phase B parse errors from Gemini output exceeding token limits
- Specialist dispatch correctness: Right specialists for the categories? Tier 1 vs Tier 2?
- State consistency: Did the TripPlan state stay consistent across turns?

Output a structured list of findings per flow:
  Flow N: [issue title] — [what happened, quoting relevant log lines] — [likely root cause file]
Skip flows with no issues. Group by severity (errors first, then warnings).
```

**Frontend agent** — reviews ALL per-flow console + SSE logs:

```
Read backend/tests/results/summary_report.txt for context on what the regex analyzer found.

Then read EVERY flow's console log (backend/tests/results/flow_N_console.log) and SSE log
(backend/tests/results/flow_N_sse.log) for N=1..13.

For each flow, analyze the test assertions AND the SSE payloads for frontend-relevant issues.
You understand the UX architecture (plan_view_state transitions, strategy sections, tile
rendering, day cards, suggestion chips).
Look for:

- SSE payload structure: Are the partial/complete payloads well-formed? Do they contain
  all fields the frontend needs (plan_view_state, strategy_sections, tiles, day_cards,
  suggested_responses, trip_settings)?
- State transition correctness: Does plan_view_state progress correctly (S0→S1→S2→S3)?
  Are there unexpected regressions?
- Tile data completeness: Do tiles have required fields (title, description, coordinates,
  photo_url, price)? Missing fields cause rendering gaps.
- Day card structure: Are day_cards properly ordered? Do they cover the full trip duration?
  Are activity blocks assigned to days correctly?
- Suggestion chips: Are suggested_responses relevant to the current state? Too many/few?
- View state consistency: Would the SSE payloads cause the frontend to render correctly?
  E.g., does a destination change clear stale tiles? Does a date extension produce enough
  day cards?
- Additive vs structural changes: Based on the SSE data, would the frontend EXPAND gate
  treat this as additive or structural? Is that correct for the change type?
- Missing data: Any null/empty fields that should have values?
- Duplicate events: Same data sent multiple times in the SSE stream?

Output a structured list of findings per flow:
  Flow N: [issue title] — [what happened, quoting relevant data] — [likely root cause]
Skip flows with no issues. Group by severity (errors first, then warnings).
```

### Step 3: Combine into final report

Merge regex analyzer results + backend agent findings + frontend agent findings:

```
## Curl E2E Test Report

### Test Results
| Flow | Description | Result | Failures |
|------|-------------|--------|----------|
| 1    | Greeting (zero tools) | pass/fail | ... |
| ...  | ... | ... | ... |

### Regex Analyzer
- Total flows: N passed / N total
- Checks: N passed, N failed, N skipped
- Analysis: N errors, N warnings
- [List any regex-detected issues]

### Backend Trace Review (LLM)
[Backend agent findings — grouped by severity, with file references]

### Frontend SSE/Console Review (LLM)
[Frontend agent findings — grouped by severity, with file references]

### Combined Issue List

Priority-ordered list merging all three sources. For each issue:
1. **[Flow N — Issue Title]** (source: regex/backend-agent/frontend-agent)
   - What happened: [description with quoted log lines]
   - Root cause: [specific file and function]
   - Severity: error/warning/info

If all clean: "No issues found — all checks green."
```

## Rules

- Run both suites regardless of failures — do not abort on first failure.
- Flow 12 skips are expected when `USE_GOOGLE_PLACES_PROVIDER` is not set — mark as skip not fail.
- Do NOT modify any source files. This command is read-only.
- Do NOT retry failed checks — report them as-is.
- The backend and frontend agents MUST be launched in parallel (single message, two Agent tool calls).
- Agent findings supplement the regex analyzer — don't duplicate what regex already found.
- The "Combined Issue List" must reference specific files/functions, not vague descriptions.
- The summary report at `backend/tests/results/summary_report.txt` contains the regex analysis.
- Per-flow raw logs in `backend/tests/results/`: `flow_N_backend.log`, `flow_N_console.log`, `flow_N_sse.log`.
