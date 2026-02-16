---
name: nomadic-verify-build
description: Run the full Nomadic build and quality pipeline to mirror Render and pre-commit checks, automatically fixing failures when possible and reporting unresolved blockers. Use before deploys or when validating repo health after changes.
---

# Nomadic Verify Build

## Pipeline

Run in this order and apply a fix loop per step (run -> fix -> rerun; max three attempts before marking unfixable):

1. Backend lint and format:
- `cd backend && ruff check . --fix`
- `cd backend && ruff format .`
2. Backend import/startup validation:
- `cd backend && python -c "import app.main"`
3. Alembic migration chain validation (single head required).
4. Frontend dependency and build matching Render:
- `cd frontend && npm ci --include=dev`
- `cd frontend && npm run build`
5. Frontend lint and autofix:
- `cd frontend && npm run lint:fix`
6. Full pre-commit hooks:
- `pre-commit run --all-files`
- rerun once after autofixes
7. Final end-to-end verification pass:
- backend ruff check + format --check
- backend import
- frontend build
- frontend lint
- pre-commit all files

## Guardrails

- Fix issues instead of deferring to report when possible.
- Do not weaken lint rules, suppress errors with `@ts-ignore`/`any`, or modify tests just to pass.
- Do not add real secrets to baseline.
- Keep Render parity for frontend build command.

## Output

Return a summary table with status for:

- backend lint
- backend import
- alembic migrations
- frontend deps
- frontend build
- frontend lint
- pre-commit hooks
- SSoT check
- secret scan
- final pass

Also list:

- files auto-fixed
- manual fixes applied
- unfixable items needing human intervention
