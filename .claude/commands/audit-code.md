Use `backend/.venv` for all Python execution (e.g. `backend/.venv/bin/python`, `backend/.venv/bin/ruff`).

Perform a comprehensive code health audit across the entire frontend and backend codebase.
**Full repo scan. Not diff-driven, not documentation-driven.** Scan ALL source code unconditionally regardless of what changed recently.
**Report only. DO NOT modify, fix, or delete anything.** This is a read-only scan that produces a findings report.

---

## Phase 1: Backend Python

### 1A: Unused Imports

```bash
cd backend && ruff check . --select F401 2>&1
```

Report all unused imports found.

### 1B: Unused Functions and Variables

```bash
cd backend && ruff check . --select F841 2>&1
```

Then manually scan for unused functions. For each Python file under `backend/app/planner/` and `backend/app/services/`:

- Grep for each function name across the entire backend to find callers
- If a function has ZERO callers and is NOT a LangGraph node function, NOT an endpoint handler, NOT an `__init__.py` export, and NOT a Pydantic validator — it's dead code. Report it.
- Do NOT flag: node functions registered in `plan_graph.py`, FastAPI route handlers, Alembic migration functions, pytest fixtures, `__all__` exports.

```bash
# Find function definitions
grep -rn "^def \|^async def " backend/app/planner/ backend/app/services/ --include="*.py" | grep -v __pycache__ | grep -v test_

# For each function, check if it's called anywhere
# Example: grep -rn "function_name" backend/app/ --include="*.py" | grep -v "def function_name"
```

### 1C: Sync Blocking in Async Functions

Scan for synchronous blocking calls inside `async def` functions:

```bash
# time.sleep inside async
grep -rn "time\.sleep" backend/app/ --include="*.py" | grep -v __pycache__

# Synchronous requests inside async
grep -rn "requests\.get\|requests\.post\|requests\.put" backend/app/ --include="*.py" | grep -v __pycache__

# Synchronous DB sessions in async functions — check for get_db (sync) vs get_async_db
grep -rn "Depends(get_db)" backend/app/main.py | head -20
# Cross-reference: which of those endpoints are `async def`?
```

Report each finding with file path and line number.

### 1D: Thread Safety & Race Conditions

This is a comprehensive thread safety audit. FastAPI runs handlers concurrently (async + thread pool), so any shared mutable state is a potential race condition.

#### 1D-1: Unprotected Shared Mutable State

```bash
# Module-level mutable state (dicts, lists, sets) that could be accessed by concurrent requests
grep -rn "^[A-Z_]*: dict\|^[A-Z_]*: list\|^[A-Z_]* = {}\|^[A-Z_]* = \[\]" backend/app/ --include="*.py" | grep -v __pycache__ | grep -v test_

# Module-level mutable state with lowercase names (common pattern for caches, registries)
grep -rn "^_[a-z_]* = {}\|^_[a-z_]* = \[\]\|^_[a-z_]*: dict\|^_[a-z_]*: list" backend/app/ --include="*.py" | grep -v __pycache__ | grep -v test_
```

For each shared mutable state, report:

- If it's a cache with concurrent access and missing a lock → **Critical**
- If it's mutated during request handling without a lock → **Critical**
- Skip module-level config that's only written at import time → OK

#### 1D-2: Lock Inventory

```bash
# Catalog all locks in the codebase
grep -rn "asyncio\.Lock\|threading\.Lock\|threading\.RLock\|RLock()" backend/app/ --include="*.py" | grep -v __pycache__ | grep -v test_

# For each lock, verify it's actually used (acquired with `with` or `async with`)
grep -rn "with.*_lock\|async with.*_lock" backend/app/ --include="*.py" | grep -v __pycache__ | grep -v test_
```

Report:

- Locks declared but never acquired → **Medium** (dead code, or state is unprotected)
- Shared state modified without its designated lock → **Critical**

#### 1D-3: Lock Type Mismatch

```bash
# threading locks (RLock, Lock) — safe for sync code and thread pool executors
grep -rn "threading\.Lock\|threading\.RLock\|from threading import" backend/app/ --include="*.py" | grep -v __pycache__ | grep -v test_

# asyncio locks — safe for async code only
grep -rn "asyncio\.Lock" backend/app/ --include="*.py" | grep -v __pycache__ | grep -v test_
```

Cross-reference:

- `threading.Lock` used inside an `async def` function → **High** (blocks the event loop if contended; should use `asyncio.Lock` or `run_in_executor`)
- `asyncio.Lock` used inside a sync `def` function → **Critical** (cannot `await` in sync context; lock is never actually acquired)
- `asyncio.Lock` used across different event loops → **Critical** (lock is loop-bound)
- `threading.RLock` protecting a TTLCache accessed from both sync and async code → OK (this is the correct pattern for FastAPI's thread pool)

#### 1D-4: In-flight Deduplication Safety

```bash
# Check for in-flight / deduplication locks (prevent duplicate concurrent work)
grep -rn "_inflight\|_pending\|_in_progress\|dedup" backend/app/ --include="*.py" | grep -v __pycache__ | grep -v test_
```

For each in-flight tracking mechanism:

- Verify it has a lock protecting the check-and-set operation → if not, **Critical** (TOCTOU race)
- Verify it cleans up on failure/exception → if not, **High** (leaked entries block future requests)
- Verify the lock scope is narrow (don't hold lock during I/O) → if held during LLM calls, **High** (serializes all concurrent requests)

#### 1D-5: Singleton / Global State Initialization

```bash
# Check for lazy initialization patterns (first-call init)
grep -rn "_initialized\|_instance\|_singleton\|if.*is None.*=" backend/app/ --include="*.py" | grep -v __pycache__ | grep -v test_

# Check if initialization is protected by a lock
grep -rn "def.*init\|def.*setup\|def.*register" backend/app/ --include="*.py" | grep -v __pycache__ | grep -v test_ | grep -v __init__
```

Report:

- Lazy init without lock → **High** (double initialization under concurrent startup)
- Module-level `_initialized` flag checked without lock → **Medium** (usually benign if idempotent, but flag it)

#### 1D-6: TTLCache and lru_cache Thread Safety

```bash
# TTLCache instances — must be wrapped with a lock (cachetools is NOT thread-safe)
grep -rn "TTLCache\|LRUCache" backend/app/ --include="*.py" | grep -v __pycache__ | grep -v test_ | grep -v cache_core

# lru_cache / functools.cache — thread-safe for reads but NOT for the underlying function call
grep -rn "lru_cache\|@cache\|functools\.cache" backend/app/ --include="*.py" | grep -v __pycache__ | grep -v test_
```

Report:

- `TTLCache` accessed without a surrounding lock → **Critical** (cachetools explicitly documents this is unsafe)
- `TTLCache` used directly instead of `MemoryCache` wrapper from `cache_core.py` → **High** (bypasses built-in thread safety)
- `lru_cache` on a function with side effects or mutable return values → **Medium**
- `lru_cache` on an `async def` → **Critical** (caches the coroutine object, not the result)

### 1E: Duplicate Code

```bash
# 1. Find functions with identical or near-identical signatures
grep -rn "^def \|^async def " backend/app/planner/ backend/app/services/ --include="*.py" | grep -v __pycache__ | awk -F'def ' '{print $2}' | sort | uniq -d

# 2. SSoT violations: logic that should only live in one place
# Constraint checking logic (should only be in constraint_guard.py)
grep -rn "constraint\|violation\|safety_check" backend/app/planner/nodes/ --include="*.py" | grep -v __pycache__ | grep -v constraint_guard | grep -v "import.*constraint"

# Specialist keyword lists (should only be in specialist_registry.py)
grep -rn "diving\|hiking\|skiing\|cycling\|surfing\|sailing" backend/app/planner/nodes/ --include="*.py" | grep -v __pycache__ | grep -v specialist_registry | grep -v "import.*registry" | grep -v "# " | head -20

# Session state serialization (should only be in state_serde.py)
grep -rn "serialize\|deserialize\|model_dump\|model_validate" backend/app/planner/nodes/ --include="*.py" | grep -v __pycache__ | grep -v state_serde | grep -v "import.*serde" | head -20

# 3. Duplicate Pydantic model fields across schema files
grep -rn "class.*BaseModel\|class.*Model" backend/app/schemas.py backend/app/planner/state/graph_state.py backend/app/planner/nodes/specialist_schemas.py | grep -v __pycache__

# 4. Duplicate error handling — look for copy-pasted try/except patterns
grep -rn "except Exception as e:" backend/app/planner/ backend/app/services/ --include="*.py" | grep -v __pycache__ | grep -v test_

# 5. Duplicate utility functions — functions with same name in different files
grep -rn "^def \|^async def " backend/app/ --include="*.py" | grep -v __pycache__ | grep -v test_ | grep -v migrations | awk -F'def ' '{print $2}' | awk -F'(' '{print $1}' | sort | uniq -d
```

For SSoT violations, check if logic is duplicated or if it properly delegates to the canonical module:

- Multiple implementations of constraint checking logic (should only be in `constraint_guard.py`)
- Duplicate specialist keyword lists (should only be in `specialist_registry.py`)
- Multiple session state serialization paths (should only be in `state_serde.py`)
- Duplicate cache key construction (should use shared helpers from `hashing.py`)

For duplicate Pydantic models, check if the same field names/types appear in multiple schema classes that should share a base.

Report any duplicates found with locations. Severity:

- SSoT violations → **High**
- Duplicate function names across files → **Medium**
- Similar error handling blocks → **Low** (flag only if 3+ identical patterns)

### 1F: Security — Code Vulnerabilities

Scan for common code-level security vulnerabilities:

```bash
# 1. Hardcoded secrets, API keys, tokens in source files (not .env)
grep -rn "OPENAI_KEY\|api_key\|secret_key\|password\|token" backend/app/ --include="*.py" | grep -v __pycache__ | grep -v "os\.environ\|os\.getenv\|config\.\|\.env\|settings\." | grep -v "# \|def \|param\|argument\|type\|Optional\|str\|None"

# 2. Raw SQL strings (should use SQLAlchemy ORM/text() with bound params)
grep -rn "\.execute(f\"\|\.execute(f'\|\.execute(\"%s\|cursor\.\|raw_connection" backend/app/ --include="*.py" | grep -v __pycache__

# 3. Unsafe eval/exec/subprocess usage
grep -rn "eval(\|exec(\|subprocess\.\|os\.system(\|os\.popen(" backend/app/ --include="*.py" | grep -v __pycache__

# 4. Run detect-secrets scan against baseline
cd backend && detect-secrets scan --baseline ../.secrets.baseline 2>&1 || echo "detect-secrets not installed, skipping"

# 5. User input interpolated directly into LLM prompts (prompt injection)
grep -rn "req\.message\|request\.message\|f\".*{message\|f'.*{message" backend/app/planner/nodes/ --include="*.py" | grep -v __pycache__ | grep -v test_ | head -20
```

For each finding, assess:

- Hardcoded secrets → **Critical** if actual values, **Low** if just variable names referencing env
- Raw SQL → **Critical** if user input can reach it, **High** otherwise
- eval/exec/subprocess → **Critical** unless input is fully controlled
- User message interpolated directly into system prompt without sanitization → **High** (prompt injection: user can override system instructions)
- Skip: test fixtures, mock data, comments explaining security patterns

### 1F2: Abuse & Spend Protection Audit

This codebase makes paid calls to OpenAI, Google Places, and Amadeus. A single unprotected endpoint can drain API budgets in minutes. Audit every layer of abuse defence.

#### 1F2-1: Rate Limit Coverage — Every Endpoint

```bash
# List all route decorators in main.py with their line numbers
grep -n "@app\.\(get\|post\|patch\|delete\|put\)" backend/app/main.py

# List all @limiter.limit decorators
grep -n "@limiter\.limit" backend/app/main.py

# Find @app.* route decorators NOT immediately preceded by @limiter.limit
# (check 1-2 lines above each @app. decorator for @limiter.limit)
awk '/^@limiter\.limit/{found=1; next} /^@app\.(get|post|patch|delete|put)/{if(!found) print NR": MISSING limiter: "$0; found=0}' backend/app/main.py

# Also check analytics_routes.py
grep -n "@limiter\.limit\|@router\.\(get\|post\|patch\|delete\)" backend/app/analytics_routes.py 2>/dev/null | head -20
```

Verify rate limits on high-cost endpoints are tight enough:
- `/api/graph_plan/stream` — expected `≤10/minute + ≤30/hour` (runs full LLM pipeline)
- `/api/expand-itinerary` — expected `≤20/minute` (runs itinerary builder)
- `/api/document/fill-day` — expected `≤10/minute` (runs experience generator LLM)
- `/api/activities/browse` — expected `≤10/minute` (runs Google Places)
- `/api/tiles/refresh` — expected `≤10/minute` (runs Google Places + Amadeus)
- `/api/specialist/{section_id}/enrichment` — expected `≤30/minute` (runs specialist LLM)

Report:
- Any endpoint without `@limiter.limit` → **Critical** if it touches a paid API, **High** otherwise
- Rate limit looser than the targets above → **High**
- `rate_limit_enabled = False` in config with no env-var guard → **Critical** if someone sets it False in production

#### 1F2-2: Spend Guard Scope Coverage

`spend_guard.py` enforces per-session and global daily USD caps via `_session_id_ctx` (a `ContextVar`). If `spend_guard_scope(session_id)` is not called before a paid API call, `_session_id_ctx.get()` returns `None` and `_reserve_or_raise()` silently no-ops. The caps are never enforced for that request.

```bash
# All spend_guard_scope call sites (these are the endpoints with active spend enforcement)
grep -n "spend_guard_scope" backend/app/main.py backend/app/streaming.py | grep -v "import\|def spend_guard"

# The most expensive generator (expand-itinerary) runs generate_ndjson —
# check if spend_guard_scope is called inside it
grep -n "spend_guard_scope" backend/app/streaming.py
# Count: if only 2 occurrences (graph_plan/stream + specialist enrichment),
# then generate_ndjson (expand-itinerary) has NO spend_guard_scope → Critical

# Confirm reserve_* is called at the factory/provider level (guards all paid calls)
grep -rn "reserve_llm_spend_or_raise\|reserve_places_spend_or_raise\|reserve_amadeus_spend_or_raise" \
  backend/app/ --include="*.py" | grep -v __pycache__ | grep -v "def reserve\|test_"
# Expected: llm_factory.py (covers all LLM), google_places_provider.py (covers Places),
# amadeus_client.py (covers Amadeus). Any paid API path bypassing these three = unguarded.

# Confirm spend guard silently skips when session_id is None
grep -n "if not sid\|if sid is None\|not sid" backend/app/services/spend_guard.py
```

Report:
- `generate_ndjson` (expand-itinerary endpoint) missing `spend_guard_scope` → **Critical** (itinerary builder makes multiple LLM calls per request; 20/minute rate limit × no session cap = unlimited cost)
- Any endpoint path calling paid APIs without an enclosing `spend_guard_scope` → **Critical**
- `spend_guard_scope(None)` silently no-ops → **High** (requests that somehow reach paid endpoints without a session_id are uncapped; verify session middleware always runs first)
- Any paid API invocation that bypasses `get_llm_by_model()` / `google_places_provider.py` / `amadeus_client.py` → **Critical** (no reserve call at all)

#### 1F2-3: Spend Guard Configuration

```bash
# All spend guard settings and their defaults in config.py
grep -n "spend_guard" backend/app/config.py

# Verify caps are non-zero (zero means disabled per _reserve_or_raise logic)
# "if session_cap > 0 and ..." — a cap of 0.0 disables that check
grep -n "spend_guard_session_daily_cap_usd\|spend_guard_global_daily_cap_usd" backend/app/config.py

# Unknown model fallback cost estimate
grep -n "spend_guard_llm_unknown_model_estimated_call_usd" backend/app/config.py
# Default $0.02 — at $2/session cap this allows 100 calls per session before cap triggers

# Admin endpoint that resets spend counters — is it rate-limited and logged?
grep -n "clear_spend_guard\|spend_guard_counters\|spend.*reset" backend/app/main.py | grep -v test_

# Spend guard state is module-level (in-memory) — confirm no persistence
grep -n "_session_spend_usd\|_global_spend_usd\|_spend_day_key" backend/app/services/spend_guard.py | head -10
```

Report:
- `spend_guard_session_daily_cap_usd = 0` → **Critical** (session cap disabled)
- `spend_guard_global_daily_cap_usd = 0` → **Critical** (global cap disabled)
- `SPEND_GUARD_ENABLED` env var can disable all guards → **Critical** (must be verified `true` in prod; there is no hard floor)
- Spend guard is in-memory — server restart resets all daily counters → **High** (attacker who forces a restart resets the day's spend budget; or autoscaling with multiple instances means each instance has its own budget)
- Unknown model estimate ($0.02) very low — if a new model is added to llm_factory without updating `_MODEL_PRICING_PER_1M` in spend_guard, every call is underestimated → **Medium**
- `clear_spend_guard_counters()` admin endpoint not rate-limited or not requiring admin auth → **High**

#### 1F2-4: Input Size & Payload Limits

Even with rate limits, unbounded input fields let each individual request cost far more than estimated.

```bash
# 1. Check message field max_length in GraphPlanRequest
grep -n "class GraphPlanRequest" backend/app/schemas.py -A 20 | head -25
# message: str with no Field(max_length=N) → unbounded

# 2. Check all user-facing string fields across request schemas
grep -rn "class.*Request.*BaseModel" backend/app/schemas.py | head -20
# For each Request model, check if string fields have Field(max_length=...)

# 3. Uvicorn request body size limit
grep -rn "limit_max_uploads\|body_limit\|max_request_body\|--limit-max-requests\|MAX_BODY" backend/ --include="*.py" --include="*.sh" --include="*.toml" 2>/dev/null | grep -v __pycache__
grep -n "uvicorn.run\|reload\|workers\|limit" backend/start.py 2>/dev/null | head -10

# 4. trip_inputs and session_state are untyped dicts — no depth/size limit
grep -n "trip_inputs.*dict\|session_state.*dict" backend/app/schemas.py | head -10
```

Report:
- `GraphPlanRequest.message` with no `max_length` → **High** (50k-char message at 6/min = 300k tokens/min through LLM; cost estimate based on 1200-token prompt assumption is wrong)
- No uvicorn body size limit → **High** (100MB JSON parsed in memory before rate limiter runs; can exhaust RAM)
- `trip_inputs: dict` / `session_state: dict` with no size/depth limit → **Medium** (deeply nested dicts exhaust stack during Pydantic validation)

#### 1F2-5: Session & Auth Hardening

```bash
# 1. Session ID generation — must use cryptographically secure random source
grep -rn "session_id\|generate.*session\|create.*session" backend/app/ --include="*.py" | grep -v __pycache__ | grep -v test_ | grep -i "secret\|uuid\|random\|token" | head -15

# 2. Session cookie attributes
grep -rn "set_cookie\|httponly\|samesite\|secure" backend/app/ --include="*.py" | grep -v __pycache__ | grep -v test_ | head -15

# 3. Rate key is session_id (cookie) → IP fallback — can attacker create unlimited sessions?
grep -n "MAX_SESSIONS_PER_IP_HOUR\|session_throttle\|sessions_per_ip" backend/app/config.py backend/app/main.py 2>/dev/null | head -10
# Without session creation throttle, attacker rotates sessions to get fresh rate limit budgets

# 4. Admin key — timing-safe comparison and no weak default
grep -n "require_admin\|compare_digest\|admin_api_key" backend/app/main.py | head -10
grep -n "admin_api_key" backend/app/config.py | head -5

# 5. CSRF — covers all unsafe methods?
grep -rn "CSRFMiddleware\|safe_methods\|CSRF_EXEMPT\|csrf_skip" backend/app/ --include="*.py" | grep -v __pycache__ | grep -v test_ | head -15
```

Report:
- Session IDs not generated with `secrets.token_urlsafe(32)` or equivalent → **Critical** (guessable sessions allow rate-limit budget theft)
- Session cookie missing `HttpOnly` → **High** (XSS steals session cookie, inherits rate limit identity)
- Session cookie missing `Secure` in prod → **High** (session hijack over HTTP)
- No session creation rate throttle per IP → **High** (attacker creates N sessions = N × rate limit budget; e.g., 100 sessions × 6/min = 600 graph_plan calls/min)
- `admin_api_key` not configured → admin endpoint returns 403 (correct) — verify this is enforced
- CSRF middleware missing or not covering POST endpoints → **High**

#### 1F2-6: SSE / Streaming Hardening

```bash
# 1. SSE connection limits
grep -n "MAX_SSE_PER_SESSION\|MAX_SSE_PER_IP" backend/app/sse_state.py

# 2. SSE slot release in finally block (leak detection)
grep -n "_release_sse_slot\|finally" backend/app/main.py | head -20
# _release_sse_slot must be in a finally block wrapping the SSE generator

# 3. Expand-itinerary mutex release in finally block
grep -n "_release_expand_slot\|_acquire_expand_slot\|finally" backend/app/main.py | head -20

# 4. Generator disconnect handling
grep -n "GeneratorExit\|CancelledError" backend/app/streaming.py | head -10

# 5. LLM call cancellation on client disconnect
# If the client disconnects mid-stream, the LLM ainvoke() call should be cancelled
# Check if there's an asyncio.Task.cancel() or AbortController equivalent wrapping LLM calls
grep -rn "asyncio\.wait_for\|asyncio\.shield\|cancel()\|task\.cancel" backend/app/streaming.py backend/app/planner/ --include="*.py" | grep -v __pycache__ | head -15
```

Report:
- `_release_sse_slot` not in a `finally` block → **Critical** (client disconnect leaves slot permanently occupied; after MAX_SSE_PER_SESSION disconnects the session is permanently blocked)
- `_release_expand_slot` not in a `finally` block → **Critical** (expand-itinerary permanently locked for session after any error)
- No `asyncio.wait_for` or task cancellation wrapping LLM calls → **High** (client disconnects mid-stream but LLM call continues to completion, burning tokens with no one reading the output)
- `GeneratorExit`/`CancelledError` not caught → **High** (cleanup code after `yield` is skipped on disconnect: DB sessions leaked, spend not finalized)
- No streaming timeout (client can hold SSE open indefinitely without reading, keeping LLM alive) → **High**

### 1G: Circular Imports

Check for circular import chains that cause runtime errors:

```bash
# Use ruff to detect import cycles
cd backend && ruff check . --select I 2>&1 | grep -i "circular\|cycle" || echo "No circular import warnings from ruff"

# Manual check: find files that import each other
# For each file in planner/nodes/, check if any of its imports also import it back
grep -rn "^from backend\.app\.\|^from app\.\|^from \.\|^from \.\." backend/app/planner/ backend/app/services/ --include="*.py" | grep -v __pycache__
```

For each pair of files, check if A imports B AND B imports A. Report any circular chains found.

- Skip: `__init__.py` re-exports (these are expected)
- Flag: Any circular chain involving node files or service files

### 1H: Test Coverage Gaps

Cross-reference source modules against test files to find untested code:

```bash
# List all backend source modules (planner nodes, services, tools)
ls backend/app/planner/nodes/*.py backend/app/planner/services/*.py backend/app/services/*.py backend/app/tools/*.py 2>/dev/null | grep -v __init__ | grep -v __pycache__

# List all test files
ls backend/tests/test_*.py 2>/dev/null
```

For each source module, check if a corresponding test file exists. Report:

- Modules with ZERO test coverage (no test file references the module at all)
- Cross-reference by grepping test files for imports of each module
- Do NOT flag: `__init__.py`, config files, migration files, `debug_utils.py`
- Severity: **High** for planner nodes and core services, **Medium** for utilities and tools

#### 1H-1: Test Harness API Drift (Starlette/httpx)

```bash
# Per-request cookies= is deprecated/removed in newer httpx paths used by TestClient.
# Flag direct request calls that still pass cookies= instead of using client cookies helpers.
grep -rn "client\.\(get\|post\|patch\|put\|delete\)(.*cookies=" backend/tests/ --include="*.py" | grep -v __pycache__

# Find existing shared cookie helpers (preferred pattern)
grep -rn "set_client_session_cookies\|request_with_session\|client\.cookies\.set" backend/tests/ --include="*.py" | grep -v __pycache__
```

Report:

- Per-request `cookies=` in TestClient calls → **Medium** (deprecation warnings now; runtime break risk on dependency upgrade)
- Test suites with repeated auth cookie setup and no helper abstraction → **Low** (high churn + easy to reintroduce deprecated usage)
- Do NOT flag plain `cookies` dict literals used as data fixtures (only request call arguments)

### 1I: Debug Print Pollution

Scan for stray `print()` statements left from debugging:

```bash
# print() calls in production code (not tests, not debug_utils)
grep -rn "^\s*print(" backend/app/ --include="*.py" | grep -v __pycache__ | grep -v test_ | grep -v debug_utils
```

Report each finding. Exclude:

- `print()` inside `if __name__ == "__main__"` blocks
- `print()` inside explicitly named debug/logging functions
- Severity: **Low** (cosmetic, but pollutes server logs)

### 1J: Cache Health

The backend has a multi-tier caching system: `cache_core.py` (shared MemoryCache primitive and `l2_upsert`), `router_cache.py` (L1-only), `specialist_cache.py` (L1+L2), `tile_cache.py` (L1+L2), `experience_generator.py` (L1+L2, two `cache_type` partitions: "experience" and "experience_single"). Audit for correctness across all layers.

#### 1J-1: TTL Consistency

```bash
# List all TTL constants per module — compare L1 vs L2 for each domain
grep -rn "L1_TTL_SECONDS\|L2_TTL_HOURS\|L2_TTL_SECONDS\|L1_MAX_SIZE" \
  backend/app/services/specialist_cache.py \
  backend/app/services/tile_cache.py \
  backend/app/services/router_cache.py \
  backend/app/services/experience_generator.py | grep -v __pycache__

# Check that L2_TTL_HOURS is sourced from settings (not hardcoded) in all L1+L2 modules
grep -rn "L2_TTL_HOURS\s*=" backend/app/services/ --include="*.py" | grep -v __pycache__
# Each should reference settings.* — a bare integer literal here is a violation

# Verify L2 TTL is always >= L1 TTL (L1 evicts first, then L2 shouldn't bring stale data back)
# For each module, compute: L2_TTL_HOURS * 3600 >= L1_TTL_SECONDS?
# specialist_cache: L1=3600s (1h), L2=settings.specialist_cache_ttl_hours (default 168h = 604800s) ✓
# tile_cache: L1=86400s (24h), L2=settings.tile_cache_ttl_hours (default 72h = 259200s) ✓
# experience: L1=3600s (1h), L2=settings.experience_cache_ttl_hours (default 72h = 259200s) ✓
# Flag any module where L2_TTL_HOURS * 3600 < L1_TTL_SECONDS
```

Report:

- `L2_TTL_HOURS` set to a hardcoded integer instead of `settings.*` → **High** (can't tune without redeploy; config.py env defaults bypass env vars)
- L2 TTL < L1 TTL for the same domain → **High** (L1 evicts entry, L2 then promotes stale data back on next L1 miss)
- Missing TTL on any `MemoryCache()`/`TTLCache()` instantiation → **Critical**

#### 1J-2: Cache Key Collisions

```bash
# All make_cache_key calls — check namespace prefixes are unique per domain
grep -rn 'make_cache_key(' backend/app/services/ backend/app/planner/ --include="*.py" | grep -v __pycache__

# Expected namespace prefixes per module:
# specialist_cache: "specialist"
# tile_cache: "tile"
# router_cache: "router"
# experience_generator (multi-category): "experience"
# experience_generator (single-category): "experience_single"
# Any duplicate first arg across different domains → collision

# Check that all cache key functions use make_cache_key (not raw string concatenation)
grep -rn "def _.*cache_key" backend/app/services/ backend/app/planner/ --include="*.py" | grep -v __pycache__
# For each, verify it calls make_cache_key internally

# Check for version tokens in all key-building functions
grep -rn '"v1"\|"v2"\|"v3"\|"v4"' backend/app/services/ --include="*.py" | grep -v __pycache__ | grep -v test_

# Check for stable_hash_short usage in cache keys (8-char = 32-bit; ~2% collision at 10k entries)
grep -rn "stable_hash_short" backend/app/services/ backend/app/planner/ --include="*.py" | grep -v __pycache__ | grep -v test_

# Check for make_cache_key calls with optional fields that could be None
# (None becomes "" in make_cache_key — keys with None vs "" in that slot will collide)
grep -rn "make_cache_key(" backend/app/services/ --include="*.py" | grep -v __pycache__ | grep -v test_
# For each call, identify any argument that could be None (check function signature defaults)
```

Report:

- Two cache domains sharing the same namespace prefix as first `make_cache_key` arg → **Critical** (key collision)
- `cache_type="experience"` and `cache_type="experience_single"` are distinct L2 partitions — verify no overlap in key space
- Cache key function not using `make_cache_key` (raw string concat) → **Medium** (can't guarantee separator stability)
- Missing version token (no `"v1"`/`"v2"` component) → **Medium** (no safe invalidation path on format change)
- `stable_hash_short` (8-char hash) in a cache key → **Medium** (32-bit birthday collision risk at scale)
- Optional `None` argument passed to `make_cache_key` without a default (`or "unknown"` guard) → **Medium** (collides with explicit empty-string input)

#### 1J-3: L1/L2 Consistency

```bash
# Check L1 write happens BEFORE L2 write in all set functions (L1 should always be warm first)
grep -rn "_mem.set\|_cache_set" backend/app/services/specialist_cache.py backend/app/services/tile_cache.py backend/app/services/experience_generator.py | grep -v __pycache__
# _mem.set should appear before l2_upsert in each set function body

# Check that l2_upsert is called (not raw pg_insert) in all L2 write paths
grep -rn "pg_insert\|l2_upsert" backend/app/services/ --include="*.py" | grep -v __pycache__ | grep -v cache_core
# Direct pg_insert outside cache_core.py → bypass of shared l2_upsert contract

# Check for rollback consistency in L2 write error handlers
# tile_cache has OperationalError branch WITHOUT rollback — check all error branches
grep -rn "except OperationalError\|except Exception" backend/app/services/tile_cache.py backend/app/services/specialist_cache.py backend/app/services/experience_generator.py | grep -v __pycache__
# Every except block that catches a DB error after an l2_upsert should call db.rollback()

# Check that callers don't commit after l2_upsert (l2_upsert commits internally)
# Any await db.commit() AFTER await l2_upsert(...) in the same function → double commit
grep -rn "l2_upsert\|db.commit" backend/app/services/ --include="*.py" | grep -v __pycache__ | grep -v cache_core

# L2 uses pg_insert (PostgreSQL-specific dialect) — incompatible with SQLite test DBs
grep -rn "pg_insert\|from sqlalchemy.dialects.postgresql" backend/app/services/ --include="*.py" | grep -v __pycache__
# Verify tests that test L2 write paths use PostgreSQL (not SQLite)
grep -rn "sqlite\|:memory:\|test_plan_document" backend/tests/ --include="*.py" | grep -v __pycache__ | head -10
```

For each `set_cached_*` function in L1+L2 caches, verify:

- L1 write (`_mem.set`) appears before the `l2_upsert` call → if reversed, first write to L2 could succeed then L1 write could fail, leaving L2 warm but L1 cold (minor but inconsistent)
- `OperationalError` branch in `tile_cache.set_cached_tiles` has NO `await db.rollback()` — verify if this is intentional or a bug → **High** if DB session is left in a failed state
- Every exception branch that follows a started DB write calls `db.rollback()` → if missing, **High** (session left in aborted state, next use will fail with `InFailedSqlTransaction`)
- `l2_upsert` commits internally — no caller should `await db.commit()` after a successful `l2_upsert` call → if found, **High** (double commit or commit of unrelated pending writes)

#### 1J-4: Cache Invalidation

```bash
# Catalog all L1 clear functions per module
grep -rn "def clear_memory_cache\|def clear_cache\|def clear_experience_cache" backend/app/services/ --include="*.py" | grep -v __pycache__
# Note naming inconsistency: specialist/tile use clear_memory_cache, router uses clear_cache,
# experience uses clear_experience_cache. The admin endpoint must know each module's exact name.

# Catalog all L2 clear functions per module
grep -rn "def clear_db_cache\|async def clear_db_cache\|async def clear_experience_db_cache" backend/app/services/ --include="*.py" | grep -v __pycache__

# Check that clear_experience_db_cache clears BOTH "experience" AND "experience_single" cache types
grep -n "clear_experience_db_cache\|cache_type.*experience" backend/app/services/experience_generator.py | grep -v __pycache__
# If only cache_type == "experience" is deleted, "experience_single" entries survive in L2 → stale fill-day cache

# Check that the admin clear endpoint calls ALL module clear functions (L1 + L2)
grep -rn "clear_memory_cache\|clear_cache\|clear_experience_cache\|clear_db_cache\|clear_experience_db_cache" backend/app/main.py | grep -v __pycache__

# Check that cancel_inflight() in experience_generator is called during lifespan shutdown
grep -n "cancel_inflight\|lifespan" backend/app/main.py | head -20
grep -n "cancel_inflight" backend/app/services/experience_generator.py | head -5
```

Report:

- `clear_experience_db_cache` only deletes `cache_type == "experience"` but NOT `"experience_single"` → **High** (fill-day L2 entries survive a "clear all" operation; users see stale data after cache flush)
- Admin endpoint missing a call to any module's `clear_memory_cache`/`clear_cache` → **High** (partial clear leaves L1 warm after expected flush)
- Admin endpoint missing a call to any module's `clear_db_cache` → **High** (L2 not cleared, will repopulate L1 on next request)
- Naming inconsistency across modules (`clear_memory_cache` vs `clear_cache` vs `clear_experience_cache`) → **Medium** (easy to accidentally skip one in admin code)
- `cancel_inflight()` not registered in lifespan shutdown → **Medium** (in-flight experience generation tasks not cancelled on graceful restart; may log errors after shutdown)

#### 1J-5: Unbounded Cache Growth

```bash
# Check all MemoryCache instantiations for maxsize
grep -rn "MemoryCache(" backend/app/ --include="*.py" | grep -v __pycache__ | grep -v test_

# Known maxsizes: specialist=128, tile=256, router=500, experience=128
# Flag any MemoryCache without explicit maxsize or with maxsize > 5000

# Check for raw dicts or lists used as ad-hoc caches without TTL/size limits
grep -rn "^_cache\s*=\s*{}\|^_cache\s*:\s*dict\|^CACHE\s*=" backend/app/ --include="*.py" | grep -v __pycache__

# Check _inflight_generation_tasks (experience_generator) — unbounded dict of asyncio Tasks
grep -n "_inflight_generation_tasks" backend/app/services/experience_generator.py | grep -v __pycache__
# This dict grows with one entry per unique in-flight key and should be cleaned up on task completion
```

Report:

- `MemoryCache()` without `maxsize` → **Critical** (unbounded memory growth)
- `_inflight_generation_tasks` dict — verify entries are removed after task completion (not just on shutdown) → **High** if entries persist after tasks finish (slow memory leak under concurrent load)
- Raw `dict` used as cache without TTL/size limit → **High**
- `maxsize` > 5000 for in-memory L1 cache → **Medium** (may exhaust heap under memory pressure)

#### 1J-6: Direct Cache Bypass

```bash
# Check if any node code accesses TTLCache directly instead of through MemoryCache service functions
grep -rn "TTLCache\|_cache\[" backend/app/planner/nodes/ --include="*.py" | grep -v __pycache__ | grep -v test_

# Check that node code imports cache SERVICE functions (not cache internals)
grep -rn "from app.services.*cache import\|from app.services.experience_generator import" backend/app/planner/nodes/ --include="*.py" | grep -v __pycache__

# Check experience_generator.has_cached() is used correctly — it only checks L1 (not L2)
# Callers that rely on has_cached() to skip LLM generation may still miss warm L2 entries
grep -rn "has_cached(" backend/app/ --include="*.py" | grep -v __pycache__ | grep -v test_
```

Report:

- Node code importing `TTLCache` directly → **Critical** (bypasses `MemoryCache` lock, race condition)
- `has_cached()` in `experience_generator.py` checks L1 only — callers that use it as a "skip LLM" gate may still generate when L2 is warm → **Medium** (unnecessary LLM spend; L1 is cold after restart)

#### 1J-7: In-flight Deduplication Safety (Experience Generator)

```bash
# Check the inflight lock and dict in experience_generator.py
grep -n "_inflight_generation_lock\|_inflight_generation_tasks\|async with _inflight_generation_lock" backend/app/services/experience_generator.py | grep -v __pycache__

# Verify the check-and-set on _inflight_generation_tasks is inside the lock
# Pattern: "async with _inflight_generation_lock: ... if key not in _inflight ... _inflight[key] = task"
# If the dict is read or written OUTSIDE the lock, there's a TOCTOU race
grep -n "_inflight_generation_tasks" backend/app/services/experience_generator.py | grep -v __pycache__

# Verify inflight entries are removed after task completion (success AND failure)
# Look for finally blocks or callbacks that delete from _inflight_generation_tasks
grep -n "finally\|_inflight_generation_tasks.pop\|del _inflight_generation_tasks" backend/app/services/experience_generator.py | grep -v __pycache__
```

Report:

- `_inflight_generation_tasks` read or written outside `async with _inflight_generation_lock` → **Critical** (TOCTOU race: two coroutines both see "not in dict", both launch LLM calls, duplicate work and duplicate L2 writes)
- `_inflight_generation_tasks[key]` not removed after task completes (in a `finally` block or `.add_done_callback`) → **High** (dict grows unboundedly; future requests for the same key see a completed Task, may get wrong result or error)
- `cancel_inflight()` clears dict but doesn't await task cancellation before returning → **Medium** (cancelled tasks may still be running when caller proceeds)

#### 1J-8: Cross-Module Stats API Consistency

```bash
# Check get_cache_stats() signature and returned keys in all cache modules
grep -rn "def get_cache_stats" backend/app/services/ --include="*.py" | grep -v __pycache__

# Check actual stat keys returned by each module
grep -n "stat_keys=" backend/app/services/ --include="*.py" -r | grep -v __pycache__
# router_cache uses stat_keys=["hits", "misses", "skipped_context_dependent"]
# specialist/tile/experience use default ["l1_hits", "l1_misses", "l2_hits", "l2_misses", "writes"]
# If admin code aggregates by standard key names (l1_hits etc), router stats return 0 for those keys

# Check admin stats endpoint for how it aggregates
grep -n "get_cache_stats\|cache_stats" backend/app/main.py | grep -v __pycache__
```

Report:

- `router_cache` uses non-standard stat keys (`"hits"`, `"misses"`) while all other modules use `"l1_hits"`, `"l1_misses"` → **Medium** (admin dashboard aggregation using standard keys returns 0 for router stats; hit rate calculations are wrong)
- Any module missing `get_cache_stats()` → **Medium** (incomplete observability)
- Admin endpoint not calling `get_cache_stats()` for all modules → **Low** (silent blind spots in cache monitoring)

### 1K: Resource Lifecycle & Leak Prevention

Audit that all opened resources (DB connections, HTTP clients, file handles, streaming generators) are properly closed, especially on error paths and shutdown.

#### 1K-1: Database Connection Lifecycle

```bash
# 1. Check that async engine is disposed on shutdown (lifespan hook)
grep -n "lifespan\|yield\|dispose\|engine.*close" backend/app/main.py | head -20

# 2. Check all DB session usage — must use `async with` or try/finally with close()
grep -rn "AsyncSession\|get_async_db\|get_db" backend/app/ --include="*.py" | grep -v __pycache__ | grep -v test_ | grep -v db\.py | head -30

# 3. Check for sessions created outside dependency injection (leaked if not closed)
grep -rn "AsyncSession(\|SessionLocal()" backend/app/ --include="*.py" | grep -v __pycache__ | grep -v test_ | grep -v db\.py

# 4. Check pool configuration — pool_size, max_overflow, pool_recycle, pool_pre_ping
grep -rn "pool_size\|max_overflow\|pool_recycle\|pool_pre_ping" backend/app/db.py
```

Report:

- Async engine not disposed in lifespan shutdown (after `yield`) → **High** (connection pool leaked on graceful restart)
- DB session created without context manager or try/finally close → **Critical** (connection leak)
- Sessions created outside FastAPI `Depends()` without proper cleanup → **High**
- Missing `pool_pre_ping` on engine → **Medium** (stale connections cause intermittent errors)

#### 1K-2: HTTP Client Lifecycle

```bash
# Check all httpx / aiohttp / requests usage patterns
grep -rn "httpx\.\|aiohttp\.\|requests\." backend/app/ --include="*.py" | grep -v __pycache__ | grep -v test_

# Check if HTTP clients are created per-request (wasteful) vs shared (efficient)
grep -rn "AsyncClient(\|Client(\|ClientSession(" backend/app/ --include="*.py" | grep -v __pycache__ | grep -v test_

# Check that all clients use context managers (async with)
grep -rn "AsyncClient\|ClientSession" backend/app/ --include="*.py" | grep -v __pycache__ | grep -v test_ | grep -v "async with"
```

Report:

- HTTP client created without `async with` or explicit `.aclose()` → **High** (connection pool leak)
- HTTP client created per-request with no connection reuse → **Medium** (performance: TCP/TLS handshake per call; consider a module-level shared client with lifespan cleanup)
- Missing timeout on HTTP client → **High** (hangs indefinitely on unresponsive external API)
- `requests.*` used in async code path → see 1C (sync-in-async)

#### 1K-3: Streaming Response Cleanup

```bash
# Find all StreamingResponse generators
grep -rn "StreamingResponse" backend/app/main.py | head -10

# For each streaming endpoint, check if the generator:
# 1. Has try/finally to clean up DB sessions
# 2. Handles client disconnect (GeneratorExit)
grep -n "def.*stream\|async def.*stream\|def.*generate\|async def.*generate" backend/app/main.py | head -10
```

For each StreamingResponse generator, verify:

- DB session obtained inside the generator is closed in a `finally` block → if not, **Critical** (client disconnect leaks connection)
- Generator handles `GeneratorExit` or `asyncio.CancelledError` → if not, **High** (cleanup code after yield is skipped)
- Generator doesn't hold locks across `yield` points → if it does, **Critical** (client disconnect leaves lock held forever)

#### 1K-4: File Handle & Temp File Cleanup

```bash
# Check for open() without context manager
grep -rn "open(" backend/app/ --include="*.py" | grep -v __pycache__ | grep -v test_ | grep -v "# "

# Check for temp files without cleanup
grep -rn "tempfile\|NamedTemporaryFile\|mkstemp\|mkdtemp" backend/app/ --include="*.py" | grep -v __pycache__ | grep -v test_
```

Report:

- `open()` without `with` statement → **High** (file descriptor leak on exception)
- Temp files created without cleanup or context manager → **Medium**
- Skip: no findings expected (this project doesn't appear to use file I/O), but flag if any appear

#### 1K-5: Lifespan Shutdown Completeness

```bash
# Read the full lifespan function to check what's cleaned up on shutdown
grep -n "async def lifespan" backend/app/main.py -A 60
```

The lifespan function should clean up ALL long-lived resources after `yield`. Check for:

- Async engine disposal (`await engine.dispose()`) → if missing, **High**
- Shared HTTP client closure → if a shared client exists but isn't closed, **High**
- Background task cancellation → if background tasks exist but aren't cancelled, **Medium**
- Cache clearing (optional, but good practice) → **Low** if missing

### 1L: LLM Output Validation

Verify that all LLM calls validate their output before feeding it into graph state. Malformed or truncated LLM responses (especially from Gemini with `max_output_tokens` limits) can silently corrupt the plan.

```bash
# 1. All structured output calls
grep -rn "with_structured_output\|\.invoke(\|\.ainvoke(" backend/app/planner/nodes/ --include="*.py" | grep -v __pycache__ | grep -v test_

# 2. Raw .content access without type checking (may be None or unexpected type)
grep -rn "\.content\b" backend/app/planner/nodes/ --include="*.py" | grep -v __pycache__ | grep -v test_ | grep -v "# "

# 3. Check if llm_structured retry wrapper is used where appropriate
grep -rn "llm_structured\|invoke_with_retry\|structured_invoke" backend/app/planner/nodes/ --include="*.py" | grep -v __pycache__ | grep -v test_

# 4. JSON parsing without validation
grep -rn "json\.loads\|json\.load" backend/app/planner/nodes/ --include="*.py" | grep -v __pycache__ | grep -v test_
```

For each `.invoke()` or `.ainvoke()` call in a node:

- Verify the result is validated (Pydantic model parse, `llm_structured` wrapper, or explicit field presence checks)
- Verify truncated output is handled (Gemini `finish_reason: "MAX_TOKENS"` or missing required fields)
- Verify `None` / empty response is handled gracefully

Report:

- Unvalidated LLM output fed directly into graph state → **Critical** (corrupts downstream nodes)
- Raw `.content` access without None check → **High** (NoneType crash)
- `json.loads` without try/except → **High** (malformed JSON from LLM crashes node)
- Missing retry/fallback on structured output failure → **Medium**

### 1M: Google Places API Tier & Guard Compliance

The project uses Google Places API (New) and **must stay on Pro tier** ($5/1k Text Search calls). Enterprise tier is triggered by requesting Enterprise-only fields in the `X-Goog-FieldMask` header ($32/1k). Additionally, every Places API call path must be protected by spend guards, circuit breakers, and error handling.

#### 1M-1: Enterprise Field Leak (FieldMask Audit)

Enterprise-only fields that bump Text Search from Pro ($5/1k) to Enterprise ($32/1k) include: `priceLevel`, `priceRange`, `rating`, `userRatingCount`, `reviews`, `currentOpeningHours`, `regularOpeningHours`, `websiteUri`, `nationalPhoneNumber`, `internationalPhoneNumber`, `currentSecondaryOpeningHours`, `regularSecondaryOpeningHours`, `allowsDogs`, `curbsidePickup`, `delivery`, `dineIn`, `goodForChildren`, `goodForGroups`, `goodForWatchingSports`, `liveMusic`, `menuForChildren`, `outdoorSeating`, `restroom`, `servesBeer`, `servesBreakfast`, `servesBrunch`, `servesCocktails`, `servesCoffee`, `servesDessert`, `servesDinner`, `servesLunch`, `servesVegetarianFood`, `servesWine`, `takeout`, `paymentOptions`, `parkingOptions`, `accessibilityOptions`, `generativeSummary`, `areaSummary`, `containingPlaces`, `addressDescriptor`, `evChargeOptions`, `fuelOptions`, `neighborhoodSummary`, `pureServiceAreaBusiness`.

```bash
# 1. Find ALL X-Goog-FieldMask definitions and string literals in the Places provider
grep -n "X-Goog-FieldMask\|FieldMask\|FIELD_MASK\|_field_mask\|field_mask" \
  backend/app/tile_service/google_places_provider.py | grep -v __pycache__

# 2. Check for Enterprise-tier fields in ANY field mask string
# These fields bump Text Search from Pro ($5/1k) to Enterprise ($32/1k):
grep -rn "priceLevel\|priceRange\|userRatingCount\|\.reviews\|currentOpeningHours\|regularOpeningHours\|websiteUri\|nationalPhoneNumber\|internationalPhoneNumber\|currentSecondaryOpeningHours\|regularSecondaryOpeningHours" \
  backend/app/tile_service/ --include="*.py" | grep -v __pycache__ | grep -v "# \|#.*Enterprise\|#.*stripped\|#.*Pro"

# 3. Check for Enterprise boolean attribute fields (allowsDogs, dineIn, etc.)
grep -rn "allowsDogs\|curbsidePickup\|delivery\b\|dineIn\|goodForChildren\|goodForGroups\|goodForWatchingSports\|liveMusic\|menuForChildren\|outdoorSeating\|restroom\|servesBeer\|servesBreakfast\|servesBrunch\|servesCocktails\|servesCoffee\|servesDessert\|servesDinner\|servesLunch\|servesVegetarianFood\|servesWine\|takeout\|paymentOptions\|parkingOptions\|accessibilityOptions\|generativeSummary\|areaSummary\|containingPlaces\|addressDescriptor" \
  backend/app/tile_service/ --include="*.py" | grep -v __pycache__ | grep -v "# "

# 4. Check for dynamic field mask construction that could accidentally include Enterprise fields
# (e.g., building mask from a list that includes Enterprise fields, or user-controlled fields)
grep -rn "field_mask.*+=\|field_mask.*join\|field_mask.*append\|field_mask.*format\|field_mask.*f\"" \
  backend/app/tile_service/ --include="*.py" | grep -v __pycache__

# 5. Cross-check: verify Pro-tier comments are accurate and adjacent to actual field masks
# Read the full field mask definitions to manually inspect
grep -n "FieldMask\|field_mask\|FIELD_MASK\|X-Goog-FieldMask" \
  backend/app/tile_service/google_places_provider.py -A 15 | head -80

# 6. Check if any OTHER file also makes Google Places API calls (bypassing the provider)
grep -rn "places.googleapis.com\|maps.googleapis.com/maps/api/place" \
  backend/app/ --include="*.py" | grep -v __pycache__ | grep -v google_places_provider
```

Report:

- Enterprise-only field in any `X-Goog-FieldMask` string → **Critical** (6.4× cost increase: $5→$32 per 1k calls; a single field triggers Enterprise billing for the entire request)
- Dynamic field mask construction that could include user-controlled or config-controlled fields without an allowlist → **High** (could accidentally add Enterprise fields via config change)
- Enterprise field referenced in code (even in a comment-disabled line) without a `# Enterprise — DO NOT UNCOMMENT` guard → **Medium** (easy to accidentally re-enable)
- Google Places API call outside `google_places_provider.py` → **Critical** (bypasses all tier/guard controls)
- Pro-tier comment is inaccurate or missing next to a field mask definition → **Low** (documentation gap)

#### 1M-2: Spend Guard Coverage on All Places Call Paths

Every Google Places API call must be preceded by `reserve_places_spend_or_raise()` from `spend_guard.py`. If a call path bypasses the spend guard, it runs uncapped.

```bash
# 1. Catalog ALL functions that make HTTP requests to Google Places endpoints
grep -rn "places.googleapis.com\|maps.googleapis.com" \
  backend/app/tile_service/google_places_provider.py | grep -v __pycache__ | grep -v "# "

# 2. Check that each call path invokes reserve_places_spend_or_raise BEFORE the HTTP call
grep -n "reserve_places_spend_or_raise\|reserve.*places.*spend" \
  backend/app/tile_service/google_places_provider.py | grep -v __pycache__

# 3. Check if spend_guard_scope wraps the calling endpoints (session-level cap)
grep -rn "spend_guard_scope" backend/app/main.py backend/app/streaming.py | grep -v "import\|def spend_guard"

# 4. Check the geocoding path — does it also call reserve_places_spend_or_raise?
# Geocoding ($5/1k) is a separate SKU but still a paid Google Maps call
grep -n "geocode\|_geocode" backend/app/tile_service/google_places_provider.py | head -20
# Cross-reference: is reserve_places_spend_or_raise called before geocoding requests?

# 5. Check the photo proxy path — is it guarded?
grep -n "proxy.*photo\|photo.*proxy\|places.googleapis.com.*media" backend/app/main.py | head -10
# Photo requests are also billed — verify spend guard or rate limit coverage

# 6. Check for any httpx/aiohttp calls to Google that bypass reserve_places_spend_or_raise
grep -rn "httpx\.\|aiohttp\.\|requests\." backend/app/tile_service/ --include="*.py" | grep -v __pycache__ | grep -v "import\|# "
```

Report:

- Places Text Search call without preceding `reserve_places_spend_or_raise()` → **Critical** (uncapped API spend)
- Geocoding call without spend guard → **High** (lower cost per call but still paid; $5/1k Geocoding calls)
- Photo proxy endpoint without spend guard or rate limit → **High** (photo requests are billed; attacker can scrape photos to drain budget)
- New call path added to provider without spend guard integration → **Critical** (silent budget bypass)
- `spend_guard_scope` not wrapping the endpoint that triggers Places calls → **High** (per-call reserve fires but session daily cap is not enforced)

#### 1M-3: Circuit Breaker Coverage

Every Google Places call path should be protected by the circuit breaker to prevent cascading failures and budget drain on API outages.

```bash
# 1. Catalog all circuit breaker path labels
grep -n "_PLACES_PATH_LABELS\|PLACES_PATH_LABELS\|path_label\|circuit.*breaker\|_circuit" \
  backend/app/tile_service/google_places_provider.py | grep -v __pycache__

# 2. For each function that calls the Places API, verify it uses circuit_breaker_guard or equivalent
grep -n "circuit_breaker\|_cb_guard\|_check_circuit\|_record_failure\|_record_success" \
  backend/app/tile_service/google_places_provider.py | grep -v __pycache__

# 3. Check that 429 (quota exhausted) triggers circuit open
grep -n "429\|quota\|RESOURCE_EXHAUSTED\|rate.limit" \
  backend/app/tile_service/google_places_provider.py | grep -v __pycache__

# 4. Check circuit breaker configuration defaults
grep -n "circuit_breaker" backend/app/config.py

# 5. Check that circuit breaker can be disabled per-path or globally (and whether disable = unguarded)
grep -n "circuit_breaker_enabled\|_CB_ENABLED\|cb_enabled" \
  backend/app/tile_service/google_places_provider.py backend/app/config.py | grep -v __pycache__
```

Report:

- Places API call function without circuit breaker guard → **Critical** (API outage or quota exhaustion causes cascading failures and continued spend on failing calls)
- 429/quota response not triggering circuit open → **High** (keeps hammering exhausted quota, delays recovery)
- Circuit breaker disabled by default (`enabled = False`) → **High** (no protection unless explicitly enabled)
- Missing circuit breaker path label for a call path → **Medium** (call works but isn't tracked in telemetry or circuit state)
- Circuit breaker open duration too short (< 10s) → **Medium** (reopens too quickly, doesn't give quota time to recover)

#### 1M-4: Error Handling & Graceful Degradation

All Places API calls must handle errors gracefully — never crash the request, never leak raw Google API errors to the client.

```bash
# 1. Check all try/except blocks around Places API calls
grep -n "try:\|except\|raise\|HTTPError\|HTTPStatusError\|RequestError\|TimeoutException" \
  backend/app/tile_service/google_places_provider.py | grep -v __pycache__ | head -40

# 2. Check for bare except or overly broad exception handling
grep -n "except Exception\|except:\s*$" \
  backend/app/tile_service/google_places_provider.py | grep -v __pycache__

# 3. Check that errors return empty results (graceful degradation) not exceptions
grep -n "return \[\]\|return None\|return {}" \
  backend/app/tile_service/google_places_provider.py | grep -v __pycache__ | head -20

# 4. Check for timeout configuration on HTTP calls
grep -n "timeout\|Timeout" \
  backend/app/tile_service/google_places_provider.py | grep -v __pycache__

# 5. Check for raw Google API error messages leaking to client responses
grep -rn "detail=.*google\|detail=.*places\|detail=.*geocod" \
  backend/app/main.py backend/app/tile_service/ --include="*.py" | grep -v __pycache__ | grep -v "# "

# 6. Check photo proxy error handling (client-facing endpoint)
grep -n "proxy.*photo\|def.*photo" backend/app/main.py -A 30 | head -40
```

Report:

- Places API call without try/except → **Critical** (unhandled exception crashes the endpoint)
- Missing timeout on HTTP request to Google → **Critical** (hangs indefinitely on unresponsive Google API, holds connection pool slot)
- Raw Google API error message in HTTP response `detail` field → **High** (leaks internal API structure to client)
- `except:` (bare) or `except Exception` without logging → **Medium** (silently swallows errors; should at least log)
- Non-empty error response (returns partial/stale data on error instead of empty) → **Medium** (may confuse downstream logic)
- Photo proxy returns 500 with raw error on Google API failure instead of placeholder/404 → **Medium**

#### 1M-5: Telemetry & Observability

Verify that all Places API call paths are instrumented for cost tracking and debugging.

```bash
# 1. Check telemetry recording function usage
grep -n "record_google_places_usage\|_record_usage\|_telemetry" \
  backend/app/tile_service/google_places_provider.py | grep -v __pycache__

# 2. Check that every call path (browse, tier1_enrich, tier2_enrich, logistics, geocode) records usage
grep -n "record_google_places_usage" \
  backend/app/tile_service/google_places_provider.py | grep -v __pycache__
# Count distinct path labels in record calls — should match _PLACES_PATH_LABELS count

# 3. Check the admin stats endpoint includes Places usage
grep -rn "google_places_usage\|places_stats\|places.*telemetry\|get_google_places_stats" \
  backend/app/main.py | grep -v __pycache__

# 4. Check for cost estimation accuracy — spend_guard estimated cost vs actual Google billing
grep -n "spend_guard_places_estimated_call_usd\|estimated_call_usd\|0\.017\|places.*cost" \
  backend/app/config.py backend/app/services/spend_guard.py | grep -v __pycache__
```

Report:

- Places API call path without telemetry recording → **High** (invisible spend; can't debug cost spikes)
- Missing path label in telemetry (call recorded but path is `None` or unknown) → **Medium** (can't attribute cost to feature)
- Admin stats endpoint doesn't expose Places usage counters → **Medium** (no visibility without log parsing)
- `spend_guard_places_estimated_call_usd` significantly under-estimates actual Google billing → **High** (caps trigger too late; e.g., estimate $0.005 but actual is $0.017 → 3.4× undershoot, session burns $6.80 before $2 cap triggers)
- Skip: exact pricing validation (Google pricing can change; flag only order-of-magnitude mismatches)

---

## Phase 2: Frontend TypeScript/React

### 2A: Unused Imports and Variables

```bash
cd frontend && npx eslint . --no-fix --rule '{"@typescript-eslint/no-unused-vars": "error", "no-unused-vars": "error"}' 2>&1 | head -50
```

Report all unused imports and variables.

### 2B: Full Type Error Check

Run a complete TypeScript type check for actual type errors (not just unused vars):

```bash
cd frontend && npx tsc --noEmit 2>&1 | head -80
```

Report ALL type errors found, grouped by file. This is separate from 2A — type errors are broken contracts, not just hygiene.

- Severity: **High** for errors in components, hooks, or state stores. **Medium** for type-only files.

### 2C: Dead Components and Functions

For each exported component/function in `frontend/components/` and `frontend/hooks/`:

```bash
# List all exports
grep -rn "^export " frontend/components/ frontend/hooks/ frontend/lib/ --include="*.ts" --include="*.tsx" | grep -v node_modules | grep -v __tests__

# For each export, check if it's imported anywhere
# Example: grep -rn "import.*ComponentName" frontend/ --include="*.ts" --include="*.tsx" | grep -v node_modules
```

Dead exports with zero importers → report them.

**Do NOT flag:**

- Page components in `frontend/app/` (Next.js auto-routes)
- Components referenced in dynamic imports or lazy loading
- Type exports used in other type files
- `design-system.ts` tokens (may be used in future)

### 2D: Unnecessary Re-renders

Scan for common re-render causes, including high-frequency UI paths that are easy to miss:

```bash
# 1. Fat Zustand selectors (selecting entire objects instead of specific fields)
grep -rn "useDocumentStore((s\|state) =>" frontend/components/ --include="*.tsx" | grep -v "\.document\?\." | head -20

# 2. Inline object/array creation in JSX props (new reference every render)
grep -rn "style={{" frontend/components/ --include="*.tsx" | grep -v __tests__ | head -20

# 3. Inline arrow functions as event handlers in mapped lists
grep -rn "\.map.*onClick={() =>" frontend/components/ --include="*.tsx" | head -20

# 4. Missing useMemo/useCallback on expensive computations passed as props
grep -rn "useMemo\|useCallback" frontend/components/ --include="*.tsx" -l

# 5. Broad trip_inputs subscriptions (fan-out rerenders on any trip input field change)
grep -rn "useDocumentTripInputs(\|document\?\.trip_inputs\|useTripInputsWithFallback(" frontend/components/ frontend/hooks/ frontend/state/ --include="*.ts" --include="*.tsx" | grep -v __tests__

# 6. Chat list identity churn: cloned/spread message objects and paragraph splitting
grep -rn "visibleMessages.*useMemo\|\\.flatMap(\|\\.map((m) => ({ ...m" frontend/components/chat/ --include="*.tsx" | grep -v __tests__

# 7. Memoized row/item renderers that still receive unstable object/handler props
grep -rn "memo(\|React\.memo\|are.*PropsEqual\|Comparator" frontend/components/chat/ frontend/components/plan/ frontend/components/map/ --include="*.tsx" | grep -v __tests__

# 8. High-frequency hover store paths (map/timeline hover sync)
grep -rn "hoveredActivityId\|setHoveredActivityId\|onMouseEnter.*setHoveredActivityId\|onMouseLeave.*setHoveredActivityId" frontend/components/map/ frontend/components/plan/ --include="*.tsx" | grep -v __tests__

# 9. DOM query hover sync (avoid React rerender, but can still be hot-path expensive)
grep -rn "querySelector(\|data-map-id\|data-map-hovered" frontend/components/plan/ --include="*.tsx" | grep -v __tests__

# 10. Map prop identity churn (derived arrays/centers passed to map components)
grep -rn "fullModeMapItems\|sectionFallbackPOIs\|mapCenter\|calculateMapCenter\|extractPOIsFromSections" frontend/components/plan/ --include="*.tsx" | grep -v __tests__

# 11. Wrapper/lambda prop churn into heavy children (TimelineThread, map, virtualized-like trees)
grep -rn "dayWrapper=\|blockWrapper=\|freeDayDropSlot=\|scrollHeaderContent=\|headerContent=\|plannerContent=\|planViewContent=" frontend/components/ --include="*.tsx" | grep -v __tests__

# 12. Expensive selector computations inside subscriptions (Object.keys in selector)
grep -rn "Object.keys(" frontend/ --include="*.ts" --include="*.tsx" | grep -E "useDocumentStore|useChatStore" | grep -v __tests__

# 13. Per-item noop callback creation in mapped lists (breaks memoized child stability)
grep -rn "\?\? (() => {})" frontend/components/ --include="*.tsx" | grep -v __tests__

# 14. Context provider value instability (new object/array literal as value prop — re-renders ALL consumers every render)
grep -rn "\.Provider value={{" frontend/components/ frontend/hooks/ --include="*.tsx" --include="*.ts" | grep -v __tests__
grep -rn "\.Provider value={\[" frontend/components/ frontend/hooks/ --include="*.tsx" --include="*.ts" | grep -v __tests__

# 15. Zustand selectors with inline computation (new reference returned every read even when data unchanged)
grep -rn "useDocumentStore((s\|state) =>" frontend/ --include="*.ts" --include="*.tsx" | grep -E "\.filter\(|\.map\(|\.find\(|\.reduce\(|\.sort\(" | grep -v __tests__
grep -rn "useChatStore((s\|state) =>" frontend/ --include="*.ts" --include="*.tsx" | grep -E "\.filter\(|\.map\(|\.find\(|\.reduce\(|\.sort\(" | grep -v __tests__

# 16. Custom hooks returning new object/array literals on every call (missing useMemo on return value)
# Hooks that return inline object literals — every caller re-renders on each invocation
grep -rn "^  return {" frontend/hooks/ --include="*.ts" --include="*.tsx" | grep -v __tests__
grep -rn "^  return \[" frontend/hooks/ --include="*.ts" --include="*.tsx" | grep -v __tests__
# Cross-reference: which of those hooks do NOT wrap the return in useMemo?
grep -rn "useMemo" frontend/hooks/ --include="*.ts" --include="*.tsx" -l

# 17. Framer Motion inline animation/variant objects (new object identity each render triggers animation churn)
grep -rn "animate={{\|initial={{\|exit={{\|transition={{\|variants={{" frontend/components/ --include="*.tsx" | grep -v __tests__ | head -20

# 18. Non-style inline JSX object props (extends check 2 — any non-style prop receiving an inline object literal)
grep -rn "={{[^}]*:[^}]*}}" frontend/components/ --include="*.tsx" | grep -v "style={{" | grep -v __tests__ | head -20

# 19. Index-as-key in dynamic lists (causes full unmount/remount instead of reconciliation)
grep -rn "key={index}\|key={i}\|key={idx}\|key={_i}\|key={_idx}" frontend/components/ --include="*.tsx" | grep -v __tests__
# Also check .map((item, index) => ... key={index}) patterns
grep -rn "\.map(.*index.*=>.*key={index}" frontend/components/ --include="*.tsx" | grep -v __tests__

# 20. Multiple store subscriptions in a single component (each subscription is an independent listener — fan-out risk)
# Find components that subscribe to 3+ stores
grep -rn "useDocumentStore\|useChatStore\|useUIStore\|useMobileNavStore" frontend/components/ --include="*.tsx" | grep -v __tests__ | awk -F: '{print $1}' | sort | uniq -c | sort -rn | head -15

# 21. useEffect setting state unconditionally (no early-return guard) — can trigger render cascade
grep -rn "useEffect" frontend/components/ --include="*.tsx" | grep -v __tests__ | xargs -I{} grep -l "setState\|set[A-Z]" 2>/dev/null | head -10
# Check for effects that set state without a conditional guard (== or !== check before setState)
grep -rn "useEffect" frontend/components/ frontend/hooks/ --include="*.tsx" --include="*.ts" -A 5 | grep -v __tests__ | grep "set[A-Z][a-z]" | grep -v "if\|==" | head -15

# 22. Referential instability in default prop values (inline object/array as default parameter in destructure)
grep -rn "= {}\|= \[\]" frontend/components/ --include="*.tsx" | grep -E "^\s*\{|function|const.*=.*\(" | grep -v __tests__ | grep -v "useState\|useRef\|useMemo" | head -15
```

Report findings with severity assessment:

- Fat selectors → report all
- Inline styles → report all
- Inline handlers in mapped lists → only flag if list is >20 items or handler triggers expensive re-renders
- Missing `useMemo` → only flag if computation is genuinely expensive
- Broad `trip_inputs` subscriptions in shared/root/hot components → **Medium** (or **High** if root-level)
- Chat message identity churn (clone/split pipeline) that defeats memoized rows → **High**
- Memoized children receiving unstable function/object props every parent render → **Medium**
- Hover-store hot paths updating global state on mousemove/mouseenter across map/timeline → **High**
- DOM query hover sync per hover event → **Low/Medium** (depends on event frequency + list size)
- Map derived props not memoized before passing to map component → **Medium**
- Wrapper/lambda prop churn into heavy timeline/map trees → **Medium**
- Selector computations like `Object.keys(...)` inside store selectors → **Low/Medium**
- Per-item fallback noop callbacks in mapped lists → **Low/Medium** (flag when it breaks memoized child)
- Context provider with inline object/array value → **High** (re-renders every consumer on every parent render; wrap value in `useMemo`)
- Zustand selector with `.filter()`/`.map()`/`.find()` returning new array/object → **High** (new reference every read; extract derived value with `useMemo` outside the selector)
- Custom hook returning inline object/array without `useMemo` → **Medium** (every caller sees identity change; wrap return in `useMemo`)
- Framer Motion inline animation/variant objects → **Medium** (animation system gets new config object each render; hoist to module-level constants or `useMemo`)
- Non-style inline JSX object props → **Medium** (same as `style={{}}` — new reference each render; flag if passed to memoized or heavy children)
- Index-as-key in dynamic lists → **High** if list items can reorder or be inserted/deleted (causes full unmount/remount), **Low** if list is append-only and stable
- Components subscribing to 3+ stores → **Medium** (multiplicative re-render exposure; consider colocating selectors or derived state into a single subscription hook)
- `useEffect` setting state unconditionally without early-return guard → **Medium** (may cause render cascade; verify deps array prevents infinite loop)
- Inline object/array default prop values (`= {}`, `= []` in destructure) → **Low/Medium** (new reference each call if used as `useEffect` dep or passed to memoized children)

When reporting rerender findings, include:

- Why it rerenders unnecessarily (identity churn vs subscription fan-out vs high-frequency state writes)
- Whether the path is hot (chat streaming, map hover, timeline scroll)
- Exact file/line and impacted subtree (e.g., "entire chat list", "all map markers", "root landing layout")

### 2E: Duplicate Code

```bash
# 1. Find components with similar names (potential duplicates)
find frontend/components -name "*.tsx" | xargs basename -a | sort | uniq -di

# 2. Find duplicate utility/hook function names across files
grep -rn "^export function\|^export const.*= (" frontend/lib/ frontend/hooks/ --include="*.ts" --include="*.tsx" | awk -F'export ' '{print $2}' | awk -F'(' '{print $1}' | sort | uniq -d

# 3. SSoT violations: logic that should only live in one file
# Streaming/SSE handling (should be in api.ts only)
grep -rn "EventSource\|text/event-stream\|ReadableStream\|getReader()" frontend/components/ frontend/hooks/ frontend/lib/ --include="*.ts" --include="*.tsx" | grep -v api\.ts | grep -v __tests__

# Plan state checking (should be in planStateHelpers.ts only)
grep -rn "plan_view_state\|planViewState\|isExploring\|isPlanning" frontend/components/ frontend/hooks/ --include="*.ts" --include="*.tsx" | grep -v planStateHelpers | grep -v __tests__ | head -20

# 4. Duplicate type definitions across type files
grep -rn "^export type\|^export interface" frontend/types/ --include="*.ts" | awk -F'export ' '{print $2}' | awk '{print $2}' | sort | uniq -d

# Also check for type definitions outside types/ folder
grep -rn "^export type\|^export interface" frontend/components/ frontend/hooks/ frontend/lib/ frontend/state/ --include="*.ts" --include="*.tsx" | grep -v __tests__ | grep -v "Props\|State" | head -20

# 5. Duplicate Zustand selectors — same selector logic in multiple components
grep -rn "useDocumentStore\|useChatStore\|useUIStore\|useMobileNavStore" frontend/components/ --include="*.tsx" | awk -F'=>' '{print $2}' | sort | uniq -d

# 6. Duplicate fetch/API calls — direct fetch() outside api.ts
grep -rn "fetch(" frontend/components/ frontend/hooks/ frontend/state/ --include="*.ts" --include="*.tsx" | grep -v api\.ts | grep -v __tests__ | grep -v node_modules

# 7. Copy-pasted DS token values instead of DS.* references (covered more deeply in 2K, quick check here)
grep -rn "bg-\[#\|text-\[#\|border-\[#" frontend/components/ --include="*.tsx" | grep -v __tests__ | head -10
```

Report findings with locations. SSoT-specific checks:

- Multiple implementations of streaming/SSE handling (should be in `api.ts` only) → **High**
- Multiple implementations of plan state checking (should be in `planStateHelpers.ts` only) → **High**
- Duplicate type definitions (same name in multiple files) → **Medium**
- Type definitions in component/hook/lib files instead of `types/` → **Medium** (except `Props`/`State` interfaces, which are fine inline)
- Direct `fetch()` calls outside `api.ts` → **High** (bypasses error handling, auth, base URL)
- Copy-pasted DS token values instead of `DS.*` references → **Medium**
- Identical Zustand selector patterns repeated across components → **Low** (consider extracting to a shared selector)

### 2F: Async/Race Conditions & Resource Cleanup

#### 2F-1: Missing useEffect Cleanup

```bash
# useEffect with fetch/API calls but no cleanup return
grep -rn "useEffect" frontend/components/ --include="*.tsx" -l | xargs grep -L "abort\|cleanup\|return ()\|return () =>\|clearTimeout\|clearInterval" | head -15

# setTimeout/setInterval without corresponding clearTimeout/clearInterval in cleanup
grep -rn "setTimeout\|setInterval" frontend/components/ --include="*.tsx" | grep -v __tests__ | head -10
```

Report:

- `useEffect` with async/fetch operations but no abort controller cleanup → **High**
- `setTimeout`/`setInterval` without `clearTimeout`/`clearInterval` in the cleanup return → **High** (memory leak + state update after unmount)

#### 2F-2: EventSource / WebSocket Cleanup

```bash
# EventSource instances — must be closed on unmount
grep -rn "new EventSource\|EventSource(" frontend/ --include="*.ts" --include="*.tsx" | grep -v node_modules | grep -v __tests__

# WebSocket instances — must be closed on unmount
grep -rn "new WebSocket\|WebSocket(" frontend/ --include="*.ts" --include="*.tsx" | grep -v node_modules | grep -v __tests__

# For each, verify .close() is called in a useEffect cleanup
```

Report:

- `EventSource` created without `.close()` in cleanup → **Critical** (holds open HTTP connection, server keeps streaming)
- `WebSocket` created without `.close()` in cleanup → **Critical** (holds open connection)

#### 2F-3: AbortController Lifecycle

```bash
# Find all AbortController usage
grep -rn "AbortController\|abort\(\)\|signal" frontend/components/ frontend/hooks/ --include="*.ts" --include="*.tsx" | grep -v node_modules | grep -v __tests__ | head -20

# Check for AbortController created but never aborted in cleanup
grep -rn "new AbortController" frontend/ --include="*.ts" --include="*.tsx" | grep -v node_modules | grep -v __tests__
```

For each `new AbortController()`:

- Verify `controller.abort()` is called in the useEffect cleanup → if not, **High** (fetch continues after unmount)
- Verify `controller.signal` is actually passed to the fetch call → if not, **Medium** (abort controller exists but does nothing)

#### 2F-4: Async State Updates After Unmount

```bash
# .then() or await followed by setState — potential update-after-unmount
grep -rn "\.then(.*set\|await.*set[A-Z]" frontend/components/ --include="*.tsx" | grep -v __tests__ | head -15

# Zustand store mutations inside async callbacks without mount guard
grep -rn "await.*useDocumentStore\|await.*useChatStore\|\.then.*getState()" frontend/ --include="*.ts" --include="*.tsx" | grep -v node_modules | grep -v __tests__ | head -10
```

Report:

- Local `setState` after `await` without mount check or abort signal → **Medium** (React 18+ handles most cases, but can still cause stale updates)
- Zustand `getState().mutate()` after await is generally safe (store persists), note but don't flag

#### 2F-5: Missing Error Handling on Async Operations

```bash
# await without try/catch in components
grep -rn "await " frontend/components/ --include="*.tsx" | grep -v __tests__ | head -20

# .then() without .catch()
grep -rn "\.then(" frontend/components/ --include="*.tsx" | grep -v __tests__ | head -15
```

Report:

- `await` in component without surrounding try/catch → **Medium** (unhandled rejection crashes the component)
- `.then()` without `.catch()` → **Medium** (silent failure)

#### 2F-6: Duplicate Request Fan-out (StrictMode + Multi-Path Triggers)

```bash
# Endpoints that are easy to trigger from multiple paths
grep -rn "expand-itinerary\|expandItinerary\|graph_plan/stream\|streamPlan\|startStream" frontend/ --include="*.ts" --include="*.tsx" | grep -v __tests__

# Effect/timer driven trigger points that can overlap
grep -rn "useEffect\|setTimeout\|setInterval" frontend/components/ frontend/hooks/ frontend/state/ --include="*.ts" --include="*.tsx" | grep -E "expand-itinerary|expandItinerary|graph_plan/stream|streamPlan|retry|refetch" | grep -v __tests__

# Single-flight/idempotency guards in client state
grep -rn "inflight\|inFlight\|pendingRequest\|requestKey\|lastRequest\|isHydrating" frontend/components/ frontend/hooks/ frontend/state/ --include="*.ts" --include="*.tsx" | grep -v __tests__
```

Report:

- Same endpoint callable from multiple trigger paths without a single-flight guard → **Critical** (duplicate backend writes and conflicting UI state)
- Timer/effect retries can overlap first request (no cancellation or guard) → **High**
- React StrictMode causes duplicate calls in development and behavior diverges from production → **Medium** (must be tested explicitly)
- Missing regression tests for overlap path (e.g., trigger A + trigger B + stream callback) → **High**

### 2G: Console.log Pollution

Scan for stray `console.log` / `console.warn` / `console.error` left from debugging:

```bash
# console.* in production code (not tests, not debug.ts)
grep -rn "console\.\(log\|warn\|error\|debug\|info\)" frontend/components/ frontend/hooks/ frontend/lib/ frontend/state/ --include="*.ts" --include="*.tsx" | grep -v __tests__ | grep -v debug\.ts
```

Report each finding. Exclude:

- `console.error` inside error boundaries or catch blocks (intentional)
- `console.warn` in development-only conditional blocks
- Anything inside `debug.ts` (that's the designated debug utility)
- Severity: **Low** (cosmetic, but pollutes browser console)

### 2H: Toast Message Quality

Scan for toast messages that expose internal variable names, raw backend keys, or snake_case identifiers instead of user-friendly strings.

```bash
# Find all toast() call sites
grep -rn "toast(" frontend/components/ frontend/hooks/ frontend/lib/ frontend/state/ --include="*.ts" --include="*.tsx" | grep -v __tests__ | grep -v "useToast\|import\|//.*toast"

# Find toasts passing a raw variable directly (not a string literal)
grep -rn "toast([a-zA-Z_][a-zA-Z0-9_]*)" frontend/components/ frontend/hooks/ --include="*.ts" --include="*.tsx" | grep -v __tests__ | grep -v "useToast\|import\|//"

# Find toasts using template literals that embed specialist_type or other internal keys
grep -rn "toast(\`.*specialist_type\|toast(\`.*activity_type\|toast(\`.*plan_view_state" frontend/ --include="*.ts" --include="*.tsx" | grep -v __tests__

# Find toasts using template literals with section.* or block.* fields that may be raw keys
grep -rn 'toast(`\${' frontend/components/ frontend/hooks/ --include="*.ts" --include="*.tsx" | grep -v __tests__

# Find any direct .specialist_type / .activity_type usage inside a toast message
grep -rn "toast.*specialist_type\|toast.*activity_type\|toast.*\.type\b" frontend/components/ frontend/hooks/ --include="*.ts" --include="*.tsx" | grep -v __tests__
```

For each `toast()` call, assess:

- **String literal**: always OK (e.g., `toast('Plan updated')`)
- **Variable from `getSendBurstGuardReason` or similar guard functions**: OK if that function returns user-friendly strings — verify the function's return values
- **Template literal embedding a `.specialist_type`, `.activity_type`, `.plan_view_state`, or other raw backend key field** without passing through a label-mapping function (e.g., `getTopicLabel`) → **High** (leaks internal identifiers to users)
- **Variable that is a raw backend response field** (e.g., `section.specialist_type`, `block.activity_type`) not mapped through a display-name function → **High**
- **Template literal using `.charAt(0).toUpperCase() + .slice(1)`** or similar naive capitalization of a snake_case key → **Medium** (produces ugly output like "Wildlife_safari")
- **`getTopicLabel()` or equivalent display-name mapping applied** before passing to toast → OK

Do NOT flag:
- Toasts with hardcoded user-readable strings
- Toasts where the variable is guaranteed to be a user-readable string (e.g., messages from the guard functions that only return English sentences)
- `debugLog` calls (not visible to users)

Report each finding with file path, line number, and the raw message expression.

### 2I: Component Size Violations

CLAUDE.md mandates "Components under 200 lines." Check for violations:

```bash
# Count lines in each .tsx component file
find frontend/components -name "*.tsx" -exec wc -l {} + | sort -rn | head -30
```

Report every `.tsx` file exceeding 200 lines with its line count.

- Severity: **Medium** for 200–300 lines, **High** for 300+ lines
- Do NOT flag: test files, type-only files, `design-system.ts`

### 2J: Bundle-Hostile Imports

Check for imports that defeat tree-shaking and bloat the bundle:

```bash
# Barrel imports from large libraries (should use deep imports)
grep -rn "from 'lodash'" frontend/ --include="*.ts" --include="*.tsx" | grep -v node_modules
grep -rn "from 'date-fns'" frontend/ --include="*.ts" --include="*.tsx" | grep -v node_modules | grep -v "from 'date-fns/"

# Importing entire icon libraries instead of individual icons
grep -rn "from 'lucide-react'" frontend/ --include="*.ts" --include="*.tsx" | grep -v node_modules
# Check if any import pulls in * or a very large named set
grep -rn "import \* as.*from\|import {[^}]*,[^}]*,[^}]*,[^}]*,[^}]*,[^}]*" frontend/ --include="*.ts" --include="*.tsx" | grep -v node_modules | head -10
```

Report findings:

- `from 'lodash'` instead of `from 'lodash/specificFunction'` → **Medium**
- `import *` from large libraries → **Medium**
- `from 'lucide-react'` is fine (it supports tree-shaking), skip unless importing `*`

### 2K: Missing Error Boundaries

Check that components with async operations or external data are wrapped in error boundaries:

```bash
# Find components that use async data fetching or external APIs
grep -rn "useEffect.*fetch\|useEffect.*api\.\|await " frontend/components/ --include="*.tsx" | grep -v __tests__ | awk -F: '{print $1}' | sort -u

# Check which components are wrapped in error boundaries
grep -rn "ErrorBoundary\|error-boundary" frontend/components/ --include="*.tsx" -l
```

Cross-reference: components with async operations that are NOT wrapped in any error boundary → report them.

- Severity: **Medium** for leaf components, **High** for route-level components
- Do NOT flag: components that only read from Zustand (no external data)

### 2L: Design System Token Compliance

Check for hardcoded values that should use `DS.*` tokens from `design-system.ts`:

```bash
# Hardcoded hex colors (should use DS.colors.*)
grep -rn "#[0-9a-fA-F]\{3,8\}" frontend/components/ --include="*.tsx" | grep -v __tests__ | grep -v "// hex" | head -20

# Hardcoded pixel values in Tailwind arbitrary syntax (should use DS tokens)
grep -rn "text-\[.*px\]\|p-\[.*px\]\|m-\[.*px\]\|gap-\[.*px\]\|rounded-\[.*px\]\|w-\[.*px\]\|h-\[.*px\]" frontend/components/ --include="*.tsx" | grep -v __tests__ | head -20

# Hardcoded rgba/hsl values
grep -rn "rgba\|hsla\|hsl(" frontend/components/ --include="*.tsx" | grep -v __tests__ | grep -v design-system | head -20

# Hardcoded font sizes outside DS
grep -rn "font-size:\|fontSize:" frontend/components/ --include="*.tsx" | grep -v __tests__ | grep -v design-system | head -10
```

Report findings:

- Hardcoded hex colors in component files → **Medium** (should reference DS tokens)
- Arbitrary Tailwind pixel values → **Low** (some are acceptable for one-off spacing)
- Skip: `globals.css` (may define CSS variables), `design-system.ts` itself, SVG fill/stroke values

### 2M: Client/Server Component Boundary

Next.js requires `'use client'` directive for components that use React hooks. Missing this causes runtime crashes in production.

```bash
# Find all .tsx files using hooks
HOOK_FILES=$(grep -rl "useState\|useEffect\|useRef\|useCallback\|useMemo\|useContext\|useReducer\|useDocumentStore\|useChatStore\|useUIStore\|useMobileNavStore\|useIsDesktop\|useMediaQuery" frontend/components/ --include="*.tsx" | grep -v node_modules | grep -v __tests__)

# Check which of those are missing 'use client'
for f in $HOOK_FILES; do
  head -3 "$f" | grep -q "'use client'\|\"use client\"" || echo "MISSING 'use client': $f"
done

# Also check hooks/ and lib/ files that export hooks
HOOK_EXPORTS=$(grep -rl "^export.*function use[A-Z]\|^export.*const use[A-Z]" frontend/hooks/ frontend/lib/ --include="*.ts" --include="*.tsx" 2>/dev/null | grep -v node_modules)

for f in $HOOK_EXPORTS; do
  head -3 "$f" | grep -q "'use client'\|\"use client\"" || echo "MISSING 'use client': $f"
done
```

Report:

- Component using hooks without `'use client'` → **Critical** (runtime crash: "useState is not a function")
- Hook file without `'use client'` that's imported by server components → **Critical**
- Skip: files in `app/` directory that are explicitly server components, type-only files

### 2N: Accessibility Baseline

Basic a11y scan for interactive elements. Not a full WCAG audit — just the most common blockers.

```bash
# 1. Icon-only buttons without accessible labels
grep -rn "<button" frontend/components/ --include="*.tsx" | grep -v "aria-label\|aria-labelledby\|title=" | grep -v __tests__ | head -20
# Cross-reference: which of those contain only an icon (no text children)?

# 2. Images without alt text
grep -rn "<img\|<Image" frontend/components/ --include="*.tsx" | grep -v "alt=" | grep -v __tests__ | head -10

# 3. Form inputs without labels or aria-label
grep -rn "<input\|<select\|<textarea" frontend/components/ --include="*.tsx" | grep -v "aria-label\|aria-labelledby\|id=.*htmlFor\|placeholder" | grep -v __tests__ | head -10

# 4. Click handlers on non-interactive elements (div, span)
grep -rn "<div.*onClick\|<span.*onClick" frontend/components/ --include="*.tsx" | grep -v "role=\|tabIndex\|button\|link" | grep -v __tests__ | head -10
```

Report:

- Icon-only buttons without aria-label → **Medium** (screen readers announce nothing)
- Images without alt text → **Low** (decorative images can use `alt=""`)
- Click handlers on `<div>`/`<span>` without `role` and `tabIndex` → **Medium** (keyboard users can't activate)
- Form inputs without labels → **Medium**
- Do NOT flag: decorative elements, Mapbox internal elements, shadcn/ui primitives (they handle a11y internally)

### 2O: Prompt Suggestion Actionability & Chat UX Contracts

Ensure chat suggestions are either actionable backend intents or explicit UI-open actions, never dead-end text.

```bash
# Suggestion/chip generation and click handling
grep -rn "suggestion\|quick action\|quick_action\|chip\|handleSuggestion\|onSuggestionClick" frontend/components/ frontend/hooks/ frontend/state/ --include="*.ts" --include="*.tsx" | grep -v __tests__

# Routes/actions that open input pills (calendar, budget, activities, origin)
grep -rn "open.*calendar\|open.*budget\|open.*activit\|open.*origin\|set.*Pill\|set.*Modal" frontend/components/ frontend/hooks/ frontend/state/ --include="*.ts" --include="*.tsx" | grep -v __tests__

# Prevent destructive commands from plain chat text (reset, destination switch)
grep -rn "reset\|switch to\|change to\|destination" frontend/components/chat frontend/hooks frontend/state backend/app/planner backend/app/main.py --include="*.ts" --include="*.tsx" --include="*.py" | grep -v __tests__ | grep -v __pycache__

# Plan view gate logic (must require destination + dates)
grep -rn "plan_view_state\|S1_DESTINATION_SET\|S2_STRATEGY_READY\|S4_ITINERARY\|destination\|start_date\|end_date" frontend/state frontend/lib backend/app/planner --include="*.ts" --include="*.tsx" --include="*.py" | grep -v __tests__ | grep -v __pycache__
```

Report:

- Suggestion chip text implies an action but has no bound action/intent metadata → **High** (dead-end UX)
- Suggestion click injects text that does nothing (no backend intent and no UI-open behavior) → **High**
- Typing `reset` in chat triggers reset/destructive state mutation → **Critical** (reset must be UI-button only)
- Destination can be changed after lock without explicit reset flow → **High**
- Itinerary/plan view unlocks with destination only (missing dates) → **Critical** (invalid plan gate)
- Chat surfaces internal operation/debug strings instead of assistant copy → **High**

---

## Phase 3: Cross-Stack

### 3A: Schema Drift

```bash
# Compare backend Pydantic fields with frontend TypeScript types
# Check PlanDocumentData fields
grep -n "class PlanDocumentData" backend/app/schemas.py -A 30
grep -n "PlanDocumentData\|PlanDocumentResponse" frontend/types/ --include="*.ts" -r
```

If fields exist in backend but not frontend (or vice versa), include in report.

### 3B: Dead API Endpoints

```bash
# List all backend endpoints
grep -n "@app\.\(get\|post\|patch\|delete\|put\)" backend/app/main.py | awk -F'"' '{print $2}'

# Check each is called from frontend
# grep -rn "/api/endpoint-path" frontend/ --include="*.ts" --include="*.tsx"
```

Endpoints with zero frontend callers AND not in admin routes → include in report.

### 3C: Environment Variable Drift

Check that env vars defined in `.env` / `.env.local` are actually used, and that env vars read in code are actually defined.

```bash
# 1. Backend: all env vars accessed in code (extract var names)
grep -rn "os\.environ\|os\.getenv\|environ\.get\|environ\[" backend/app/ --include="*.py" | grep -v __pycache__ | grep -v test_

# 2. Frontend: all env vars accessed in code (extract var names)
grep -rn "process\.env\." frontend/ --include="*.ts" --include="*.tsx" | grep -v node_modules | grep -v __tests__ | grep -v ".next/"

# 3. Read actual .env files to get defined vars
cat backend/.env 2>/dev/null | grep -v "^#\|^$" | awk -F= '{print $1}' | sort
cat frontend/.env.local 2>/dev/null | grep -v "^#\|^$" | awk -F= '{print $1}' | sort

# 4. Also check .env.example files for documented expectations
cat backend/.env.example 2>/dev/null || echo "No backend .env.example found"
cat frontend/.env.example 2>/dev/null || cat frontend/.env.local.example 2>/dev/null || echo "No frontend .env.example found"

# 5. Check for env vars used without fallback defaults (will crash if missing)
grep -rn 'os\.environ\[' backend/app/ --include="*.py" | grep -v __pycache__ | grep -v test_
grep -rn 'os\.getenv(' backend/app/ --include="*.py" | grep -v __pycache__ | grep -v test_ | grep -v ", "
# (os.getenv without a second arg returns None — may cause downstream TypeError)

# 6. Pydantic settings fields in config.py — each field maps to an env var that must be defined
# Extract all field names from the Settings class (these are read automatically by pydantic-settings)
grep -n "^\s\+[a-z_]\+\s*:" backend/app/config.py | grep -v __pycache__
# Cross-reference: for each field, check if the corresponding env var (uppercased field name) is in .env
```

Cross-reference and report:

- **Defined in .env but never read in code** → **Medium** (dead config, cleanup candidate)
- **Read in code but not defined in .env/.env.local** → **High** (will be `None`/`undefined` at runtime; new devs will hit errors)
- **Read with `os.environ[]` (hard crash if missing) but not in .env** → **Critical** (KeyError on startup)
- **Read with `os.getenv()` without a default AND used without None-check** → **High** (silent `None` propagation)
- **Frontend `process.env.NEXT_PUBLIC_*` used but not in `.env.local`** → **High** (will be `undefined`, may cause hydration mismatch or runtime error)
- **Env vars in `.env.example` but not in actual `.env`/`.env.local`** → **Medium** (setup docs are stale)
- **Pydantic `Settings` field in `config.py` with no default AND no matching entry in `.env`** → **Critical** (pydantic-settings raises `ValidationError` on startup if a required field has no env var and no default)
- **Pydantic `Settings` field referencing a model name (e.g., `*_model`) with no `.env` entry** → **High** (LLM factory will receive `None` or the Pydantic default, silently using wrong model)
- Do NOT read or report the actual VALUES of any env vars — only report variable names. Never print secrets.

### 3D: Alembic Migration Health

```bash
# Check for multiple migration heads (should be exactly 1)
cd backend && alembic heads 2>&1

# Check current migration state
cd backend && alembic current 2>&1

# Look for migration files without proper down_revision chain
grep -rn "down_revision" backend/migrations/versions/*.py 2>/dev/null
```

Report:

- Multiple heads → **Critical** (migrations will fail on deploy)
- Broken down_revision chain → **Critical**
- If `alembic heads` returns more than one hash, flag immediately

### 3E: Dependency Health

```bash
# Frontend: check for known vulnerabilities
cd frontend && npm audit --omit=dev 2>&1 | tail -20

# Frontend: find unused dependencies (installed but never imported)
# For each dependency in package.json "dependencies", check if it's imported
cat frontend/package.json | python3 -c "
import json, sys
pkg = json.load(sys.stdin)
for dep in sorted(pkg.get('dependencies', {})):
    print(dep)
" 2>/dev/null

# For each listed dependency, check if it appears in any import statement
# grep -rn "from 'dep-name'\|require('dep-name')" frontend/ --include="*.ts" --include="*.tsx" --include="*.mjs" | grep -v node_modules

# Backend: check for unused requirements
# For each package in requirements.txt, check if it's imported
grep -v "^#\|^$\|^-" backend/requirements.txt | awk -F'[=><]' '{print $1}' | sort
```

For each dependency:

- Grep the codebase for its import. If zero matches → report as potentially unused.
- Do NOT flag: transitive dependencies (e.g., `types/*` packages), build tools (`typescript`, `eslint`), runtime-only deps (`dotenv`), or framework peers (`react-dom`).
- npm audit critical/high vulnerabilities → **High**
- Unused dependencies → **Medium**

### 3F: CORS & Security Headers

Verify that CORS configuration and security headers are production-safe.

```bash
# 1. CORS configuration
grep -rn "CORSMiddleware\|allow_origins\|allow_methods\|allow_credentials\|allow_headers" backend/app/main.py

# 2. Security headers middleware
grep -rn "X-Content-Type-Options\|X-Frame-Options\|Strict-Transport-Security\|X-XSS-Protection\|Content-Security-Policy\|Referrer-Policy" backend/app/main.py

# 3. Check if CORS origins are env-driven or hardcoded
grep -rn "allow_origins" backend/app/main.py | grep -v "settings\.\|os\.environ\|os\.getenv"
```

Report:

- `allow_origins=["*"]` in production config (not gated by debug/dev flag) → **Critical** (any domain can call your API)
- `allow_credentials=True` combined with wildcard origins → **Critical** (browsers reject this, but it signals misconfiguration)
- Missing `X-Content-Type-Options: nosniff` → **High**
- Missing `X-Frame-Options` → **Medium** (clickjacking protection)
- Missing `Strict-Transport-Security` → **Medium** (HTTPS downgrade protection)
- Hardcoded origin list instead of env-driven → **Medium** (can't change without redeploy)
- Skip: development-only CORS settings gated by `DEBUG` or `settings.debug`

### 3G: Middleware Ordering & Preflight Safety

Starlette middleware executes in LIFO order (`app.add_middleware()` first → runs last). Incorrect ordering causes CORS preflight failures, rate limiter false-positives on OPTIONS, CSRF blocking of browser preflight, and security headers missing from error responses.

#### 3G-1: Middleware Registration Order

```bash
# Catalog all middleware registrations in order (both app.add_middleware and @app.middleware)
grep -n "app\.add_middleware\|@app\.middleware" backend/app/main.py
```

Verify the effective execution order (LIFO for `add_middleware`, top-down for `@app.middleware("http")`):

- CORSMiddleware must execute **after** (i.e., be added **before**) any rate limiter or auth middleware → if not, **Critical** (preflight OPTIONS hits rate limiter/auth before CORS can short-circuit it)
- Security headers middleware should execute last (added first) so headers appear on ALL responses including error responses → if not, **Medium**
- SessionMiddleware must execute before any middleware that reads `request.cookies` or session state → if not, **High**

#### 3G-2: OPTIONS Preflight Rate Limiting

Rate limiters (slowapi, custom middleware) must exempt `OPTIONS` preflight requests. Browsers send `OPTIONS` before every cross-origin request — if these count against rate limits, legitimate users get 429 errors.

```bash
# 1. Check if rate limiter exempts OPTIONS
grep -rn "OPTIONS\|preflight\|_rate_limiting_complete" backend/app/ --include="*.py" | grep -v __pycache__ | grep -v test_

# 2. Check slowapi/limiter configuration for preflight handling
grep -rn "Limiter\|limiter\.\|@limiter" backend/app/ --include="*.py" | grep -v __pycache__ | grep -v test_

# 3. Check if a shared rate-limit bucket exists for OPTIONS (anti-pattern: all users share one bucket)
grep -rn "preflight\|__preflight__\|shared.*bucket\|OPTIONS.*key" backend/app/ --include="*.py" | grep -v __pycache__ | grep -v test_
```

Report:

- No OPTIONS exemption in rate limiter → **Critical** (preflight requests consume user's rate budget; under CORS-heavy usage, legitimate requests get 429)
- Shared rate-limit bucket for all OPTIONS requests (e.g., returning a fixed key for all preflights) → **High** (all users share one bucket; any user's preflight traffic exhausts the limit for everyone)
- `request.state._rate_limiting_complete = True` set for OPTIONS before route handlers → OK (correct slowapi exemption pattern)
- Rate limiter key function returns different keys for OPTIONS vs actual requests but still counts OPTIONS → **Medium** (separate budget but still unnecessary counting)

#### 3G-3: CSRF & Auth on Preflight

CSRF middleware and authentication checks must not block `OPTIONS` requests. Browsers do not send cookies, CSRF tokens, or auth headers on preflight.

```bash
# 1. Check CSRF middleware for OPTIONS exemption
grep -rn "CSRF\|csrf\|X-CSRF\|_csrf" backend/app/ --include="*.py" | grep -v __pycache__ | grep -v test_

# 2. Check auth/session middleware for OPTIONS handling
grep -rn "authorization\|Authorization\|Bearer\|session_id\|authenticate" backend/app/main.py | grep -v __pycache__ | grep -v test_ | grep -v "# "
```

Report:

- CSRF middleware blocks OPTIONS requests → **Critical** (all cross-origin POST/PATCH/DELETE preflight fails with 403)
- Auth middleware rejects OPTIONS for missing credentials → **Critical** (preflight never carries auth headers)
- CSRF/auth middleware explicitly skips OPTIONS → OK

#### 3G-4: Middleware Error Response Headers

When middleware raises an error (e.g., 429 from rate limiter, 403 from CSRF), the response must still include CORS headers. Otherwise, the browser cannot read the error and shows an opaque "CORS error" instead of the actual status code.

```bash
# Check if error responses from middleware include CORS headers
# Look for PlainTextResponse, JSONResponse, or Response in middleware that might skip CORS
grep -rn "PlainTextResponse\|JSONResponse\|Response(" backend/app/main.py | grep -v "StreamingResponse\|# "
```

Report:

- Rate limiter 429 response missing `Access-Control-Allow-Origin` header → **High** (browser shows generic CORS error instead of rate limit message; frontend can't distinguish 429 from network failure)
- CSRF 403 response missing CORS headers → **High** (same problem)
- All middleware error responses include CORS headers (or CORSMiddleware wraps them) → OK

### 3H: Expand-Itinerary Idempotency & Stream Contract

Verify duplicate itinerary expansion requests are idempotent and emit a stable terminal stream contract.

```bash
# Backend idempotency, inflight lock, duplicate short-circuit markers
grep -rn "expand_itinerary\|inflight\|idempot\|duplicate_noop\|already_in_progress" backend/app/main.py backend/app/services/ backend/app/planner/ --include="*.py" | grep -v __pycache__

# Stream response framing and terminal events
grep -rn "StreamingResponse\|text/event-stream\|application/x-ndjson\|yield .*\\\"done\\\"\|yield .*duplicate_noop" backend/app/main.py backend/app/services/ --include="*.py" | grep -v __pycache__

# Frontend handling of duplicate_noop/done terminal cases
grep -rn "duplicate_noop\|already_in_progress\|expand-itinerary\|expandItinerary" frontend/components/ frontend/hooks/ frontend/state/ frontend/lib/ --include="*.ts" --include="*.tsx" | grep -v __tests__

# Contract tests for first-call and duplicate-call behavior
grep -rn "expand_itinerary\|duplicate_noop\|stream contract\|test_expand_itinerary" backend/tests/ frontend/__tests__/ --include="*.py" --include="*.ts" --include="*.tsx"
```

Report:

- Duplicate request path can run full expansion work again (no lock/idempotency guard) → **Critical**
- Duplicate request returns non-terminal or malformed stream (no `done` frame) → **Critical** (frontend hangs/spins)
- Frontend treats duplicate-noop as error and retries, causing call storms → **High**
- Duplicate request response leaks internal debug/diff payload into chat UI → **High**
- Missing tests that assert first-call + duplicate-call terminal behavior → **High**

---

## Phase 4: Project Invariant Verification

Verify CLAUDE.md hard rules are not violated in the codebase.

### 4A: 7-Node LangGraph Invariant

```bash
# Count nodes registered in plan_graph.py
grep -n "add_node\|\.add_node" backend/app/plan_graph.py
```

Count the total number of `add_node` calls. If not exactly 7, report as **Critical**.
List each registered node name for verification.

### 4B: Coordinate Format Invariant

CLAUDE.md mandates `[lng, lat]` format throughout the entire pipeline. Check for violations:

```bash
# Backend: look for lat/lng ordering hints in variable names or comments
grep -rn "lat.*lng\|latitude.*longitude" backend/app/ --include="*.py" | grep -v __pycache__ | grep -v "lng.*lat\|longitude.*latitude"

# Frontend: same check
grep -rn "lat.*lng\|latitude.*longitude" frontend/ --include="*.ts" --include="*.tsx" | grep -v node_modules | grep -v __tests__ | grep -v "lng.*lat\|longitude.*latitude"

# Check for [lat, lng] array construction (wrong order)
grep -rn "\[.*lat.*,.*lng\|LatLng\|latLng" backend/app/ frontend/ --include="*.py" --include="*.ts" --include="*.tsx" | grep -v node_modules | grep -v __pycache__
```

Report any instances where coordinates appear in `[lat, lng]` order instead of `[lng, lat]`.

- Severity: **Critical** (will cause map pins and routing to be wrong)
- Skip: third-party library type definitions, Mapbox API calls (Mapbox uses `[lng, lat]` natively)

### 4C: Hardcoded World Data & Matching Lists

CLAUDE.md mandates "no hard-coded world data." Beyond that, any hardcoded matching list that maps real-world concepts (cities, airports, activities, synonyms) is a maintenance burden and will become stale. Flag them all.

#### 4C-1: Hardcoded Geographic Data

```bash
# 1. Hardcoded city-to-airport mappings (should use iata_resolver.py LLM-backed resolution)
grep -rn "CITY_TO_AIRPORT\|city_to_airport\|airport_map\|airport_code" backend/app/ --include="*.py" | grep -v __pycache__ | grep -v test_ | grep -v iata_resolver

# 2. Hardcoded IATA codes as string literals in planner/service logic
grep -rn '"[A-Z]\{3\}"' backend/app/ --include="*.py" | grep -v __pycache__ | grep -v test_ | grep -v "\.txt\|\.md" | grep -v "iata_resolver\|# \|def \|class \|example\|e\.g\." | head -20

# 3. Hardcoded city/country names in logic (not in prompts or demo data)
grep -rn "\"Paris\"\|\"Tokyo\"\|\"London\"\|\"New York\"\|\"Dubai\"\|\"Bali\"\|\"Maldives\"" backend/app/ --include="*.py" | grep -v __pycache__ | grep -v test_ | grep -v placeholders | grep -v demo_curation | grep -v "\.txt" | head -15

# 4. Frontend: hardcoded location data outside destination-coords.ts
grep -rn "\"Paris\"\|\"Tokyo\"\|\"London\"\|\"New York\"\|\"Dubai\"\|\"Bali\"" frontend/lib/ frontend/components/ --include="*.ts" --include="*.tsx" | grep -v node_modules | grep -v __tests__ | grep -v destination-coords | grep -v placeholders | head -10
```

Report:

- `CITY_TO_AIRPORT` dict in `amadeus_client.py` → **High** (hardcoded city→airport map; should use `iata_resolver.py` which is LLM-backed)
- Hardcoded IATA codes in planner/service logic → **High**
- Hardcoded city names in conditionals or mappings → **High** (won't scale, will miss destinations)
- Skip: test fixtures, demo/curated data (`demo_curation.py`), placeholder text, prompt templates, `destination-coords.ts`

#### 4C-2: Hardcoded Activity / Category Matching Lists

```bash
# 1. Activity type keyword lists (should be data-driven or registry-driven)
grep -rn "_KEYWORDS\s*=\|_SYNONYMS\s*=\|_ALIASES\s*=\|_HINTS\s*=\|_CATEGORIES\s*=" backend/app/ --include="*.py" | grep -v __pycache__ | grep -v test_
grep -rn "KEYWORDS\s*=\|SYNONYMS\s*=\|ALIASES\s*=" frontend/ --include="*.ts" --include="*.tsx" | grep -v node_modules | grep -v __tests__

# 2. Activity category alias dicts (e.g., mapping "scuba" → "diving")
grep -rn "CATEGORY_ALIASES\|ACTIVITY_ALIASES\|_ALIASES:\s*dict" backend/app/ --include="*.py" | grep -v __pycache__ | grep -v test_

# 3. Hardcoded tile type keywords in frontend
grep -rn "FLIGHT_TYPE_KEYWORDS\|ACTIVITY_TYPE_KEYWORDS\|HOTEL_TYPE_KEYWORDS\|ALL_CATEGORIES" frontend/ --include="*.ts" --include="*.tsx" | grep -v node_modules | grep -v __tests__
```

For each hardcoded list, assess:

- **Is this the SSoT?** If the list lives in `specialist_registry.py` (backend SSoT) or `specialists.ts` (frontend SSoT), it's the canonical source — note it but **Low** severity
- **Is this a duplicate of the SSoT?** If the same keywords/aliases appear in another file, it's a duplication → **High** (will drift from SSoT)
- **Should this be LLM-driven instead?** If the list maps user input to internal categories (e.g., "scuba" → "diving"), an LLM classifier is more robust → **Medium** (flag as candidate for LLM migration)
- **Is this an unbounded real-world domain?** Airport codes, city names, cuisine types — these will always be incomplete → **High** (hardcoded list will miss valid inputs)

#### 4C-3: Hardcoded Pattern Matching (Regex Lists)

```bash
# 1. Backend: regex pattern lists for intent/input parsing
grep -rn "_PATTERNS\s*=\s*[\[\(]\|_PATTERNS\s*=\s*(" backend/app/ --include="*.py" | grep -v __pycache__ | grep -v test_

# 2. Specific known pattern lists
grep -rn "BUDGET_PATTERNS\|TRAVELER_PATTERNS\|HOTEL_PATTERNS\|FLIGHT_PATTERNS\|ORIGIN_PATTERNS\|FLEXIBLE_DATE_KEYWORDS\|SETTINGS_KEYWORDS" backend/app/ --include="*.py" | grep -v __pycache__ | grep -v test_

# 3. Frontend: pattern matching lists
grep -rn "_PATTERNS\s*=\s*\[" frontend/ --include="*.ts" --include="*.tsx" | grep -v node_modules | grep -v __tests__
```

Report:

- Regex lists used for intent classification that duplicate what the LLM router already does → **Medium** (redundant with `router_extraction.py` LLM extraction; will miss edge cases the LLM handles)
- Regex lists used as pre-filters or fast-path shortcuts before LLM → **Low** (acceptable optimization, but document)
- Pattern lists that parse user-facing natural language (e.g., budget amounts, traveler counts) → **Medium** (fragile; "2 adults and a kid" may not match `TRAVELER_PATTERNS`)

#### 4C-4: Hardcoded Greeting / Farewell Lists

```bash
# Greeting/farewell word lists
grep -rn "GREETINGS\|FAREWELL\|greeting_patterns\|EXACT_MATCH" backend/app/ --include="*.py" | grep -v __pycache__ | grep -v test_
```

Report:

- Greeting lists used for exact-match fast-path → **Low** (acceptable: these are finite and rarely change)
- Greeting lists that duplicate across files → **High** (should be single SSoT)
- Note: these are the one category of hardcoded list that's generally acceptable — greetings are a closed set

#### 4C-5: Inventory All Hardcoded Lists

Produce a complete inventory of every hardcoded constant list/dict in both stacks:

```bash
# Backend: all module-level list/dict/set/frozenset constants (uppercase or _prefixed)
grep -rn "^[A-Z_][A-Z_0-9]*\s*=\s*[\[\{(]\|^[A-Z_][A-Z_0-9]*\s*:\s*\(dict\|list\|set\|frozenset\)" backend/app/ --include="*.py" | grep -v __pycache__ | grep -v test_ | grep -v migrations | head -40

# Frontend: all module-level const arrays/objects
grep -rn "^const [A-Z_][A-Z_0-9]*\s*=\s*[\[\{]\|^const [A-Z_][A-Z_0-9]*\s*:" frontend/lib/ frontend/components/ --include="*.ts" --include="*.tsx" | grep -v node_modules | grep -v __tests__ | grep -v design-system | head -30
```

For each list, categorize:

- **Configuration** (e.g., TTL values, feature flags) → OK, skip
- **UI constants** (e.g., DS tokens, animation timings) → OK, skip
- **Real-world data** (e.g., cities, airports, cuisines) → **High** (will be incomplete)
- **Synonym/alias mappings** (e.g., "scuba"→"diving") → **Medium** (candidate for LLM or registry)
- **Pattern matching** (e.g., regex for parsing) → **Medium** (fragile)
- **Error suppression patterns** (e.g., Mapbox error strings) → **Low** (acceptable, tied to specific library versions)

### 4D: Component Size Invariant Cross-Check

This is a cross-check for 2H at the project-rule level. If any `.tsx` component exceeds 200 lines (per CLAUDE.md), flag it as an invariant violation here as well.

### 4E: LLM Factory Compliance

CLAUDE.md mandates all LLM usage goes through `llm_factory.py` with model strings from `settings.*_model`. Check for violations.

```bash
# 1. Direct LLM constructors (should use llm_factory.get_llm_by_model or equivalent)
grep -rn "ChatOpenAI(\|ChatGoogleGenerativeAI(\|ChatAnthropic(\|AsyncOpenAI(" backend/app/ --include="*.py" | grep -v __pycache__ | grep -v test_ | grep -v llm_factory

# 2. Hardcoded model strings (should reference settings.*_model)
grep -rn '"gpt-4o"\|"gpt-4o-mini"\|"gpt-4-turbo"\|"gemini-2.5-flash"\|"gemini-2.5-pro"\|"claude-3"\|"claude-sonnet"\|"claude-haiku"' backend/app/ --include="*.py" | grep -v __pycache__ | grep -v test_ | grep -v config\.py | grep -v debug_utils

# 3. Provider-specific params leaked outside factory (should be encapsulated in llm_factory)
grep -rn "max_output_tokens\|thinking_budget\|model_kwargs\|include_thoughts" backend/app/planner/nodes/ --include="*.py" | grep -v __pycache__

# 4. Direct langchain provider imports in node code (should import from llm_factory)
grep -rn "from langchain_openai\|from langchain_google_genai\|from langchain_anthropic" backend/app/planner/nodes/ --include="*.py" | grep -v __pycache__ | grep -v test_
```

Report:

- Direct LLM constructor in node/service code (bypassing factory) → **Critical** (breaks provider portability, ignores config)
- Hardcoded model string outside `config.py` → **High** (can't change model without code change)
- Provider-specific params in node code → **Medium** (couples node to specific provider; should be in factory)
- Direct langchain provider imports in nodes → **High** (tight coupling; factory should be the only import)
- Skip: `llm_factory.py` itself, `config.py` (where settings are defined), `debug_utils.py` (pricing tables), test files

### 4G: OpenAI vs Gemini Structured Output Compatibility

Both `ChatOpenAI` and `ChatGoogleGenerativeAI` are used via `llm_factory.py`. Each provider has different constraints for structured output and tool calling. Verify that every call site is compatible with **both** providers — i.e., the factory can swap providers without breaking the call.

```bash
# 1. Find all with_structured_output() calls across the codebase
grep -rn "with_structured_output(" backend/app/ --include="*.py" | grep -v __pycache__ | grep -v test_

# 2. Check for method="json_mode" — NOT supported by Gemini (Gemini uses native function calling)
grep -rn 'with_structured_output.*method.*=.*"json_mode"\|with_structured_output.*method.*=.*json_mode' backend/app/ --include="*.py" | grep -v __pycache__ | grep -v test_

# 3. Check for method="function_calling" — supported by both, but verify it's not hardcoded to OpenAI-only params
grep -rn 'with_structured_output.*method.*=.*"function_calling"' backend/app/ --include="*.py" | grep -v __pycache__ | grep -v test_

# 4. Check for include_raw=True — behavior differs: OpenAI returns AIMessage, Gemini may not populate 'raw' consistently
grep -rn 'with_structured_output.*include_raw.*=.*True' backend/app/ --include="*.py" | grep -v __pycache__ | grep -v test_

# 5. Check for strict=True — OpenAI-only param, silently ignored or errors on Gemini
grep -rn 'with_structured_output.*strict.*=.*True' backend/app/ --include="*.py" | grep -v __pycache__ | grep -v test_

# 6. Check llm_factory.py for how it handles provider-specific structured output differences
grep -n "with_structured_output\|json_mode\|function_calling\|structured_output\|provider" backend/app/planner/llm_factory.py

# 7. Check for OpenAI response_format param (not supported by Gemini via LangChain)
grep -rn "response_format" backend/app/ --include="*.py" | grep -v __pycache__ | grep -v test_ | grep -v llm_factory

# 8. Check for bind_tools() calls — tool schemas must be JSON-schema compatible for both providers
grep -rn "bind_tools\|\.bind(" backend/app/ --include="*.py" | grep -v __pycache__ | grep -v test_

# 9. Check for Pydantic models used as structured output schemas — both providers support this, but verify no OpenAI-specific field metadata
grep -rn "with_structured_output(.*Model\|with_structured_output(.*Schema\|with_structured_output(.*Output\|with_structured_output(.*Response" backend/app/planner/nodes/ --include="*.py" | grep -v __pycache__ | grep -v test_

# 10. Check for any direct ChatOpenAI or ChatGoogleGenerativeAI calls that set provider-specific invoke params
grep -rn "\.invoke(\|\.ainvoke(" backend/app/planner/nodes/ backend/app/services/ --include="*.py" | grep -v __pycache__ | grep -v test_ | grep -v "llm_factory\|#"

# 11. Check for OpenAI-specific token_usage key in response_metadata (Gemini uses usage_metadata instead)
# Sites that access result["raw"].response_metadata.get("token_usage") will silently return {} for Gemini
grep -rn 'response_metadata.*token_usage\|token_usage.*response_metadata' backend/app/ --include="*.py" | grep -v __pycache__ | grep -v test_

# Cross-reference: sites using include_raw=True should use usage_metadata for Gemini compat
# (Gemini: response.usage_metadata["input_tokens"/"output_tokens"], OpenAI: response_metadata["token_usage"])
grep -rn "usage_metadata\|token_usage" backend/app/planner/nodes/ backend/app/services/ --include="*.py" | grep -v __pycache__ | grep -v test_
```

For each finding, assess:

- `method="json_mode"` passed to `with_structured_output` → **Critical** (Gemini does not support `json_mode`; will fail at runtime when Gemini model is configured)
- `strict=True` in `with_structured_output` → **High** (OpenAI-only param; harmless on Gemini today but may error on future LangChain versions)
- `include_raw=True` without provider guard → **Medium** (raw message shape differs between OpenAI and Gemini; downstream parsing may fail)
- `response_format` kwarg set outside `llm_factory.py` → **High** (OpenAI-only; Gemini ignores or errors)
- `bind_tools()` with OpenAI-specific tool schema fields (e.g., `strict`, `additionalProperties: false`) → **Medium** (may silently be ignored by Gemini or cause validation errors)
- Factory correctly dispatches provider-specific params internally → **OK** (this is the expected pattern)
- Any `.invoke()` or `.ainvoke()` call passing provider-specific kwargs directly (not via factory) → **High** (bypasses factory abstraction)
- `result["raw"].response_metadata.get("token_usage")` after `include_raw=True` → **High** (OpenAI-specific key; Gemini populates `usage_metadata` with `input_tokens`/`output_tokens` instead — token tracking silently returns `{}` for all Gemini calls)

Skip: `llm_factory.py` itself (it owns provider dispatch), `config.py`, `debug_utils.py`, test files.

### 4F: State Machine Transition Integrity

PlanViewState transitions are a core invariant. The backend is SSoT for plan_view_state — the frontend should never fabricate states.

```bash
# 1. Backend: verify _compute_plan_view_state covers all enum values
grep -rn "PlanViewState\." backend/app/planner/services/response_envelope.py | grep -v __pycache__

# 2. All PlanViewState enum values
grep -rn "class PlanViewState\|S0_\|S1_\|S2_\|S3_\|S4_\|S5_" backend/app/schemas.py | grep -v __pycache__

# 3. Frontend: check for plan_view_state being SET (not just read) outside of API response handling
grep -rn "plan_view_state\s*[:=]\|setPlanViewState\|plan_view_state:" frontend/state/ frontend/lib/ frontend/components/ --include="*.ts" --include="*.tsx" | grep -v __tests__ | grep -v "// \|type \|interface " | head -20

# 4. Frontend: raw string comparisons instead of typed constants
grep -rn "'S0_EMPTY'\|'S1_DESTINATION_SET'\|'S2_STRATEGY_READY'\|'S3_PARTIAL'\|'S4_ITINERARY'\|'S5_BOOKABLE'" frontend/ --include="*.ts" --include="*.tsx" | grep -v node_modules | grep -v __tests__ | grep -v types/ | head -20
```

Report:

- Frontend code that sets/fabricates plan_view_state (outside of hydrating from API response) → **Critical** (violates backend SSoT invariant)
- Exception: `S1_DESTINATION_SET` may be set client-side as an allowed special case — verify against UX spec
- PlanViewState enum value in backend not handled by `_compute_plan_view_state` → **High** (unreachable state)
- Raw string comparisons instead of typed enum/constant → **Medium** (typo-prone, refactor candidate)
- Frontend logic that infers plan_view_state from other fields instead of reading the backend-computed value → **High**

---

## Phase 5: TODO / Placeholder Comment Audit

Scan source code for unresolved TODO, FIXME, HACK, XXX, and PLACEHOLDER comments. These are implementation debts left in code — not documentation — and should be inventoried and classified.

### 5A: Backend Python

```bash
# All TODO/FIXME/HACK/XXX comments in backend source
grep -rn "TODO\|FIXME\|HACK\|XXX\|PLACEHOLDER\|NOT IMPLEMENTED\|stub" backend/app/ --include="*.py" | grep -v __pycache__ | grep -v test_ | grep -v migrations
```

For each finding:
- Extract the file, line number, and full comment text
- Classify:
  - `TODO: implement X` with no surrounding implementation → likely an unfinished stub
  - `FIXME: broken when Y` → known bug, flag as **High** if in a live code path
  - `HACK:` / `XXX:` → acknowledged workaround; flag as **Medium** and note the reason given
  - `# stub` / `raise NotImplementedError` in non-test code → **Critical** if reachable at runtime
  - `PLACEHOLDER` → **High** (often means the real implementation was never done)

### 5B: Frontend TypeScript

```bash
# All TODO/FIXME/HACK/XXX comments in frontend source
grep -rn "TODO\|FIXME\|HACK\|XXX\|PLACEHOLDER" frontend/components/ frontend/hooks/ frontend/lib/ frontend/state/ --include="*.ts" --include="*.tsx" | grep -v node_modules | grep -v __tests__
```

Apply the same classification as 5A.

### 5C: Unimplemented throw / NotImplementedError

```bash
# Python: raise NotImplementedError in non-test, non-abstract code
grep -rn "raise NotImplementedError" backend/app/ --include="*.py" | grep -v __pycache__ | grep -v test_

# TypeScript: throw new Error("not implemented") patterns
grep -rn "not implemented\|TODO: implement\|throw.*Error.*implement" frontend/ --include="*.ts" --include="*.tsx" | grep -v node_modules | grep -v __tests__
```

Report:
- `raise NotImplementedError` in a live code path (not abstract base class) → **Critical** (will crash at runtime if that path is reached)
- `throw new Error("not implemented")` in a component or hook → **High**
- In abstract base classes or explicitly optional method stubs → **Low** (document, don't flag as broken)

### 5D: Report Format

Include a dedicated section in the final report:

```
| TODO/Placeholder comments (backend) | X found | [severity range] | [count by type: TODO/FIXME/HACK/stub] |
| TODO/Placeholder comments (frontend) | X found | [severity range] | [count by type] |
| Unimplemented throws                 | X found | [severity]       | [files] |
```

List each finding with file path, line number, comment text, and severity.

---

## Phase 6: Report

Produce the final report in this format:

```
## Code Health Audit Report

| Category                      | Found | Severity | Notes |
|-------------------------------|-------|----------|-------|
| Unused imports                |       |          |       |
| Unused functions              |       |          |       |
| Dead components               |       |          |       |
| Sync-in-async                 |       |          |       |
| Thread safety & race conds    |       |          |       |
| Unnecessary re-renders        |       |          |       |
| Duplicate code                |       |          |       |
| Schema drift                  |       |          |       |
| Dead endpoints                |       |          |       |
| Security — code vulnerabilities |       |          |       |
| Abuse — rate limit coverage   |       |          |       |
| Abuse — spend guard scope     |       |          |       |
| Abuse — spend guard config    |       |          |       |
| Abuse — input size limits     |       |          |       |
| Abuse — session & auth        |       |          |       |
| Abuse — SSE/streaming hardening |      |          |       |
| CORS & security headers       |       |          |       |
| Middleware ordering & preflight |      |          |       |
| Circular imports              |       |          |       |
| Test coverage gaps            |       |          |       |
| Debug print/console pollution |       |          |       |
| Toast message quality         |       |          |       |
| Type errors                   |       |          |       |
| Component size violations     |       |          |       |
| Bundle-hostile imports        |       |          |       |
| Missing error boundaries      |       |          |       |
| DS token compliance           |       |          |       |
| Env variable drift            |       |          |       |
| Alembic migration health      |       |          |       |
| Dependency health             |       |          |       |
| Cache health — TTL consistency |       |          |       |
| Cache health — key collisions |       |          |       |
| Cache health — L1/L2 consistency |     |          |       |
| Cache health — invalidation   |       |          |       |
| Cache health — unbounded growth |      |          |       |
| Cache health — in-flight dedup |       |          |       |
| Cache health — stats API      |       |          |       |
| Resource lifecycle & leaks    |       |          |       |
| LLM output validation         |       |          |       |
| Google Places — Pro tier compliance |  |          |       |
| Google Places — spend guard coverage | |          |       |
| Google Places — circuit breaker |     |          |       |
| Google Places — error handling |      |          |       |
| Google Places — telemetry     |       |          |       |
| LangGraph node count          |       |          |       |
| Coordinate format violations  |       |          |       |
| Hardcoded lists & world data  |       |          |       |
| LLM factory compliance        |       |          |       |
| OpenAI/Gemini structured output compat |  |     |       |
| State machine transitions     |       |          |       |
| Client/server boundary        |       |          |       |
| Accessibility baseline        |       |          |       |
| TODO/placeholder comments (backend)  |  |       |       |
| TODO/placeholder comments (frontend) |  |       |       |
| Unimplemented throws          |       |          |       |

### Detailed Findings

[For each category with findings, list file paths, line numbers, and a brief description]

### Recommended Priority

[Order findings by severity: Critical > High > Medium > Low]
```

---

## Rules

- **REPORT ONLY. DO NOT MODIFY ANY FILES.** This is a read-only audit. No fixes, no deletions, no edits.
- **FULL REPO SCAN.** Scan the entire codebase unconditionally. Do NOT use `git diff`, `git status`, or any diff-based approach. Do NOT limit scope to recent changes.
- **CODE ONLY.** Do NOT scan, read, update, or reference documentation files (`.md`, `docs/`, `CLAUDE.md`, `README.md`). This audit covers source code exclusively (`.py`, `.ts`, `.tsx`).
- Produce a clear, actionable report with file paths and line numbers for every finding.
- Classify severity: Critical (runtime bugs, race conditions, security, invariant violations), High (dead code, sync-in-async, test gaps), Medium (unused imports, re-render issues, component size), Low (style, minor duplicates, console.log pollution).
- Do NOT flag functions that are part of public APIs, even if currently uncalled — note them as "possibly unused, verify externally".
- Do NOT suggest adding `useMemo`/`useCallback` everywhere — only flag where there's a measurable re-render problem.
- Do NOT suggest refactoring. This is a hygiene audit, not a rewrite proposal.
