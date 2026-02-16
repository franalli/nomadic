---
name: nomadic-audit-code
description: Run a full read-only code health audit across backend and frontend (not diff-driven) and produce a findings report. Use when asked for dead code, async/race risks, duplication, schema drift, endpoint usage drift, or broad quality scanning without applying fixes.
---

# Nomadic Audit Code

## Scope

- Scan the whole repository source code, not just recent changes.
- Produce findings only. Do not modify code.
- Include file paths and line numbers for each issue.

## Backend Checks

1. Run unused import checks (`ruff` F401).
2. Run unused variable checks (`ruff` F841).
3. Manually detect dead functions in `backend/app/planner/` and `backend/app/services/` by searching callers.
4. Skip valid exceptions: LangGraph node functions, FastAPI handlers, `__all__` exports, migrations, fixtures, validators.
5. Detect blocking sync calls inside `async def` (for example `time.sleep`, `requests.*`, sync DB dependencies).
6. Detect shared mutable state risks and missing locks.
7. Detect duplicate implementations for constraint checks, specialist keyword lists, state serialization, and cache key helpers.

## Frontend Checks

1. Run TypeScript/ESLint checks for unused imports and variables.
2. Find dead exports in `frontend/components/`, `frontend/hooks/`, and `frontend/lib/`.
3. Skip expected exceptions: Next.js page components, dynamic imports, type-only exports, and design tokens.
4. Audit unnecessary rerender patterns:
- fat Zustand selectors
- inline style objects
- inline handlers in large mapped lists
- expensive computations missing memoization
5. Detect duplicate logic for SSE handling, plan state checking, duplicated type definitions, and copied token values.
6. Detect async cleanup/race issues in React effects.

## Cross-Stack Checks

1. Compare backend and frontend plan schema fields for drift.
2. List backend endpoints and verify active frontend callers.
3. Flag dead endpoints not used by frontend and not admin-only.

## Output Format

Produce a report table:

```markdown
## Code Health Audit Report

| Category | Found | Severity | Notes |
|----------|-------|----------|-------|
```

Then list findings grouped by category with severity and exact locations.

## Operational Rules

- Prefer deterministic CLI checks first, then manual verification.
- Treat this as a read-only audit.
- Do not auto-fix.
