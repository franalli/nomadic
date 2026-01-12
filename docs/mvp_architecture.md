# Nomadic MVP Architecture

> Complete technical documentation for deployment planning

---

## Table of Contents

1. [Full Directory Structure](#full-directory-structure)
2. [Backend Overview](#backend-overview)
3. [Frontend Overview](#frontend-overview)
4. [File Descriptions](#file-descriptions)
5. [Cache Behavior](#cache-behavior)
6. [API Routes](#api-routes)
7. [UI and UX](#ui-and-ux)
8. [LangGraph Architecture Summary](#langgraph-architecture-summary)
9. [Database Schema](#database-schema)

---

## Full Directory Structure

```
nomadic/
├── backend/
│   ├── alembic.ini                          # Alembic migrations config
│   ├── pyproject.toml                       # Project metadata and dependencies
│   ├── requirements.txt                     # Python dependencies
│   ├── Dockerfile                           # Docker container config
│   ├── .env                                 # Environment configuration
│   ├── .env.docker                          # Docker environment config
│   ├── app/
│   │   ├── main.py                          # FastAPI app entry point
│   │   ├── config.py                        # Settings & config management
│   │   ├── db.py                            # Database engine setup (sync + async)
│   │   ├── db_models.py                     # SQLAlchemy ORM models
│   │   ├── schemas.py                       # Pydantic request/response schemas
│   │   ├── plan_graph.py                    # Core LangGraph planner engine
│   │   ├── crud_trip.py                     # Trip/session DB operations
│   │   ├── crud_document.py                 # Plan document DB operations
│   │   ├── validation.py                    # Trip input validation (LLM)
│   │   ├── graph_plan_utils.py              # Utility functions for graph
│   │   ├── debug_utils.py                   # Debug logging utilities
│   │   ├── pattern_matching.py              # Regex patterns for parsing
│   │   ├── routing_keywords.py              # Keywords for routing logic
│   │   ├── known_places.py                  # Geographic location data
│   │   ├── geocoding.py                     # Geocoding utilities
│   │   ├── middleware/
│   │   │   ├── __init__.py                  # Middleware exports
│   │   │   └── session.py                   # Session & CSRF middleware
│   │   ├── planner/
│   │   │   ├── __init__.py                  # Planner exports & cache functions
│   │   │   ├── plan_graph.py                # Core LangGraph execution
│   │   │   ├── streaming.py                 # SSE streaming implementation
│   │   │   ├── telemetry.py                 # Telemetry/observability
│   │   │   ├── metadata_mutator.py          # State metadata manipulation
│   │   │   ├── meta.py                      # Metadata helpers
│   │   │   ├── meta_keys.py                 # Metadata key constants
│   │   │   ├── hashing.py                   # Stable hashing utilities
│   │   │   ├── node_utils.py                # Node helper functions
│   │   │   ├── cache_access.py              # Cache access patterns
│   │   │   ├── test_mode.py                 # Test mode utilities
│   │   │   ├── cache/
│   │   │   │   ├── __init__.py              # Cache exports
│   │   │   │   ├── framework.py             # Unified cache framework
│   │   │   │   └── compat.py                # Cache compatibility layer
│   │   │   ├── gates/
│   │   │   │   ├── __init__.py              # Gate exports
│   │   │   │   ├── evaluator_v2.py          # Gate evaluation engine
│   │   │   │   ├── base.py                  # Gate base classes
│   │   │   │   ├── readiness.py             # Trip readiness checks
│   │   │   │   ├── precedence.py            # Gate precedence order
│   │   │   │   ├── result.py                # Gate result types
│   │   │   │   ├── intent_detection.py      # Intent parsing
│   │   │   │   ├── topic_detection.py       # Topic detection
│   │   │   │   ├── keyword_utils.py         # Keyword matching utilities
│   │   │   │   ├── suppression.py           # Gate suppression logic
│   │   │   │   ├── constants.py             # Gate constants
│   │   │   │   ├── types.py                 # GraphMetadata TypedDict
│   │   │   │   ├── checks/
│   │   │   │   │   ├── short_circuit.py     # Short circuit checks
│   │   │   │   │   └── strategy.py          # Strategy checks
│   │   │   │   └── implementations/
│   │   │   │       ├── __init__.py          # Gate class exports
│   │   │   │       ├── fast_path.py         # Fast path gate
│   │   │   │       ├── short_circuit.py     # Short circuit gate
│   │   │   │       ├── core_collection.py   # Core collection gate
│   │   │   │       ├── router_llm.py        # Router LLM gate
│   │   │   │       ├── specialist_pre_core.py
│   │   │   │       ├── strategy_pre_core.py
│   │   │   │       ├── strategy_post_core.py
│   │   │   │       ├── strategy_expansion.py
│   │   │   │       ├── strategy_topic_switch.py
│   │   │   │       ├── generate_requested.py
│   │   │   │       ├── ready_no_fields.py
│   │   │   │       └── heuristic_gates.py
│   │   │   ├── nodes/
│   │   │   │   ├── __init__.py              # Node exports
│   │   │   │   ├── base.py                  # Base node classes
│   │   │   │   ├── router.py                # Router node
│   │   │   │   ├── extractor.py             # Extractor node
│   │   │   │   ├── lqa_prepass.py           # LQA pre-pass node
│   │   │   │   ├── confidence.py            # Confidence scoring
│   │   │   │   ├── llm_utils.py             # LLM utility functions
│   │   │   │   ├── specialist_main.py       # Main specialist dispatcher
│   │   │   │   ├── strategy_main.py         # Main strategy dispatcher
│   │   │   │   ├── specialist/
│   │   │   │   │   ├── __init__.py
│   │   │   │   │   ├── base.py              # CORE_FIELDS, SPECIALIST_TYPES
│   │   │   │   │   ├── guards.py            # Core field guards
│   │   │   │   │   ├── parallel.py          # Parallel execution
│   │   │   │   │   ├── response_processor.py
│   │   │   │   │   ├── groundedness.py      # Tile-based groundedness
│   │   │   │   │   └── templates.py         # Response templates
│   │   │   │   └── strategy/
│   │   │   │       ├── __init__.py
│   │   │   │       ├── base.py              # Strategy keywords/helpers
│   │   │   │       ├── stage0.py            # Stage0Coordinator
│   │   │   │       └── stages.py            # Stage coordinators
│   │   │   ├── normalization/
│   │   │   │   ├── __init__.py              # Normalization exports
│   │   │   │   ├── date.py                  # Date parsing normalization
│   │   │   │   ├── trip_inputs.py           # Trip inputs normalization
│   │   │   │   └── types.py                 # Normalization types
│   │   │   ├── parsing/
│   │   │   │   ├── __init__.py              # Parsing exports
│   │   │   │   ├── lqa_parsers.py           # LQA response parsers
│   │   │   │   └── provenance.py            # Provenance tracking
│   │   │   └── state/
│   │   │       ├── __init__.py              # State exports
│   │   │       └── writer.py                # State writing utilities
│   │   ├── tile_service/
│   │   │   ├── __init__.py                  # Tile service exports
│   │   │   ├── service.py                   # Tile search orchestration
│   │   │   ├── provider_base.py             # Provider interface
│   │   │   ├── mock_provider.py             # Mock tile providers
│   │   │   └── models.py                    # Tile service models
│   │   └── prompts/                         # LLM prompt templates
│   │       ├── extractor.txt
│   │       ├── extractor_light.txt
│   │       ├── router.txt
│   │       ├── required_fields.txt
│   │       ├── flights.txt
│   │       ├── hotels.txt
│   │       ├── transport.txt
│   │       ├── activities.txt
│   │       ├── correction.txt
│   │       ├── general.txt
│   │       ├── response_polish.txt
│   │       ├── strategy_pre_core.txt
│   │       ├── strategy_hiking.txt
│   │       ├── strategy_diving.txt
│   │       └── ...
│   ├── migrations/
│   │   └── versions/                        # Alembic migration files
│   └── tests/                               # Test suite
│
├── frontend/
│   ├── package.json                         # NPM dependencies
│   ├── next.config.js                       # Next.js configuration
│   ├── tailwind.config.js                   # Tailwind CSS config
│   ├── tsconfig.json                        # TypeScript config
│   ├── Dockerfile                           # Docker container config
│   ├── app/
│   │   ├── layout.tsx                       # Root layout
│   │   ├── page.tsx                         # Main page
│   │   ├── globals.css                      # Global styles
│   │   └── providers.tsx                    # Context providers
│   ├── components/
│   │   ├── chat/
│   │   │   ├── ChatPanel.tsx                # Core chat UI (1000+ lines)
│   │   │   ├── ChatSkeleton.tsx             # Loading skeleton
│   │   │   ├── FlowStageIndicator.tsx       # Progress indicator
│   │   │   ├── NodeProgress.tsx             # Task progress bar
│   │   │   └── useChatStateMachine.ts       # Chat state machine
│   │   ├── layout/
│   │   │   ├── SplitLayoutView.tsx          # Main layout container
│   │   │   ├── NomadicLanding.tsx           # Page orchestrator
│   │   │   ├── TripDetailsForm.tsx          # Trip input form (1000+ lines)
│   │   │   └── hooks/
│   │   │       ├── useTripInputsEditor.ts   # Trip editing (600+ lines)
│   │   │       ├── useDateRangeSelector.ts  # Calendar state
│   │   │       ├── useBranchManager.ts      # Branch/tile management
│   │   │       ├── useLocalBookingSettings.ts
│   │   │       └── useComparisonMode.ts     # Branch comparison
│   │   ├── branches/
│   │   │   ├── BranchPanel.tsx              # Single branch display
│   │   │   ├── BranchComparisonView.tsx     # Side-by-side comparison
│   │   │   └── TileCard.tsx                 # Individual tile card
│   │   ├── pill/
│   │   │   ├── InlineEditPill.tsx           # Inline edit component
│   │   │   ├── ExpandablePill.tsx           # Expandable settings
│   │   │   ├── LocationBadge.tsx            # Location display
│   │   │   └── TruncatedDestinationList.tsx # Destination truncation
│   │   └── ui/                              # shadcn-style components
│   │       ├── button.tsx
│   │       ├── card.tsx
│   │       ├── calendar.tsx
│   │       ├── popover.tsx
│   │       ├── switch.tsx
│   │       ├── skeleton.tsx
│   │       └── confirm-dialog.tsx
│   ├── state/
│   │   ├── chatStore.ts                     # Chat messages (Zustand)
│   │   ├── documentStore.ts                 # Plan document (Zustand)
│   │   └── uiStore.ts                       # UI state (Zustand)
│   ├── hooks/
│   │   └── useTripPlanning.ts               # Compound planning hook
│   ├── lib/
│   │   ├── api.ts                           # API integration (500+ lines)
│   │   ├── utils.ts                         # Helper functions
│   │   └── summary.ts                       # Trip summary logic
│   └── types/
│       ├── document.ts                      # Document types
│       ├── chat.ts                          # Chat types
│       ├── tile.ts                          # Tile types
│       └── generated.ts                     # OpenAPI generated types
│
├── docs/
│   ├── plan_graph_analysis.md               # LangGraph architecture docs
│   └── mvp_architecture.md                  # This file
│
└── docker-compose.yml                       # Docker orchestration
```

---

## Backend Overview

The backend is a **FastAPI** application implementing a conversational trip planning system powered by **LangGraph** (a state machine framework built on LangChain).

### Tech Stack

| Component | Technology |
|-----------|------------|
| Framework | FastAPI |
| Database | PostgreSQL (production) / SQLite (development) |
| ORM | SQLAlchemy (async + sync) |
| Migrations | Alembic |
| LLM Integration | OpenAI API (gpt-4o-mini) |
| State Machine | LangGraph |
| Observability | LangSmith |
| Caching | In-memory TTL caches |

### Architecture Layers

```
┌─────────────────────────────────────────┐
│  API Layer (FastAPI)                    │
│  - REST endpoints                       │
│  - SSE streaming                        │
│  - Session/CSRF middleware              │
├─────────────────────────────────────────┤
│  Business Logic                         │
│  - LangGraph state machine              │
│  - Gate-based routing                   │
│  - Specialist nodes                     │
├─────────────────────────────────────────┤
│  Data Access                            │
│  - CRUD operations                      │
│  - Document merge logic                 │
│  - Caching layer                        │
├─────────────────────────────────────────┤
│  Database (PostgreSQL/SQLite)           │
│  - Sessions, Contexts, Messages         │
│  - PlanDocument (source of truth)       │
└─────────────────────────────────────────┘
```

### Key Design Patterns

1. **Single Source of Truth (SSoT)**: `PlanDocument` is the authoritative state
2. **Gate-Based Routing**: 13 gates determine conversation flow in precedence order
3. **CRDT-Style Merging**: Conflict resolution for concurrent updates
4. **Optimistic Concurrency**: Version-based conflict detection (HTTP 409)
5. **Real-Time Streaming**: SSE for token-by-token LLM responses

---

## Frontend Overview

The frontend is a **Next.js 16** application using the App Router with **Zustand** for state management.

### Tech Stack

| Component | Technology |
|-----------|------------|
| Framework | Next.js 16 (App Router) |
| State Management | Zustand 5 |
| UI Components | Radix UI |
| Icons | Lucide React |
| Calendar | React Day Picker |
| Markdown | react-markdown + remark-gfm |
| Animations | Framer Motion |
| Styling | Tailwind CSS 3.4 |
| Types | TypeScript 5.5 |

### State Architecture

```
┌─────────────────────────────────────────┐
│  Zustand Stores                         │
├─────────────────────────────────────────┤
│  chatStore.ts                           │
│  - messages: ChatMessage[]              │
│  - sessionState: object                 │
│  - historyLoaded: boolean               │
├─────────────────────────────────────────┤
│  documentStore.ts                       │
│  - version: number                      │
│  - document: PlanDocumentData           │
│  - llmUpdatedFields: Set<string>        │
│  - selectedTiles: Record<string, Set>   │
├─────────────────────────────────────────┤
│  uiStore.ts                             │
│  - selectedBranchId: string             │
│  - isComparisonMode: boolean            │
│  - comparisonBranchIds: [string, string]│
└─────────────────────────────────────────┘
```

### Component Hierarchy

```
NomadicLanding (page orchestrator)
├── SplitLayoutView (responsive layout)
│   ├── ChatPanel (sidebar)
│   │   ├── Messages (with streaming)
│   │   ├── TripDetailsForm (collapsible)
│   │   │   ├── InlineEditPill (origin, destinations)
│   │   │   ├── Calendar (date picker)
│   │   │   └── ExpandablePill (settings)
│   │   ├── PromptSuggestions
│   │   └── InputArea (with generate button)
│   └── MainContent
│       ├── BranchPanel (itinerary display)
│       │   └── TileCard (hotel/flight/activity)
│       └── BranchComparisonView (side-by-side)
```

---

## File Descriptions

### Backend Core Files

| File | Purpose |
|------|---------|
| `main.py` | FastAPI app entry point with all REST endpoints |
| `config.py` | Pydantic settings with environment variable loading |
| `db.py` | Database engine setup (async + sync), connection pooling |
| `db_models.py` | SQLAlchemy ORM models (Session, TripContext, ChatMessage, PlanDocument) |
| `schemas.py` | Pydantic request/response schemas for API validation |
| `plan_graph.py` | Main LangGraph state machine orchestration |
| `crud_trip.py` | CRUD operations for sessions, contexts, messages |
| `crud_document.py` | Document operations with CRDT-style merge logic |
| `validation.py` | LLM-based trip input validation with caching |

### Backend Planner Package

| File | Purpose |
|------|---------|
| `streaming.py` | SSE streaming infrastructure with StreamingContext registry |
| `telemetry.py` | LangSmith integration for observability |
| `metadata_mutator.py` | Type-safe atomic metadata mutations |
| `cache/framework.py` | CacheNode ABC with TTL, versioning, and invalidation |
| `gates/evaluator_v2.py` | Central gate evaluation engine |
| `gates/precedence.py` | GatePrecedence IntEnum (10-999) |
| `gates/readiness.py` | TripReadiness dataclass for trip status |
| `nodes/extractor.py` | LLM-based trip data extraction |
| `nodes/router.py` | Intent classification with scoring |
| `nodes/lqa_prepass.py` | Zero-LLM pre-pass for simple answers |
| `nodes/specialist_main.py` | Dispatcher for domain specialists |
| `nodes/strategy_main.py` | Multi-stage strategy generation |

### Frontend Core Files

| File | Purpose |
|------|---------|
| `ChatPanel.tsx` | Core chat UI with streaming, messages, input |
| `TripDetailsForm.tsx` | Trip input editing form with validation |
| `SplitLayoutView.tsx` | Responsive layout (sidebar + main content) |
| `chatStore.ts` | Zustand store for chat messages and session |
| `documentStore.ts` | Zustand store for plan document (SSoT) |
| `api.ts` | API client with CSRF, retry logic, streaming |
| `useTripInputsEditor.ts` | State machine for trip input editing |
| `useBranchManager.ts` | Branch selection and tile management |

---

## Cache Behavior

### Backend Caches

The backend implements **5 parallel caches** with version-controlled payloads:

| Cache | Max Size | TTL | Purpose |
|-------|----------|-----|---------|
| `ExtractorCache` | 500 | 5 min | Avoid re-extracting same input |
| `ResponseCache` | 500 | 30 min | Reuse specialist responses |
| `StrategyCache` | 200 | 5 min | Reuse strategy content |
| `TileCache` | 100 | 5 min | Cache tile API results |
| `GateEvaluationCache` | 200 | 5 min | Cache routing decisions |
| `ValidationCache` | 1000 | 24 hours | Trip input validation results |

### Cache Key Components

| Cache | Key Contains |
|-------|--------------|
| Extractor | session_id, user_text_hash, core_fields_hash, mode, model_id |
| Response | node_name, core_fields_hash, follow_up_hash, user_text_hash, model_id |
| Strategy | session_id, topic, core_fields_hash, section_id, lifecycle_hash |
| Tile | session_id, tile_type, query_hash, settings_hash |
| Validation | normalized_text (city/location name) |

### Cache Invalidation Triggers

| Trigger | Caches Invalidated |
|---------|-------------------|
| Core fields change | extractor, response, strategy, tile |
| Date change | tile |
| Travelers change | tile |
| Hotel settings change | tile (hotels) |
| Flight settings change | tile (flights) |
| Activity settings change | tile (activities) |
| Strategy topic switch | strategy |
| Session timeout (14d) | All |
| Admin clear endpoint | All (except rate limiting) |

### Cache Version Control

All caches wrap data in a versioned payload:

```python
CachePayload:
    schema_version: int       # CACHE_SCHEMA_VERSION
    logic_version: int        # NODE_LOGIC_VERSION[node]
    prompt_bundle_hash: str   # Hash of all prompt files
    planner_build_id: str     # Build identifier
    created_at: float
    data: Any
```

### Frontend Caches

| Type | Storage | Purpose |
|------|---------|---------|
| Branch selection | localStorage | Persist selected branch across sessions |
| Chat history | Zustand (memory) | Single-load, not re-fetched on mount |
| UI preferences | localStorage | Comparison mode, consent state |

---

## API Routes

### Health & Admin

| Method | Endpoint | Purpose |
|--------|----------|---------|
| GET | `/health` | Health check with build info |
| POST | `/v1/admin/clear-validation-cache` | Clear validation cache |
| POST | `/v1/admin/fresh-start` | Clear all caches & checkpoints |
| GET | `/v1/admin/graph-stats` | Graph routing statistics |
| POST | `/v1/admin/clear-all-checkpoints` | Emergency checkpoint clear |
| POST | `/v1/admin/gate-trace` | Debug gate evaluation (no execution) |
| GET | `/v1/admin/planner` | Planner configuration debug |

### Planning

| Method | Endpoint | Purpose |
|--------|----------|---------|
| POST | `/v1/graph_plan` | Main planning endpoint (sync) |
| POST | `/v1/graph_plan/stream` | SSE streaming planning |
| POST | `/v1/validate-trip-input` | Validate origin/destination with LLM |

### Session & Chat

| Method | Endpoint | Purpose |
|--------|----------|---------|
| DELETE | `/v1/session` | Reset session & clear cookies |
| GET | `/v1/chat` | Get chat history (last 50 messages) |
| DELETE | `/v1/chat/last` | Delete last message with undo |

### Document Management

| Method | Endpoint | Purpose |
|--------|----------|---------|
| GET | `/v1/document` | Get current plan document |
| PATCH | `/v1/document` | Apply partial updates (CRDT merge) |
| POST | `/v1/document/tiles/{branch_id}` | Fetch tiles for branch |
| POST | `/v1/tiles/refresh` | Force refresh tiles with new settings |

### Analytics

| Method | Endpoint | Purpose |
|--------|----------|---------|
| POST | `/v1/tiles/click` | Track tile click |
| POST | `/v1/suggestions/click` | Track suggestion pill click |

### Request/Response Schemas

**GraphPlanRequest:**
```typescript
{
  message: string
  trip_inputs?: DocumentTripInputs
  session_state?: object
  thread_id?: string
}
```

**GraphPlanResponse:**
```typescript
{
  document: PlanDocumentData
  session_state: object
  observability?: {
    gate_trace: string[]
    cache_summary: object
    model_used: string
  }
}
```

---

## UI and UX

### Layout Patterns

**Desktop (>768px):**
- Fixed sidebar (25% width) with chat panel
- Scrollable main content with branches/results
- Trip details form collapsible within sidebar

**Mobile (<768px):**
- Full-screen main content
- Bottom-right floating chat toggle
- Slide-in drawer for chat panel
- Single-month calendar view

### Input Patterns

| Pattern | Component | Use Case |
|---------|-----------|----------|
| Inline Pill | `InlineEditPill` | Origin, destinations, dates |
| Expandable Pill | `ExpandablePill` | Flight/hotel/activity settings |
| Location Badge | `LocationBadge` | Display removable locations |
| Calendar Popover | `Calendar` | Date range selection with presets |

### Loading States

| State | Component | Trigger |
|-------|-----------|---------|
| Chat skeleton | `ChatSkeleton` | Initial history load |
| Typing indicator | 3 animated dots | LLM processing |
| Node progress | `NodeProgress` | Task-specific progress bar |
| Generating loader | Animated spinner | Itinerary generation |

### Feedback Mechanisms

| Type | Implementation |
|------|----------------|
| Validation errors | Inline below fields with red styling |
| Pending validation | Spinner inside input pill |
| LLM updates | Sparkle animation on affected fields |
| Toast notifications | Top-right for confirmations/errors |
| Flow progress | `FlowStageIndicator` showing pipeline stage |

### Accessibility

- ARIA labels and descriptions on all interactive elements
- Role attributes (log, alert, button)
- Touch targets minimum 36x36px
- Semantic HTML structure
- Keyboard navigation support

### Animations

- **Framer Motion**: Message entrance (staggered), collapse/expand
- **CSS Transitions**: Hover states, button feedback
- **Custom**: Typing indicator dots, sparkle effect for LLM updates

---

## LangGraph Architecture Summary

> Extracted from [plan_graph_analysis.md](plan_graph_analysis.md)

### Overview

LangGraph-based conversational trip planning system with **19 nodes**.

| Category | Count | Description |
|----------|-------|-------------|
| LLM-Powered Nodes | 11 | Use OpenAI API for generation |
| Deterministic Nodes | 8 | Pure Python logic, no LLM |
| Short Circuit Types | 7 | Bypass patterns for fast response |
| Caching Strategies | 5 | Token-saving cache mechanisms |

### Design Principles

1. **Template-First**: Use templates before LLM calls
2. **Gated Specialists**: Block domain specialists until core fields collected
3. **Pre-Core Mode**: Answer domain questions while collecting core fields
4. **Value-First Strategy**: Provide destination inspiration before asking
5. **LLM Budget**: Max 1 LLM call per non-ready turn with deterministic fallback
6. **SSoT Enforcement**: Single source of truth via `StateWriter`

### Node Pipeline

```
User Input
    │
    ▼
┌───────────────┐
│  lqa_prepass  │  Zero-LLM parsing (dates, numbers, cities)
└───────┬───────┘
        │
        ▼
┌───────────────┐
│   extractor   │  LLM-based trip data extraction
└───────┬───────┘
        │
        ▼
┌───────────────┐
│ GateEvaluator │  13 gates checked in precedence order
└───────┬───────┘
        │
   ┌────┼────┬────┬────┬────┐
   │    │    │    │    │    │
   ▼    ▼    ▼    ▼    ▼    ▼
┌─────┐┌─────┐┌─────┐┌─────┐┌─────┐┌─────┐
│short││req'd││spec-││rout-││strat││gener│
│circ.││field││ialist││er   ││egy  ││ate  │
└──┬──┘└──┬──┘└──┬──┘└──┬──┘└──┬──┘└──┬──┘
   │      │      │      │      │      │
   └──────┴──────┴──────┴──────┴──────┘
                    │
                    ▼
          ┌─────────────────┐
          │validate_and_merge│
          └────────┬────────┘
                   │
                   ▼
          ┌─────────────────┐
          │branch_postprocess│
          └────────┬────────┘
                   │
              ┌────┴────┐
              ▼         │
        ┌──────────┐    │
        │tile_search│   │
        └────┬─────┘    │
             │          │
             └────┬─────┘
                  ▼
           ┌──────────┐
           │ summarize │
           └────┬─────┘
                │
                ▼
         ┌──────────────┐
         │response_polish│
         └──────────────┘
```

### Gate Precedence

| Precedence | Gate | Destination |
|------------|------|-------------|
| 10 | STRATEGY_EXPANSION | strategy_node |
| 20 | GENERATE_REQUESTED | generate_responder |
| 30 | SHORT_CIRCUIT | short_circuit_responder |
| 35 | STRATEGY_POST_CORE | strategy_node (stage 1) |
| 40 | READY_NO_FIELDS | summarize / specialist |
| 50 | FAST_PATH | required_fields_node |
| 60 | SPECIALIST_PRE_CORE | specialists (pre-core) |
| 70 | STRATEGY_TOPIC_SWITCH | strategy_node |
| 80 | STRATEGY_PRE_CORE_VALUE | strategy_node (stage 0) |
| 90 | CORE_COLLECTION | required_fields_node |
| 110 | QUESTION_KEYWORD | based on keyword |
| 999 | ROUTER_LLM | router node (fallback) |

### Strategy Stages

| Stage | Name | Trigger | Max Tokens |
|-------|------|---------|------------|
| 0 | Pre-Core | Strategy topic + dates + destination | 300 |
| 1 | Outline | Core fields complete | 512 |
| 2 | Expansion | User requests "show more" | 600-1536 |

### Streaming Architecture

| Mode | Symbol | Behavior |
|------|--------|----------|
| Real-time | streaming | Tokens from OpenAI as generated |
| Simulated | simulated | Token-by-token 15-35ms delays |
| Buffered | none | Internal nodes, no output |

---

## Database Schema

### Tables Overview

| Table | Purpose | Key Fields |
|-------|---------|------------|
| `sessions` | User session tracking | session_token, last_activity_at, expires_at |
| `trip_contexts` | Trip planning context | session_id, raw_prompt, parent_context_id |
| `chat_messages` | Chat history | trip_context_id, role, content, trip_inputs_snapshot |
| `plan_documents` | Centralized plan state (SSoT) | trip_context_id, document_data, version, updated_by |
| `tile_clicks` | Analytics tracking | tile_id, session_id, clicked_at |
| `suggestion_clicks` | Analytics tracking | suggestion_text, session_id, clicked_at |

### Session Table

```sql
CREATE TABLE sessions (
    id SERIAL PRIMARY KEY,
    session_token VARCHAR(255) UNIQUE NOT NULL,
    created_at TIMESTAMP DEFAULT NOW(),
    last_activity_at TIMESTAMP DEFAULT NOW(),
    expires_at TIMESTAMP NOT NULL,  -- 90 days from creation
    CONSTRAINT session_token_unique UNIQUE (session_token)
);
```

| Column | Type | Description |
|--------|------|-------------|
| id | SERIAL | Primary key |
| session_token | VARCHAR(255) | UUID4 unique identifier |
| created_at | TIMESTAMP | Session creation time |
| last_activity_at | TIMESTAMP | For idle timeout (14 days) |
| expires_at | TIMESTAMP | Absolute expiration (90 days) |

**Methods:**
- `is_expired()`: Check if session has expired
- `refresh_activity()`: Update last_activity_at timestamp

### TripContext Table

```sql
CREATE TABLE trip_contexts (
    id SERIAL PRIMARY KEY,
    session_id INTEGER REFERENCES sessions(id),
    raw_prompt TEXT,
    parent_context_id INTEGER REFERENCES trip_contexts(id),
    created_at TIMESTAMP DEFAULT NOW()
);
```

| Column | Type | Description |
|--------|------|-------------|
| id | SERIAL | Primary key |
| session_id | INTEGER (FK) | References sessions.id |
| raw_prompt | TEXT | User's initial prompt |
| parent_context_id | INTEGER (FK) | For hierarchical contexts |
| created_at | TIMESTAMP | Context creation time |

### ChatMessage Table

```sql
CREATE TABLE chat_messages (
    id SERIAL PRIMARY KEY,
    trip_context_id INTEGER REFERENCES trip_contexts(id),
    role VARCHAR(50) NOT NULL,  -- 'user', 'assistant', 'system'
    content TEXT NOT NULL,
    trip_inputs_snapshot JSONB,  -- For undo functionality
    metadata JSONB,
    created_at TIMESTAMP DEFAULT NOW()
);
```

| Column | Type | Description |
|--------|------|-------------|
| id | SERIAL | Primary key |
| trip_context_id | INTEGER (FK) | References trip_contexts.id |
| role | VARCHAR(50) | 'user', 'assistant', or 'system' |
| content | TEXT | Message content |
| trip_inputs_snapshot | JSONB | Snapshot for undo capability |
| metadata | JSONB | Additional metadata |
| created_at | TIMESTAMP | Message timestamp |

### PlanDocument Table (Source of Truth)

```sql
CREATE TABLE plan_documents (
    id SERIAL PRIMARY KEY,
    trip_context_id INTEGER UNIQUE REFERENCES trip_contexts(id),
    document_data JSONB NOT NULL,
    version INTEGER DEFAULT 1,
    updated_by VARCHAR(50),  -- 'user' or 'planner'
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
```

| Column | Type | Description |
|--------|------|-------------|
| id | SERIAL | Primary key |
| trip_context_id | INTEGER (FK) | Unique reference to trip_contexts.id |
| document_data | JSONB | Plan data (see structure below) |
| version | INTEGER | Optimistic concurrency control |
| updated_by | VARCHAR(50) | 'user' or 'planner' |
| created_at | TIMESTAMP | Document creation time |
| updated_at | TIMESTAMP | Last update time |

### PlanDocument Data Structure (JSONB)

```typescript
{
  trip_context_id: number,
  trip_inputs: {
    destinations: string[],
    origin: string | null,
    start_date: string | null,        // YYYY-MM-DD
    end_date: string | null,
    adults: number | null,
    children: number | null,
    requires_assistance: boolean | null,
    budget: number | null,
    currency: string,                 // USD, EUR, GBP, etc.
    missing_fields: string[],
    multi_city_intent: 'multi_city' | 'separate' | null,

    booking_types: {
      flights: boolean,
      hotels: boolean,
      ground_transport: boolean,
      activities: boolean
    },
    flight_settings: {
      round_trip: boolean,
      direct_only: boolean,
      cabin_class: 'economy' | 'premium_economy' | 'business' | 'first'
    },
    hotel_settings: {
      min_stars: number,              // 0-5
      amenities: string[]
    },
    activity_settings: {
      categories: string[],
      skill_level: string | null
    },
    transport_settings: {
      car: boolean,
      train: boolean,
      bus: boolean
    }
  },
  branches: [
    {
      id: string,
      label: string,
      description: string,
      destinations: string[],
      is_primary: boolean,
      tiles: {
        stays: string[],
        flights: string[],
        activities: string[]
      },
      selections: {
        stay: string | null,
        flight: string | null,
        activities: string[]
      }
    }
  ],
  tiles: {
    [tile_id]: {
      id: string,
      type: 'stay' | 'flight' | 'activity',
      title: string,
      subtitle: string,
      image_url: string,
      price_estimate: number,
      currency: string,
      deeplink_url: string,
      rating: number,                 // 0-5
      location_label: string,
      meta: object
    }
  },
  ready_to_generate: boolean,
  suggested_responses: string[]
}
```

### Analytics Tables

```sql
CREATE TABLE tile_clicks (
    id SERIAL PRIMARY KEY,
    tile_id VARCHAR(255) NOT NULL,
    session_id INTEGER REFERENCES sessions(id),
    clicked_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE suggestion_clicks (
    id SERIAL PRIMARY KEY,
    suggestion_text TEXT NOT NULL,
    session_id INTEGER REFERENCES sessions(id),
    clicked_at TIMESTAMP DEFAULT NOW()
);
```

### Indexes

```sql
-- Session lookups
CREATE INDEX idx_sessions_token ON sessions(session_token);
CREATE INDEX idx_sessions_expires ON sessions(expires_at);

-- Trip context lookups
CREATE INDEX idx_trip_contexts_session ON trip_contexts(session_id);

-- Chat message lookups
CREATE INDEX idx_chat_messages_context ON chat_messages(trip_context_id);
CREATE INDEX idx_chat_messages_created ON chat_messages(created_at);

-- Document lookups
CREATE UNIQUE INDEX idx_plan_documents_context ON plan_documents(trip_context_id);
```

### Connection Configuration

**Development (SQLite):**
```
DATABASE_URL=sqlite:///./nomadic.db
```

**Production (PostgreSQL):**
```
DATABASE_URL=postgresql://user:pass@host:5432/nomadic
```

**Async Driver Conversion:**
- SQLite: `sqlite+aiosqlite://`
- PostgreSQL: `postgresql+asyncpg://`

**Pool Configuration:**
- Base connections: 15
- Overflow: 25
- Pool recycle: 3600s (1 hour)

---

## Deployment Considerations

### Environment Variables

**Required:**
| Variable | Description |
|----------|-------------|
| `DATABASE_URL` | PostgreSQL/SQLite connection string |
| `OPENAI_API_KEY` | OpenAI API key |
| `FRONTEND_ORIGIN` | CORS allowed origin |
| `COOKIE_DOMAIN` | Cookie domain for subdomain sharing |

**Optional:**
| Variable | Description |
|----------|-------------|
| `LANGSMITH_API_KEY` | LangSmith tracing key |
| `LANGSMITH_PROJECT` | LangSmith project name |
| `TRACE_SAMPLE_RATE` | Sampling rate for traces (0.0-1.0) |

### Production Requirements

1. **Database**: PostgreSQL with async driver (asyncpg)
2. **Compute**: Single instance sufficient for MVP
3. **Memory**: ~2GB recommended for caching
4. **Storage**: Minimal (database-backed state)
5. **Network**: HTTPS required for cookies

### Docker Deployment

```yaml
services:
  backend:
    build: ./backend
    ports:
      - "8000:8000"
    environment:
      - DATABASE_URL=postgresql://...
      - OPENAI_API_KEY=${OPENAI_API_KEY}
      - FRONTEND_ORIGIN=https://your-domain.com
    depends_on:
      - postgres

  frontend:
    build: ./frontend
    ports:
      - "3000:3000"
    environment:
      - NEXT_PUBLIC_API_URL=https://api.your-domain.com

  postgres:
    image: postgres:15
    volumes:
      - postgres_data:/var/lib/postgresql/data
    environment:
      - POSTGRES_DB=nomadic
      - POSTGRES_USER=nomadic
      - POSTGRES_PASSWORD=${POSTGRES_PASSWORD}
```

### Scaling Considerations

| Component | Scale Strategy |
|-----------|---------------|
| Backend API | Horizontal (stateless) |
| Database | Vertical (single source of truth) |
| LangGraph Checkpoints | External store (PostgreSQL) |
| Cache | Per-instance (not shared) |
| Frontend | CDN + Edge functions |
