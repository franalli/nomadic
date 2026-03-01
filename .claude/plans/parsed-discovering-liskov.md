# Plan: Fix Gemini `anyOf` silent type erasure in structured output schemas

## Context

Pydantic v2 renders `Optional[float]` fields as `{"anyOf": [{"type": "number"}, {"type": "null"}]}`. While `strip_unsupported_schema_keys()` preserves `anyOf` (it's in the allowed list), **Gemini's API itself silently drops `anyOf`**, leaving those fields with **zero type definition**. Fields like `lat`, `lng`, `day_number`, `buffer_hours` get no type constraint — Gemini guesses from context.

The fix: a `gemini_safe_schema()` transform that converts `anyOf` Optional patterns into Gemini's native `{"type": "number", "nullable": true}` format. This is also valid for OpenAI's non-strict function calling, so it can be applied universally to the pre-computed module-level schemas.

## Implementation

### Step 1: Add `gemini_safe_schema()` to `llm_factory.py`

**File:** `backend/app/planner/llm_factory.py` (after `strip_unsupported_schema_keys`, ~line 243)

```python
def gemini_safe_schema(node: object) -> object:
    """Convert Pydantic anyOf-nullable patterns to Gemini-native nullable format.

    Pydantic v2 renders Optional[T] as {"anyOf": [{"type": T}, {"type": "null"}]}.
    Gemini silently drops anyOf, erasing all type info for those fields.
    This transform converts them to {"type": T, "nullable": true} which Gemini enforces.

    Safe for OpenAI too — nullable is valid in non-strict function calling schemas.
    """
    if isinstance(node, dict):
        if "anyOf" in node:
            any_of = node["anyOf"]
            if isinstance(any_of, list) and len(any_of) == 2:
                non_null = [b for b in any_of if not (isinstance(b, dict) and b.get("type") == "null")]
                null_branch = [b for b in any_of if isinstance(b, dict) and b.get("type") == "null"]
                if len(non_null) == 1 and len(null_branch) == 1:
                    # Optional[T] pattern — merge non-null branch + nullable
                    merged = dict(gemini_safe_schema(non_null[0]))
                    merged["nullable"] = True
                    # Preserve sibling keys (description, default, etc.)
                    for k, v in node.items():
                        if k != "anyOf" and k not in merged:
                            merged[k] = gemini_safe_schema(v)
                    return merged
        # Regular dict — recurse
        return {k: gemini_safe_schema(v) for k, v in node.items()}
    if isinstance(node, list):
        return [gemini_safe_schema(item) for item in node]
    return node
```

Export it alongside existing schema utilities.

### Step 2: Update all 8 schema pipeline sites

Wrap each existing `strip_unsupported_schema_keys(resolve_schema_refs(...))` with `gemini_safe_schema(...)`:

| # | File | Schema Constant | Pydantic Model |
|---|------|----------------|----------------|
| 1 | `backend/app/planner/nodes/vertical_specialist.py:112` | `_SPECIALIST_FLAT_SCHEMA` | `LLMSpecialistOutput` (12 Optional fields) |
| 2 | `backend/app/planner/nodes/router_extraction.py:301` | `_ROUTER_FLAT_SCHEMA` | `RouterOutput` (~21 Optional fields) |
| 3 | `backend/app/planner/nodes/router_extraction.py:1069` | inline `classifier_schema` | `ChangeClassification` |
| 4 | `backend/app/planner/services/feasibility_service.py:29` | `_FEASIBILITY_FLAT_SCHEMA` | `FeasibilityCheck` |
| 5 | `backend/app/planner/services/iata_resolver.py:34` | `_IATA_FLAT_SCHEMA` | `IataResponse` |
| 6 | `backend/app/services/experience_generator.py:272` | `_EXPERIENCE_FLAT_SCHEMA` | `ExperienceOutput` |
| 7 | `backend/app/services/activity_browser.py:100` | `_BROWSE_ESTIMATE_FLAT_SCHEMA` | `_BrowseEstimateBatch` |
| 8 | `backend/app/validation.py:52` | `_VALIDATION_FLAT_SCHEMA` | `ValidationResponse` |

Each change is the same pattern — add `gemini_safe_schema` to import, wrap the pipeline:

```python
# Before:
_FOO_FLAT_SCHEMA: dict = strip_unsupported_schema_keys(
    resolve_schema_refs(FooModel.model_json_schema())
)

# After:
_FOO_FLAT_SCHEMA: dict = gemini_safe_schema(
    strip_unsupported_schema_keys(
        resolve_schema_refs(FooModel.model_json_schema())
    )
)
```

## Files modified (8 total)

1. `backend/app/planner/llm_factory.py` — add `gemini_safe_schema()` function
2. `backend/app/planner/nodes/vertical_specialist.py` — update import + wrap schema
3. `backend/app/planner/nodes/router_extraction.py` — update import + wrap 2 schemas
4. `backend/app/planner/services/feasibility_service.py` — update import + wrap schema
5. `backend/app/planner/services/iata_resolver.py` — update import + wrap schema
6. `backend/app/services/experience_generator.py` — update import + wrap schema
7. `backend/app/services/activity_browser.py` — update import + wrap schema
8. `backend/app/validation.py` — update import + wrap schema

## What this does NOT touch

- Pydantic models (no schema changes)
- `with_structured_output()` calls (no invocation changes)
- `llm_factory.py` provider/model routing (per CLAUDE.md "DO NOT touch" rule)
- `_GEMINI_ALLOWED_SCHEMA_KEYS` (keep `anyOf` in allowed list for non-Optional union edge cases)

## Verification

1. `cd backend && ruff check . --fix` — lint passes
2. `cd backend && pytest` — existing tests pass
3. Spot-check: after module load, inspect `_SPECIALIST_FLAT_SCHEMA` to verify `lat`/`lng` have `{"type": "number", "nullable": true}` instead of empty `{}`
4. End-to-end: trigger a specialist plan with Gemini model and verify coordinates come back as floats (not strings)
