Use `backend/.venv` for all Python execution (e.g. `backend/.venv/bin/python`, `backend/.venv/bin/ruff`, `backend/.venv/bin/alembic`, `backend/.venv/bin/pre-commit`).

Run all build checks matching the actual Render deploy pipeline and pre-commit hooks.
Auto-fix what you can, report what you can't.

## Step 1: Backend Lint + Format (mirrors pre-commit ruff hooks)

```bash
cd backend && ruff check . --fix 2>&1 && ruff format . 2>&1
```

If ruff reports unfixable errors, read each flagged file and fix manually.

## Step 2: Backend Import + Dependency + Migration Check

**Import check** (if this fails, Render's Docker container won't start):

```bash
cd backend && python -c "import app.main" 2>&1
```

If this fails, read the traceback and fix the import error.

**Alembic migration chain** (Render runs `alembic upgrade head` on deploy):

```bash
cd backend && python -c "
from alembic.config import Config
from alembic.script import ScriptDirectory
cfg = Config('alembic.ini')
scripts = ScriptDirectory.from_config(cfg)
heads = scripts.get_heads()
if len(heads) > 1:
    print(f'ERROR: Multiple migration heads: {heads}')
    print('Fix: alembic merge -m \"merge heads\" head1 head2')
else:
    print(f'Migration chain OK (head: {heads[0][:12]})')
" 2>&1
```

If multiple heads exist, create a merge migration before deploying.

## Step 3: Frontend Build (mirrors Render: `npm ci --include=dev && npm run build`)

```bash
cd frontend && npm ci --include=dev 2>&1 | tail -5 && npm run build 2>&1
```

This is the EXACT Render build command from `render.yaml`. If it fails:
- Read the FULL error output (not just tail)
- TypeScript errors: fix the type issue in the source file
- Module not found: check import paths
- Build warnings are OK — only errors block deploy

## Step 4: Frontend Lint + Fix

```bash
cd frontend && npm run lint:fix 2>&1
```

If ESLint reports unfixable errors, read each flagged file and fix manually.

## Step 5: Pre-commit Hooks (mirrors .pre-commit-config.yaml)

Run the full hook suite:

```bash
cd .. && pre-commit run --all-files 2>&1
```

This runs, in order:
1. `end-of-file-fixer` — auto-fixes missing newlines
2. `trailing-whitespace` — auto-fixes trailing spaces
3. `check-merge-conflict` — fails if conflict markers present
4. `check-yaml` — validates all YAML files
5. `detect-private-key` — fails if SSH/PEM keys found in repo
6. `detect-secrets` — fails if secrets detected (baseline: `.secrets.baseline`)
7. `ruff` + `ruff-format` — Python lint/format (already ran in Step 1, should pass)
8. `ssot-check` — validates `plan_graph.py` against SSoT constraints

Pre-commit may auto-fix files (whitespace, EOF, formatting).
If it does, the run shows "Failed" but files are already fixed.
Run it a SECOND time to confirm:

```bash
pre-commit run --all-files 2>&1
```

If second run still fails:
- `detect-secrets`: update baseline with `detect-secrets scan > .secrets.baseline` if the secret is a false positive. If it's a real secret, REMOVE IT and rotate the key.
- `ssot-check`: read the violation output, fix `plan_graph.py` to match SSoT docs.
- `check-merge-conflict`: resolve the conflict markers in the flagged file.

## Step 6: Final Verification Pass

After all fixes are applied, run the ENTIRE pipeline once more end-to-end:

```bash
cd backend && ruff check . 2>&1 && ruff format --check . 2>&1
cd backend && python -c "import app.main" 2>&1
cd frontend && npm run build 2>&1
cd frontend && npm run lint 2>&1
cd .. && pre-commit run --all-files 2>&1
```

If anything fails here, go back and fix it. Do NOT proceed to the report with failures.

## Step 7: Report

Output a summary:

```
## Build Verification

| Check              | Status | Notes |
|--------------------|--------|-------|
| Backend lint       | ✅/❌  |       |
| Backend import     | ✅/❌  |       |
| Alembic migrations | ✅/❌  |       |
| Frontend deps      | ✅/❌  |       |
| Frontend build     | ✅/❌  |       |
| Frontend lint      | ✅/❌  |       |
| Pre-commit hooks   | ✅/❌  |       |
| SSoT check         | ✅/❌  |       |
| Secret scan        | ✅/❌  |       |
| Final pass         | ✅/❌  |       |

Files auto-fixed: [list or "none"]
Manual fixes applied: [list or "none"]
Unfixable (needs human): [list or "none — all green, ready to deploy"]
```

## Rules

- **FIX EVERYTHING.** This command does not end with errors in the report. If a check fails, fix it and re-run that check before moving to the next step.
- Each step follows a FIX LOOP: run check → if fail → fix → re-run check → if fail → fix → re-run check → if 3rd fail → report as unfixable and move on.
- Do NOT skip a failing step. Do NOT defer fixes to the report.
- Do NOT modify test files to make builds pass. Fix the source.
- Do NOT suppress TypeScript errors with `@ts-ignore` or `any` casts.
- Do NOT add secrets to the baseline without confirming they are false positives.
- Do NOT weaken ruff rules or ESLint configs to pass checks.
- The frontend build command MUST be `npm ci --include=dev && npm run build` — this matches Render exactly.
- The final report should ideally show ALL ✅. Any ❌ means you exhausted 3 fix attempts and need human intervention — explain exactly what's wrong and what you tried.
