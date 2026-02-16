Analyze the git diff of the current working tree (staged + unstaged) to determine what changed. If no uncommitted changes exist, use the last commit's diff instead.

## Step 1: Classify Changed Files

Map each changed file to its affected SSoT doc(s):

| Changed File Pattern                          | Update Target                                                                        |
| --------------------------------------------- | ------------------------------------------------------------------------------------ |
| `backend/app/planner/nodes/*`                 | `docs/plan_graph_analysis.md` (node details, routing logic)                          |
| `backend/app/planner/specialist_registry.py`  | `docs/plan_graph_analysis.md` (specialist domain knowledge, constraint validation)   |
| `backend/app/planner/state/schemas.py`        | `docs/data-contracts.md` (core schema reference, enums)                              |
| `backend/app/planner/state/typed_meta.py`     | `docs/data-contracts.md` (state shape)                                               |
| `backend/app/planner/services/*`              | `docs/plan_graph_analysis.md` (itinerary builder phases, response envelope, caching) |
| `backend/app/planner/plan_graph.py`           | `docs/plan_graph_analysis.md` (graph definition, edge routing)                       |
| `backend/app/planner/*_cache.py`              | `docs/plan_graph_analysis.md` (caching architecture)                                 |
| `backend/app/planner/regen_strategy.py`       | `docs/plan_graph_analysis.md` (selective regeneration)                               |
| `backend/app/planner/router_extraction.py`    | `docs/plan_graph_analysis.md` (router extraction schema)                             |
| `backend/app/planner/experience_generator.py` | `docs/plan_graph_analysis.md` (tile service, experience generation)                  |
| `backend/app/main.py`                         | `docs/data-contracts.md` (API routes, rate limiting, streaming, middleware)          |
| `backend/app/crud_document.py`                | `docs/data-contracts.md` (persistence, session lifecycle)                            |
| `backend/app/tile_service/*`                  | `docs/plan_graph_analysis.md` (tile service architecture)                            |
| `frontend/components/plan/*`                  | `docs/ux_unified_architecture.md` (component responsibilities, rendering)            |
| `frontend/components/chat/*`                  | `docs/ux_unified_architecture.md` (chat panel, suggestion chips)                     |
| `frontend/components/sheets/*`                | `docs/design-system.md` (component mapping)                                          |
| `frontend/state/*`                            | `docs/data-contracts.md` (frontend state store, key actions, guards)                 |
| `frontend/types/*`                            | `docs/data-contracts.md` (schema reference)                                          |
| `frontend/lib/design-system.ts`               | `docs/design-system.md` (tokens, materials, actions, pills)                          |
| `frontend/lib/api.ts`                         | `docs/data-contracts.md` (frontend API client, retry logic)                          |
| `frontend/lib/planStateHelpers.ts`            | `docs/ux_unified_architecture.md` (state helpers, timeline variants)                 |
| `frontend/lib/animation-config.ts`            | `docs/ux_unified_architecture.md` (animation timing)                                 |
| `.codex/*`                                    | `docs/repo_structure.md` (local Codex skills/config tree)                            |

| Any new/deleted/moved file OR new directory | `docs/repo_structure.md` (directory tree, key architectural notes) |

If the diff creates a NEW directory not in the pattern table above, flag it:
"⚠️ New directory detected: `<path>`. Add a mapping row to this table in `.claude/commands/update-docs.md`."

If a changed file doesn't match any pattern, skip it — not every change needs doc updates.

## Step 2: Update SSoT Docs

For EACH affected doc, read the current version, then apply ONLY the sections affected by the diff:

### `docs/plan_graph_analysis.md`

- If node logic changed: update the relevant node's section (routing, behavior, model routing)
- If specialist registry changed: update Specialist Domain Knowledge section (constraints table, registry flags, keywords)
- If itinerary builder changed: update Algorithm Phases section (phase descriptions, capacity model)
- If constraint guard changed: update Constraint Validation section (validation categories table)
- If caching changed: update Caching Architecture section (cache table, key format, TTL)
- If new endpoint serves planner data: update relevant architecture description
- PRESERVE all sections not affected by the diff

### `docs/data-contracts.md`

- If endpoints changed: update API Route Reference tables (method, path, purpose, request/response)
- If schemas changed: update Core Schema Reference (PlanDocumentData tree, field descriptions)
- If streaming changed: update Streaming Protocols section (SSE/NDJSON event tables)
- If rate limiting changed: update rate limiting tier table
- If state store changed: update Frontend State Store section (store shape, key actions, guards)
- If enums changed: update Enums & State Machines section
- PRESERVE all sections not affected by the diff

### `docs/design-system.md`

- If DS tokens changed: update Design Tokens Reference tables (materials, actions, pills, text)
- If component patterns changed: update Component Mapping table
- If new interaction pattern added: add to Interaction Patterns section
- If color usage changed: update Restricted Colors guidance
- PRESERVE all sections not affected by the diff

### `docs/ux_unified_architecture.md`

- If view states changed: update Planning Phase Progression table and Legacy Mapping
- If renderer logic changed: update Single Renderer Pattern section
- If timeline variants changed: update TimelineVariant Mapping table
- If component responsibilities changed: update Component Responsibilities table
- If streaming behavior changed: update relevant streaming section
- If state guards changed: update State Transition Guards section
- PRESERVE all sections not affected by the diff

### `docs/repo_structure.md`

- If files were CREATED: add them to the correct directory tree with a brief purpose comment
- If files were DELETED: remove them from the tree
- If files were MOVED or RENAMED: update the path in the tree
- If a new directory was created: add the directory with its children
- Do NOT regenerate the entire tree — only patch the affected subtree
- If Key Architectural Notes at the bottom need updating (new invariant, new SSoT), update them
- PRESERVE all sections not affected by the diff

## Step 3: Update Agent Specs (Only When Invariants Change)

Most diffs do NOT require agent updates. Only update agents when the diff changes a PATTERN or INVARIANT, not just a feature.

### `.claude/agents/backend-specialist.md` — Update when:

- New LangGraph node added or removed (update node list — this should also trigger a CLAUDE.md invariant review)
- Routing logic changed (update routing pattern description)
- New itinerary builder phase added (update phase list)
- New cache layer or key format introduced (update caching section)
- New constraint category in guard (update constraint guard section)
- State serialization pattern changed (update state serde section)
- New derived constant from specialist registry (update registry section)
- DO NOT update for: new specialist entry, new endpoint, bug fixes, prompt changes

### `.claude/agents/frontend-specialist.md` — Update when:

- New DS token category added to design-system.ts (update token list)
- New view state or timeline variant (update variant mapping)
- New Zustand store action pattern (update store section)
- New streaming protocol or event type (update streaming section)
- Renderer pattern changed (update component patterns section)
- New critical design rule (Tactile Rule, Carousel Rule equivalent)
- DO NOT update for: new component, styling tweaks, animation changes, mobile fixes

### `.claude/agents/code-reviewer.md` — Update when:

- New invariant discovered (add to review checklist)
- New anti-pattern found during debugging (add to anti-patterns list)
- New restricted color or design rule (update DS compliance checks)
- New API contract constraint (update API contract section)
- Constraint logic rule changed (update constraint correctness checks)
- DO NOT update for: feature additions, test changes, doc-only changes

## Step 4: Update Sprint in CLAUDE.md

Read the `## 🎯 Current Sprint` section in `CLAUDE.md`.

1. **"Active work"**: Update to reflect what this diff accomplished (one-line summary).
2. **"Known broken"**: If the diff fixes a known broken item, remove it. If the diff introduces a known issue, add it.
3. **DO NOT modify**: Focus, Secondary, DO NOT touch — those are manually curated at sprint start.

If the git log since the last update shows multiple commits not yet reflected in "Active work",
summarize them all. Group related commits into a single line.

Example:

```markdown
- **Active work:** Shipped activity day preference extraction (router_extraction, schemas), smart suggestion chips (synthesizer, frontend)
- **Known broken:** Yoga tile 48h duration (experience_generator.py)
```

## Rules

- ONLY update sections directly affected by the diff. Never rewrite unchanged sections.
- PRESERVE existing formatting, table structures, and section ordering in all docs.
- If a doc section needs updating but you're unsure of the correct new content, flag it with `<!-- TODO: verify after [description of change] -->` instead of guessing.
- If no docs need updating (e.g., test-only changes, comment edits), say so and skip to Step 5.
- Max 6 doc files modified per run. If more are affected, prioritize by: plan_graph_analysis > data-contracts > ux_unified_architecture > design-system > repo_structure > agents.
