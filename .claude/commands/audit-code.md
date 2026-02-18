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

### 1F: Security

Scan for common security vulnerabilities:

```bash
# 1. Hardcoded secrets, API keys, tokens in source files (not .env)
grep -rn "OPENAI_KEY\|api_key\|secret_key\|password\|token" backend/app/ --include="*.py" | grep -v __pycache__ | grep -v "os\.environ\|os\.getenv\|config\.\|\.env\|settings\." | grep -v "# \|def \|param\|argument\|type\|Optional\|str\|None"

# 2. Raw SQL strings (should use SQLAlchemy ORM/text() with bound params)
grep -rn "\.execute(f\"\|\.execute(f'\|\.execute(\"%s\|cursor\.\|raw_connection" backend/app/ --include="*.py" | grep -v __pycache__

# 3. Unsafe eval/exec/subprocess usage
grep -rn "eval(\|exec(\|subprocess\.\|os\.system(\|os\.popen(" backend/app/ --include="*.py" | grep -v __pycache__

# 4. Run detect-secrets scan against baseline
cd backend && detect-secrets scan --baseline ../.secrets.baseline 2>&1 || echo "detect-secrets not installed, skipping"
```

For each finding, assess:

- Hardcoded secrets → **Critical** if actual values, **Low** if just variable names referencing env
- Raw SQL → **Critical** if user input can reach it, **High** otherwise
- eval/exec/subprocess → **Critical** unless input is fully controlled
- Skip: test fixtures, mock data, comments explaining security patterns

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

The backend has a multi-tier caching system: `cache_core.py` (shared MemoryCache primitive), `router_cache.py` (L1-only), `specialist_cache.py` (L1+L2), `tile_cache.py` (L1+L2), `experience_generator.py` (L1+L2), and `cache_access.py` (planner-level cache handles). Audit for correctness across all cache layers.

#### 1J-1: TTL Consistency

```bash
# Check all TTL values across cache modules
grep -rn "TTL\|ttl\|_TTL_" backend/app/services/*cache*.py backend/app/planner/cache_access.py backend/app/services/experience_generator.py --include="*.py" | grep -v __pycache__

# Check L2 TTL vs L1 TTL — L2 should always be >= L1 to avoid serving stale L2 data that L1 has already evicted
```

Report:

- L2 TTL shorter than L1 TTL for the same cache domain → **High** (L1 evicts, L2 promotes stale data back)
- Inconsistent TTL values between related caches → **Medium**
- Missing TTL on any cache instantiation → **Critical**

#### 1J-2: Cache Key Collisions

```bash
# Check all cache key construction — should use make_cache_key from hashing.py
grep -rn "def.*cache_key\|make_cache_key\|cache_key =" backend/app/services/ backend/app/planner/ --include="*.py" | grep -v __pycache__

# Check namespace prefixes — each domain must use a unique prefix
grep -rn 'make_cache_key(' backend/app/services/ backend/app/planner/ --include="*.py" | grep -v __pycache__
```

Report:

- Cache key functions that DON'T use `make_cache_key` from `hashing.py` → **Medium** (inconsistent key format)
- Two different cache domains using the same namespace prefix → **Critical** (key collision across domains)
- Cache keys missing version token (e.g., "v2") → **Medium** (no safe cache invalidation on format change)

#### 1J-3: L1/L2 Consistency

```bash
# Check that every set operation writes to BOTH L1 and L2 (for L1+L2 caches)
grep -rn "def set_cached\|async def set_cached" backend/app/services/*cache*.py backend/app/services/experience_generator.py --include="*.py" | grep -v __pycache__
```

For each `set_cached_*` function in L1+L2 caches (`specialist_cache.py`, `tile_cache.py`, `experience_generator.py`), verify:

- L1 write (`_mem.set`) AND L2 write (`pg_insert` / db write) both happen → if only one, report as **High**
- L2 write failure is caught and doesn't crash the request → if uncaught, report as **High**
- L2 write failure doesn't leave L1 with data that L2 doesn't have (acceptable short-term, but document) → **Low**

#### 1J-4: Cache Invalidation

```bash
# Check for cache invalidation/clearing paths
grep -rn "cache_clear\|clear_cache\|clear_memory_cache\|\.clear()\|cache_pop\|cache_delete" backend/app/ --include="*.py" | grep -v __pycache__ | grep -v test_

# Check if invalidation clears BOTH L1 and L2 where applicable
grep -rn "def clear\|async def clear" backend/app/services/*cache*.py --include="*.py" | grep -v __pycache__
```

Report:

- Invalidation clears L1 but not L2 (or vice versa) → **High** (stale data survives in the other tier)
- No invalidation path exists for a cache domain → **Medium** (can only wait for TTL expiry)
- Invalidation called without proper lock → **High** (race condition)

#### 1J-5: Unbounded Cache Growth

```bash
# Check all MemoryCache / TTLCache instantiations for maxsize
grep -rn "MemoryCache(\|TTLCache(" backend/app/ --include="*.py" | grep -v __pycache__ | grep -v test_

# Check for raw dicts or lists used as ad-hoc caches without TTL/size limits
grep -rn "^_cache\s*=\s*{}\|^_cache\s*:\s*dict\|^CACHE\s*=" backend/app/ --include="*.py" | grep -v __pycache__
```

Report:

- `TTLCache` or `MemoryCache` without `maxsize` → **Critical** (unbounded memory growth)
- Raw `dict` used as cache without size limit or TTL → **High** (memory leak under load)
- `maxsize` set unreasonably high (>10000 for in-memory) → **Medium**

#### 1J-6: Direct Cache Bypass

```bash
# Check if any code accesses cache internals directly instead of using cache_access.py or service functions
grep -rn "TTLCache\|_cache\[" backend/app/planner/nodes/ --include="*.py" | grep -v __pycache__ | grep -v test_

# Check if node code imports cache modules directly instead of going through cache_access
grep -rn "from app.services.*cache import\|from app.planner.cache_access import" backend/app/planner/nodes/ --include="*.py" | grep -v __pycache__
```

Report:

- Node code directly accessing `TTLCache` internals (bypassing lock-protected accessors) → **Critical** (race condition)
- Inconsistent import patterns (some nodes using `cache_access`, others importing cache services directly) → **Medium**

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

Scan for common re-render causes:

```bash
# 1. Fat Zustand selectors (selecting entire objects instead of specific fields)
grep -rn "useDocumentStore((s\|state) =>" frontend/components/ --include="*.tsx" | grep -v "\.document\?\." | head -20

# 2. Inline object/array creation in JSX props (new reference every render)
grep -rn "style={{" frontend/components/ --include="*.tsx" | grep -v __tests__ | head -20

# 3. Inline arrow functions as event handlers in mapped lists
grep -rn "\.map.*onClick={() =>" frontend/components/ --include="*.tsx" | head -20

# 4. Missing useMemo/useCallback on expensive computations passed as props
grep -rn "useMemo\|useCallback" frontend/components/ --include="*.tsx" -l
```

Report findings with severity assessment:

- Fat selectors → report all
- Inline styles → report all
- Inline handlers in mapped lists → only flag if list is >20 items or handler triggers expensive re-renders
- Missing `useMemo` → only flag if computation is genuinely expensive

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

### 2H: Component Size Violations

CLAUDE.md mandates "Components under 200 lines." Check for violations:

```bash
# Count lines in each .tsx component file
find frontend/components -name "*.tsx" -exec wc -l {} + | sort -rn | head -30
```

Report every `.tsx` file exceeding 200 lines with its line count.

- Severity: **Medium** for 200–300 lines, **High** for 300+ lines
- Do NOT flag: test files, type-only files, `design-system.ts`

### 2I: Bundle-Hostile Imports

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

### 2J: Missing Error Boundaries

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

### 2K: Design System Token Compliance

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

### 2L: Client/Server Component Boundary

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

### 2M: Accessibility Baseline

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
```

Cross-reference and report:

- **Defined in .env but never read in code** → **Medium** (dead config, cleanup candidate)
- **Read in code but not defined in .env/.env.local** → **High** (will be `None`/`undefined` at runtime; new devs will hit errors)
- **Read with `os.environ[]` (hard crash if missing) but not in .env** → **Critical** (KeyError on startup)
- **Read with `os.getenv()` without a default AND used without None-check** → **High** (silent `None` propagation)
- **Frontend `process.env.NEXT_PUBLIC_*` used but not in `.env.local`** → **High** (will be `undefined`, may cause hydration mismatch or runtime error)
- **Env vars in `.env.example` but not in actual `.env`/`.env.local`** → **Medium** (setup docs are stale)
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

## Phase 5: Report

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
| Security vulnerabilities      |       |          |       |
| CORS & security headers       |       |          |       |
| Circular imports              |       |          |       |
| Test coverage gaps            |       |          |       |
| Debug print/console pollution |       |          |       |
| Type errors                   |       |          |       |
| Component size violations     |       |          |       |
| Bundle-hostile imports        |       |          |       |
| Missing error boundaries      |       |          |       |
| DS token compliance           |       |          |       |
| Env variable drift            |       |          |       |
| Alembic migration health      |       |          |       |
| Dependency health             |       |          |       |
| Cache health                  |       |          |       |
| Resource lifecycle & leaks    |       |          |       |
| LLM output validation         |       |          |       |
| LangGraph node count          |       |          |       |
| Coordinate format violations  |       |          |       |
| Hardcoded lists & world data  |       |          |       |
| LLM factory compliance        |       |          |       |
| State machine transitions     |       |          |       |
| Client/server boundary        |       |          |       |
| Accessibility baseline        |       |          |       |

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
