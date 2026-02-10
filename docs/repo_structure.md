# Repository Structure

This document provides a comprehensive overview of the Nomadic codebase structure.

## Root Directory

```
nomadic/
├── .claude/                    # Claude Code configuration
├── .github/                    # GitHub workflows and instructions
├── .vscode/                    # VS Code settings
├── backend/                    # Python FastAPI backend
├── docs/                       # Architecture documentation
├── frontend/                   # Next.js frontend
├── scripts/                    # Root-level utility scripts
├── tests/                      # Root-level tests
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
│   ├── config.py               # Application configuration
│   ├── crud_document.py        # Document CRUD operations
│   ├── crud_trip.py            # Trip CRUD operations
│   ├── db.py                   # Database connection
│   ├── db_models.py            # SQLAlchemy models
│   ├── debug_utils.py          # Debugging utilities
│   ├── graph_plan_utils.py     # LangGraph plan utilities
│   ├── main.py                 # FastAPI application entry
│   ├── placeholders.py         # Placeholder data
│   ├── plan_graph.py           # LangGraph workflow definition
│   ├── safety_snippets.json    # Safety-related content
│   ├── schemas.py              # Pydantic request/response schemas
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
│   │   ├── cache_access.py     # Planner cache utilities
│   │   ├── hashing.py          # Hash utilities
│   │   ├── meta.py             # Metadata utilities
│   │   ├── meta_keys.py        # Metadata key constants
│   │   ├── specialist_registry.py # Specialist config SSoT (keywords, constraints, flags)
│   │   ├── telemetry.py        # Telemetry/logging
│   │   ├── test_mode.py        # Test mode utilities
│   │   │
│   │   ├── nodes/              # LangGraph nodes (7-node structure)
│   │   │   ├── __init__.py
│   │   │   ├── constraint_guard.py    # Constraint validation
│   │   │   ├── intent_router.py       # Intent classification
│   │   │   ├── local_expert.py        # Local knowledge node
│   │   │   ├── logistics_node.py      # Flights/hotels data fetcher
│   │   │   ├── specialist_llm.py      # Specialist LLM generation logic
│   │   │   ├── specialist_schemas.py  # Specialist Pydantic schemas
│   │   │   ├── synthesizer.py         # Response synthesizer
│   │   │   ├── trip_architect.py      # Main planning architect
│   │   │   └── vertical_specialist.py # Domain experts (8 specialists, registry-driven)
│   │   │
│   │   ├── services/
│   │   │   ├── __init__.py
│   │   │   ├── iata_resolver.py     # IATA airport code resolver (LLM-backed)
│   │   │   ├── itinerary_adapter.py # Thin bridge: GraphState → ItineraryBuilder
│   │   │   └── section_builder.py   # Strategy section CRUD
│   │   │
│   │   └── state/
│   │       ├── __init__.py
│   │       ├── schemas.py      # Planner state schemas
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
│   │   ├── base_cache.py           # Base cache class
│   │   ├── experience_generator.py # Tier 2 experience tile generation via gpt-4o-mini (L1+L2 cache)
│   │   ├── itinerary_builder.py    # Itinerary construction service
│   │   ├── regen_strategy.py       # Selective regeneration strategy computation
│   │   ├── router_cache.py         # Thread-safe L1 cache for router extraction (context-aware)
│   │   ├── specialist_cache.py     # Thread-safe L1+L2 cache for specialist LLM outputs
│   │   ├── tile_cache.py           # Thread-safe L1+L2 cache for tile provider data (24h TTL)
│   │   ├── unsplash.py             # Unsplash image service
│   │   └── unsplash_queries.py     # Unsplash query helpers (includes Tier 2 activity queries)
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
│       ├── constraint_engine.py # Constraint processing
│       └── tile_service.py     # Tile service tool
│
├── migrations/                 # Alembic database migrations
│   ├── env.py
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
│   ├── test_experience_generator.py      # Experience generator tests
│   ├── test_hash_ban.py                  # Hash ban tests
│   ├── test_import_contract.py           # Import contract tests
│   ├── test_itinerary_builder.py         # Itinerary builder tests
│   ├── test_llm_feasibility.py           # LLM geographic feasibility tests
│   ├── test_multi_specialist_integration.py  # Multi-specialist tests
│   ├── test_plan_schema.py               # Plan schema tests
│   ├── test_router_cache.py              # Router cache tests (context-dependency detection)
│   ├── test_specialist_cache.py          # Specialist LLM cache tests (thread safety, L1/L2)
│   ├── test_specialist_structured.py     # Specialist structured output tests
│   ├── test_stage2_integration.py        # Stage 2 integration tests
│   ├── test_tile_cache.py                # Tile cache tests (L1/L2, thread safety)
│   ├── test_typed_meta.py                # Typed metadata bridge tests
│   └── db/
│       └── test_plan_document_api.py
│
├── test_artifacts/             # Test output artifacts
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
│   ├── layout.tsx              # Root layout
│   ├── page.tsx                # Home page
│   ├── contact/page.tsx
│   ├── cookies/page.tsx
│   ├── credits/page.tsx
│   ├── privacy/page.tsx
│   ├── sitemap/page.tsx
│   ├── summary/page.tsx
│   └── terms/page.tsx
│
├── components/
│   ├── animations/
│   │   ├── StartupSequence.tsx
│   │   └── Typewriter.tsx
│   │
│   ├── chat/                   # Chat interface components
│   │   ├── ChatPanel.tsx
│   │   ├── ChatSkeleton.tsx
│   │   ├── CollapsedSetupSummary.tsx
│   │   ├── HoldToDeleteButton.tsx
│   │   ├── MobileChatInput.tsx
│   │   ├── MobileSetupCollapsedHeader.tsx
│   │   ├── SmartLoader.tsx
│   │   ├── SystemAckLine.tsx
│   │   ├── SystemReceipt.tsx
│   │   ├── TripStatusBar.tsx
│   │   └── useChatStateMachine.ts
│   │
│   ├── layout/                 # Layout components
│   │   ├── FloatingBuildButton.tsx
│   │   ├── MobileModeHeader.tsx
│   │   ├── MobileSwipeLayout.tsx
│   │   ├── NomadicLanding.tsx
│   │   ├── SplitLayoutView.tsx
│   │   ├── TripDetailsForm.tsx
│   │   └── hooks/              # Layout-specific hooks
│   │       ├── useBranchManager.ts
│   │       ├── useBranchState.ts
│   │       ├── useDateRangeSelector.ts
│   │       ├── useLocalBookingSettings.ts
│   │       ├── useSessionHydration.ts
│   │       ├── useTileSelection.ts
│   │       └── useTripInputsEditor.ts
│   │
│   ├── map/                    # Map components
│   │   ├── InteractiveMap.tsx
│   │   ├── MapboxErrorSuppressor.tsx
│   │   ├── MapErrorBoundary.tsx
│   │   └── MapLayerFilter.tsx
│   │
│   ├── nomadic/                # Marketing/landing components
│   │   ├── consent-manager.tsx
│   │   ├── features-section.tsx
│   │   ├── footer.tsx
│   │   └── legal-page.tsx
│   │
│   ├── pill/                   # Pill/badge components
│   │   ├── ExpandablePill.tsx
│   │   ├── index.ts
│   │   ├── LocationBadge.tsx
│   │   └── TruncatedDestinationList.tsx
│   │
│   ├── plan/                   # Plan view components
│   │   ├── index.ts
│   │   ├── BookingSection.tsx
│   │   ├── ConflictResolutionBanner.tsx  # Path A: Conflict resolution options for constraint clashes
│   │   ├── CoreChip.tsx
│   │   ├── DaySection.tsx
│   │   ├── DestinationMapPlaceholder.tsx
│   │   ├── DocumentHeader.tsx
│   │   ├── ExplorationProgress.tsx
│   │   ├── ItineraryProgressIndicator.tsx  # Path A: Auto-generation progress display
│   │   ├── NextStepBar.tsx
│   │   ├── OnboardingChips.tsx
│   │   ├── OptionalRefinementsSection.tsx
│   │   ├── OriginPromptCard.tsx
│   │   ├── PlanDocument.tsx
│   │   ├── PlanHeader.tsx
│   │   ├── PlanningProgress.tsx
│   │   ├── planStateHelpers.ts
│   │   ├── ReadyToPlanBanner.tsx
│   │   ├── Segment.tsx
│   │   ├── SelectionsBar.tsx       # Hearted tiles carousel (sticky bar of preferred tiles)
│   │   ├── StrategyStageRenderer.tsx  # Main orchestrator: 60/40 map layout when destination set
│   │   ├── TimelineThread.tsx
│   │   ├── TripHealthBar.tsx
│   │   ├── TripHealthDashboard.tsx
│   │   ├── TripSummaryPills.tsx
│   │   ├── UnifiedChipRow.tsx
│   │   │
│   │   ├── booking/
│   │   │   ├── BookingDrawer.tsx
│   │   │   ├── CategorySection.tsx
│   │   │   └── CheckoutSidebar.tsx
│   │   │
│   │   ├── modals/
│   │   │   ├── AlternativesModal.tsx
│   │   │   ├── ConflictResolutionModal.tsx
│   │   │   ├── index.ts
│   │   │   └── RegenerateConfirmModal.tsx
│   │   │
│   │   ├── sheets/             # Bottom sheets
│   │   │   ├── ActivitiesSheet.tsx
│   │   │   ├── BaseSheet.tsx
│   │   │   ├── BudgetSheet.tsx
│   │   │   ├── CheckoutSheet.tsx
│   │   │   ├── DatesSheet.tsx
│   │   │   ├── DestinationSheet.tsx
│   │   │   ├── FlightsSheet.tsx
│   │   │   ├── index.ts
│   │   │   ├── OriginSheet.tsx
│   │   │   ├── StaysSheet.tsx
│   │   │   ├── TravelersSheet.tsx
│   │   │   └── TripSettingsSheet.tsx
│   │   │
│   │   ├── stages/             # Stage-specific views
│   │   │   ├── index.ts
│   │   │   ├── S1FramingView.tsx
│   │   │   ├── S2BlockedView.tsx
│   │   │   ├── S2StrategyView.tsx
│   │   │   ├── S3BlockedView.tsx
│   │   │   ├── S3EditingView.tsx
│   │   │   ├── S3ItineraryView.tsx
│   │   │   └── StrategyHero.tsx
│   │   │
│   │   ├── tiles/
│   │   │   ├── BookableCard.tsx
│   │   │   ├── index.ts
│   │   │   └── SuggestionCard.tsx
│   │   │
│   │   └── timeline/
│   │       ├── InlineDatePrompt.tsx
│   │       ├── TimelineSkeleton.tsx
│   │       └── blocks/
│   │           ├── ActivityMiniCard.tsx
│   │           ├── FreeDayCard.tsx
│   │           ├── GhostSlot.tsx
│   │           ├── index.ts
│   │           ├── LogisticsBlock.tsx
│   │           ├── PreferenceAttributionBadge.tsx  # "You preferred this" badge
│   │           ├── SafetyBlock.tsx
│   │           ├── SuggestionBlock.tsx
│   │           └── types.ts
│   │
│   ├── providers/
│   │   └── Providers.tsx       # App providers wrapper
│   │
│   ├── tiles/                  # Tile display components
│   │   ├── MiniCard.tsx
│   │   ├── TaxesFeesTooltip.tsx
│   │   ├── TileCard.tsx
│   │   ├── TileDetailsModal.tsx
│   │   ├── TileFilterBar.tsx
│   │   ├── TileSectionHeader.tsx  # Section headers for tile categories
│   │   └── TilesGrid.tsx
│   │
│   └── ui/                     # Base UI components
│       ├── bottom-sheet.tsx
│       ├── button.tsx
│       ├── calendar.tsx
│       ├── card.tsx
│       ├── confirm-dialog.tsx
│       ├── loader.tsx
│       ├── popover.tsx
│       ├── sheet.tsx
│       ├── skeleton.tsx
│       ├── switch.tsx
│       ├── toast.tsx
│       └── tooltip.tsx
│
├── contexts/
│   └── MobileModeContext.tsx
│
├── hooks/                      # Custom React hooks
│   ├── useActionLoader.ts
│   ├── useDelayedLoader.ts
│   ├── useIsDesktop.ts
│   ├── useMapSync.ts
│   ├── usePreferenceAutoRegen.ts # Auto-triggers itinerary regen on heart changes
│   ├── useScrollCollapse.ts
│   ├── useScrollSpy.ts
│   ├── useSheetManager.ts
│   ├── useShortlist.ts         # Heart preferences - backed by documentStore.preferredTileIds
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
│   ├── debug.ts                # Debug/logging utilities
│   ├── design-system.ts        # Design system tokens
│   ├── destination-coords.ts   # Destination coordinate lookup (~90 destinations)
│   ├── format-utils.ts         # Formatting utilities
│   ├── ghost-timeline-adapter.ts
│   ├── loaderConfig.ts         # Loader configuration
│   ├── loaderCopyConfig.ts     # Loader copy text
│   ├── placeholders.ts         # Placeholder data
│   ├── plan-transform.ts       # Plan data transforms
│   ├── refinementSummaries.ts
│   ├── route-utils.ts          # Routing utilities
│   ├── specialist-utils.ts     # Specialist topic utilities
│   ├── specialistLinkParser.ts
│   ├── specialists.ts          # Specialist registry SSoT (colors, icons, keywords, IDs)
│   ├── statusCopyMap.ts        # Status text mappings
│   ├── streamParser.ts         # Stream parsing utilities
│   ├── summary.ts              # Summary utilities
│   ├── tileSelectors.ts        # Tile selection logic
│   ├── tileUtils.ts            # Tile utilities
│   └── utils.ts                # General utilities (cn, etc.)
│
├── public/
│   └── assets/                 # Static assets
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
│   ├── constraint-states.test.tsx
│   └── plan-copy.test.tsx
│
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
├── design-system.md            # Frontend styling SSoT
├── key_backend_files/          # Backend reference snapshots (prompts, nodes, services)
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
| `settings.json` | Editor settings |
| `tasks.json` | Task definitions |

---

## Key Architectural Notes

1. **TripPlan is SSoT** - All trip state flows through `TripPlan` schema
2. **7-Node LangGraph** - Backend planner uses exactly 7 nodes (see `plan_graph_analysis.md`)
3. **Design Tokens** - Frontend uses tokens from `design-system.md`
4. **UnifiedStageRenderer** - Single renderer adapts to data density (see `ux_unified_architecture.md`)
