Run the full 28-flow curl suite against the local backend and produce a detailed failure report.

The test suite captures backend uvicorn trace logs, test console output, and SSE response data per flow. A regex analyzer runs first for deterministic checks, then LLM agents review the raw traces for semantic issues the regex can't catch.

## Flow

1. **Run all tests** — backend trace + console + SSE saved to `backend/tests/results/`
2. **Regex analyzer** — `analyze_flow_logs.py` scans for deterministic issues (tracebacks, step ordering, etc.)
3. **LLM agent review** — backend-specialist reviews backend traces, frontend-specialist reviews console + SSE
4. **Combined report** — merge regex + LLM findings into a single structured report

## Run Full Suite

Rate limits are auto-disabled. The script kills any existing server on :8000 and starts its own with `DEBUG=full`.

```bash
bash backend/tests/run_curl_flows.sh 2>&1
```

## Parse Results and Produce Report

After the suite completes:

### Step 1: Read regex analyzer results

Read `backend/tests/results/summary_report.txt` for the per-flow breakdown across flows `1..28`.

### Step 2: Build the per-flow result table

For each flow `N` in `1..28`, read:

- `backend/tests/results/flow_N_console.log`
- `backend/tests/results/flow_N_backend.log`
- `backend/tests/results/flow_N_sse.log`

Use `flow_N_console.log` as the source of truth for the suite result:

- `══ Flow N PASS ══` → `pass`
- `══ Flow N FAIL ══` → `fail`

Use `⏭ ... SKIPPED (...)` lines as per-check skip notes, not as the overall flow result.
If a conditional flow logs both `SKIPPED (...)` and `══ Flow N PASS ══`, record the flow as `pass`
and include the skip reason in the `Failures` or notes column.

Use `summary_report.txt` as the source of truth for regex analyzer issues and warnings.

### Step 3: Identify flows that need detailed review

Treat a flow as requiring detailed review if any of the following are true:

- The per-flow console log marked the flow as `FAIL`
- The regex analyzer marked the flow with `RESULT: ISSUES FOUND`
- The regex analyzer marked the flow with `RESULT: WARNINGS`
- The flow was conditionally skipped and the skip reason matters for the current audit
- Any raw log is missing, empty, or obviously truncated

If the summary report is missing or malformed, fall back to reviewing all flows `1..28`.

### Step 4: Delegate LLM agent review (run in parallel)

Launch both agents concurrently. Each agent is read-only — no file modifications.

**Backend agent** — reviews the backend traces for every flagged flow:

```
Read backend/tests/results/summary_report.txt for context on what the regex analyzer found.
Read each flagged flow's `flow_N_console.log` first so you know the exact failing assertion or skip reason.

First, identify the flagged flows from the per-flow console logs plus the summary report.

Then read each flagged flow's backend trace:
  backend/tests/results/flow_N_backend.log
for every flagged N in 1..28.

If the summary report is incomplete, review all backend traces for N=1..28.

For each reviewed flow, analyze the FULL trace for issues the regex can't catch. You understand
the agent-loop architecture (create_agent tool loop → model-selected tools → post-loop reconcile → _build_envelope).
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
- Failure mechanics: what exact step, turn, or contract broke and whether the failure
  started in extraction, specialist dispatch, tile search, local intel, build, or response

Output a structured list of findings per flow:
  Flow N: [issue title] — [what happened, quoting relevant log lines] — [likely root cause file/function] — [recommended next test]
Skip flows with no issues. Group by severity (errors first, then warnings).
```

**Frontend agent** — reviews the console + SSE logs for every flagged flow:

```
Read backend/tests/results/summary_report.txt for context on what the regex analyzer found.
Read each flagged flow's `flow_N_console.log` first so you know the exact failing assertion or skip reason.

First, identify the flagged flows from the per-flow console logs plus the summary report.

Then read each flagged flow's console log and SSE log:
  backend/tests/results/flow_N_console.log
  backend/tests/results/flow_N_sse.log
for every flagged N in 1..28.

If the summary report is incomplete, review all console + SSE logs for N=1..28.

For each reviewed flow, analyze the test assertions AND the SSE payloads for frontend-relevant issues.
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
- Failure mechanics: which payload, event type, or assertion mismatch would actually break
  the frontend, and whether the bad state appears in `partial`, `complete`, or test output

Output a structured list of findings per flow:
  Flow N: [issue title] — [what happened, quoting relevant data] — [likely root cause file/function] — [recommended next test]
Skip flows with no issues. Group by severity (errors first, then warnings).
```

### Step 5: Combine into final report

Merge regex analyzer results + backend agent findings + frontend agent findings:

```
## Curl E2E Test Report

### Test Results
| Flow | Description | Result | Failures |
|------|-------------|--------|----------|
| 1    | Greeting (zero tools) | pass/fail | ... |
| ...  | ... | ... | ... |

Build this table from the per-flow console logs, not from the totals block in `summary_report.txt`.

### Regex Analyzer
- Total flows: N passed / 28 total
- Checks: N passed, N failed, N skipped
- Analysis: N errors, N warnings
- [List any regex-detected issues]

### Backend Trace Review (LLM)
[Backend agent findings — grouped by severity, with file references]

### Frontend SSE/Console Review (LLM)
[Frontend agent findings — grouped by severity, with file references]

### Detailed Failure Report

Priority-ordered list merging all three sources. For each issue:
1. **[Flow N — Issue Title]** (source: regex/backend-agent/frontend-agent)
   - What happened: [description with quoted log lines]
   - Root cause: [specific file and function]
   - Severity: error/warning/info
   - Fix direction: [most likely corrective action]
   - Next test: [specific follow-up test or rerun target]

If all clean: "No issues found — all checks green."
```

## Rules

- Run the single full suite even if individual flows fail — do not abort on first failure.
- Flow 12 skips are expected when `USE_GOOGLE_PLACES_PROVIDER` is not set — mark as skip not fail.
- Flow 27 skips are expected when `VIATOR_ENABLED` is not `true` or `VIATOR_API_KEY` is not set — mark as skip not fail.
- Do NOT modify any source files. This command is read-only.
- Do NOT retry failed checks — report them as-is.
- The backend and frontend agents MUST be launched in parallel (single message, two Agent tool calls).
- Agent findings supplement the regex analyzer — don't duplicate what regex already found.
- The detailed failure report must reference specific files/functions, not vague descriptions.
- The summary report at `backend/tests/results/summary_report.txt` contains the regex analysis.
- Per-flow raw logs in `backend/tests/results/`: `flow_N_backend.log`, `flow_N_console.log`, `flow_N_sse.log`.
