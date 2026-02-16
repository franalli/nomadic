# Remediation Proof Gates

This checklist is mandatory for any symbol deletion during remediation.

## Scope
- Applies to functions, classes, constants, components, hooks, exports, and types.
- Does **not** apply to backend endpoint paths in `backend/app/main.py`: endpoint removal is disallowed in this cycle.

## Required Proof Before Deletion
1. Zero code references across `backend/`, `frontend/`, `tests/`, and `scripts/`.
2. Symbol is not exposed via `__all__`, facade exports, or re-export modules.
3. Symbol is not referenced through dynamic dispatch (string keys, getattr/importlib style access).
4. Symbol is not listed as architecture-critical in top-level docs under `docs/`.
5. Symbol is not part of generated/OpenAPI/public API contract.
6. Reviewer sign-off is recorded for each deleted symbol.

## Commands / Evidence to Collect
- `rg -n "<symbol_name>" backend frontend tests scripts`
- Export surface check:
  - `rg -n "__all__|export \{|export \*|from .* import .*<symbol_name>" backend frontend`
- Dynamic reference checks:
  - `rg -n "getattr\(|importlib|\[\s*['\"]<symbol_name>['\"]\s*\]" backend frontend`
- Contract checks:
  - backend routes and schema references
  - frontend generated types and direct type imports

## Cycle Default
- **No pre-approved symbol deletions.**
- If proof is incomplete, keep the symbol and add it to follow-up tracking.
