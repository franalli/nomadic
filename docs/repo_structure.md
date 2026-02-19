# Repository Structure

This document provides a comprehensive overview of the Nomadic codebase structure.

## Root Directory

```
nomadic/
├── .claude/                    # Claude Code configuration
│   ├── agents/                 # Specialist agent specs (backend, frontend, code-reviewer)
│   └── commands/               # Custom slash commands (audit, verify-build, etc.)
├── .codex/                     # (deleted) Codex skills migrated to Claude Code `.claude/commands/`
├── .github/                    # GitHub workflows and instructions
├── .vscode/                    # VS Code settings
├── backend/                    # Python FastAPI backend
├── docs/                       # Architecture documentation
├── frontend/                   # Next.js frontend
├── scripts/                    # Root-level utility scripts
│   ├── cleanup-claude-history.ps1  # Windows history cleanup
│   ├── cleanup-claude-history.sh   # Unix history cleanup
│   ├── copy-key-files.sh           # Copy key backend files to docs/
│   └── count_prompt_tokens.py      # Token counting utility
├── .claudeignore               # Claude Code ignore patterns
├── .gitignore                  # Git ignore patterns
├── .pre-commit-config.yaml     # Pre-commit hooks
├── .secrets.baseline           # detect-secrets baseline
├── AGENTS.md                   # Local Codex agent/skill trigger instructions
├── CLAUDE.md                   # AI assistant instructions
├── docker-compose.yml          # Docker configuration
├── README.md                   # Project readme
└── render.yaml                 # Render deployment config
```

---

## Backend (`/backend`)

Python FastAPI application with LangGraph-based trip planning.

```
backend/
├── app/
│   ├── __init__.py
│   ├── analytics_routes.py     # Analytics API routes (extracted from main.py)
│   ├── config.py               # Application configuration
│   ├── crud_document.py        # Document CRUD operations
│   ├── crud_trip.py            # Trip CRUD operations
│   ├── db.py                   # Database connection
│   ├── db_models.py            # SQLAlchemy models
│   ├── debug_utils.py          # Debugging utilities
│   ├── graph_plan_utils.py     # LangGraph plan utilities
│   ├── lifespan.py             # Application lifespan hooks (startup + shutdown)
│   ├── main.py                 # FastAPI application entry
│   ├── placeholders.py         # Placeholder data
│   ├── request_dedup.py        # Idempotency key cache for expand-itinerary (TTLCache, extracted from main.py)
│   ├── streaming.py            # SSE + NDJSON streaming generators (extracted from main.py)
│   ├── validation_cache.py     # Validation cache infrastructure (6 TTL caches, extracted from validation.py)
│   ├── plan_graph.py           # LangGraph workflow definition
│   ├── rate_limit.py           # Rate limiting configuration (extracted from main.py)
│   ├── safety_snippets.json    # Safety-related content
│   ├── schemas.py              # Pydantic request/response schemas
│   ├── sse_state.py            # SSE connection tracking state (extracted from main.py)
│   ├── validation.py           # Input validation
│   │
│   ├── data/
│   │   ├── __init__.py
│   │   └── demo_curation.py    # Demo/curated data
│   │
│   ├── middleware/
│   │   ├── __init__.py
│   │   └── session.py          # Session middleware
│   │
│   ├── planner/                # LangGraph trip planner (7-node architecture)
│   │   ├── __init__.py
│   │   ├── hashing.py          # Hash utilities
│   │   ├── llm_factory.py      # Provider-agnostic LLM factory (OpenAI/Gemini auto-routing)
│   │   ├── specialist_registry.py # Specialist config SSoT (keywords, constraints, flags)
│   │   ├── test_mode.py        # Test mode utilities
│   │   │
│   │   ├── nodes/              # LangGraph nodes (7-node structure)
│   │   │   ├── __init__.py
│   │   │   ├── constraint_guard.py         # Constraint validation
│   │   │   ├── input_gate_config.py        # Input gate threshold constants (dates, travelers, budget)
│   │   │   ├── input_gates.py              # Pre-routing input validation (5 gates: Date, Duration, Traveler, Budget, Destination)
│   │   │   ├── intent_router.py            # Intent classification (main orchestration)
│   │   │   │   ├── router_extraction.py        # LLM extraction & field validation (Stage 9A)
│   │   │   ├── router_category_sync.py     # Tier 2 detection & actionable input (Stage 9B)
│   │   │   ├── router_utils.py             # Shared router utilities (greetings, origin detection, destination context)
│   │   │   ├── expert_constraints.py      # Local expert Pydantic schemas + LOCAL_EXPERT_CONSTRAINTS (constraint grounding injected into LLM prompt)
│   │   │   ├── local_expert.py             # Local knowledge node
│   │   │   ├── logistics_node.py           # Flights/hotels data fetcher
│   │   │   ├── specialist_schemas.py  # Specialist Pydantic schemas
│   │   │   ├── synthesizer.py         # Response synthesizer
│   │   │   ├── trip_architect.py      # Main planning architect
│   │   │   └── vertical_specialist.py # Domain experts (8 specialists, registry-driven)
│   │   │
│   │   ├── services/
│   │   │   ├── __init__.py
│   │   │   ├── admin_utils.py       # Admin utility functions
│   │   │   ├── feasibility_service.py # LLM-backed geographic feasibility checks (extracted from vertical_specialist.py)
│   │   │   ├── iata_resolver.py     # IATA airport code resolver (LLM-backed)
│   │   │   ├── itinerary_adapter.py # Thin bridge: GraphState → ItineraryBuilder
│   │   │   ├── response_envelope.py # Response envelope builder for plan state
│   │   │   ├── section_builder.py   # Strategy section CRUD
│   │   │   └── state_serde.py       # State serialization/deserialization
│   │   │
│   │   └── state/
│   │       ├── __init__.py
│   │       ├── graph_state.py   # Planner state schemas (renamed from schemas.py)
│   │       └── typed_meta.py   # Typed metadata bridge (TurnMeta, get_trip_settings)
│   │
│   ├── prompts/                # LLM prompt templates
│   │   ├── synthesizer.txt
│   │   └── specialists/
│   │       ├── climbing.txt
│   │       ├── cycling.txt
│   │       ├── diving.txt
│   │       ├── hiking.txt
│   │       ├── local_expert.txt
│   │       ├── sailing.txt
│   │       ├── skiing.txt
│   │       ├── surfing.txt
│   │       └── wildlife_safari.txt
│   │
│   ├── services/
│   │   ├── __init__.py
│   │   ├── cache_core.py            # Shared MemoryCache primitive (TTLCache + RLock + stats) + l2_upsert()
│   │   ├── experience_generator.py  # Tier 2 experience tile generation via gpt-4o-mini (L1+L2 cache)
│   │   ├── itinerary_builder.py     # Itinerary construction service
│   │   ├── regen_strategy.py        # Selective regeneration strategy computation
│   │   ├── router_cache.py          # Thread-safe L1 cache for router extraction (context-aware)
│   │   ├── specialist_cache.py      # Thread-safe L1+L2 cache for specialist LLM outputs
│   │   ├── task_tracker.py          # Shared fire-and-forget background task tracker
│   │   ├── tile_cache.py            # Thread-safe L1+L2 cache for tile provider data (24h TTL)
│   │   ├── unsplash.py              # Unsplash image service (cooldown pruning on prefetch)
│   │   └── unsplash_queries.py      # Unsplash query helpers (includes Tier 2 activity queries)
│   │
│   ├── utils/                 # Shared utility modules
│   │   ├── __init__.py
│   │   └── tile_utils.py      # Tile flattening (category-grouped → ID-based map)
│   │
│   ├── tile_service/           # Tile data providers
│   │   ├── __init__.py
│   │   ├── amadeus_provider.py # Amadeus API integration
│   │   ├── curated_provider.py # Curated content provider
│   │   ├── mock_provider.py    # Mock data for testing
│   │   ├── models.py           # Tile models
│   │   ├── provider_base.py    # Base provider class
│   │   └── service.py          # Tile service orchestrator
│   │
│   └── tools/                  # LangGraph tools
│       ├── __init__.py
│       ├── amadeus_client.py   # Amadeus API client
│       ├── circuit_breaker.py  # Circuit breaker + rate limiter for external APIs (extracted from amadeus_client.py)
│       ├── constraint_engine.py # Constraint processing
│       └── tile_service.py     # Tile service tool
│
├── migrations/                 # Alembic database migrations
│   ├── env.py
│   ├── README                  # Alembic migrations readme
│   ├── script.py.mako          # Alembic migration template
│   └── versions/               # Migration version files
│       ├── 0cc367f7e2df_add_suggestion_clicks_table.py
│       ├── 297678ec8f79_add_plan_documents_table.py
│       ├── 2a4d5c1b6f2c_drop_unused_planner_inputs.py
│       ├── 2e2c7a728ad8_add_session_expiration_columns.py
│       ├── 448d1359999b_add_trip_inputs_snapshot_to_chat_.py
│       ├── 46379117fccb_drop_user_id_from_tile_clicks.py
│       ├── 4a6c1f40c1d2_initial_schema.py
│       ├── 5d9c7b4d3a10_merge_planner_cleanup_and_chat_messages.py
│       ├── 5f2c5416d5c3_tile_click_nullable_and_session_token.py
│       ├── 817b72698e5b_add_unsplash_image_cache_table.py
│       ├── 8ef3b6a8e5c1_trip_context_parents_and_session_prefs.py
│       ├── add_variant_to_unsplash_cache.py
│       ├── ae0f06f2c384_remove_legacy_tables.py
│       ├── c1f8e8bf9d21_chat_messages_table.py
│       ├── 0347ceb87559_add_response_cache_table.py  # Specialist LLM cache
│       └── add_cache_type_column.py                  # cache_type column for multi-tier caching
│
├── scripts/
│   └── check_ssot_violations.py  # SSOT validation script
│
├── tests/
│   ├── conftest.py                       # Pytest fixtures
│   ├── llm_stub.py                       # LLM mock for testing
│   ├── run_curl_flows.sh                 # End-to-end curl flow tests
│   ├── test_architecture.py              # Architecture tests
│   ├── test_conflict_resolution.py       # Conflict resolution & constraint alias tests
│   ├── test_cross_domain_constraints.py  # Cross-domain constraint tests
│   ├── test_demo_dataset.py              # Demo data tests
│   ├── test_endpoint_contract.py         # Endpoint response contract tests
│   ├── test_experience_generator.py      # Experience generator tests
│   ├── test_fill_day_coordinates.py      # Fill-day coordinate + constraint mapping tests
│   ├── test_hash_ban.py                  # Hash ban tests
│   ├── test_iata_resolver.py             # IATA resolver tests
│   ├── test_import_contract.py           # Import contract tests
│   ├── test_input_gates.py              # Input gate validation tests (5 gates + registry)
│   ├── test_intent_router_settings.py    # IntentRouter extracted settings contract tests
│   ├── test_itinerary_builder.py         # Itinerary builder tests
│   ├── test_llm_feasibility.py           # LLM geographic feasibility tests
│   ├── test_logistics_tier2.py           # Logistics Tier-2 generation, backfill pipeline, affinity sorting tests
│   ├── test_main_trip_input_merge.py     # Document PATCH no-op dedupe + merge behavior tests
│   ├── test_multi_specialist_integration.py  # Multi-specialist tests
│   ├── test_plan_schema.py               # Plan schema tests
│   ├── test_regen_strategy.py            # Selective regen field hash + strategy tests
│   ├── test_response_envelope.py         # Plan view state resolver + envelope contract tests
│   ├── test_router_cache.py              # Router cache tests (context-dependency detection)
│   ├── test_router_category_sync.py      # Router category merge-mode + prefetch metadata tests
│   ├── test_routing.py                   # Routing tests
│   ├── test_session_middleware.py        # Session middleware behavior tests
│   ├── test_specialist_cache.py          # Specialist LLM cache tests (thread safety, L1/L2)
│   ├── test_fill_day_constraints.py      # Fill-day constraint validation (Tier 1 placement gates)
│   ├── test_specialist_structured.py     # Specialist structured output tests
│   ├── test_stage2_integration.py        # Stage 2 integration tests
│   ├── test_stage11_day_preferences.py   # Stage 11 day preference tests
│   ├── test_synthesizer_template_contract.py  # Synthesizer prompt + model-id contract tests
│   ├── test_tile_cache.py                # Tile cache tests (L1/L2, thread safety)
│   ├── test_typed_meta.py                # Typed metadata bridge tests
│   ├── test_admin_utils.py               # Admin utility tests
│   ├── test_amadeus_client.py            # Amadeus client tests
│   ├── test_cache_core.py                # Cache core tests
│   ├── test_constraint_engine.py         # Constraint engine tests
│   ├── test_itinerary_adapter.py         # Itinerary adapter tests
│   ├── test_llm_factory.py              # LLM factory tests
│   ├── test_section_builder.py          # Section builder tests
│   ├── test_state_serde.py              # State serde tests
│   ├── test_unsplash_service.py          # Unsplash service fallback + retry tests
│   ├── test_constraint_guard.py         # Constraint guard tests
│   ├── test_debug_utils.py              # Debug utilities tests
│   ├── test_hashing_behavior.py         # Hashing behavior tests
│   ├── test_local_expert.py             # Local expert node tests
│   ├── test_logistics_helpers.py        # Logistics helper tests
│   ├── test_streaming_helpers.py        # Streaming helper tests
│   ├── test_synthesizer_grounding.py    # Synthesizer grounding tests
│   ├── test_test_mode.py                # Test mode tests
│   ├── test_tile_service.py             # Tile service tests
│   ├── test_trip_architect.py           # Trip architect tests
│   ├── test_vertical_specialist_node.py # Vertical specialist node tests
│   └── db/
│       ├── test_expand_itinerary_api.py
│       └── test_plan_document_api.py
│
├── alembic.ini                 # Alembic migration config
├── Dockerfile                  # Backend Docker image
├── pyproject.toml              # Python project config
├── requirements.txt            # Python dependencies
├── start.py                    # Server startup script
└── test_unsplash.py            # Unsplash integration test
```

---

## Frontend (`/frontend`)

Next.js 16 / React 19 application with Zustand state management.

```
frontend/
├── app/                        # Next.js App Router
│   ├── globals.css             # Global styles
│   ├── icon.png                # App icon
│   ├── layout.tsx              # Root layout
│   ├── page.tsx                # Home page
│   ├── error.tsx               # Root error boundary
│   ├── contact/page.tsx
│   ├── cookies/page.tsx
│   ├── credits/page.tsx
│   ├── privacy/page.tsx
│   ├── sitemap/page.tsx
│   ├── summary/error.tsx
│   ├── summary/page.tsx
│   └── terms/page.tsx
│
├── components/
│   ├── animations/
│   │   ├── StartupSequence.tsx
│   │   └── Typewriter.tsx
│   │
│   ├── chat/                   # Chat interface components
│   │   ├── ChatInputBar.tsx          # Desktop input capsule (extracted from ChatPanel)
│   │   ├── ChatInputHandler.tsx      # Thin wrapper around ChatInputBar for ChatPanel integration
│   │   ├── ChatMessageList.tsx       # Scrollable message list renderer (extracted from ChatPanel)
│   │   ├── ChatMessageRenderer.tsx  # Individual message rendering (extracted from ChatPanel)
│   │   ├── ChatPanel.tsx
│   │   ├── ChatSkeleton.tsx
│   │   ├── ChatSuggestionBar.tsx     # Thin wrapper around ChatSuggestionChips for ChatPanel integration
│   │   ├── ChatSuggestionChips.tsx   # Suggestion chips rendering (extracted from ChatPanel)
│   │   ├── HoldToDeleteButton.tsx
│   │   ├── MobileChatInput.tsx
│   │   ├── MobileSetupCollapsedHeader.tsx
│   │   ├── SmartLoader.tsx
│   │   ├── SystemAckLine.tsx
│   │   ├── SystemReceipt.tsx
│   │   ├── TripStatusBar.tsx
│   │   └── suggestion-actions.ts     # Shared trigger_action handler (avoids circular import)
│   │
│   ├── layout/                 # Layout components
│   │   ├── FloatingBuildButton.tsx
│   │   ├── LandingHelpers.ts         # Shared types and utilities for NomadicLanding (topic detection, field diffing)
│   │   ├── LandingSheets.tsx         # Sheet rendering extracted from NomadicLanding
│   │   ├── MobileModeHeader.tsx
│   │   ├── MobileSwipeLayout.tsx
│   │   ├── NomadicLanding.tsx
│   │   ├── SplitLayoutView.tsx
│   │   └── hooks/              # Layout-specific hooks
│   │       ├── useBranchManager.ts
│   │       ├── useBranchState.ts
│   │       ├── useLocalBookingSettings.ts
│   │       ├── useSessionHydration.ts
│   │       ├── useTileSelection.ts
│   │       └── useTripInputsEditor.ts
│   │
│   ├── map/                    # Map components
│   │   ├── InteractiveMap.tsx
│   │   ├── MapboxErrorSuppressor.tsx
│   │   ├── MapErrorBoundary.tsx
│   │   └── mapbox-error-handler.ts   # Global Mapbox error suppression (shared patterns)
│   │
│   ├── nomadic/                # Marketing/landing components
│   │   ├── consent-manager.tsx
│   │   └── legal-page.tsx
│   │
│   ├── plan/                   # Plan view components
│   │   ├── BookingSection.tsx
│   │   ├── CoreChip.tsx
│   │   ├── DestinationMapPlaceholder.tsx
│   │   ├── ItineraryProgressIndicator.tsx  # Path A: Auto-generation progress display
│   │   ├── NextStepBar.tsx
│   │   ├── OriginPromptCard.tsx
│   │   ├── PlanDensityViews.tsx            # Ghost, bridge, and mirror-loader density views
│   │   ├── PlanFullDensityView.tsx         # Full-density view (map + specialists + timeline)
│   │   ├── PlanHeader.tsx
│   │   ├── PlanSpecialistsSection.tsx      # Specialists section for full-density view
│   │   ├── PlanTimelineSection.tsx         # Timeline section with DnD wiring for full-density view
│   │   ├── planStateHelpers.ts
│   │   ├── StrategyConstraintBar.tsx       # Trip DNA constraint pill bar (validated/violated rules)
│   │   ├── StrategyStageRenderer.tsx  # Main orchestrator: 60/40 map layout when destination set
│   │   ├── TimelineThread.tsx
│   │   ├── TripHealthBar.tsx
│   │   ├── TripSummaryPills.tsx
│   │   ├── UnifiedChipRow.tsx
│   │   ├── useBookingDrawerState.ts        # Booking drawer open/close + fill-day API hook
│   │   ├── useStrategyStageOrchestration.ts # Heavy computation/state/effects for StrategyStageRenderer
│   │   │
│   │   ├── booking/
│   │   │   ├── BookingDrawer.tsx
│   │   │   ├── CategorySection.tsx
│   │   │   └── CheckoutSidebar.tsx
│   │   │
│   │   ├── modals/
│   │   │   └── AlternativesModal.tsx
│   │   │
│   │   ├── sheets/             # Bottom sheets
│   │   │   ├── ActivitiesSheet.tsx
│   │   │   ├── BaseSheet.tsx
│   │   │   ├── BudgetSheet.tsx
│   │   │   ├── DatesSheet.tsx
│   │   │   ├── DestinationSheet.tsx
│   │   │   ├── FlightsSheet.tsx
│   │   │   ├── GatingBlocker.tsx     # Shared gate-check blocker (gates array, used by Flights/Stays/Activities sheets)
│   │   │   ├── OriginSheet.tsx
│   │   │   ├── StaysSheet.tsx
│   │   │   ├── TravelersSheet.tsx
│   │   │   └── TripSettingsSheet.tsx
│   │   │
│   │   ├── stages/             # Stage-specific views
│   │   │   ├── S2AgentCard.tsx           # Single agent card (collapsed strategy section card)
│   │   │   ├── S2AgentCardExpanded.tsx   # Expanded agent card with travel intelligence
│   │   │   ├── S2LocalIntelSection.tsx   # Local intel section within expanded agent card
│   │   │   ├── S2StrategyStack.tsx       # Strategy card stack layout for S2 view
│   │   │   ├── S2StrategyView.tsx
│   │   │   ├── S2TopicConfig.tsx         # Topic configuration panel for S2 specialists
│   │   │   ├── StrategyHero.tsx
│   │   │   ├── StrategyHeroAccordion.tsx        # Accordion expansion for StrategyHero sections
│   │   │   ├── StrategyHeroCompactSheet.tsx     # Compact sheet variant for StrategyHero
│   │   │   ├── StrategyHeroHeroSheet.tsx        # Hero sheet variant for StrategyHero
│   │   │   ├── StrategyHeroTISectionsA.tsx      # Travel intelligence sections (part A)
│   │   │   ├── StrategyHeroTISectionsB.tsx      # Travel intelligence sections (part B)
│   │   │   ├── StrategyHeroTravelIntelligence.tsx # Travel intelligence display component
│   │   │   └── StrategyHeroUtils.tsx            # Shared utilities for StrategyHero components
│   │   │
│   │   ├── tiles/
│   │   │   ├── BookableCard.tsx
│   │   │   └── SuggestionCard.tsx
│   │   │
│   │   └── timeline/
│   │       ├── DragPreviewCard.tsx     # Ghost card shown in DragOverlay during block drag
│   │       ├── DraggableBlock.tsx      # useDraggable wrapper; locked blocks show Lock icon
│   │       ├── DroppableDay.tsx        # useDroppable wrapper for activity days (two-div: hit area + highlight)
│   │       ├── FreeDayDropSlot.tsx     # Drop zone inside FreeDayCard (via freeDayDropSlot render prop)
│   │       ├── InlineDatePrompt.tsx
│   │       ├── ItineraryDndWrapper.tsx # DndContext root; orchestrates validate/apply-arrangement flow
│   │       ├── TimelineSkeleton.tsx
│   │       └── blocks/
│   │           ├── ActivityMiniCard.tsx
│   │           ├── FreeDayCard.tsx
│   │           ├── GhostSlot.tsx
│   │           ├── LogisticsBlock.tsx
│   │           ├── PreferenceAttributionBadge.tsx  # "You preferred this" badge
│   │           ├── SafetyBlock.tsx
│   │           └── types.ts
│   │
│   ├── providers/
│   │   └── Providers.tsx       # App providers wrapper
│   │
│   ├── tiles/                  # Tile display components
│   │   ├── MiniCard.tsx
│   │   ├── TaxesFeesTooltip.tsx
│   │   ├── TileCard.tsx
│   │   └── TileDetailsModal.tsx
│   │
│   └── ui/                     # Base UI components
│       ├── ModalErrorBoundary.tsx  # Error boundary for modals/sheets (crash isolation)
│       ├── bottom-sheet.tsx
│       ├── button.tsx
│       ├── calendar.tsx
│       ├── card.tsx
│       ├── popover.tsx
│       ├── sheet.tsx
│       ├── skeleton.tsx
│       ├── switch.tsx
│       ├── stepper.tsx         # +/- stepper (Glass Fill, sm/default sizes)
│       ├── toast.tsx
│       └── tooltip.tsx
│
├── hooks/                      # Custom React hooks
│   ├── useActionLoader.ts
│   ├── useChatSse.ts             # SSE/streaming connection manager for ChatPanel (extracted from ChatPanel)
│   ├── useDelayedLoader.ts
│   ├── useIsDesktop.ts
│   ├── usePreferenceAutoRegen.ts # Auto-triggers itinerary regen on heart changes
│   ├── useScrollCollapse.ts
│   ├── useSheetManager.ts
│   ├── useSpecialistDeepLink.ts
│   ├── useTripInputsWithFallback.ts
│   └── useViewNavigation.ts
│
├── lib/                        # Utility functions
│   ├── animation-config.ts     # Progressive disclosure timing constants
│   ├── api.ts                  # API client
│   ├── chipStyles.ts           # Chip styling utilities
│   ├── contentPolicyGuard.ts   # Content policy validation
│   ├── date-utils.ts           # Date formatting/parsing utilities
│   ├── dayIntensity.ts         # Day intensity scoring (relaxed/balanced/packed) from DayBlock hours
│   ├── debug.ts                # Debug/logging utilities
│   ├── design-system.ts        # Design system tokens
│   ├── destination-coords.ts   # Demo POI data for curated destinations (Bali dive/hike)
│   ├── fillDayGuards.ts        # Fill-day client cooldown guard helpers
│   ├── format-utils.ts         # Formatting utilities
│   ├── ghost-timeline-adapter.ts
│   ├── loaderConfig.ts         # Loader configuration
│   ├── loaderCopyConfig.ts     # Loader copy text
│   ├── placeholders.ts         # Placeholder data
│   ├── specialist-utils.ts     # Specialist topic utilities
│   ├── specialistLinkParser.ts
│   ├── specialists.ts          # Specialist registry SSoT (colors, icons, keywords, IDs)
│   ├── statusCopyMap.ts        # Status text mappings
│   ├── streamParser.ts         # Stream parsing utilities
│   ├── summary.ts              # Summary utilities
│   ├── tileSelectors.ts        # Tile selection logic
│   ├── tileUtils.ts            # Tile utilities
│   ├── popular-places.ts       # Static list of popular destination suggestions for landing input
│   └── utils.ts                # General utilities (cn, etc.)
│
├── public/
│   ├── assets/                 # Static assets
│   └── nomadic_logo.png        # Nomadic logo
│
├── scripts/
│   └── generate-contours.ts    # Map contour generation
│
├── state/                      # Zustand stores
│   ├── chatStore.ts            # Chat state
│   ├── documentStore.ts        # Document/plan state
│   ├── mobileNavStore.ts       # Mobile navigation state
│   └── uiStore.ts              # UI state
│
├── types/                      # TypeScript types
│   ├── chat.ts
│   ├── document.ts
│   ├── generated.ts            # Auto-generated types
│   ├── hooks.ts
│   ├── loader.ts
│   ├── plan-envelope.ts
│   ├── sheets.ts
│   ├── summary.ts
│   └── tile.ts
│
├── __tests__/                  # Frontend tests
│   ├── anti-fragmentation.test.tsx
│   ├── chat-suggestion-actions.test.ts
│   ├── constraint-states.test.tsx
│   ├── documentStore.test.ts
│   ├── fill-day-guards.test.ts
│   ├── ghost-timeline-adapter.test.ts
│   ├── map-error-boundary.test.ts
│   ├── plan-copy.test.tsx
│   └── streaming.test.ts
│
├── .prettierignore             # Prettier ignore patterns
├── .prettierrc.cjs             # Prettier configuration
├── Dockerfile                  # Frontend Docker image
├── eslint.config.mjs
├── next.config.mjs
├── next-env.d.ts
├── package.json
├── package-lock.json
├── postcss.config.mjs
├── tailwind.config.mts
├── tsconfig.json
├── vitest.config.ts
└── vitest.setup.ts
```

---

## Documentation (`/docs`)

```
docs/
├── data-contracts.md           # API routes, schemas, state store contracts
├── design-system.md            # Frontend styling SSoT
├── key_files/                  # Backend reference snapshots (prompts, nodes, services)
├── plan_graph_analysis.md      # Backend architecture SSoT
├── repo_structure.md           # This file
└── ux_unified_architecture.md  # UX/view states SSoT
```

---

## Configuration Files

### Root Level
| File | Purpose |
|------|---------|
| `CLAUDE.md` | AI assistant project instructions |
| `docker-compose.yml` | Docker services configuration |
| `render.yaml` | Render.com deployment config |
| `.pre-commit-config.yaml` | Pre-commit hooks |

### GitHub (`.github/`)
| File | Purpose |
|------|---------|
| `workflows/check-types-sync.yml` | Type checking CI workflow |
| `instructions/instructions.instructions.md` | GitHub Copilot instructions |

### VS Code (`.vscode/`)
| File | Purpose |
|------|---------|
| `extensions.json` | Recommended extensions |
| `settings.json` | Editor settings |
| `tasks.json` | Task definitions |

---

## Key Architectural Notes

1. **TripPlan is SSoT** - All trip state flows through `TripPlan` schema
2. **7-Node LangGraph** - Backend planner uses exactly 7 nodes (see `plan_graph_analysis.md`)
3. **Design Tokens** - Frontend uses tokens from `design-system.md`
4. **StrategyStageRenderer** - Single renderer adapts to data density (see `ux_unified_architecture.md`)
5. **DnD via `blockWrapper` render prop** - `TimelineThread` is DnD-agnostic; `ItineraryDndWrapper` + `DraggableBlock` + `DroppableDay` inject drag via `blockWrapper` prop. New deps: `@dnd-kit/core`, `@dnd-kit/utilities`.
