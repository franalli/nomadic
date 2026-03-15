# Repository Structure

This document provides a comprehensive overview of the Nomadic codebase structure.

## Root Directory

```
nomadic/
├── .claude/                    # Claude Code configuration
│   ├── agents/                 # Canonical agent specs
│   │   ├── backend-specialist.md
│   │   ├── code-reviewer.md
│   │   └── frontend-specialist.md
│   ├── commands/               # Claude command frontends
│   │   ├── audit-code.md
│   │   ├── clear-cache.md
│   │   ├── clear-sprint.md
│   │   ├── enforce-style.md
│   │   ├── reassemble-docs.md
│   │   ├── run-curl.md
│   │   ├── update-docs.md
│   │   └── verify-build.md
│   ├── plans/                  # Persisted planning artifacts and run notes
│   │   ├── kind-pondering-seahorse.md
│   │   ├── parsed-discovering-liskov.md
│   │   ├── unified-dreaming-oasis.md
│   ├── settings.json           # Claude Code settings
│   └── settings.local.json     # Local Claude Code settings
├── .codex/                     # Codex wrappers + skills
│   ├── agents/                 # Wrapper specs pointing to canonical `.claude/agents/*`
│   │   ├── backend-specialist.md
│   │   ├── code-reviewer.md
│   │   └── frontend-specialist.md
│   └── skills/                 # Codex skills (SKILL.md per skill directory)
│       ├── audit-code/SKILL.md
│       ├── clear-cache/SKILL.md
│       ├── clear-sprint/SKILL.md
│       ├── enforce-style/SKILL.md
│       ├── reassemble-docs/SKILL.md
│       ├── run-curl/SKILL.md
│       ├── update-docs/SKILL.md
│       └── verify-build/SKILL.md
├── .github/                    # GitHub workflows and instructions
├── .vscode/                    # VS Code settings
├── backend/                    # Python FastAPI backend
├── docs/                       # Architecture documentation
├── frontend/                   # Next.js frontend
├── scripts/                    # Root-level utility scripts
│   ├── cleanup-claude-history.sh   # Unix history cleanup
│   ├── copy-key-files.sh           # Copy key backend files to docs/
│   └── restart-dev.sh              # Restart local backend/frontend/db dev stack from VS Code
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

Python FastAPI application with a coordinator-driven trip planner.

```
backend/
├── app/
│   ├── __init__.py
│   ├── analytics_routes.py     # Analytics API routes (extracted from main.py)
│   ├── auth.py                 # Google OAuth exchange + session-to-user linking helpers
│   ├── config.py               # Application configuration
│   ├── crud_document.py        # Document CRUD operations
│   ├── crud_trip.py            # Trip CRUD operations
│   ├── db.py                   # Database connection
│   ├── db_models.py            # SQLAlchemy models
│   ├── debug_utils.py          # Debugging utilities
│   ├── graph_plan_utils.py     # Graph plan route utilities
│   ├── lifespan.py             # Application lifespan hooks (startup + shutdown)
│   ├── main.py                 # FastAPI application entry
│   ├── placeholders.py         # Placeholder data
│   ├── request_dedup.py        # DB-backed idempotency + expand-itinerary lease helpers
│   ├── streaming.py            # SSE + NDJSON streaming generators (extracted from main.py)
│   ├── validation_cache.py     # Validation cache infrastructure (6 TTL caches, extracted from validation.py)
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
│   ├── planner/                # Coordinator-driven planner package
│   │   ├── __init__.py
│   │   ├── chip_generator.py   # Suggestion chip generator extracted from legacy middleware
│   │   ├── conversationalist.py # Single-LLM response generator for coordinator path
│   │   ├── coordinator.py      # Deterministic turn planner + step execution + envelope builder
│   │   ├── hashing.py          # Hash utilities
│   │   ├── llm_factory.py      # Provider-agnostic LLM factory (OpenAI/Gemini auto-routing)
│   │   ├── specialist_registry.py # Specialist config SSoT (keywords, constraints, flags)
│   │   ├── test_mode.py        # Test mode utilities
│   │   │
│   │   ├── schemas/            # Coordinator protocol schemas
│   │   │   ├── __init__.py
│   │   │   └── coordinator_schemas.py  # ChangeType, ClassifierOutput, TripBrief, SpecialistPlan, ReplanRequest, ExecutionPlan
│   │   │
│   │   ├── nodes/              # Domain logic modules called by coordinator
│   │   │   ├── __init__.py
│   │   │   ├── constraint_guard.py         # Constraint validation
│   │   │   ├── input_gate_config.py        # Input gate threshold constants (dates, travelers, budget)
│   │   │   ├── router_extraction.py        # LLM extraction + change classification
│   │   │   ├── expert_constraints.py        # Local expert schema + grounded constraints
│   │   │   ├── local_expert.py             # Local knowledge section generation
│   │   │   ├── logistics_node.py           # Flights/hotels/activity fetching
│   │   │   ├── specialist_schemas.py       # Specialist Pydantic schemas
│   │   │   └── vertical_specialist.py      # Tier 1 specialist planning
│   │   │
│   │   ├── services/
│   │   │   ├── __init__.py
│   │   │   ├── admin_utils.py       # Admin utility functions
│   │   │   ├── feasibility_service.py # LLM-backed geographic feasibility checks
│   │   │   ├── iata_resolver.py     # IATA airport code resolver (LLM-backed)
│   │   │   ├── itinerary_adapter.py # Thin bridge: GraphState → ItineraryBuilder
│   │   │   ├── section_builder.py   # Strategy section builders/fallbacks
│   │   │   └── state_serde.py       # State serialization/deserialization
│   │   │
│   │   └── state/
│   │       ├── __init__.py
│   │       ├── agent_state.py       # NomadicAgentState schema + reducers
│   │       ├── graph_state.py       # Shared planner state schemas
│   │       └── typed_meta.py        # Typed metadata bridge (TurnMeta, get_trip_settings)
│   │
│   ├── prompts/                # LLM prompt templates
│   │   ├── synthesizer.txt
│   │   └── specialists/
│   │       ├── climbing.txt
│   │       ├── cycling.txt
│   │       ├── diving.txt
│   │       ├── generic_activity.txt  # Fallback prompt for Tier 2 categories without dedicated prompts
│   │       ├── hiking.txt
│   │       ├── local_expert.txt
│   │       ├── sailing.txt
│   │       ├── skiing.txt
│   │       ├── surfing.txt
│   │       └── wildlife_safari.txt
│   │
│   ├── services/
│   │   ├── __init__.py
│   │   ├── activity_browser.py      # On-demand activity search for Browse Activities sheet (Viator first, GYG supplement, Google Places backfill/fallback)
│   │   ├── activity_category_conflicts.py  # Shared category conflict rules for partner activity matching
│   │   ├── aviasales_provider.py           # Aviasales/Travelpayouts real-time flight search provider with affiliate deeplinks
│   │   ├── cache_core.py            # Shared MemoryCache primitive (TTLCache + RLock + stats) + l2_upsert()
│   │   ├── circuit_breaker.py       # Shared async circuit breaker used by partner/provider integrations
│   │   ├── experience_generator.py  # Tier 2 experience tile generation via settings.experience_model (L1+L2 cache)
│   │   ├── gyg_provider.py          # GetYourGuide affiliate browse/match provider with cache + circuit breaker
│   │   ├── itinerary_builder.py     # Itinerary construction service
│   │   ├── partner_enrichment.py    # Unified Viator + GYG pre-build tile enrichment
│   │   ├── regen_strategy.py        # Selective regeneration strategy computation
│   │   ├── router_cache.py          # Thread-safe L1 cache for router extraction (context-aware)
│   │   ├── sharing.py               # Shared-trip snapshot building + metadata helpers
│   │   ├── specialist_cache.py      # Thread-safe L1+L2 cache for specialist LLM outputs
│   │   ├── spend_guard.py           # Spend/budget guard logic
│   │   ├── task_tracker.py          # Shared fire-and-forget background task tracker
│   │   ├── tile_cache.py            # Thread-safe L1+L2 cache for tile provider data (24h TTL)
│   │   ├── unsplash.py              # Unsplash image service (cooldown pruning on prefetch)
│   │   ├── unsplash_queries.py      # Unsplash query helpers (includes Tier 2 activity queries)
│   │   └── viator_provider.py       # Viator affiliate browse/match provider with cache + circuit breaker
│   │
│   ├── utils/                 # Shared utility modules
│   │   ├── __init__.py
│   │   └── tile_utils.py      # Tile flattening (category-grouped → ID-based map)
│   │
│   ├── tile_service/           # Tile data providers
│   │   ├── __init__.py
│   │   ├── curated_provider.py       # Curated content provider
│   │   ├── google_places_provider.py # Google Places API integration (sync + async; Hotels + Activities)
│   │   ├── mock_provider.py          # Mock data for testing
│   │   ├── models.py                 # Tile models
│   │   ├── provider_base.py          # Base provider class
│   │   ├── service.py                # Tile service orchestrator (3-tier cascade: Curated → Google Places → Mock)
│   │   └── title_utils.py            # Title normalization helpers for provider matching/deduping
│   │
│   └── tools/                  # Planner tool adapters
│       ├── __init__.py
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
│       ├── 9f6a2e4b7c1d_drop_suggestion_clicks_table.py
│       ├── 3c42a4c8a9f1_add_shared_trips.py
│       ├── 7a1b2c3d4e5f_add_users_and_session_user_fk.py
│       ├── add_variant_to_unsplash_cache.py
│       ├── ae0f06f2c384_remove_legacy_tables.py
│       ├── c1f8e8bf9d21_chat_messages_table.py
│       ├── c4b7e1a29d3f_add_runtime_state_table.py  # Shared runtime leases + spend counters
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
│   ├── analyze_flow_logs.py               # Flow log analysis and regression checks
│   ├── test_activity_browser.py          # Browse activities backend contract tests
│   ├── test_activity_category_conflicts.py  # Shared partner-category conflict rule tests
│   ├── test_activity_image_placeholder_mapping.py  # Activity image placeholder mapping tests
│   ├── test_analyze_flow_logs.py         # Flow-log analyzer regression tests
│   ├── test_aviasales_provider.py           # Aviasales provider flight search and tile conversion tests
│   ├── test_agent_multiturn.py           # Agent multi-turn conversation tests
│   ├── test_chip_generator.py            # Chip output and deterministic variant generation tests
│   ├── test_conflict_resolution.py       # Conflict resolution & constraint alias tests
│   ├── test_contracts.py                 # Backend/frontend schema parity contract tests
│   ├── test_conversationalist.py         # Conversationalist streaming + response tests
│   ├── test_coordinator.py              # Coordinator turn flow + step execution tests
│   ├── test_cross_domain_constraints.py  # Cross-domain constraint tests
│   ├── test_expert_constraints.py        # Expert-constraint schema/model alignment
│   ├── test_demo_dataset.py              # Demo data tests
│   ├── test_endpoint_contract.py         # Endpoint response contract tests
│   ├── test_experience_generator.py      # Experience generator tests
│   ├── test_feasibility_inflight.py      # Inflight feasibility service behavior tests
│   ├── test_fill_day_coordinates.py      # Fill-day coordinate + constraint mapping tests
│   ├── test_google_places_circuit_breaker.py  # Google Places circuit breaker tests
│   ├── test_google_places_enrichment.py  # Google Places enrichment/cache tests
│   ├── test_google_places_hotel_provider.py  # Google Places hotel provider tests
│   ├── test_google_places_photo_proxy.py # Google Places photo proxy tests
│   ├── test_gyg_provider.py              # GetYourGuide provider tile conversion, matching, and browse cache tests
│   ├── test_hash_ban.py                  # Hash ban tests
│   ├── test_iata_resolver.py             # IATA resolver tests
│   ├── test_import_contract.py           # Import contract tests
│   ├── test_itinerary_builder.py         # Itinerary builder tests
│   ├── test_llm_feasibility.py           # LLM geographic feasibility tests
│   ├── test_logistics_tier2.py           # Logistics Tier-2 generation, backfill pipeline, affinity sorting tests
│   ├── test_main_middleware.py           # Main middleware tests (chunked body-size guard)
│   ├── test_main_trip_input_merge.py     # Document PATCH no-op dedupe + merge behavior tests
│   ├── test_multi_specialist_integration.py  # Multi-specialist tests
│   ├── test_partner_enrichment.py        # Unified Viator/GYG winner-selection and tile-merge tests
│   ├── test_plan_schema.py               # Plan schema tests
│   ├── test_poi_category_canonicalization.py  # POI category canonicalization tests
│   ├── test_regen_strategy.py            # Selective regen field hash + strategy tests
│   ├── test_request_dedup.py             # Request deduplication tests
│   ├── test_rate_limit_keying.py         # Route-aware/IP-vs-session rate-limit keying regression tests
│   ├── test_router_cache.py              # Router cache tests (context-dependency detection)
│   ├── test_session_middleware.py        # Session middleware behavior tests
│   ├── test_specialist_cache.py          # Specialist LLM cache tests (thread safety, L1/L2)
│   ├── test_fill_day_constraints.py      # Fill-day constraint validation (Tier 1 placement gates)
│   ├── test_specialist_enrichment_endpoint.py  # Specialist enrichment endpoint tests
│   ├── test_specialist_structured.py     # Specialist structured output tests
│   ├── test_spend_guard.py              # Spend guard tests
│   ├── test_stage11_day_preferences.py   # Day-preference placement regression tests
│   ├── test_graph_integration.py         # ItineraryBuilder full-pipeline integration tests
│   ├── test_tile_cache.py                # Tile cache tests (L1/L2, thread safety)
│   ├── test_typed_meta.py                # Typed metadata bridge tests
│   ├── test_admin_utils.py               # Admin utility tests
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
│   ├── test_test_mode.py                # Test mode tests
│   ├── test_tile_service.py             # Tile service tests
│   ├── test_vertical_specialist_node.py # Vertical specialist node tests
│   ├── test_logistics_tile_scaling.py # Logistics tile scaling tests
│   ├── test_post_arrangement_constraints.py  # Post-arrangement constraint recomputation tests
│   ├── test_constraint_guard_merge.py # Constraint guard merge/dedup regression tests
│   ├── test_graph_plan_utils.py       # Graph plan helper contract tests
│   ├── test_itinerary_builder_bugs.py # ItineraryBuilder edge case regression tests (D3 filter, D4 cap)
│   ├── test_logistics_scaling.py      # Logistics provider scaling + cascade tests
│   ├── test_router_extraction.py      # Router extraction schema/logic tests
│   ├── test_sse_state.py              # SSE connection state accounting tests
│   ├── test_task_tracker.py           # Background task tracker lifecycle tests
│   ├── test_unsplash_queries.py       # Unsplash query helper tests
│   ├── test_validation_cache.py       # Validation cache behavior tests
│   ├── test_viator_provider.py        # Viator provider tile conversion, matching, and circuit-breaker tests
│   └── db/
│       ├── test_expand_itinerary_api.py
│       ├── test_plan_document_api.py
│       └── test_share_and_auth_api.py    # Shared-trip, auth, and resume API tests
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
│   ├── auth/callback/error.tsx # Route-level error UI for OAuth callback failures
│   ├── auth/callback/page.tsx  # OAuth callback completion page (exchanges code, then redirects home)
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
│   ├── trip/[slug]/error.tsx   # Route-level error UI for shared-trip load failures
│   ├── trip/[slug]/page.tsx    # Public shared-trip route with metadata generation
│   └── terms/page.tsx
│
├── components/
│   ├── chat/                   # Chat interface components
│   │   ├── ChatBootstrapHero.tsx    # Desktop bootstrap hero/banner for ChatPanel
│   │   ├── ChatInputBar.tsx          # Desktop input capsule (extracted from ChatPanel)
│   │   ├── ChatInputHandler.tsx      # Thin wrapper around ChatInputBar for ChatPanel integration
│   │   ├── ChatMessageList.tsx       # Scrollable message list renderer (extracted from ChatPanel)
│   │   ├── ChatMessageRenderer.tsx  # Individual message rendering (extracted from ChatPanel)
│   │   ├── ChatModuleSheets.tsx      # Module sheets (flights/stays/activities) extracted from ChatPanel
│   │   ├── ChatPanel.tsx
│   │   ├── chatMessageMarkdown.tsx        # Markdown renderer extracted from ChatMessageRenderer
│   │   ├── ChatPanel.types.ts              # ChatPanel shared types
│   │   ├── ChatPanelContent.tsx            # ChatPanel content rendering (extracted from ChatPanel)
│   │   ├── ChatStatusHeader.tsx        # Desktop status hero/mini bar above chat
│   │   ├── ChatSkeleton.tsx
│   │   ├── ChatSuggestionBar.tsx     # Thin wrapper around ChatSuggestionChips for ChatPanel integration
│   │   ├── ChatSuggestionChips.tsx   # Suggestion chips rendering (extracted from ChatPanel)
│   │   ├── MobileChatInput.tsx
│   │   ├── SmartLoader.tsx
│   │   ├── chatMessageProcessing.ts  # Pure chat-message sanitizing/splitting utilities
│   │   ├── suggestion-actions.ts     # Shared trigger_action handler (avoids circular import)
│   │   └── useChatPanelController.ts       # ChatPanel controller hook (state+effects extracted from ChatPanel)
│   │
│   ├── layout/                 # Layout components
│   │   ├── FloatingBuildButton.tsx
│   │   ├── LandingHeaderContent.tsx  # Desktop header chrome extracted from NomadicLanding
│   │   ├── LandingHeaderUserMenu.tsx       # User menu section extracted from LandingHeaderContent
│   │   ├── LandingHelpers.ts         # Shared types and utilities for NomadicLanding (topic detection, field diffing)
│   │   ├── LandingPreferenceSheets.tsx     # Preference-sheet group extracted from LandingSheets
│   │   ├── LandingPrimarySheets.tsx        # Primary trip-input sheet group extracted from LandingSheets
│   │   ├── LandingSheets.tsx         # Sheet rendering extracted from NomadicLanding
│   │   ├── MobileHeaderMenu.tsx      # Popover body for MobileModeHeader overflow actions
│   │   ├── MobileModeHeader.tsx
│   │   ├── MobileModeHeaderSections.tsx    # Mobile header sections extracted from MobileModeHeader
│   │   ├── MobileSwipeLayout.tsx
│   │   ├── NomadicLanding.tsx
│   │   ├── NomadicLandingContent.tsx       # Landing content extracted from NomadicLanding
│   │   ├── SplitLayoutSections.tsx         # Split layout sections extracted from SplitLayoutView
│   │   ├── SplitLayoutView.tsx
│   │   ├── headerMenuParts.tsx             # Shared header menu parts
│   │   └── hooks/              # Layout-specific hooks
│   │       ├── useBranchManager.ts
│   │       ├── useBranchState.ts
│   │       ├── useItineraryGeneration.ts  # Itinerary generation orchestration (extracted from NomadicLanding)
│   │       ├── useItineraryGenerationController.ts  # Itinerary generation controller (extracted from useItineraryGeneration)
│   │       ├── useLandingControllerStores.ts        # Landing controller store selectors/aggregator
│   │       ├── useLandingDerived.ts       # Derived state computations for NomadicLanding (extracted)
│   │       ├── useLandingEffects.ts       # Side effects for NomadicLanding (extracted)
│   │       ├── useLandingHandlers.ts
│   │       ├── useLandingPlanState.ts             # Landing plan-state orchestration extracted from controller
│   │       ├── useLandingRenderSurfaces.tsx       # Planner/header/mobile surface assembly for landing route
│   │       ├── useLandingStoreSnapshot.ts         # Landing document snapshot helpers
│   │       ├── useLocalBookingSettings.ts
│   │       ├── useNomadicLandingController.tsx      # NomadicLanding controller hook (state+effects)
│   │       ├── useSessionHydration.ts
│   │       ├── useTileSelection.ts
│   │       └── useTripInputsEditor.ts
│   │
│   ├── map/                    # Map components
│   │   ├── InteractiveMap.tsx
│   │   ├── InteractiveMapHelpers.tsx       # Map helper utilities extracted from InteractiveMap
│   │   ├── MapMarkerItem.tsx
│   │   ├── MapboxErrorSuppressor.tsx
│   │   ├── map-marker-config.tsx           # Map marker configuration extracted from MapMarkerItem
│   │   ├── MapErrorBoundary.tsx
│   │   └── mapbox-error-handler.ts   # Global Mapbox error suppression (shared patterns)
│   │
│   ├── nomadic/                # Marketing/landing components
│   │   ├── ConsentManagerSections.tsx      # Consent manager sections extracted from consent-manager
│   │   ├── consent-manager-storage.ts      # Consent manager storage utilities
│   │   ├── consent-manager.tsx
│   │   └── legal-page.tsx
│   │
│   ├── shared/                 # Public shared-trip surfaces
│   │   ├── ReadOnlyTimeline.tsx    # Non-editable itinerary renderer for shared trips
│   │   ├── SharedTripSections.tsx          # Shared trip sections extracted from SharedTripView
│   │   └── SharedTripView.tsx      # Shared-trip page shell, map, fork CTA, and metadata surface
│   │
│   ├── plan/                   # Plan view components
│   │   ├── BookingPlanningView.tsx           # Booking controls rendered in full-density planning context
│   │   ├── BookingSection.helpers.ts         # BookingSection helper utilities
│   │   ├── BookingSection.tsx
│   │   ├── BookingSectionBookingView.tsx     # Booking view extracted from BookingSection
│   │   ├── BookingSummary.tsx                # Grouped booking-links summary for bookable stays/flights/activities
│   │   ├── BrowseActivitiesSheet.tsx  # Bottom sheet for browsing categorized activity tiles (Tier 1 free days)
│   │   ├── PdfExportButton.tsx               # Export generated itinerary to PDF
│   │   ├── ChipGroup.helpers.ts            # ChipGroup helper utilities
│   │   ├── ChipGroup.tsx
│   │   ├── ChipScrollContainer.tsx        # Shared horizontal chip wrapper (carousel-safe)
│   │   ├── FullDensityTimeline.tsx       # Activity timeline container used by full-density view
│   │   ├── ItineraryProgressIndicator.tsx  # Path A: Auto-generation progress display
│   │   ├── ModuleChip.tsx                  # Individual module chip component
│   │   ├── NextStepBar.tsx
│   │   ├── OriginPromptCard.tsx
│   │   ├── PlanDensityViews.tsx            # Mirror-loader density view (`PlanMirrorLoader`)
│   │   ├── PlanFullDensityDesktopMap.tsx   # Desktop map section for PlanFullDensityView
│   │   ├── PlanFullDensityMobileSummary.tsx # Mobile summary for PlanFullDensityView
│   │   ├── PlanFullDensityTilesSection.tsx # Tiles section for PlanFullDensityView
│   │   ├── PlanFullDensityTravelAdvice.tsx # Travel advice section for PlanFullDensityView
│   │   ├── PlanFullDensityView.tsx         # Full-density view (map + specialists + timeline)
│   │   ├── PlanFullDensityView.types.ts    # PlanFullDensityView shared types
│   │   ├── PlanHeader.tsx
│   │   ├── PlanTimelineSection.tsx         # Timeline section with DnD wiring for full-density view
│   │   ├── pdf/                            # PDF export rendering subtree
│   │   │   ├── TripPdfDocument.tsx          # @react-pdf renderer for itinerary output
│   │   │   ├── TripPdfSections.tsx          # PDF sections extracted from TripPdfDocument
│   │   │   └── TripPdfStyles.ts             # PDF styling constants
│   │   ├── nextStepBarUtils.ts             # NextStepBar utilities
│   │   ├── planStateHelpers.ts
│   │   ├── SetupCoreChip.tsx               # Setup core chip component
│   │   ├── ShareTripButton.tsx             # Share-link CTA for itinerary surfaces
│   │   ├── StrategyStageRenderer.tsx  # Main orchestrator: 60/40 map layout when destination set
│   │   ├── strategyStagePoi.ts             # Stable day-card snapshot + fingerprint helpers for map POI rendering
│   │   ├── TimelineBlockList.helpers.ts    # TimelineBlockList helper utilities
│   │   ├── TimelineBlockList.tsx
│   │   ├── TimelineBlockListAddActivityButton.tsx # Add activity button extracted from TimelineBlockList
│   │   ├── TimelineBlockListFreeDay.tsx    # Free day block extracted from TimelineBlockList
│   │   ├── TimelineBlockListLegacyBlock.tsx # Legacy block extracted from TimelineBlockList
│   │   ├── TimelineDayCard.tsx
│   │   ├── TimelineThread.tsx
│   │   ├── TripSummaryPills.helpers.ts     # TripSummaryPills helper utilities
│   │   ├── TripSummaryPills.tsx
│   │   ├── TripSummaryPillsSegment.tsx     # Pill segment extracted from TripSummaryPills
│   │   ├── tripSummaryUtils.ts        # Shared category/day-count inference for pills and activity sheet
│   │   ├── UnifiedChipRow.tsx
│   │   ├── useBookingDrawerState.ts        # Booking drawer open/close + fill-day API hook
│   │   ├── usePlanFullDensityData.tsx      # PlanFullDensityView data hook
│   │   ├── useStickyHeaderOffset.ts        # Sticky header offset hook
│   │   ├── useStrategyStageOrchestration.ts # Heavy computation/state/effects for StrategyStageRenderer
│   │   ├── useTimelineBufferLogic.ts       # Buffer/day-card classification helper for timeline states
│   │   ├── useTimelineThreadBrowseSheet.ts # TimelineThread browse sheet hook
│   │   ├── useTimelineThreadMapSync.ts     # TimelineThread map sync hook
│   │   ├── useTripSummaryFade.ts           # Trip summary fade animation hook
│   │   │
│   │   ├── booking/
│   │   │   ├── BookingDrawer.tsx
│   │   │   ├── CategorySection.tsx
│   │   │   ├── CategorySectionTile.tsx         # Individual tile within CategorySection
│   │   │   └── CheckoutSidebar.tsx
│   │   │
│   │   ├── modals/
│   │   │   ├── AlternativesModal.helpers.ts    # AlternativesModal helper utilities
│   │   │   ├── AlternativesModal.tsx
│   │   │   ├── AlternativesModalContent.tsx    # AlternativesModal content (extracted from AlternativesModal)
│   │   │   ├── AlternativesModalOptionCard.tsx # Option card for AlternativesModal
│   │   │   └── AlternativesModalThumbnail.tsx  # Thumbnail for AlternativesModal
│   │   │
│   │   ├── sheets/             # Bottom sheets
│   │   │   ├── ActivitiesSheet.helpers.ts      # ActivitiesSheet helper utilities
│   │   │   ├── ActivitiesSheet.tsx
│   │   │   ├── ActivitiesSheetContent.tsx      # Activity sheet form/section rendering
│   │   │   ├── ActivitiesSheetFooter.tsx       # Activities sheet footer
│   │   │   ├── BaseSheet.shared.tsx            # Shared BaseSheet utilities/types
│   │   │   ├── BaseSheet.tsx
│   │   │   ├── BaseSheetDesktopDialog.tsx      # Desktop dialog variant of BaseSheet
│   │   │   ├── BaseSheetMobileSheet.tsx        # Mobile sheet variant of BaseSheet
│   │   │   ├── BudgetSheet.tsx
│   │   │   ├── BudgetSheetControls.tsx         # Budget sheet form controls
│   │   │   ├── DatesSheet.tsx
│   │   │   ├── DatesSheet.utils.ts             # DatesSheet utility functions
│   │   │   ├── DatesSheetDialog.tsx            # Dates sheet dialog content
│   │   │   ├── DestinationSheet.tsx
│   │   │   ├── FlightsSheet.tsx
│   │   │   ├── FlightsSheetControls.tsx        # Flights sheet form controls
│   │   │   ├── GatingBlocker.tsx     # Shared gate-check blocker (gates array, used by Flights/Stays/Activities sheets)
│   │   │   ├── LocationSheetParts.tsx          # Location sheet parts (shared by Origin/Destination)
│   │   │   ├── OriginSheet.tsx
│   │   │   ├── SheetFooterActions.tsx          # Shared sheet footer action buttons
│   │   │   ├── StaysSheet.tsx
│   │   │   ├── StaysSheetFields.tsx            # Stays sheet form fields
│   │   │   ├── TravelersSheet.tsx
│   │   │   ├── TravelersSheetControls.tsx      # Travelers sheet form controls
│   │   │   └── TripSettingsSheet.tsx
│   │   │
│   │   ├── stages/             # Stage-specific views
│   │   │   ├── S2AgentCard.tsx           # Single agent card (collapsed strategy section card)
│   │   │   ├── S2AgentCardExpanded.tsx   # Expanded agent card with travel intelligence
│   │   │   ├── S2LocalIntelSection.tsx   # Local intel section within expanded agent card
│   │   │   ├── S2TopicConfig.tsx         # Topic configuration panel for S2 specialists
│   │   │   ├── StrategyHero.tsx
│   │   │   ├── StrategyHeroCompact.tsx         # Compact variant of StrategyHero
│   │   │   ├── StrategyHeroContent.tsx
│   │   │   ├── StrategyHeroAccordion.tsx        # Accordion expansion for StrategyHero sections
│   │   │   ├── StrategyHeroCompactSheet.tsx     # Compact sheet variant for StrategyHero
│   │   │   ├── StrategyHeroHeroSheet.tsx        # Hero sheet variant for StrategyHero
│   │   │   ├── StrategyHeroTISectionsA.tsx      # Travel intelligence sections (part A)
│   │   │   ├── StrategyHeroTISectionsB.tsx      # Travel intelligence sections (part B)
│   │   │   ├── StrategyHeroTravelIntelligence.tsx # Travel intelligence display component
│   │   │   ├── StrategyHeroUtils.tsx            # Shared utilities for StrategyHero components
│   │   │   └── useStrategyHeroEnrichment.ts    # StrategyHero enrichment hook
│   │   │
│   │   ├── tiles/
│   │   │   ├── SuggestionCard.tsx
│   │   │   ├── SuggestionCardContent.tsx
│   │   │   └── suggestionCardSections.tsx      # SuggestionCard sections (extracted)
│   │   │
│   │   └── timeline/
│   │       ├── DragPreviewCard.tsx     # Ghost card shown in DragOverlay during block drag
│   │       ├── DraggableBlock.tsx      # useDraggable wrapper; locked blocks show Lock icon
│   │       ├── DroppableDay.tsx        # useDroppable wrapper for activity days (two-div: hit area + highlight)
│   │       ├── FreeDayDropSlot.tsx     # Drop zone inside FreeDayCard (via freeDayDropSlot render prop)
│   │       ├── InlineDatePrompt.tsx
│   │       ├── ItineraryDndWrapper.tsx # DndContext root; orchestrates validate/apply-arrangement flow
│   │       ├── RichBlockRenderer.helpers.ts    # RichBlockRenderer helper utilities
│   │       ├── RichBlockRenderer.tsx   # Smart block router: logistics → safety → ghost → activity (extracted from TimelineThread)
│   │       ├── TimelineSkeleton.tsx
│   │       ├── useTimelineFillDay.ts   # Fill-day state + handler hook (extracted from TimelineThread)
│   │       └── blocks/
│   │           ├── ActivityCardActionParts.tsx     # Action parts extracted from ActivityCardActions
│   │           ├── ActivityCardActions.tsx
│   │           ├── ActivityCardMeta.helpers.ts     # ActivityCardMeta helper utilities
│   │           ├── ActivityCardMeta.tsx
│   │           ├── ActivityCardPhoto.tsx
│   │           ├── ActivityMiniCard.tsx
│   │           ├── FreeDayCard.tsx
│   │           ├── FreeDayCardSections.tsx         # FreeDayCard sections
│   │           ├── GhostSlot.tsx
│   │           ├── HoldToDeleteButton.tsx          # Press-and-hold circular progress delete button
│   │           ├── LogisticsBlock.tsx
│   │           ├── LogisticsBlockParts.tsx         # LogisticsBlock parts
│   │           ├── PreferenceAttributionBadge.tsx  # "You preferred this" badge
│   │           ├── SafetyBlock.tsx
│   │           ├── activityMiniCardTheme.ts       # Activity mini card theme constants
│   │           └── types.ts
│   │
│   ├── providers/
│   │   └── Providers.tsx       # App providers wrapper
│   │
│   ├── tiles/                  # Tile display components
│   │   ├── MiniCard.tsx
│   │   ├── MiniCardContent.tsx
│   │   ├── MiniCardQuickFacts.tsx          # Quick facts section extracted from MiniCardContent
│   │   ├── MiniCardSummary.tsx             # Summary section extracted from MiniCardContent
│   │   ├── MiniCardSummaryPricing.tsx      # Pricing section of MiniCardSummary
│   │   ├── MiniCardSummaryThumbnail.tsx    # Thumbnail section of MiniCardSummary
│   │   ├── TaxesFeesTooltip.tsx
│   │   ├── TileCard.tsx
│   │   ├── TileCardActions.tsx             # Tile card actions extracted from TileCard
│   │   ├── TileCardContent.tsx
│   │   ├── TileCardMedia.tsx               # Tile card media section extracted from TileCard
│   │   ├── TileDetailsFooter.tsx           # Tile details footer extracted from TileDetailsModal
│   │   ├── TileDetailsInfo.tsx
│   │   ├── TileDetailsModal.tsx
│   │   ├── TileDetailsSupportingSections.tsx # Supporting sections for TileDetailsModal
│   │   ├── tileHelpers.ts                  # Shared tile helper utilities
│   │   └── tileSections.tsx                # Tile section barrel/re-exports
│   │
│   └── ui/                     # Base UI components
│       ├── ErrorBoundary.tsx       # Generic error boundary wrapper
│       ├── ModalErrorBoundary.tsx  # Error boundary for modals/sheets (crash isolation)
│       ├── UserAvatar.tsx          # Shared avatar primitive for account chrome
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
│   ├── useChatEffects.ts         # ChatPanel side effects (scroll, focus, ready-to-generate; extracted from ChatPanel)
│   ├── useChatMessagePipeline.ts # Memoized stable/streaming chat-message derivation hook
│   ├── useChatScrolling.ts       # Chat scroll container, auto-scroll, collapse header (extracted from ChatPanel)
│   ├── useChatSend.ts            # Chat send orchestration + SSE lifecycle (extracted from ChatPanel)
│   ├── useChatSse.ts             # SSE/streaming connection manager for ChatPanel (extracted from ChatPanel)
│   ├── useDelayedLoader.ts
│   ├── useHeaderActions.tsx      # Shared mobile header actions (share/PDF/new trip/auth)
│   ├── useIsDesktop.ts
│   ├── useLocalExpertPolling.ts  # Local Expert enrichment cache/polling orchestration
│   ├── usePreferenceAutoRegen.ts # Auto-triggers itinerary regen on heart changes
│   ├── useScrollCollapse.ts
│   ├── useSheetManager.ts
│   ├── useSpecialistDeepLink.ts
│   ├── useTripInputsWithFallback.ts
│   ├── useMapSync.ts             # Zustand store for map↔timeline two-way sync
│   ├── useUndoStack.ts           # Auto-expire side effect hook for undo stack (clears undoEntry after 8s)
│   └── useViewNavigation.ts
│
├── lib/                        # Utility functions
│   ├── animation-config.ts     # Progressive disclosure timing constants
│   ├── api.ts                  # API client
│   ├── config.ts               # Shared backend URL constant for RSC + client fetches
│   ├── contentPolicyGuard.ts   # Content policy validation
│   ├── date-utils.ts           # Date formatting/parsing utilities
│   ├── dayIntensity.ts         # Day intensity scoring (relaxed/balanced/packed) from DayBlock hours
│   ├── debug.ts                # Debug/logging utilities
│   ├── pdfData.ts              # Transform day cards + tiles to PDF-ready shape
│   ├── design-system.ts        # Design system tokens
│   ├── destination-intel-cache.ts # Shared destination-intel cache + inflight dedupe for Local Expert enrichment
│   ├── specialist-colors.ts    # Specialist-to-color text class mappings (SSoT for specialist badge text colors)
│   ├── fillDayGuards.ts        # Fill-day client cooldown guard helpers
│   ├── format-utils.ts         # Formatting utilities
│   ├── ghost-timeline-adapter.ts  # Ghost timeline + MapPOI extraction helpers
│   ├── googlePlacesPhoto.ts    # Google Places photo URL helpers
│   ├── sharedTripApi.ts        # Shared client/server helpers for `/api/shared/{slug}`
│   ├── categoryNormalization.ts  # Category canonicalization and chip filtering helpers
│   ├── showMutationToast.ts    # Toast helper with Undo CTA for drag/remove mutations
│   ├── loaderConfig.ts         # Loader configuration
│   ├── loaderCopyConfig.ts     # Loader copy text
│   ├── placeholders.ts         # Placeholder data
│   ├── renderStarRating.ts     # Shared numeric-rating -> star-string helper for tile surfaces
│   ├── specialist-utils.ts     # Specialist topic utilities
│   ├── specialistLinkParser.ts
│   ├── specialists.ts          # Specialist registry SSoT (colors, icons, keywords, IDs)
│   ├── statusCopyMap.ts        # Status text mappings
│   ├── streamParser.ts         # Stream parsing utilities
│   ├── summary.ts              # Summary utilities
│   ├── theme.ts                # Theme mode constants for app-level styling
│   ├── tileSelectors.ts        # Tile selection logic
│   ├── tileUtils.ts            # Tile utilities
│   ├── travelIntel.ts          # Travel intelligence data helpers
│   ├── popular-places.ts       # Static list of popular destination suggestions for landing input
│   ├── use-sync-external-store-shim.js  # useSyncExternalStore shim for SSR compatibility
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
│   ├── panelToggleStore.ts     # Zustand toggle state for mutually exclusive stays/flights/activities/intel panels
│   ├── uiStore.ts              # UI state
│   └── userStore.ts            # Auth user + recent-trip resume state
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
├── e2e/                       # End-to-end Playwright tests
│   └── rome-golden-path.spec.ts  # Golden-path E2E test for Rome trip flow
│
├── __tests__/                  # Frontend tests
│   ├── anti-fragmentation.test.tsx
│   ├── chat-suggestion-actions.test.ts
│   ├── constraint-states.test.tsx
│   ├── browse-activities-cache.test.ts
│   ├── chat-suggestion-chips.test.tsx
│   ├── documentStore.test.ts
│   ├── fill-day-guards.test.ts
│   ├── category-normalization.test.ts
│   ├── ghost-timeline-adapter.test.ts
│   ├── google-places-photo.test.ts
│   ├── itinerary-generation-dedupe.test.tsx
│   ├── LandingHelpers.test.ts          # Landing helper keyword/diff tests
│   ├── landing-derived.test.tsx
│   ├── map-error-boundary.test.ts
│   ├── map-helpers.test.ts             # InteractiveMap helper hook tests
│   ├── booking-links.test.tsx          # Booking deeplink label and rewrite tests
│   ├── booking-planning-view.test.tsx  # BookingPlanningView section-toggle rendering tests
│   ├── booking-summary.test.tsx        # Stage-3 booking-links summary coverage
│   ├── logistics-block-sizing.test.tsx # Timeline logistics block thumbnail/CTA layout tests
│   ├── plan-copy.test.tsx
│   ├── placeholders.test.ts
│   ├── rich-block-renderer.test.tsx
│   ├── suggestion-card-sizing.test.tsx # Suggestion card compact-thumbnail layout tests
│   ├── split-render-surfaces.test.tsx  # Split render surfaces component extraction tests
│   ├── strategy-stage-orchestration.test.ts  # StrategyStage orchestration helper tests
│   ├── streaming.test.ts
│   ├── tileHelpers.test.ts             # Tile helper utility tests
│   ├── useBranchManager.test.tsx       # Immediate plan-result apply + missing-flight refresh timing tests
│   ├── useChatScrolling.test.tsx       # Forced bottom-settle and user-scroll cancellation tests
│   ├── useChatSend.optimistic-extension.test.tsx  # Optimistic extension rollback tests for chat send
│   ├── useTripInputsWithFallback.test.tsx  # Trip-input fallback subscription behavior tests
│   ├── userStore.test.ts               # Auth/recent-trips store tests
│   └── travel-intel.test.ts
│
├── .prettierignore             # Prettier ignore patterns
├── .prettierrc.cjs             # Prettier configuration
├── Dockerfile                  # Frontend Docker image
├── eslint.config.mjs
├── next.config.mjs
├── next-env.d.ts
├── package.json
├── package-lock.json
├── playwright.config.ts
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
├── data-extraction-matrix.md   # Provider field-priority notes for Viator vs GYG vs Google Places
├── data-contracts.md           # API routes, schemas, state store contracts
├── design-system.md            # Frontend styling SSoT
├── key_files/                  # Reference snapshots of key source files (backend + frontend)
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
2. **Coordinator Architecture** - `coordinator.execute_turn()` plans deterministic step execution around `classify`, optional parallel `dispatch_specialists` + `search_tiles`, then `local_intel` / `build_itinerary`, and final response generation. See `plan_graph_analysis.md`.
3. **Design Tokens** - Frontend uses tokens from `design-system.md`
4. **StrategyStageRenderer** - Single renderer adapts to data density (see `ux_unified_architecture.md`)
5. **DnD via `blockWrapper` render prop** - `TimelineThread` is DnD-agnostic; `ItineraryDndWrapper` + `DraggableBlock` + `DroppableDay` inject drag via `blockWrapper` prop. Dependency: `@dnd-kit/core`.
6. **PDF Export Path** - `frontend/lib/pdfData.ts` prepares itinerary/doc data for `frontend/components/plan/pdf/TripPdfDocument.tsx` and `frontend/components/plan/PdfExportButton.tsx`.
7. **Agent Specs Canonical Source** - `.claude/agents/*` are canonical specialist specs; `.codex/agents/*` are wrappers that reference those canonical files.
