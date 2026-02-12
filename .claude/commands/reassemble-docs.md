This is a FULL RECONCILIATION of all SSoT documentation against the live codebase.
Unlike /update-docs (diff-based, incremental), this command reads the actual source
files and corrects any drift between docs and code. Run this weekly or after major stages.

⚠️ This is a heavy operation. It will read many files. Do NOT skip steps.

---

## Phase 1: `docs/repo_structure.md`

**Source of truth:** The filesystem itself.

1. Run `find backend/ frontend/ docs/ scripts/ -type f | head -300` and `find . -maxdepth 1 -type f` to get the actual file tree
2. Read current `docs/repo_structure.md`
3. For each directory section in the doc:
   - Verify every listed file still exists. Remove entries for deleted files.
   - Check for new files not listed. Add them with a brief purpose comment.
   - Verify directory nesting is accurate.
4. Check the "Key Architectural Notes" section at the bottom still holds true.
5. Write corrections directly to `docs/repo_structure.md`.

---

## Phase 2: `docs/plan_graph_analysis.md`

**Sources of truth:** The backend planner code.

### 2A: Node Architecture (read each node file, verify doc matches)

For each node, read the ACTUAL source and verify the doc:

| Doc Section           | Read These Files                                                                         | Verify                                                                                                                          |
| --------------------- | ---------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------- |
| Architecture Overview | `backend/app/planner/plan_graph.py`                                                      | Node count, node names in `create_optimized_graph()`, edge definitions                                                          |
| IntentRouter          | `backend/app/planner/nodes/intent_router.py`, `backend/app/planner/router_extraction.py` | Classification flow, `RouterOutput` fields, static responses, specialist detection                                              |
| TripArchitect         | `backend/app/planner/nodes/trip_architect.py`                                            | Settings extraction, field handling, mode determination                                                                         |
| VerticalSpecialist    | `backend/app/planner/nodes/vertical_specialist.py`                                       | Execution flow, parallel batching, `SpecialistOutput` fields                                                                    |
| LocalExpert           | `backend/app/planner/nodes/local_expert.py`                                              | LLM gating, fallback behavior                                                                                                   |
| LogisticsNode         | `backend/app/planner/nodes/logistics_node.py`                                            | Tile fetching, provider routing, experience generation trigger                                                                  |
| ConstraintGuard       | `backend/app/planner/nodes/constraint_guard.py`                                          | Validation functions, violation types, auto-fix loop, `route_after_guard()` logic                                               |
| Synthesizer           | `backend/app/planner/nodes/synthesizer.py`                                               | Model routing (`_MODEL_BY_COMPLEXITY` or equivalent), response types, `generate_suggestions()` priority cascade, prompt caching |

For each: if the doc describes behavior that doesn't match the code, FIX THE DOC.

### 2B: Routing Logic

Read `plan_graph.py` functions: `route_after_router()`, `route_after_specialist()`, `route_after_guard()`, `route_after_architect()`. Verify the routing diagram and conditional edge descriptions match.

### 2C: Specialist Domain Knowledge

Read `backend/app/planner/specialist_registry.py` — the ENTIRE file.

- Verify every specialist in `SPECIALIST_REGISTRY` is documented with correct: keywords (first 5), constraints table, registry flags, cross-domain blocks, tier, min_days_needed
- Verify derived constants section matches: `TIER1_SPECIALIST_NAMES`, `ALL_SPECIALIST_KEYWORDS`, `ALL_CATEGORY_TO_SPECIALIST`, `ALL_CONSTRAINT_ALIASES`
- Remove doc entries for specialists no longer in registry
- Add doc entries for new specialists

### 2D: Itinerary Builder

Read `backend/app/services/itinerary_builder.py` — focus on the `build()` method and phase methods.

- Verify phase list matches (numbered phases, sub-phases like 5.25, 5.5, 5.6)
- Verify capacity model (hours/day, max blocks)
- Verify cross-domain clustering logic description
- Verify no-fly buffer enforcement (two-layer: count truncation + day restriction)

### 2E: Caching Architecture

Read: `specialist_cache.py`, `router_cache.py`, `tile_cache.py`, `experience_generator.py` (cache sections), `base_cache.py`.

- Verify cache table: class, max size, TTL, key format, purpose
- Verify L1/L2 architecture description

### 2F: Selective Regeneration

Read `backend/app/planner/regen_strategy.py`.

- Verify `FIELD_IMPACT` mapping matches doc
- Verify strategy tiers and priority order

### 2G: Services

Read `response_envelope.py`, `section_builder.py`, `state_serde.py`, `itinerary_adapter.py`.

- Verify described public APIs match actual function signatures
- Verify `_compute_plan_view_state()` logic matches doc

### 2H: Streaming

Read `plan_graph.py` streaming functions (`run_turn_streaming` or equivalent).

- Verify SSE event types and data shapes
- Verify NDJSON event types for expand-itinerary

Write all corrections to `docs/plan_graph_analysis.md`.

---

## Phase 3: `docs/data-contracts.md`

**Sources of truth:** Endpoints, schemas, stores.

### 3A: API Routes

Read `backend/app/main.py` — scan all `@app.get`, `@app.post`, `@app.patch`, `@app.delete`, `@app.put` decorators.

- Verify every endpoint is listed in the API Route Reference tables
- Verify method, path, purpose, request/response types
- Verify rate limiting tiers match `slowapi` decorators
- Remove doc entries for deleted endpoints
- Add entries for new endpoints

### 3B: Core Schemas

Read `backend/app/schemas.py` and `backend/app/planner/state/schemas.py`.

- Verify `PlanDocumentData` tree structure matches actual fields
- Verify all Pydantic models referenced in endpoint signatures are documented
- Verify enums: `PlanViewState`, `PlanState`, `UIPhase`, `BookingTypeState`, `AckStatus` — check actual values match doc

### 3C: Streaming Protocols

Read the streaming handler in `main.py` and `plan_graph.py`.

- Verify SSE event table (type, data shape, purpose)
- Verify NDJSON event table
- Verify CSRF description matches middleware

### 3D: Security & Middleware

Read `main.py` middleware setup.

- Verify rate limiting tiers and limits
- Verify security headers list
- Verify body size limit
- Verify session throttle and SSE connection limits

### 3E: Frontend State Store

Read `frontend/state/documentStore.ts`.

- Verify store shape table (all state fields listed)
- Verify key actions table (all public actions listed)
- Verify state guards description matches actual guard logic

### 3F: Frontend API Client

Read `frontend/lib/api.ts`.

- Verify function table matches exported functions
- Verify retry logic description

Write all corrections to `docs/data-contracts.md`.

---

## Phase 4: `docs/design-system.md`

**Source of truth:** `frontend/lib/design-system.ts` and `frontend/tailwind.config.mts`.

### 4A: Design Tokens

Read `frontend/lib/design-system.ts` — the full `DS` object.

- For each token category (materials, actions, pills, text, infoBox, stepper):
  - Verify every token in the doc exists in code
  - Verify light/dark mode values match
  - Remove doc entries for deleted tokens
  - Add entries for new tokens
- Verify `DS` usage examples are correct imports

### 4B: Custom Tailwind Config

Read `frontend/tailwind.config.mts`.

- Verify custom shadow tokens (`shadow-soft`, `shadow-card`) values
- Verify `rounded-lg` override value (should be 12px / 0.75rem)
- Verify any custom color extensions

### 4C: Component Mapping

Read the actual component files listed in the Component Mapping table.

- Verify each component uses the DS tokens listed
- Flag any component using raw Tailwind where a DS token exists
- Update table if components were renamed or deleted

### 4D: Interaction Patterns

Grep for heart/preference patterns, constraint visualization, stepper buttons:

```bash
grep -r "fill-emerald-500" frontend/components/ --include="*.tsx" -l
grep -r "DS.pills" frontend/components/ --include="*.tsx" -l
grep -r "severity.*warning\|severity.*blocking" frontend/components/ --include="*.tsx" -l
```

Verify documented patterns match actual usage.

Write all corrections to `docs/design-system.md`.

---

## Phase 5: `docs/ux_unified_architecture.md`

**Sources of truth:** Frontend components, state helpers, store.

### 5A: Planning Phases & View States

Read `frontend/lib/planStateHelpers.ts` and `backend/app/planner/services/response_envelope.py` (`_compute_plan_view_state`).

- Verify Planning Phase Progression table
- Verify Legacy Mapping table (S* → P* states)
- Verify state helper functions table (getNextAction, isGenerating, isReady, deprecated functions)

### 5B: Single Renderer Pattern

Read `frontend/components/plan/StrategyStageRenderer.tsx`.

- Verify it's still the single entry point (no alternate renderers created)
- Verify conditional layout logic (no destination vs desktop vs mobile)
- Verify timeline section rendering condition

### 5C: Component Responsibilities

Read each component listed in the Component Responsibilities table.

- Verify responsibilities match actual code behavior
- Verify TimelineVariant mapping (PlanViewState → variant → badge)
- Check for new components that should be listed

### 5D: Session Lifecycle

Read `frontend/hooks/useSessionHydration.ts` (or equivalent) and `frontend/state/documentStore.ts`.

- Verify lifecycle steps (first visit, chat interaction, build, refresh, expiration)
- Verify downgrade protection logic
- Verify expand-in-progress mutex description

### 5E: Suggestion Chips

Read `backend/app/planner/nodes/synthesizer.py` (`generate_suggestions`) and the chip rendering component.

- Verify chip state table (what chips show in what state)
- Verify priority cascade description

### 5F: Invariants

Re-verify each numbered invariant against the codebase:

1. Right Panel never empty — check StrategyStageRenderer fallback
2. No view swapping — check no alternate renderer mounts
3. No UI chrome removal — check status header transforms
4. Backend SSoT for plan_view_state — check store doesn't fabricate (except S0_EMPTY, S3_PARTIAL_CONFLICT)
5. Coordinate format [lng, lat] — grep for coordinate handling
6. Dates gate Plan tab — check tab lock logic

Write all corrections to `docs/ux_unified_architecture.md`.

---

## Phase 6: Agent Specs

Audit each agent file against the LIVE CODEBASE. Do NOT rely on hardcoded file lists —
discover what's relevant dynamically.

### Step 6.1: Inventory

For each agent in `.claude/agents/`:

1. Read the agent spec file completely
2. Extract every source file path, function name, class name, constant name, and pattern referenced in the spec
3. Verify each referenced file still exists: `ls <path>` — if deleted, remove from spec
4. Scan the agent's **File Ownership** section, extract the listed directories, then `find` those directories. Also check for new top-level directories not in any agent's ownership that contain relevant code:

```bash
# Discover all Python/TS source directories
find backend/app/ -type d | grep -v __pycache__
find frontend/ -type d | grep -v node_modules
```

If a directory exists that no agent owns and contains production code, flag it:
"⚠️ Unowned directory: `<path>`. Assign to an agent or add to shared zone."

5. For each NEW file found that isn't in the agent spec: read the file, determine if it's relevant to that agent's domain, add to file ownership if so

### Step 6.2: Verify Claims

For each factual claim in the agent spec (function names, phase lists, constant values, invariants, patterns):

1. Read the actual source file containing that claim
2. If the claim matches code → leave it
3. If the claim doesn't match code → fix the agent spec to match
4. If the referenced symbol no longer exists → remove the claim

Key areas to verify per agent:

**backend-specialist**: Node names + count in `create_optimized_graph()`, routing function signatures, itinerary builder phase method names, constraint guard validation function names, cache class names + key formats, derived constants from specialist registry, state serialization function signatures

**frontend-specialist**: DS token categories + names in the `DS` object, Tailwind config overrides, store action names + guard logic, streaming protocol details in api.ts, renderer component name + conditional logic, component file names in ownership list

**code-reviewer**: Every function name referenced in the review checklist, every anti-pattern example, every invariant check description, rate limiting tier values, restricted color list

### Step 6.3: Cross-Check Agents Against Each Other

Verify no contradictions between agents:

- File ownership boundaries don't overlap (except documented shared files)
- Invariant descriptions are consistent (e.g., node count, coordinate format, renderer pattern)
- Anti-patterns in code-reviewer align with rules in backend/frontend specialists

### Step 6.4: Write Corrections

For each agent: if the spec describes behavior that doesn't match the source code, FIX THE AGENT SPEC. If new files/patterns/functions exist that the agent should know about, ADD THEM.

---

## Phase 7: Validate & Report

Finally, output a summary:

```
## Reassembly Report

### Files Updated
- docs/repo_structure.md: [X additions, Y removals]
- docs/plan_graph_analysis.md: [sections changed]
- docs/data-contracts.md: [sections changed]
- docs/design-system.md: [sections changed]
- docs/ux_unified_architecture.md: [sections changed]
- .claude/agents/*: [which agents updated, why]

### Drift Found
- [List each factual discrepancy found between doc and code]

### No Drift
- [List doc sections verified as accurate]

---

## Rules

- READ the actual source code. Do not rely on memory or assumptions.
- Fix the DOC to match the CODE, never the reverse. Code is truth.
- Preserve doc formatting, table structures, and section ordering.
- If a section is accurate, do not rewrite it. Only touch drifted sections.
- If you're unsure whether something drifted or is intentional, add `<!-- REVIEW: [description] -->` instead of guessing.
- **Strip sprint-level and development-timeline content.** Docs must reflect current state, not development history. Remove changelog sections, "shipped in sprint X" notes, "TODO" items that are done, migration/upgrade notes for completed migrations, and any other time-bound content that no longer serves a reader trying to understand the system as it exists today. If a section's only purpose was tracking a past transition, delete it entirely.
- This command will read many files. Take it phase by phase. Do not rush.
```
