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

### 1D: Race Conditions

Check for unprotected shared mutable state:

```bash
# Module-level mutable state (dicts, lists, sets) that could be accessed by concurrent requests
grep -rn "^[A-Z_]*: dict\|^[A-Z_]*: list\|^[A-Z_]* = {}\|^[A-Z_]* = \[\]" backend/app/planner/ --include="*.py" | grep -v __pycache__

# asyncio.Lock usage (should exist near shared state)
grep -rn "asyncio\.Lock\|threading\.Lock" backend/app/ --include="*.py" | grep -v __pycache__

# Check TTLCache and lru_cache for thread safety
grep -rn "TTLCache\|lru_cache" backend/app/ --include="*.py" | grep -v __pycache__
```

For each shared mutable state, report:
- If it's a cache with concurrent access and missing a lock
- If it's mutated during request handling without a lock
- Skip module-level config that's only written at import time

### 1E: Duplicate Code

```bash
# Find functions with identical or near-identical signatures
grep -rn "^def \|^async def " backend/app/planner/ backend/app/services/ --include="*.py" | grep -v __pycache__ | awk -F'def ' '{print $2}' | sort | uniq -d
```

Also check for:
- Multiple implementations of constraint checking logic (should only be in `constraint_guard.py`)
- Duplicate specialist keyword lists (should only be in `specialist_registry.py`)
- Multiple session state serialization paths (should only be in `state_serde.py`)
- Duplicate cache key construction (should use shared helpers from `hashing.py`)

Report any duplicates found with locations.

---

## Phase 2: Frontend TypeScript/React

### 2A: Unused Imports and Variables

```bash
cd frontend && npx tsc --noEmit 2>&1 | grep -i "declared but\|is defined but never used\|no-unused" | head -30
```

Also check ESLint:
```bash
cd frontend && npx eslint . --no-fix --rule '{"@typescript-eslint/no-unused-vars": "error", "no-unused-vars": "error"}' 2>&1 | head -50
```

Report all unused imports and variables.

### 2B: Dead Components and Functions

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

### 2C: Unnecessary Re-renders

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

### 2D: Duplicate Code

```bash
# Find components with similar names (potential duplicates)
find frontend/components -name "*.tsx" | xargs basename -a | sort | uniq -di

# Find duplicate utility functions
grep -rn "^export function\|^export const.*= (" frontend/lib/ frontend/hooks/ --include="*.ts" --include="*.tsx" | awk -F'export ' '{print $2}' | sort | uniq -d
```

Also check for:
- Multiple implementations of streaming/SSE handling (should be in `api.ts` only)
- Duplicate type definitions (should be in `types/` only)
- Multiple implementations of plan state checking (should be in `planStateHelpers.ts` only)
- Copy-pasted DS token values instead of `DS.*` references

Report any duplicates found with locations.

### 2E: Async/Race Conditions

```bash
# Missing abort controller cleanup in useEffect
grep -rn "useEffect" frontend/components/ --include="*.tsx" -l | xargs grep -L "abort\|cleanup\|return ()" | head -10

# State updates after unmount (missing cleanup)
grep -rn "setTimeout\|setInterval" frontend/components/ --include="*.tsx" | grep -v __tests__ | head -10

# Missing error boundaries around async operations
grep -rn "await " frontend/components/ --include="*.tsx" | grep -v __tests__ | head -20
```

Report each finding with file path and line number.

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

---

## Phase 4: Report

Produce the final report in this format:

```
## Code Health Audit Report

| Category                  | Found | Severity | Notes |
|---------------------------|-------|----------|-------|
| Unused imports            |       |          |       |
| Unused functions          |       |          |       |
| Dead components           |       |          |       |
| Sync-in-async             |       |          |       |
| Race conditions           |       |          |       |
| Unnecessary re-renders    |       |          |       |
| Duplicate code            |       |          |       |
| Schema drift              |       |          |       |
| Dead endpoints            |       |          |       |

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
- Classify severity: Critical (runtime bugs, race conditions), High (dead code, sync-in-async), Medium (unused imports, re-render issues), Low (style, minor duplicates).
- Do NOT flag functions that are part of public APIs, even if currently uncalled — note them as "possibly unused, verify externally".
- Do NOT suggest adding `useMemo`/`useCallback` everywhere — only flag where there's a measurable re-render problem.
- Do NOT suggest refactoring. This is a hygiene audit, not a rewrite proposal.
