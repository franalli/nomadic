Clear L1 + L2 caches through the admin API endpoint.

## Prerequisites

Backend must be running locally on port 8000.

Optional (if `ADMIN_API_KEY` is configured): export your key first.

```bash
export ADMIN_API_KEY="your-key" # pragma: allowlist secret
```

## Step 1: Health Check

```bash
curl -s http://localhost:8000/health | python3 -c "import sys,json; d=json.load(sys.stdin); print('Backend UP:', d.get('status'))" 2>/dev/null || echo "ERROR: Backend not running"
```

If backend is not running, stop and ask the user to start it.

## Step 2: Clear L1 + L2 Caches

With admin key:

```bash
curl -s -X POST http://localhost:8000/api/admin/clear-l1-l2-caches \
  -H "X-Admin-Key: ${ADMIN_API_KEY}" \
  -H "Content-Type: application/json" | python3 -m json.tool
```

Without admin key (dev/local where admin routes are open):

```bash
curl -s -X POST http://localhost:8000/api/admin/clear-l1-l2-caches \
  -H "Content-Type: application/json" | python3 -m json.tool
```

## Step 3: Report

Return:

1. Whether the endpoint call succeeded.
2. `totals.l1`, `totals.l2`, and `totals.overall`.
3. Any non-zero entries in `cleared.l1` and `cleared.l2`.

## Rules

- Do NOT modify source files while running this command.
- If the endpoint fails, include HTTP status and response body in the report.
