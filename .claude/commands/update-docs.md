Analyze the git diff of the current working tree (staged + unstaged) to determine what changed. If no uncommitted changes exist, use the last commit's diff instead.

## Step 1: Classify Changed Files

Map each changed file to its affected SSoT doc(s):

| Changed File Pattern                          | Update Target                                                                        |
| --------------------------------------------- | ------------------------------------------------------------------------------------ |
| `backend/app/planner/nodes/*`                 | `docs/plan_graph_analysis.md` (node details, routing logic)                          |
| `backend/app/planner/specialist_registry.py`  | `docs/plan_graph_analysis.md` (specialist domain knowledge, constraint validation)   |
| `backend/app/planner/state/graph_state.py`    | `docs/data-contracts.md` (core schema reference, enums, graph state shape)           |
| `backend/app/planner/state/typed_meta.py`     | `docs/data-contracts.md` (state shape)                                               |
| `backend/app/planner/services/*`              | `docs/plan_graph_analysis.md` (itinerary builder phases, response envelope, caching) |
| `backend/app/plan_graph.py`                   | `docs/plan_graph_analysis.md` (graph definition, edge routing, node registration)    |
| `backend/app/planner/cache_access.py`         | `docs/plan_graph_analysis.md` (planner cache handles, cache access patterns)         |
| `backend/app/planner/hashing.py`              | `docs/plan_graph_analysis.md` (cache key construction, hashing strategy)             |
| `backend/app/planner/llm_factory.py`          | `docs/plan_graph_analysis.md` (model routing, LLM configuration)                     |
| `backend/app/planner/test_mode.py`            | `docs/plan_graph_analysis.md` (test mode behavior, mock responses)                   |
| `backend/app/planner/nodes/router_extraction.py`| `docs/plan_graph_analysis.md` (router extraction schema, input parsing)              |
| `backend/app/main.py`                         | `docs/data-contracts.md` (API routes, rate limiting, streaming, middleware)          |
| `backend/app/crud_document.py`                | `docs/data-contracts.md` (persistence, session lifecycle)                            |
| `backend/app/services/*cache*.py`             | `docs/plan_graph_analysis.md` (caching architecture, L1/L2 tiers, TTLs)             |
| `backend/app/services/itinerary_builder.py`   | `docs/plan_graph_analysis.md` (itinerary builder phases, capacity model)             |
| `backend/app/services/experience_generator.py`| `docs/plan_graph_analysis.md` (experience generation, tile enrichment)               |
| `backend/app/services/regen_strategy.py`      | `docs/plan_graph_analysis.md` (selective regeneration strategy)                      |
| `backend/app/services/unsplash*.py`           | `docs/plan_graph_analysis.md` (image service, unsplash queries)                      |
| `backend/app/tools/amadeus_client.py`         | `docs/data-contracts.md` (Amadeus API integration, flight/hotel data)                |
| `backend/app/tools/tile_service.py`           | `docs/plan_graph_analysis.md` (tile service orchestration)                           |
| `backend/app/tools/constraint_engine.py`      | `docs/plan_graph_analysis.md` (constraint evaluation engine)                         |
| `backend/app/schemas.py`                      | `docs/data-contracts.md` (core Pydantic schemas, PlanDocumentData, API models)       |
| `backend/app/db.py`                           | `docs/data-contracts.md` (database engine config, connection pooling, session mgmt)  |
| `backend/app/db_models.py`                    | `docs/data-contracts.md` (ORM models, table definitions, response cache schema)      |
| `backend/app/prompts/*`                       | `docs/plan_graph_analysis.md` (synthesizer prompt templates, prompt caching)         |
| `backend/app/tile_service/*`                  | `docs/plan_graph_analysis.md` (tile service architecture, providers)                 |
| `frontend/components/plan/*`                  | `docs/ux_unified_architecture.md` (component responsibilities, rendering)            |
| `frontend/components/chat/*`                  | `docs/ux_unified_architecture.md` (chat panel, suggestion chips)                     |
| `frontend/components/tiles/*`                 | `docs/design-system.md` (tile card patterns, component mapping)                      |
| `frontend/state/*`                            | `docs/data-contracts.md` (frontend state store, key actions, guards)                 |
| `frontend/types/*`                            | `docs/data-contracts.md` (schema reference)                                          |
| `frontend/lib/design-system.ts`               | `docs/design-system.md` (tokens, materials, actions, pills)                          |
| `frontend/lib/api.ts`                         | `docs/data-contracts.md` (frontend API client, retry logic)                          |
| `frontend/hooks/*`                            | `docs/ux_unified_architecture.md` (custom hooks, view navigation, sheet management)  |
| `frontend/components/layout/*`                | `docs/ux_unified_architecture.md` (layout structure, mobile/desktop split)           |
| `frontend/components/map/*`                   | `docs/ux_unified_architecture.md` (map integration, error boundaries)                |
| `frontend/lib/planStateHelpers.ts`            | `docs/ux_unified_architecture.md` (state helpers, timeline variants)                 |
| `frontend/lib/animation-config.ts`            | `docs/ux_unified_architecture.md` (animation timing)                                 |
| `frontend/lib/specialists.ts`                 | `docs/plan_graph_analysis.md` (frontend specialist config, mirrors registry)         |
| `frontend/lib/streamParser.ts`                | `docs/data-contracts.md` (SSE stream parsing, event type handling)                   |
| `frontend/lib/tileUtils.ts`                   | `docs/ux_unified_architecture.md` (tile rendering utilities)                         |
| `frontend/lib/tileSelectors.ts`               | `docs/ux_unified_architecture.md` (tile selection logic, filtering)                  |
| `frontend/lib/fillDayGuards.ts`               | `docs/ux_unified_architecture.md` (day fill validation, state guards)                |
| `frontend/lib/ghost-timeline-adapter.ts`      | `docs/ux_unified_architecture.md` (ghost timeline rendering, skeleton states)        |
| `frontend/lib/chipStyles.ts`                  | `docs/design-system.md` (suggestion chip styling, DS token usage)                    |
| `frontend/lib/destination-coords.ts`          | `docs/data-contracts.md` (coordinate mapping, `[lng, lat]` format)                   |
| `frontend/lib/contentPolicyGuard.ts`          | `docs/ux_unified_architecture.md` (content policy enforcement)                       |
| `frontend/lib/statusCopyMap.ts`               | `docs/ux_unified_architecture.md` (status display text mapping)                      |
| `frontend/app/layout.tsx`                     | `docs/ux_unified_architecture.md` (root layout, providers, global structure)         |
| `frontend/app/page.tsx`                       | `docs/ux_unified_architecture.md` (landing page, entry point)                        |
| `.claude/commands/*`                          | `docs/repo_structure.md` (Claude Code slash commands)                                |
| `.claude/agents/*`                            | `docs/repo_structure.md` (Claude Code agent specs)                                   |
| `.codex/*`                                    | `docs/repo_structure.md` (Codex skills/config tree)                                  |
| `backend/requirements.txt`                    | `docs/repo_structure.md` (Python dependencies)                                       |
| `frontend/package.json`                       | `docs/repo_structure.md` (Node dependencies)                                         |
| `backend/migrations/versions/*`               | `docs/data-contracts.md` (migration history, schema evolution)                       |

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
- If caching changed (`cache_access.py`, `*_cache.py`, `cache_core.py`): update Caching Architecture section (cache table, key format, TTL, L1/L2 tier config)
- If hashing changed: update cache key construction documentation
- If LLM factory changed: update Model Routing section (model selection, config)
- If prompt templates changed (`prompts/*`): update Synthesizer section (prompt structure, caching note)
- If experience generator changed: update Tile Service / Experience Generation section
- If tools changed (`tools/*`): update relevant architecture description (Amadeus integration, constraint engine)
- If new endpoint serves planner data: update relevant architecture description
- PRESERVE all sections not affected by the diff

### `docs/data-contracts.md`

- If endpoints changed: update API Route Reference tables (method, path, purpose, request/response)
- If schemas changed (`schemas.py`, `graph_state.py`): update Core Schema Reference (PlanDocumentData tree, field descriptions)
- If DB models changed (`db_models.py`): update ORM Models / table definitions section
- If DB config changed (`db.py`): update Database Configuration section (pool settings, engine config)
- If streaming changed: update Streaming Protocols section (SSE/NDJSON event tables)
- If stream parser changed (`streamParser.ts`): update SSE Event Types section (frontend event handling)
- If rate limiting changed: update rate limiting tier table
- If state store changed: update Frontend State Store section (store shape, key actions, guards)
- If enums changed: update Enums & State Machines section
- If Amadeus client changed: update External API Integration section (Amadeus endpoints, data models)
- If coordinate mapping changed (`destination-coords.ts`): update Coordinate Format section (verify `[lng, lat]` invariant)
- If migrations changed: update Schema Evolution section (migration history)
- PRESERVE all sections not affected by the diff

### `docs/design-system.md`

- If DS tokens changed: update Design Tokens Reference tables (materials, actions, pills, text)
- If component patterns changed: update Component Mapping table
- If new interaction pattern added: add to Interaction Patterns section
- If chip styles changed (`chipStyles.ts`): update Pill/Chip Styling section (DS token references)
- If tile card patterns changed (`tiles/*`): update Component Mapping table
- If color usage changed: update Restricted Colors guidance
- PRESERVE all sections not affected by the diff

### `docs/ux_unified_architecture.md`

- If view states changed: update Planning Phase Progression table and Legacy Mapping
- If renderer logic changed: update Single Renderer Pattern section
- If timeline variants changed: update TimelineVariant Mapping table
- If component responsibilities changed: update Component Responsibilities table
- If hooks changed (`hooks/*`): update Custom Hooks section (view navigation, sheet management, scroll behavior)
- If layout components changed (`layout/*`): update Layout Architecture section (mobile/desktop split, swipe layout)
- If map components changed (`map/*`): update Map Integration section (Mapbox config, error boundaries)
- If ghost timeline adapter changed: update Skeleton/Loading States section
- If fill day guards changed: update State Guards section (day fill validation rules)
- If content policy guard changed: update Content Policy section
- If status copy map changed: update Status Display section (copy mapping)
- If tile utilities changed (`tileUtils.ts`, `tileSelectors.ts`): update Tile Rendering section
- If streaming behavior changed: update relevant streaming section
- If state guards changed: update State Transition Guards section
- If app layout/page changed (`app/layout.tsx`, `app/page.tsx`): update Root Layout / Entry Point section
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
