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
│   │   ├── season.py           # Season detection logic
│   │   ├── telemetry.py        # Telemetry/logging
│   │   ├── test_mode.py        # Test mode utilities
│   │   │
│   │   ├── nodes/              # LangGraph nodes (7-node structure)
│   │   │   ├── __init__.py
│   │   │   ├── constraint_guard.py    # Constraint validation
│   │   │   ├── intent_router.py       # Intent classification
│   │   │   ├── local_expert.py        # Local knowledge node
│   │   │   ├── logistics_node.py      # Flights/hotels data fetcher
│   │   │   ├── synthesizer.py         # Response synthesizer
│   │   │   ├── trip_architect.py      # Main planning architect
│   │   │   └── vertical_specialist.py # Domain experts (diving/hiking/skiing)
│   │   │
│   │   └── state/
│   │       ├── __init__.py
│   │       └── schemas.py      # Planner state schemas
│   │
│   ├── prompts/                # LLM prompt templates
│   │   ├── synthesizer.txt
│   │   └── specialists/
│   │       ├── diving.txt
│   │       ├── hiking.txt
│   │       ├── local_expert.txt
│   │       └── skiing.txt
│   │
│   ├── services/
│   │   ├── __init__.py
│   │   ├── itinerary_builder.py  # Itinerary construction
│   │   ├── unsplash.py           # Unsplash image service
│   │   └── unsplash_queries.py   # Unsplash query helpers
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
│       └── c1f8e8bf9d21_chat_messages_table.py
│
├── scripts/
│   └── check_ssot_violations.py  # SSOT validation script
│
├── tests/
│   ├── conftest.py             # Pytest fixtures
│   ├── llm_stub.py             # LLM mock for testing
│   ├── test_architecture.py    # Architecture tests
│   ├── test_demo_dataset.py    # Demo data tests
│   ├── test_hash_ban.py        # Hash ban tests
│   ├── test_import_contract.py # Import contract tests
│   ├── test_plan_schema.py     # Plan schema tests
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
│   │   ├── MinimizedChatInput.tsx
│   │   ├── MobileChatCompactHeader.tsx
│   │   ├── MobileSetupCollapsedHeader.tsx
│   │   ├── PlanModeHint.tsx
│   │   ├── SmartLoader.tsx
│   │   ├── SystemAckLine.tsx
│   │   ├── SystemReceipt.tsx
│   │   └── useChatStateMachine.ts
│   │
│   ├── layout/                 # Layout components
│   │   ├── FloatingBuildButton.tsx
│   │   ├── MobileModeHeader.tsx
│   │   ├── MobilePlanFooter.tsx
│   │   ├── MobileTabBar.tsx
│   │   ├── NomadicLanding.tsx
│   │   ├── SetupDrawer.tsx
│   │   ├── SetupProgressIndicator.tsx
│   │   ├── SplitLayoutView.tsx
│   │   ├── TripDetailsForm.tsx
│   │   └── hooks/              # Layout-specific hooks
│   │       ├── useBranchManager.ts
│   │       ├── useBranchState.ts
│   │       ├── useDateRangeSelector.ts
│   │       ├── useLocalBookingSettings.ts
│   │       ├── usePlanRegeneration.ts
│   │       ├── useSessionHydration.ts
│   │       ├── useTileSelection.ts
│   │       └── useTripInputsEditor.ts
│   │
│   ├── map/                    # Map components
│   │   ├── InteractiveMap.tsx
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
│   │   ├── CoreChip.tsx
│   │   ├── DaySection.tsx
│   │   ├── DestinationMapPlaceholder.tsx
│   │   ├── DocumentHeader.tsx
│   │   ├── GlassCommandBar.tsx
│   │   ├── NextStepBar.tsx
│   │   ├── NextStepPanel.tsx
│   │   ├── OnboardingChips.tsx
│   │   ├── OptionalRefinementsSection.tsx
│   │   ├── PlanDocument.tsx
│   │   ├── PlanHeader.tsx
│   │   ├── PlanningProgress.tsx
│   │   ├── planStateHelpers.ts
│   │   ├── Segment.tsx
│   │   ├── StrategyStageRenderer.tsx
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
│   │   │   └── index.ts
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
│   │   │   └── TravelersSheet.tsx
│   │   │
│   │   ├── stages/             # Stage-specific views
│   │   │   ├── BookingAnchorCard.tsx
│   │   │   ├── BookView.tsx
│   │   │   ├── CulturalProtocolCard.tsx
│   │   │   ├── index.ts
│   │   │   ├── InfoCard.tsx
│   │   │   ├── LogisticsGrid.tsx
│   │   │   ├── NeighborhoodStrategyCard.tsx
│   │   │   ├── PriorityBookingsSection.tsx
│   │   │   ├── S1FramingView.tsx
│   │   │   ├── S2BlockedView.tsx
│   │   │   ├── S2StrategyView.tsx
│   │   │   ├── S3BlockedView.tsx
│   │   │   ├── S3EditingView.tsx
│   │   │   ├── S3ItineraryView.tsx
│   │   │   ├── ScarcityRadarCard.tsx
│   │   │   ├── StrategyHero.tsx
│   │   │   └── TransportStrategyCard.tsx
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
│   ├── useMapSync.ts
│   ├── useScrollCollapse.ts
│   ├── useScrollSpy.ts
│   ├── useSheetManager.ts
│   ├── useShortlist.ts
│   ├── useSpecialistDeepLink.ts
│   ├── useSpeculativeExecution.ts
│   ├── useTripInputsWithFallback.ts
│   └── useViewNavigation.ts
│
├── lib/                        # Utility functions
│   ├── api.ts                  # API client
│   ├── chipStyles.ts           # Chip styling utilities
│   ├── contentPolicyGuard.ts   # Content policy validation
│   ├── design-system.ts        # Design system tokens
│   ├── format-utils.ts         # Formatting utilities
│   ├── ghost-timeline-adapter.ts
│   ├── loaderConfig.ts         # Loader configuration
│   ├── loaderCopyConfig.ts     # Loader copy text
│   ├── placeholders.ts         # Placeholder data
│   ├── plan-transform.ts       # Plan data transforms
│   ├── refinementSummaries.ts
│   ├── route-utils.ts          # Routing utilities
│   ├── specialistLinkParser.ts
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
