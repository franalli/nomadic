# Unified UX Architecture & Rendering Protocol

**Version:** 3.0 (The "Two-Mode Unification")
**Philosophy:** Two clear modes (PLANNING + BOOKING) instead of three confusing phases. The UI evolves naturally based on user inputs.

---

## I. The Two-Mode System

The application uses **two modes** instead of three phases. This simplifies the user experience by eliminating the artificial boundary between "Setup" and "Plan".

### Overview

| Mode | Purpose | Unlock Condition |
|------|---------|------------------|
| **PLANNING** | Build your perfect trip | Always accessible (default) |
| **BOOKING** | Lock in your plans | Explicit "Proceed to Booking" click + finalized plan |

### PLANNING Mode ("Inspiration → Logistics → Refinement")

PLANNING mode evolves naturally based on what the user has provided. No artificial gates or confusing transitions.

#### Stage 1: Initial Input (Destination Only)
* **Trigger:** User mentions destination (e.g., "I want to go to Bali")
* **UI Shows:**
  * Hero image of destination
  * Specialist strategy cards (diving, local expert, etc.)
  * Progress indicator: "Add dates to see itinerary"
  * Map with static destination pin (POIs from specialists deferred)
* **Tiles:** HIDDEN (no prices without dates)

#### Stage 2: After Dates Added
* **Trigger:** User provides dates (e.g., "April 15-25")
* **UI Shows:**
  * Day-by-day itinerary auto-generates
  * Map shows day markers (route lines deferred to post-MVP)
  * Suggested hotels/flights/activities appear in timeline
  * Strategy cards compact into "Trip DNA" bar
  * "Proceed to Booking" button appears at bottom
* **Tiles:** VISIBLE as suggestions. Planning surfaces may already expose partner/map deeplinks from detail views, but locked-in booking remains secondary to plan refinement.

#### Stage 3: Refinement
* **User Can:**
  * Modify suggestions ("Change hotel")
  * Adjust itinerary via chat
  * Save items to shortlist
  * Open partner/map deeplinks from supported tile/detail surfaces without leaving PLANNING mode
* **Exit:** Click "Proceed to Booking" to enter BOOKING mode

### BOOKING Mode ("The Commitment")

* **Goal:** Lock selections and centralize external booking actions around the chosen itinerary
* **Trigger:** User clicks "Proceed to Booking" (HARD gate - explicit action required)
* **UI Shows:**
  * Read-only itinerary summary
  * Tile-level external booking actions (single `tile.deeplink` path) centered on the committed selection set
  * Placeholder copy for future comparison/checkout flow
* **Tiles:** BOOKABLE via per-tile deeplinks (no partner comparison table yet). Unlike PLANNING, BOOKING mode is the dedicated committed-booking surface rather than the first place deeplinks can ever appear.

---

## I.A Progress Indicator (PLANNING Mode)

The progress indicator replaces the confusing three-tab navigation.

### Visual Design
```
┌──────────────────────────────────────────────────────┐
│  [PLANNING ●]  [BOOKING 🔒]   ▓▓▓▓▓▓░░░░ 60%        │
└──────────────────────────────────────────────────────┘
```

### Progress Calculation
| Item | Weight | Example |
|------|--------|---------|
| Destination | 25% | ✓ Bali |
| Origin | 15% | ✓ Rome |
| Dates | 30% | ⏳ Not set |
| Itinerary Generated | 20% | ○ Waiting for dates |
| Ready to Book | 10% | ○ Waiting for selections |

### Implementation
```typescript
type ViewMode = 'planning' | 'booking';

interface PlanningPhase {
  hasDestination: boolean;
  hasOrigin: boolean;
  hasDates: boolean;
  hasItinerary: boolean;
  isReadyToBook: boolean;
}
```

---

## I.A.1 Single-Scroll Progressive Disclosure (PLANNING Mode)

PLANNING mode uses a **single-scroll layout** that progressively reveals content based on data density. No tab switching required.

### Content Stack (Top to Bottom)

**Pre-Generation (P0-P2): No Map - Tiles get full width**
```
┌─────────────────────────────────────────────────┐
│  SECTION 1: Specialist Strategy Cards           │  ← Stage 1+
│  (Collapsed by default, expandable)             │
├─────────────────────────────────────────────────┤
│  SECTION 2: Tile Browser (full width)           │  ← Stage 2+
│  Hotels, Flights, Activities with heart actions │
│  Heart = preference signal for AI weighting     │
│  Component: BookingSection.tsx                  │
├─────────────────────────────────────────────────┤
│  Build Itinerary CTA                           │  ← Stage 2+
│  Triggers itinerary generation                 │
│  Component: StrategyStageRenderer.tsx          │
└─────────────────────────────────────────────────┘
```

**Post-Generation (P3+) - Desktop: Content + Flex Map Sidebar**
```
┌─────────────────────────────────┬──────────────┐
│  LEFT COLUMN (flex-1)           │  RIGHT       │
│  min: 480px, max: 800px         │  flex-1      │
│  ┌────────────────────────────┐ │  min: 350px  │
│  │ SECTION 1: Specialists     │ │  ┌─────────┐ │
│  │ (Collapsed cards)          │ │  │         │ │
│  ├────────────────────────────┤ │  │   MAP   │ │
│  │ SECTION 2: Tile Browser    │ │  │  sticky │ │
│  │ (Hotels, Flights, etc.)    │ │  │top-align│ │
│  ├────────────────────────────┤ │  │  100vh  │ │
│  │ SECTION 3: Timeline        │ │  │-header  │ │
│  │ (Day cards + activities)   │ │  │         │ │
│  └────────────────────────────┘ │  └─────────┘ │
└─────────────────────────────────┴──────────────┘
```

**Post-Generation (P3+) - Mobile: Stacked with Inline Map**
```
┌─────────────────────────────────────────────────┐
│  SECTION 1: Specialist Strategy Cards           │
├─────────────────────────────────────────────────┤
│  SECTION 2: Tile Browser                        │
├─────────────────────────────────────────────────┤
│  MAP (clamp(220px,35vh,300px), inline, non-sticky)│
├─────────────────────────────────────────────────┤
│  SECTION 3: Timeline                            │
└─────────────────────────────────────────────────┘
```

### Supporting Hooks

| Component | File | Purpose |
|-----------|------|---------|
| startPreferenceAutoRegen | `hooks/usePreferenceAutoRegen.ts` | Module-level Zustand subscription (not a React hook) that auto-triggers itinerary regeneration when preferences (hearts) change. Idempotent: calling it multiple times returns the existing cleanup. Sets up two subscriptions: (1) watches `preferredTileIds` with a 1.5s debounce to batch rapid toggles, defers during active streaming/expand; (2) flushes queued regen when `expandInProgress` transitions false. `expandInProgress` remains the only hard mutex; `isRegenerating` is display-only and must not suppress queued regen work. Also exports `triggerRegeneration()` for direct invocation (e.g., from `ChatModuleSheets` after activity category changes). |
| useMapSync | `hooks/useMapSync.ts` | Zustand store for two-way map↔timeline sync (visibleDayNumber, scrollTargetDayNumber, highlightedCardId) |
| useUndoStack | `hooks/useUndoStack.ts` | Exposes undo entry from documentStore with 8s auto-expire timer |
| useNomadicLandingController | `frontend/components/layout/hooks/useNomadicLandingController.tsx` | Top-level landing controller that composes store selectors, plan-state derivation, and render-surface assembly before feeding `SplitLayoutView`, `LandingSheets`, and the floating build button. |
| useLandingRenderSurfaces | `frontend/components/layout/hooks/useLandingRenderSurfaces.tsx` | Memoizes the desktop planner pane, plan pane, header chrome, and mobile input surfaces so `NomadicLanding` stays a thin shell over extracted content components. |
| useLandingHandlers | `frontend/components/layout/hooks/useLandingHandlers.ts` | Bundles landing lifecycle handlers for `NomadicLanding`: reset/session restart, plan receipt tracking, generate/finalize actions, gear-sheet controls, user message topic detection, and mobile send/stop plumbing. |
| useTimelineThreadMapSync | `frontend/components/plan/useTimelineThreadMapSync.ts` | Extracts the `TimelineThread` day-header observer and scroll-target listener that bridge `useMapSync` with timeline scrolling. |
| useTimelineThreadBrowseSheet | `frontend/components/plan/useTimelineThreadBrowseSheet.ts` | Owns Browse Activities sheet open state plus the insert-activity call/optimistic day-card update path extracted from `TimelineThread`. |
| useChatPanelController | `frontend/components/chat/useChatPanelController.ts` | Composes ChatPanel state, scrolling, `useChatSend`, `useChatEffects`, and suggestion filtering so `ChatPanelContent` stays focused on rendering. |
| useChatMessagePipeline | `frontend/hooks/useChatMessagePipeline.ts` | Six-stage memoized derivation chain for chat rendering: fingerprints non-streaming messages, builds stable visible bubbles via `chatMessageProcessing.ts`, then appends the live streaming message without forcing full-list recomputation on every token. |
| useTripInputsWithFallback | `frontend/hooks/useTripInputsWithFallback.ts` | Prefers parent-supplied `tripInputs` without subscribing to Zustand when props are present; only falls back to a live store subscription when parents omit trip inputs, reducing rerenders on hot planning surfaces. |
| useHeaderActions | `frontend/hooks/useHeaderActions.tsx` | Shared mobile-header action hook for new trip, PDF export, share link, and auth actions. Keeps share/PDF loading state local to the header chrome and closes the overflow menu on successful completion paths. |
| useLocalExpertPolling | `frontend/hooks/useLocalExpertPolling.ts` | Owns Local Expert destination-intel cache reuse, in-flight polling dedupe, abort-on-new-stream guards, and `panelToggleStore` travel-advice count/pending sync for `PlanFullDensityView`. |

### Progressive Disclosure Rules

| Data Available | Content Shown | Map State |
|----------------|---------------|-----------|
| Destination only (no specialist content) | PlanHeader with hero image (desktop only) | Hidden (no POIs) |
| Destination + specialist content (no tiles) | Strategy cards, ghost timeline | **Visible (destination pin, desktop only)** |
| + Tiles (dates set, logistics fetched) | + Tile browser (prices available) | Visible (destination pin) |
| + Generation complete (day_cards exist) | + Itinerary timeline | Visible (destination pin + POIs from day_cards) |
| + Hearts/preferences | Preference attribution in timeline | Visible |

### Map Display Rules

| Phase | Desktop (>1024px) | Mobile (<1024px) |
|-------|-------------------|------------------|
| With Destination (full mode) | Flex column (min 350px), sticky top aligned with Day 1, height `calc(100vh - headerOffset)`, destination pin centered | `clamp(220px,35vh,300px)` height, inline before timeline (only when `hasItineraryContent && (fullModePOIs.length > 0 \|\| destinationCenter !== null)`) |
| With Destination (bridge mode) | Hidden (bridge density returns null from renderer; plan panel hidden) | Hidden |
| No Destination | Hidden | Hidden |

**Map Content:**
- Map centered on POIs via `calculateMapCenter()` (zoom derived from POI spread); returns `null` when no valid POIs exist
- Falls back to the first hotel tile with valid `geo` coordinates when no POIs are available
- Final fallback is the global default center used by `PlanFullDensityView` (`lat: 20, lng: 0, zoom: 2`)
- **POI Pins:** Activity markers from `extractPOIsFromDayCards()` with fallback to `extractPOIsFromSections()` in `ghost-timeline-adapter.ts`
  - Prefers day-card coordinates, then falls back to strategy-section activity pins in bridge mode
  - Extracts coordinates from strategy section tiles and activities (`[lng, lat]` transformed to `{ lat, lng }`)
  - Per-marker rendering uses `MapMarkerItem.tsx` to isolate marker state transitions and keep marker re-renders scoped to active/hover targets
  - **Destination fallback chain:** `effectiveTripInputs?.destination ?? destinationCard?.title`
  - POI format: `{ lat, lng }` object (not array)
  - All POI coordinates validated via `_normalizeMapCoordinates()` (rejects non-finite or out-of-range values)
  - Proximity outlier filtering removes pins outside a ~200km radius of the median centroid (`_filterProximityOutliers`) to suppress hallucinated coordinates.

### Scroll Behavior
- **Strategy Cards:** Collapsed by default, user can expand
- **Tiles:** Natural scroll, `data-tile-id` attribute for scroll targeting
- **Map (Desktop P3+):** Sticky right sidebar - stays visible while scrolling content
- **Map (Mobile P3+):** Inline between tiles and timeline, scrolls with content
- **Timeline:** Inline after tiles (or after map on mobile)

### Auto-Scroll Triggers
- **Itinerary generated:** Scrolls to timeline section (smooth scroll, 100ms delay after scroll position freeze/restore)

> **Note:** SelectionsBar has been deleted. Heart preferences are tracked in `preferredTileIds` and reflected in itinerary regeneration, not a separate UI bar.

### Animation Specification

Progressive disclosure uses coordinated animations to reveal UI elements at the right moment.

**Configuration File:** `frontend/lib/animation-config.ts`

#### Timing Constants
| Element | Trigger | Duration | Animation |
|---------|---------|----------|-----------|
| Tiles fade-in | Tiles fetched | 400ms | Opacity 0→1 |
| Timeline fade-in | Itinerary ready (day_cards exist) | 400ms | Opacity 0→1 (200ms group stagger delay) |
| Map fade-in | Destination set | 400ms | Opacity 0→1 (400ms group stagger delay) |
| NextStepBar slide-up | S2+ | Spring | Slide up from bottom |

#### Spring Physics
Spring physics are reserved for user-initiated interactions (drag & drop, card expansions). Content reveals and streaming animations use timed opacity fades instead.
- **SLIDE config:** `{ stiffness: 400, damping: 30 }` - for slide animations
- **EXPAND config:** `{ stiffness: 300, damping: 25 }` - for card expansions
- **BOUNCE config:** `{ stiffness: 500, damping: 35 }` - for bouncy elements (buttons, badges)

#### State-Based Reveals

> **Note:** In practice, the backend emits S* states (not P* directly), and `computeDataDensity()` maps to `empty`/`ghost`/`bridge`/`full` density levels. The P* phases below are conceptual guides for what renders at each density.

```
empty (no specialist content)
├─ Hero + chips (PlanHeader topo background)
└─ Map hidden

ghost (specialist content + dates, no tiles — P0 or P1)
├─ PlanMirrorLoader skeleton surface while logistics catches up
└─ Map hidden (no POIs yet)

bridge (specialist content + no dates, no tiles — P0 or P1)
├─ Plan panel hidden (SplitLayoutView treats bridge as landing layout)
└─ Map hidden

full (tiles exist or P3)
├─ Strategy cards (collapsible in S3)
├─ Tiles (fade in, 400ms) ← AnimatePresence
├─ Timeline (fade in, 400ms + 200ms delay) ← AnimatePresence + auto-scroll (when day_cards exist)
└─ Map (desktop: flex-1 min 350px, sticky h-screen, 400ms fade + 400ms delay) ← motion.div
```
```

#### Interaction-Based Reveals

```
Itinerary generated
├─ Scroll position frozen when expansion starts (useEffect captures window.scrollY)
├─ Scroll position restored synchronously before paint (useLayoutEffect)
└─ Smooth scroll to timeline section (100ms delay after restore)
```

> **Note:** SelectionsBar has been deleted. Heart-based interactions now feed directly into preference auto-regen.

#### Mobile Optimization

Mobile skips heavy animations for performance:
- **Tiles:** Immediate render (no AnimatePresence wrapper)
- **Timeline:** Immediate render
- **Map:** `clamp(220px,35vh,300px)` inline block, no slide animation

#### Loading States

Initial page bootstrap now enters directly into the route shell without a separate startup overlay:

```
First load:
├─ App shell mounts immediately
├─ Chat + plan surfaces render in-place
└─ Loading feedback comes from route-local skeletons/loaders (`PlanMirrorLoader`, chat loaders, generation state)
```

Subsequent navigations in same tab:
- Reuse the same direct-entry path
- Keep shell visible immediately (single-render entry path)

```
isExpandingItinerary = true:
├─ Tiles: 60% opacity, pointer-events-none
├─ CTA: Spinner + "Building your itinerary..."
└─ Timeline placeholder shown
```

#### Component Implementation

All animations use Framer Motion with `AnimatePresence` for enter/exit:

```tsx
// Tiles fade-in example
<AnimatePresence>
  {hasTiles && (
    <motion.section
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: REVEAL_TIMING.TILES_FADE / 1000 }}
    >
      <BookingSection ... />
    </motion.section>
  )}
</AnimatePresence>
```

**Files:**
- `frontend/lib/animation-config.ts` - Centralized timing constants
- `frontend/components/plan/StrategyStageRenderer.tsx` - Main orchestrator with AnimatePresence wrappers

### Implementation Notes
- No `subView` state - tab navigation removed entirely
- `StrategyStageRenderer.tsx` delegates layout to `PlanFullDensityView.tsx`:
  - **No Destination:** Single column `<div className="flex flex-col w-full">`
  - **With Destination (Desktop):** Content (flex-1, min 480px, max 800px) + Map (flex-1, min 350px, sticky with `calc(100vh - headerOffset)`)
  - **With Destination (Mobile):** Single column with inline map (`clamp(220px,35vh,300px)` height, shown after itinerary)
- Desktop map visibility controlled by `showDesktopMap = isDesktop && (fullModeMapItems.length > 0 || destinationCenter !== null)` (shows when POIs exist from day_cards/strategy sections or when a destination center coordinate is available)
- Mobile map only shows when `hasItineraryContent && (fullModePOIs.length > 0 || destinationCenter !== null)` (requires itinerary content plus either POIs or a destination center coordinate)
- Timeline section conditionally renders when `hasItineraryContent === true`
- Mode prop threads through TimelineThread → ActivityMiniCard for Book button visibility
- Preference attribution uses `preferredTileIds` to show "You preferred this" badge
- Legacy stage views (S3ItineraryView, S1FramingView, etc.) removed from unified flow
- Strategy cards stay inside the density-driven renderer path (`StrategyStageRenderer` -> `PlanFullDensityView` -> its subsections)

<!-- REVIEW: StrategyHero appears unmounted — possible dead code, confirm with team.
     `StrategyHero` / `StrategyHeroContent` / `StrategyHeroCompact` / `StrategyHeroAccordion`
     and the `S2AgentCard*` cluster have NO external JSX consumer in the live render path
     (verified: zero imports of the `StrategyHero` component across `frontend/`). Only utility
     exports from `StrategyHeroUtils` (e.g. `getTopicLabel`) are imported elsewhere. The live
     P1/P3 surface is `PlanFullDensityView` and its subsections
     (`PlanFullDensityTilesSection`, `FullDensityTimeline` → `PlanTimelineSection` →
     `TimelineThread`, `PlanFullDensityTravelAdvice`, map/summary). Sections of this doc that
     describe `StrategyHero` as the live strategy renderer (e.g. §I.A image guards below,
     §XII "The Magazine") are describing components that are no longer mounted. -->


### Defensive Rendering (Image Guards)

`StrategyHero.tsx` renders images from specialist content (`vibe_trio`, `destination_gallery`, `content_added`). These arrays may contain items with missing/empty `image_url` (especially for dynamically generated hiking activities).

**Pattern:** Always filter before mapping:
```tsx
// WRONG: May render <Image src="" /> which causes browser errors
{section.destination_gallery.map((img) => <Image src={img.image_url} />)}

// CORRECT: Filter out empty URLs first
{section.destination_gallery
  .filter((img) => img.image_url)
  .map((img) => <Image src={img.image_url} alt={img.label || 'Image'} />)}
```

**Guarded locations in StrategyHero.tsx:**
- `destination_gallery.map()` - Filter before render
- `vibe_trio` section - Guard primary image + filter secondary images
- `content_added` items - Conditional render with `{item.image_url && ...}`

---

## I.A.2 Heart Preference System (Consolidated)

Users can heart tiles to signal preference to the AI. Hearts are preference signals, not cart additions.

### States
| State | Visual | Interaction |
|-------|--------|-------------|
| Unpressed | Outline heart, zinc-400 | Click to prefer |
| Pressed | Filled heart, emerald-500, scale animation | Click to unprefer |

### Selection Behavior by Tile Type

| Type | Behavior | Rationale |
|------|----------|-----------|
| **Hotels** | Single-select (radio) | Hotel is "your base" - one preferred stay per trip |
| **Activities** | Multi-select (checkbox) | Activities distributed across days |

**Hotel single-select:** When hearting a new hotel, any previously hearted hotel is automatically cleared. This prevents confusion where users heart 3 hotels expecting all to be used, but builder can only assign one.

**Implementation:** `toggleTilePreference()` checks tile type. If hotel/stay/accommodation, clears existing hotel preferences before adding new one.

### Data Flow
1. User hearts tiles via `SuggestionCard` or `TileCard`
2. All heart clicks route through `documentStore.toggleTilePreference()`
3. For hotels: clears existing hotel preference (single-select enforcement)
4. `preferredTileIds` stored in Zustand + persisted to DB via PATCH `/api/document` (with 409 conflict retry)
5. On page refresh, `fetchDocument()` hydrates `preferredTileIds` from DB
6. On auto-regen trigger (1.5s debounced after preference change via `startPreferenceAutoRegen`):
   - Preferences read via `useDocumentStore.getState().preferredTileIds` (live read)
   - Categorized by tile type and sent to backend
7. Backend applies 1.5x score multiplier to preferred tiles in `ItineraryBuilder`
8. Timeline shows attribution badge: "You preferred this" on check-in blocks

**Important (Stale Closure Fix):** `proceedWithItineraryGeneration` reads ALL document state via `useDocumentStore.getState()` at call time, not from React state captured at render time. This ensures:
- Latest hearted tiles are sent (`preferredTileIds`)
- Latest strategy sections are sent (`strategy_sections`) - critical for multi-specialist flows

**Multi-Specialist Auto-Expand Flow:**
When user adds a second specialist (e.g., "hiking too" after diving):
1. ChatPanel receives response with new hiking section
2. `setFromPlanResponse` merges sections (2 → 3)
3. ChatPanel detects structural change, calls `onAutoExpandItinerary`
4. `proceedWithItineraryGeneration` reads FRESH state via `getState()` (not stale closure)
5. Backend receives all 3 sections including hiking's `content_added`

Without `getState()`, the callback would capture pre-merge state and send only 2 sections.

### Itinerary Generation with Preferences

When auto-regen triggers (preference change or chat-based regeneration), preferences flow to backend:

```
┌─────────────────────────────────────────────────────────────────┐
│  Frontend: useItineraryGenerationController.ts                  │
│            (proceedWithItineraryGeneration)                     │
│                                                                  │
│  1. Read preferredTileIds via useDocumentStore.getState()        │
│     (LIVE READ - avoids stale closure from React render)         │
│  2. Categorize by tile.type:                                     │
│     - hotel/stay/accommodation → preferred_hotel_ids (max 1)     │
│     - activity/experience/tour → preferred_activity_ids (multi)  │
│  3. POST /api/expand-itinerary { preferences: {...} }            │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  Backend: ItineraryBuilder (services/itinerary_builder.py)       │
│                                                                  │
│  1. PreferenceOverrideInput receives hotel/activity IDs          │
│  2. Phase 5.25: Preferred activities fill free days:             │
│     - Collects tiles from preferred_activity_ids (user order)    │
│     - Finds free days (days with only FreeDay placeholder)       │
│     - Replaces placeholders with preferred activity blocks       │
│     - Drops extras if more activities than free days             │
│  3. Hotel selection: preferred tiles get 1.5x score boost        │
│  4. Sort by: is_preferred (desc), adjusted_score (desc)          │
│  5. Set preference_status on DayBlockOutput:                     │
│     - "user_preferred": Selected tile was hearted                │
│     - "ai_selected": AI chose without user preference            │
│     - "ai_override": AI chose different tile over user's pick    │
│  6. alternative_tile_id: User's preferred tile if AI overrode    │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  Frontend: TimelineThread.tsx → LogisticsBlock                   │
│                                                                  │
│  Renders PreferenceAttributionBadge based on block data:         │
│  - user_preferred → "💚 You preferred this"                      │
│  - ai_override → "AI selected" + "Switch" button                 │
│  - ai_selected → No badge (default)                              │
└─────────────────────────────────────────────────────────────────┘
```

### Tile Type Matching

Frontend categorizes tiles by type (case-insensitive):

| Category | Matched Types |
|----------|---------------|
| Hotels | `hotel`, `stay`, `accommodation` |
| Activities | `activity`, `experience`, `tour`, `attraction`, `excursion`, `ticket`, `event` |
| Flights | `flight` (not currently used in preferences) |

### Regeneration Flow (Three-Tier Policy)

Regeneration uses a **three-tier approach** based on input method:

```
CHAT MESSAGES:
User: "from rome" → Auto-regenerate + auto-expand itinerary (no FAB needed)
User: "add hiking" → Auto-regenerate + auto-expand itinerary (no FAB needed)

PREFERENCE CHANGES (hearts):
User hearts a tile → 1.5s debounced auto-regen → Itinerary updates

CHIP/SETTINGS CHANGES:
User edits date chip → GENERATE_PLAN_TRIGGER sent → Full regeneration
```

**Why this policy:**
- **Chat = Auto**: User typed natural language → intent is fully expressed → immediate action
- **Hearts = Auto (debounced 1.5s)**: Batches rapid heart toggles into a single expand call. Deferred during active streaming to prevent noise during plan generation.
- **Chips/Settings = Auto via chat trigger**: Changes sent as GENERATE_PLAN_TRIGGER message for full regeneration

#### Chat Auto-Regeneration

**Trigger:** User sends chat message that updates plan content (origin, destination, activities, dates)

**Components:**
- `ChatPanel` - Detects plan updates in SSE `onComplete` handler
- `onAutoExpandItinerary` callback - Triggers itinerary expansion when chat updates plan with existing itinerary

**Flow:**
1. User sends chat message (e.g., "from rome", "add hiking")
2. Backend agent loop runs (the model calls `extract_trip_fields`, then specialist/tile tools as needed, then streams the terminal response)
3. Turn completes → SSE `onComplete` handler checks:
   - `hasItinerary = (day_cards?.length ?? 0) > 0`
   - `structureChanged = strategy_sections topics differ (not just tiles added)`
4. If both true → auto-call `proceedWithItineraryGeneration()` after 100ms
5. Itinerary regenerates with new tiles/strategy (selective strategy computation)
6. No user action required - plan reacts to conversation

**Strategy Hash Check (Cascade Prevention):**
```typescript
// Only auto-expand if structure actually changed (not just tiles added)
const prevStrategyTopics = prevDoc?.strategy_sections?.map(s => s.topic) ?? [];
const newStrategyTopics = doc.strategy_sections?.map(s => s.topic) ?? [];
const preHash = JSON.stringify(prevStrategyTopics.sort());
const postHash = JSON.stringify(newStrategyTopics.sort());
const structureChanged = preHash !== postHash;

if (hasItinerary && structureChanged && !isSilentPlanGeneration) {
  onAutoExpandItinerary?.();  // Structural change - needs itinerary rebuild
} else if (hasItinerary && !structureChanged) {
  // Additive-only change (e.g., flights) - skip expand, itinerary intact
}
```

> **Note:** `isSilentPlanGeneration` is a local variable inside `ChatPanel.tsx` (derived from `isGenerateTrigger`), not a store field.

**Agent-Built Itinerary Skip:** When the turn response includes `day_cards` (the itinerary was built inside the agent turn — either via the model's `build_itinerary` tool call or `agent_runner`'s deterministic auto-build, see `_should_autobuild`), the SSE `onComplete` handler skips `expand-itinerary` entirely (`expandPath = 'GRAPH_BUILT'`). The itinerary is already up-to-date — a redundant expand would waste a round-trip. `structuralRebuildTriggered` is still set to `true` so downstream logic (e.g., scroll-to-itinerary) fires correctly.

**Example flows:**
- "from rome" with existing plan → Flights added (tiles only) → **No auto-expand** → Itinerary preserved
- "add hiking" with itinerary → Hiking specialist runs (structure change) → Itinerary auto-updates
- "thanks" acknowledgment → No plan changes → No auto-expand
- "tell me about diving" with dates → Graph builds itinerary → `GRAPH_BUILT` skip → No expand needed

**Origin-only handling:**
- "from rome" without destination → Sets origin, prompts for destination (`extract_trip_fields`)
- "from rome" with destination → Sets origin, then triggers immediate tile search (`search_tiles`)

**FAB Suppression for Chat Changes:**
Chat-originated changes update `trip_inputs` (e.g., origin from "from rome"). The chat auto-regeneration flow handles these changes automatically without manual user intervention.

**trip_inputs in POST body:**
Every chat message includes `trip_inputs` in the POST body (not just generate triggers). The backend
hydrates session state from the document before graph execution, using the document as SSoT for
user-owned settings (`activity_settings`, `hotel_settings`, `flight_settings`, `transport_settings`,
`booking_types`). Session values cannot override these fields.
See `plan_graph_analysis.md` > Settings Ownership & Document Merge.

**Files:**
- `ChatPanel.tsx` - Calls `onAutoExpandItinerary` in SSE `onComplete` when structure changes; always sends `trip_inputs` in POST
- `useItineraryGenerationController.ts` - Handles regeneration via `proceedWithItineraryGeneration` (re-exported by `useItineraryGeneration.ts` and consumed from `useLandingPlanState.ts`)

#### Chip/Settings Regeneration

**Trigger:** User changes destination, dates, origin, or settings via chip bar or settings sheets

**Flow:**
1. User modifies trip inputs (e.g., changes destination chip from "Bali" to "Paris")
2. `updateTripInputs()` writes to store **synchronously** (tiles NOT cleared - old content stays visible)
3. GENERATE_PLAN_TRIGGER sent via chat system
4. Backend forces tile cache clear → fetches fresh tiles
5. New itinerary generates automatically

**Origin atomic update rule:** Origin edits in `LandingSheets` and `useTripInputsEditor` patch
`origin` and `booking_types.flights='suggested'` in the same commit when flights were previously
`off`, preventing split writes and one-render stale booking state.

**Preference sheet auto-regeneration:**
When the user saves activity or hotel preferences via the Activities/Stays sheets while a plan is active
(S2/S3), the sheet save handler:
1. Calls `documentStore.updateTripInputs()` immediately (bypasses 300ms debounce)
2. Sends `GENERATE_PLAN_TRIGGER` to re-run the graph with updated preferences
3. Backend detects constraint hash change → specialists re-run with new settings

**Activities sheet explicit-clear behavior:** `LandingSheets` and `ChatModuleSheets` track a local `activityUserSaved` flag and pass it as `hasExplicitSettings` into `ActivitiesSheet`. This prevents day-card inference from re-populating categories after the user explicitly saved an empty category list.

**S3 early regeneration overlay:** when Activities sheets save into an active itinerary state (`S3_ITINERARY_READY` / `S3_EDITING`), both desktop and chat surfaces set `documentStore.isRegenerating=true` immediately before the `commitTripInputs()` round-trip. This is visual feedback only; the actual hard mutex remains `expandInProgress`.

**State tracking:**
- `documentStore.updateTripInputs()` - Sync local state write (before validation)
- `documentStore.commitTripInputs()` - Async API persist (after validation)

**Controlled input pattern:**
```typescript
// In useTripInputsEditor.ts - SYNC write before ASYNC validation
const handleAddDestination = async (destination: string) => {
  prevDestinationRef.current = tripInputs.destination; // Capture for race-safe revert
  documentStore.updateTripInputs({ destination });     // SYNC: Store updates immediately

  // Async validation follows...
  const result = await validateTripInput('destination', destination);
  if (!result.is_valid) {
    documentStore.updateTripInputs({ destination: prevDestinationRef.current }); // Revert
  }
};
```

#### Preference Auto-Regeneration (Hearts)

**Trigger:** User hearts/unhearts a tile after itinerary exists

**Component:** `startPreferenceAutoRegen` / `triggerRegeneration` from `hooks/usePreferenceAutoRegen.ts` - Module-level subscription managing auto-regeneration for preference changes (not a React hook)

**Flow:**
1. User hearts a hotel → preference change detected
2. **1.5s debounce** to batch rapid heart toggles into a single expand call
3. Auto-calls `/api/expand-itinerary` with current preferences
4. Itinerary rebuilds with new preference weighting
5. `markPreferencesAsApplied()` updates last-generated state

**Cascade Prevention Guards:**
```typescript
// Guard 1: expandInProgress is the hard mutex (in triggerRegeneration)
if (useDocumentStore.getState().expandInProgress) return;

// isRegenerating may already be true as early visual feedback from sheet-save/SSE.
// Do NOT use it as a blocker for triggerRegeneration.

// Guard 2: Skip in subscription if expand or streaming in progress (queued, not dropped)
if (expandInProgress || isStreamingResponse) {
  pendingRegen = true;
  lastPrefsRef = new Set(prefs);
  return;  // Queue for later, flush when mutex releases
}
```

**State tracking:**
- `documentStore.preferredTileIds` - Current preferences (Set)
- `documentStore.lastGeneratedPreferences` - Preferences at last generation
- `documentStore.expandInProgress` - Hard mutex flag for expand-itinerary calls
- `documentStore.isRegenerating` - Shared overlay/display flag; may be set early by sheet saves or SSE node-status callbacks before rebuild work actually starts
- `markPreferencesAsApplied()` - Snapshots current preferences after regeneration (compares `preferredTileIds` vs `lastGeneratedPreferences` inline to detect changes)

**Visual feedback:**
- Activities-sheet saves in S3 show the regeneration overlay immediately, before the preference PATCH resolves, so the timeline never appears frozen during commit latency.
- SSE rebuild nodes (`generate_plan`, `update_plan`, `create_itinerary`) can also set the overlay when day cards already exist; `useChatSse` and `useChatSend` clear it on complete, error, stale stream, or abort.
- Specialist section shows "Updating itinerary..." overlay during regeneration (`isRegenUpdating`)
- Timeline dims with black overlay + "Updating with N preferences..." spinner
- Attribution badges show preference vs AI selection

**Selective regeneration (backend):**
- @see `docs/plan_graph_analysis.md` Section 11 - Selective Regeneration
- Preference-only changes use `BUILDER` strategy (~100ms)
- Trip input changes trigger appropriate strategy based on changed fields

**Backend cache invalidation:**
Current backend does **not** clear `state.tiles` inside `extract_trip_fields` itself. On generate/question turns,
`main.py` sanitizes request-side category merge behavior (`_sanitize_trip_inputs_for_category_merge`), while
state clearing happens during middleware merge (`_merge_trip_fields`) when destination changes
(`tiles`, `strategy_sections`, `day_cards`, and constraints are reset together).

**Note:** Frontend does NOT clear tiles on destination change. Old tiles stay visible until backend returns new data after Refresh.

**Attribution badges:** After regeneration, `PreferenceAttributionBadge` shows:
- "You preferred this" - user-preferred hotel was selected
- "AI selected" + "Switch" button - AI overrode user preference

### Specialist Filtering (Domain Mode)

When Tier 1 domain specialists (diving, hiking, skiing, cycling, surfing, climbing, sailing, wildlife_safari) are active, BookingSection filters activities to show only specialist-relevant items. Hotels always pass through. Tier 2 categories (yoga, cooking, nightlife, temples, beach, shopping, photography, wellness, culture, music, wine, food) do not trigger specialists — they bias tile selection via tag-based filtering in LogisticsNode.

**Keyword Mappings (from `frontend/lib/specialists.ts` registry):**
```typescript
// filterKeywords per specialist in SPECIALIST_REGISTRY:
diving:          ['div', 'scuba', 'snorkel', 'reef', 'underwater', 'wreck'],
hiking:          ['hik', 'trek', 'trail', 'climb', 'summit', 'mountain'],
skiing:          ['ski', 'snow', 'slope', 'piste', 'powder', 'chairlift', 'gondola'],
cycling:         ['cycl', 'bike', 'biking', 'pedal', 'mtb'],
surfing:         ['surf', 'wave', 'board', 'swell'],
climbing:        ['climb', 'boulder', 'crag', 'via ferrata', 'rope', 'ascent'],
sailing:         ['sail', 'yacht', 'charter', 'catamaran', 'marina', 'regatta'],
wildlife_safari: ['safari', 'wildlife', 'game drive', 'big five', 'savanna'],
```

**Filtering Logic:**
```typescript
function activityMatchesSpecialist(tile: Tile, specialistTypes: string[]): boolean {
  if (isHotelType(tile.type)) return true;  // Hotels always show
  if (!specialistTypes || specialistTypes.length === 0) return true;  // No filter

  const category = (tile.category || tile.type || '').toLowerCase();
  const title = (tile.title || '').toLowerCase();

  for (const specialist of specialistTypes) {
    if (specialist === 'local_expert') return true;  // General: allow all
    const keywords = SPECIALIST_KEYWORDS[specialist] || [];
    for (const keyword of keywords) {
      if (category.includes(keyword) || title.includes(keyword)) return true;
    }
  }
  return false;
}
```

**Where Applied:**
- **Backend (Two-Tier Suppression):** `LogisticsNode` applies tier-aware filtering when niche specialists (all 8 Tier 1 specialists) are active. Pure Tier 1 → suppress all generic tiles. Mixed Tier 1+2 → keep only tiles matching Tier 2 selections. `local_expert` does NOT trigger suppression.
- `BookingSection.tsx`: Filters activity tiles in `tilesByCategory` when specialists are active

**Backend Two-Tier Suppression Logic:**
```python
# logistics_node.py - after fetching activities
if settings.booking_types.activities == "off":
    state.tiles["activities"] = []
    # clear browseable/tier2 metadata, return early

NICHE_SPECIALISTS = TIER1_SPECIALISTS  # 8 specialists from specialist_registry.py
TIER1_CATEGORIES = TIER1_SPECIALISTS

executed = state.metadata.get("executed_strategy_topics", [])
has_niche_specialist = any(t in NICHE_SPECIALISTS for t in executed)

if has_niche_specialist:
    selected_cats = set(trip_inputs.get("activity_settings", {}).get("categories", []))
    tier2_cats = selected_cats - TIER1_CATEGORIES

    if not tier2_cats:
        state.tiles["activities"] = []  # Pure Tier 1: specialists own the activity layer
    else:
        # Mixed: keep ONLY tiles matching Tier 2 selections (via tags or keyword fallback)
        matching = [t for t in activity_dicts if _tile_matches_categories(t, tier2_cats)]
        state.tiles["activities"] = matching
```

**Rationale:** When a diving specialist is active, showing "Night market" or "Sunrise ridge" creates expectation mismatch. But if a user selects both diving AND cooking, cooking tiles (matched via `tags` on curated tiles or keyword fallback on mock tiles) should survive — only the Tier 1 categories are handled by specialists. This two-tier approach gives specialists ownership of their domain while preserving Tier 2 experience tiles.

### Infeasible Specialist Card Filtering

**Problem:** When a specialist (e.g., skiing) runs but the destination is infeasible or has caveats (e.g., Bali), showing the card in the strategy surface creates confusion.

**Solution:** Filter specialist sections by `feasibility_status` in `useStrategyStageOrchestration`. Sections with `feasibility_status === 'infeasible'` or `feasibility_status === 'caveat'` are excluded from `fullModeSections`. Toast notifications are shown for newly infeasible sections.

**Location:** `useStrategyStageOrchestration.ts` — `specialistData` memo

```typescript
// Filter out infeasible/caveat specialist sections
const fullModeSections = (viewModel.strategy_sections ?? []).filter(
  s => s.feasibility_status !== 'infeasible' && s.feasibility_status !== 'caveat'
);
```

**Why feasibility filtering?** Backend constraint evaluation determines feasibility at the domain level (e.g., skiing infeasible in Bali), making `feasibility_status` the authoritative signal. The frontend surfaces the reason via toast so users understand why a specialist was dropped.

### Inline Constraints Display (S3 View)

Activity and logistics blocks display inline constraint badges to show constraint-first optimization. This makes the builder's constraint enforcement visible to users.

**Visual Example:**
```
┌─────────────────────────────────────┐
│ 🌊 EVENING  diving  ⏱ 3.0h          │
│ Crystal Bay                         │
│                                     │
│ ┌─────────────────────────────────┐ │
│ │ ℹ️ Dive Safety                  │ │
│ │    Scheduled with appropriate   │ │
│ │    surface intervals            │ │
│ └─────────────────────────────────┘ │
│                                     │
│ ┌─────────────────────────────────┐ │
│ │ ⚠️ 24h No-Fly Buffer            │ │
│ │    Day 8 departure requires     │ │
│ │    finishing diving by 2pm      │ │
│ └─────────────────────────────────┘ │
│                                     │
│ ❤️ You preferred this               │
└─────────────────────────────────────┘
```

**Constraint Structure:**
```typescript
interface ActiveConstraint {
  id: string;                           // Unique ID (e.g., "no_fly_buffer")
  severity: 'warning' | 'info' | 'success' | 'blocking';
  icon: string;                         // Emoji (⚠️, ℹ️, ✅, 🚫)
  title: string;                        // Short label
  description: string;                  // Context-specific explanation
}
```

**Severity Colors:**
| Severity | Use Case | Light BG | Border |
|----------|----------|----------|--------|
| `warning` | Safety constraints (24h no-fly) | `bg-amber-50` | `border-amber-200` |
| `info` | Informational (surface interval) | `bg-blue-50` | `border-blue-200` |
| `success` | Positive (constraint satisfied) | `bg-emerald-50` | `border-emerald-200` |
| `blocking` | Hard constraint violation | `bg-red-50` | `border-red-200` |

**Implementation:** `frontend/components/plan/timeline/blocks/ActivityMiniCard.tsx`, `LogisticsBlock.tsx`

See `docs/design-system.md` Section 4 "Inline Constraint Badge Colors" for full Tailwind classes.

### Trip DNA Bar (S3 View)

In S3 (itinerary ready), full specialist strategy cards are replaced with a compact "Trip DNA" bar. This bar is **constraint-forward** — it shows the actual constraints that shaped the plan, not just specialist names.

**Visual Layout:**
```
┌──────────────────────────────────────────────────────────────────────────────┐
│ Trip DNA:  [⚠️ 24H No-fly Buffer]  [🕐 Morning only]  [🛡️ Reef protection]   │
└──────────────────────────────────────────────────────────────────────────────┘
```

**Behavior:**
- **S2 (strategy ready):** Full specialist cards with expandable constraint lists
- **S3 (itinerary ready):** Compact DNA bar showing **constraint pills** (not specialist pills)
- Pills show: icon + constraint short label (full text, horizontally scrollable)
- Hover: Native `title` tooltip shows full constraint text
- **Filtering:** Only shows constraints from **niche specialists** (all 8 Tier 1 specialists via `NICHE_SPECIALIST_IDS`) — filters out Local Expert tips to focus on hard constraints. Additionally filters by severity: only shows constraints with no severity set (legacy), `blocking`, or `strong` — excludes `soft`/`info` severity constraints.

**Icon Selection (Priority-Based):**

Icons are selected based on constraint priority/severity, not validation state:

| Priority | Keywords | Icon | Color | Example |
|----------|----------|------|-------|---------|
| **Blocking** | `no_fly`, `safety`, `altitude`, `diving`, `decompression`, `flight` | `AlertTriangle` | Red | 24h no-fly buffer |
| **Strong** | `morning`, `footwear`, `gear`, `timing`, `equipment`, `certification` | `Clock` | Amber | Morning departures only |
| **Soft** | (default) | `Shield` | Zinc | Reef-safe sunscreen |

> **Note:** Backend emits `constraints_validated` and `constraint_violations` which enable three-state styling: violated (amber ring via `violatedRules` Set), validated (emerald via `validatedRules` Set), and unchecked (priority-based color). The code currently implements all three states. When validation data is not populated, the pill falls through to the priority-based color (blocking=red, strong=amber, soft=zinc).

**Implementation:**
```tsx
// NICHE_SPECIALIST_IDS from lib/specialists.ts — all 8 Tier 1 specialists (registry-driven)
import { NICHE_SPECIALIST_IDS } from '@/lib/specialists';

const engineConstraints = fullModeSections
  .filter((s) => NICHE_SPECIALIST_IDS.includes(s.specialist_type || ''))
  .flatMap((s) => s.constraints_applied || []);

// Short label extraction: label > shortConstraintLabel(rule) > 'Constraint'
const getShortLabel = (c) =>
  c.label ||
  (c.rule ? getShortConstraintLabel(c.rule) : null) ||
  'Constraint';

{engineConstraints.length > 0 && (
  <div className="flex items-start gap-2 my-4 mx-4 p-3 rounded-lg bg-zinc-100 dark:bg-zinc-950 border border-zinc-300 dark:border-zinc-700">
    <span className="text-xs uppercase font-semibold text-zinc-500 dark:text-zinc-400 shrink-0">
      Trip DNA:
    </span>
    <div className="flex flex-wrap gap-2">
      {engineConstraints.map((c, i) => {
        const style = getPillStyle(c); // Three-state: violated (amber ring) > validated (emerald) > unchecked (priority-based)
        return (
          <span
            key={`${c.rule}-${i}`}
            title={c.reason || c.rule?.replace(/_/g, ' ')}
            className={cn(
              'inline-flex items-center gap-2 px-3.5 py-1.5 rounded-full border text-xs font-medium whitespace-nowrap',
              style.pillClass
            )}
          >
            <style.Icon className="w-4 h-4 shrink-0" />
            <span>{getShortLabel(c)}</span>
          </span>
        );
      })}
    </div>
    {/* Toggle for specialist cards when itinerary exists */}
    {hasItineraryContent && (
      <button onClick={() => setShowConstraints(!showConstraints)}>
        {showConstraints ? 'Hide' : 'Details'}
      </button>
    )}
  </div>
)}
```

**File:** `frontend/components/plan/PlanFullDensityView.tsx`

### Architecture (Consolidated)
```
┌─────────────────────────────────────────────────────────────────┐
│  UI Components                                                   │
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐               │
│  │SuggestionCard│ │  TileCard   │ │ TileCard    │               │
│  └──────┬──────┘ └──────┬──────┘ └──────┬──────┘               │
│         │               │               │                        │
│         ▼               ▼               ▼                        │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  documentStore (state/documentStore.ts)                   │   │
│  │  - preferredTileIds: Set<string>                          │   │
│  │  - lastGeneratedPreferences: Set<string> (for regen)      │   │
│  │  - toggleTilePreference() → optimistic update + PATCH     │   │
│  │    (hotel single-select enforced: clears existing hotels)  │   │
│  │  - markPreferencesAsApplied() → syncs sets                │   │
│  │  - fetchDocument() → hydrates preferredTileIds from DB    │   │
│  │  - 409 conflict handling: refetches version + retries once │   │
│  └──────────────────────────────────────────────────────────┘   │
│                           │                                      │
└───────────────────────────┼──────────────────────────────────────┘
                            ▼
┌───────────────────────────────────────────────────────────────────┐
│  Backend: PATCH /api/document                                      │
│  - preferred_tile_ids persisted to plan_documents table            │
│  - Survives page refresh, session timeout (24h)                    │
└───────────────────────────────────────────────────────────────────┘
```

### Storage
- **Zustand state:** `documentStore.preferredTileIds: Set<string>` - current preferences
- **Zustand state:** `documentStore.lastGeneratedPreferences: Set<string>` - preferences at last generation
- **Database:** `plan_documents.document.preferred_tile_ids[]` (survives refresh)

---

## I.B Booking Suggestions Pattern

### In PLANNING Mode: Suggestions with Reasoning
```
┌──────────────────────────────────────────────────┐
│ 🏨 ACCOMMODATION                                 │
│ ┌──────────────────────────────────────────┐    │
│ │ Suggested: Hotel Tugu Bali               │    │
│ │ $75/night • 4.8★ • Seminyak Beach        │    │
│ │                                          │    │
│ │ 💡 Why this hotel:                       │    │
│ │ • 5min walk to beach                     │    │
│ │ • Close to dive shop (Day 2 departure)   │    │
│ │ • In budget ($50-80 range)               │    │
│ │                                          │    │
│ │ [Change Hotel] [Save to Trip]            │    │
│ └──────────────────────────────────────────┘    │
└──────────────────────────────────────────────────┘
```

### In BOOKING Mode: Current Behavior (Single Deeplink)
> **Note:** Partner price comparison rows below are a roadmap mock, not current implementation.
```
┌──────────────────────────────────────────────────┐
│ 🏨 Accommodation • Day 1-7                       │
├──────────────────────────────────────────────────┤
│ Hotel Tugu Bali • Seminyak • Apr 15-20 (5 nights)│
│                                                  │
│ ┌──────────────────────────────────────────┐    │
│ │ 🏢 Booking.com      $365  [Book Now →]   │    │
│ │ Free cancellation until Apr 1            │    │
│ └──────────────────────────────────────────┘    │
│                                                  │
│ ┌──────────────────────────────────────────┐    │
│ │ 🏢 Expedia          $375  [Book Now →]   │    │
│ │ Earn 750 points                          │    │
│ └──────────────────────────────────────────┘    │
└──────────────────────────────────────────────────┘
```

---

## I.C Plan State Density (Progressive Density)

Backend rendering is single-source-of-truth via `plan_view_state` and a small compatibility shim:

### Plan State Progression

| Backend state | Data State | UI Shows | Chat Status Header |
|---|---|---|---|
| `S0_BOOTSTRAP` | Core fields incomplete (destination + dates not both set) | Hero image, empty timeline | "Your trip is taking shape" · REFINE PLAN |
| `S2_STRATEGY_READY` | Strategy exists, no itinerary yet | Strategy cards, bridge timeline | "Your trip is taking shape" · REFINE PLAN |
| `S2_BLOCKED` | Legacy/frontend-compatible alias for a blocked strategy-ready bridge state | Bridge view with blocker messaging when manually normalized | "Your trip is taking shape" · REFINE PLAN |
| `S3_ITINERARY_READY` | Builder success, no conflicts | Full schedule + tile-rich plan | "Itinerary complete" · READY |
| `S3_EDITING` | Builder success with constraints | Draft schedule + constraint banner | "Your trip is taking shape" · REFINE PLAN |
| `S3_PARTIAL_CONFLICT` | Partial schedule from failed build | Partial draft schedule + conflict notes | "Your trip is taking shape" · REFINE PLAN |
| `S3_BLOCKED` | Builder failed, no valid day cards | Strategy preview + actionable suggestions | "Your trip is taking shape" · REFINE PLAN |

> **Note:** `S0_EMPTY` and `S1_DESTINATION_SET` are frontend-only guard states (`S0_EMPTY` for reset intent; `S1_DESTINATION_SET` for fallback ordering). `S1_FRAMING` and `S2_BLOCKED` remain in shared type unions for compatibility, but the current coordinator path emits `S0_BOOTSTRAP`, `S2_STRATEGY_READY`, and `S3_*` states.

---

## II. The "Single Renderer" Pattern

We do not swap `SetupView` for `PlanView`. We use a single **`StrategyStageRenderer`** that adapts based on data density (`computeDataDensity()`).

```tsx
// StrategyStageRenderer delegates to density-specific views via useStrategyStageOrchestration:
function StrategyStageRenderer({ state, viewModel, ... }) {
  const o = useStrategyStageOrchestration({ state, viewModel, ... });
  const hasPartialItinerary = (o.effectiveDayCards?.length ?? 0) > 0;

  // shouldUsePlanMirrorLoader() gate:
  //   - Returns false when hasPartialItinerary (progressive content should render)
  //   - Returns true when isShowingMirrorLoader || density === 'ghost'
  //   - Returns true when generation active with empty/bridge density
  if (shouldUsePlanMirrorLoader({ ... })) return <PlanMirrorLoader tripDuration={tripDuration} />;
  if (immediateDensity === 'empty' || immediateDensity === 'bridge') return null;
  // default: full density
  return <PlanFullDensityView ... timelineVariant={computeTimelineVariant(state, hasPartialItinerary)} />;
}
```

> **Note:** The component file is `StrategyStageRenderer.tsx`, not `UnifiedStageRenderer`. There is no `UnifiedStageRenderer` component in the codebase. Rendering is now a two-branch flow: loading states use `PlanMirrorLoader`, while non-loading states go into `PlanFullDensityView`. The dedicated density components `PlanGhostDensityView` and `PlanBridgeDensityView` are no longer in use.

---

## III. Backend State Logic (`coordinator.py` + `/api/expand-itinerary`)

The backend dictates Planning Phase based on data richness. For `/api/graph_plan/stream`, coordinator `_build_envelope()` computes `plan_view_state`. For `/api/expand-itinerary`, NDJSON events emit Stage 3 states from builder outcomes.

**Primary envelope base logic (evaluated in order):**

| Logic Check (evaluated in order) | State Output | Explanation |
| --- | --- | --- |
| Missing core fields (destination + start_date + end_date), or `date_flex=true` — **but** has destination + strategy_sections | `S2_STRATEGY_READY` | **Bridge State.** Destination exists with specialist content but dates are missing or flexible. Strategy cards visible. |
| Missing core fields, no destination or no strategy_sections | `S0_BOOTSTRAP` | **Blank slate.** Setup checklist until core trip fields are set. |
| Builder ran (turn_meta.builder_result present) | `S3_*` (via `_compute_coordinator_s3_state`) | **Itinerary built.** Sub-state depends on builder success/conflicts. |
| `day_cards` exist (from prior turn) | `S3_*` (via `_compute_coordinator_s3_state`) | **Itinerary persisted.** Re-evaluates S3 sub-state from existing day_cards. |
| `strategy_sections` exist | `S2_STRATEGY_READY` | **Bridge State.** Strategy cards + ghost timeline. |
| `tiles` exist (hotels or activities non-empty) | `S2_STRATEGY_READY` | **Full logistics mode.** Tiles loaded (may have been auto-built into day_cards above). |
| Fallthrough (core fields set, no tiles/specialist yet) | `S0_BOOTSTRAP` | **Awaiting data.** Frontend stays closed to avoid showing an empty plan panel. |

> **Note:** Coordinator `_build_envelope()` computes base states (`S0_BOOTSTRAP`, `S2_STRATEGY_READY`) inline. Stage-3 states are resolved by `_compute_coordinator_s3_state()` from builder metadata in `turn_meta`: `S3_ITINERARY_READY` (success/no conflicts), `S3_EDITING` (success/with conflicts), `S3_PARTIAL_CONFLICT` (failure/partial with day_cards), `S3_BLOCKED` (failure/no cards). NDJSON itinerary endpoints emit the same Stage 3 variants.

### Itinerary Generation State Transition

When the user has dates and tiles, clicking "BUILD ITINERARY" triggers the `ItineraryBuilder` service:

```
S2_STRATEGY_READY → BUILD ITINERARY → S3_* outcomes
                            │
                  ItineraryBuilder.build()
                            │
                ┌───────────┴─────────────────────────────────┐
                ├─ Success/no conflicts → S3_ITINERARY_READY
                ├─ Success/with conflicts → S3_EDITING
                ├─ Partial schedule only → S3_PARTIAL_CONFLICT
                └─ No schedule → S3_BLOCKED
```

**Conflict Resolution Flow (Chat-Driven):**

When the builder fails (trip too short or route/constraint issues), coordinator records state in `turn_meta.builder_result` (and validation payloads when present) and reflects it in the same-turn complete envelope (`ack_status`, `ack_updates`, partial `itinerary_day_cards` where possible). Suggestion chips are generated from current state via `chip_generator._generate_chips_from_state()`. Partial `day_cards` (what CAN fit) can render at `S3_PARTIAL_CONFLICT` immediately.

**Invariant:** User is NEVER left with silently dropped activities. All conflicts are surfaced via suggestion chips with actionable resolutions.

---

## III.A Local Expert Trip-DNA Anchor

The Local Expert "Trip Overview" card is the right-panel anchor card carrying destination context (vibe, local tips) and trip framing (destination, dates, travelers).

### Rationale

The Local Expert "Trip Overview" card serves as the right-panel anchor:
1. Destination context (vibe, local tips)
2. Trip framing (destination, dates, travelers)
3. Stable scan order before niche specialist detail

### Agent behavior

- The model calls the `get_local_intel` tool (wrapping the `local_expert` node) to produce the `local_expert` section.
- `middleware._merge_local_intel()` emits that section as a single-element `strategy_sections` delta.
- The `_merge_strategy_sections` reducer (`state/agent_state.py`) upserts by `specialist_type` (right wins) and preserves existing list order — so `local_expert` is not re-sorted to the front.

> **Note (verified):** The legacy "local_expert is inserted at index 0 / first strategy card" invariant is **not enforced on the agent path**. The reducer `_merge_strategy_sections` (`state/agent_state.py`) dedups by `specialist_type` (right wins) preserving insertion order; section order therefore follows tool-call order, which the model decides. `section_builder.sort_sections_anchor_first()` (anchor-first sort) still exists but is reached **only** via `upsert_section()`, whose only callers are the legacy GraphState node helpers `_merge_specialist_into_state` (`vertical_specialist.py`) and `_run_local_expert` (`local_expert.py`) — both off the agent loop (the `get_specialist_advice`/`get_local_intel` tools call `generate_specialist_output_llm()`/`build_local_expert_section` and merge via the reducer; `build_itinerary` appends its placeholder `local_expert` section to a local list, not via `upsert_section`). No frontend reordering exists either (`useStrategyStageOrchestration` / `PlanFullDensityView` do not unshift/sort `local_expert` to first).

### Invariants

1. Strategy updates never duplicate `local_expert` sections (upsert by `specialist_type`).

---

## III.B Map-Itinerary Two-Way Synchronization

The map and itinerary timeline are connected with two-way synchronization for seamless navigation.

### Overview

| Direction | Trigger | Action |
|-----------|---------|--------|
| **Timeline → Map** | User scrolls itinerary | Map highlights current day, flies to location |
| **Map → Timeline** | User clicks map pin | Timeline scrolls to that activity, highlights card |

### Map Content by Mode

| Mode | Map Shows | Interactive Features |
|------|-----------|---------------------|
| **Early PLANNING** (no dates) | POI pins from specialist recommendations | Click pin → expand specialist card |
| **Late PLANNING** (with dates) | Day-by-day route + hotels + activities | Click pin → scroll to timeline, day filter |
| **BOOKING** | Confirmed bookings only | Click pin → show booking details |

### Visual Synchronization

#### Scroll-Driven Map Updates
```
User scrolls to Day 2
↓
Map highlights: Day 2 pins (others dimmed)
↓
Map flies to: Day 2 center location
↓
Route line: Day 1→2 segment highlighted
```

#### Click-Driven Timeline Navigation
```
User clicks Day 4 pin on map
↓
Timeline auto-scrolls to Day 4 (scrollIntoView smooth, block: center)
↓
scrollTargetDayNumber cleared immediately after scroll
```

> **Note:** The store defines `highlightedCardId` for a planned 2s highlight ring effect, but no component currently reads or renders it. Pin clicks trigger scroll only.

### Route Visualization

**GeoJSON LineString** connects day locations:
- Color: `#10b981` (emerald-500)
- Style: Dashed (`line-dasharray: [2, 1]`)
- Opacity: 0.7
- Day-based coloring (optional)

### Layer Filters

> **Deleted:** `MapLayerFilter.tsx` has been removed. Layer filtering is now handled internally by `InteractiveMap.tsx` via the `visibleLayers` prop (a `Set<string>` passed by the parent). No standalone filter UI component exists currently.

### Implementation

**State Management — `useMapSync` (Zustand store):**

`frontend/hooks/useMapSync.ts` is a lightweight Zustand store (not persisted) that coordinates the two-way sync:

| Field | Type | Purpose |
|-------|------|---------|
| `visibleDayNumber` | `number \| null` | Set by `TimelineThread` scroll observer; consumed by `InteractiveMap` as `highlightedDay` |
| `scrollTargetDayNumber` | `number \| null` | Set by `InteractiveMap` on pin click or by `useChatSse` after hidden-plan itinerary updates; consumed by `TimelineThread` to trigger scroll |
| `scrollTargetBlockId` | `string \| null` | Set alongside `scrollTargetDayNumber` by `requestScrollTo()`; identifies the specific block to highlight |
| `highlightedCardId` | `string \| null` | Defined in the store but not currently consumed by any component. Intended for a 2s highlight ring after pin-click scroll, but not wired up. |

**Scroll → Map (`TimelineThread.tsx`):**
- `dayHeaderRefs` (Map of dayNumber → HTMLElement) stores refs on each day header button.
- An `IntersectionObserver` on the `scrollContainerRef` watches day header elements with a 150ms debounce.
- On intersection: `useMapSync.getState().setVisibleDayNumber(day)`.
- `PlanFullDensityView` reads `visibleDayNumber` and passes it as `highlightedDay` to `InteractiveMap`.

**Map → Timeline (`InteractiveMap.tsx` + `PlanFullDensityView.tsx`):**
- `onMarkerClick` callback: `handleMarkerClick(itemId)` in `PlanFullDensityView` finds the matching `MapPOI` by `itemId`, reads `poi.dayNumber`, then calls `useMapSync.getState().requestScrollTo(dayNumber, itemId)`.
- `useChatSse.ts` also reuses `requestScrollTo(dayNumber)` after a `complete` event when the user is still on Chat and an existing itinerary changed. It diffs previous vs incoming `day_cards`, picks the first changed day, applies the plan result, then queues the shared timeline scroll target.
- `TimelineThread` (via `useTimelineThreadMapSync`) listens to `scrollTargetDayNumber` → `scrollIntoView({ behavior: 'smooth', block: 'center' })` on the corresponding day header, then clears the target. The planned 2s highlight ring (`ring-2 ring-emerald-500`) is not yet wired up.
- `MapPOI.dayNumber` (added to `ghost-timeline-adapter.ts`) is populated by `extractPOIsFromDayCards` from `dayCard.day_number`.

**Pin Icon Lookup — `PIN_CONFIG` (`map-marker-config.tsx`):**

Replaced fragile string-matching `getMarkerIcon()`/`getMarkerColor()` helpers with an exact-key `PIN_CONFIG: Record<string, PinConfig>` lookup object (`getPinConfig(type, source?)` function). Colors are hex strings (not Tailwind classes) to survive JIT tree-shaking. Covers all 8 Tier 1 specialist types, Tier 2 categories, and logistics types. `DEFAULT_PIN` fallback is `MapPin` with zinc-400 (`#a1a1aa`). Browse-sourced items use a distinct `BROWSE_PIN` (Search icon, amber `#f59e0b`).

**Route overlay status:**

There is no route-geometry utility module in the current frontend. `InteractiveMap` still supports an optional `routeGeoJson` prop, but current plan views do not generate or pass route geometry.

**Fly-to on day highlight (`InteractiveMap.tsx`):**
- When `highlightedDay` changes, the map computes the average `lat`/`lng` of all pins for that day and calls `map.flyTo()` with `zoom: 9` (single pin) or `zoom: 7` (multiple pins), `duration: 1200`.
- `isUserInteractingRef` tracks active pan/zoom via `onMoveStart`/`onMoveEnd` handlers — fly-to is suppressed while the user is manually navigating.

**Marker click debounce (`InteractiveMap.tsx`):**
- `lastClickRef` enforces a 500ms debounce between marker clicks to prevent rapid-fire scroll requests.

**Mapbox runtime error suppression (`mapbox-error-handler.ts`):**
- Mapbox-specific message patterns are suppressed directly (`errorCb`, `sku_token`, `mapbox-gl`).
- Generic null-reference errors are suppressed only when the `Error.stack` includes Mapbox sources, so non-Mapbox app bugs still surface.

**Telemetry opt-out (`InteractiveMap.tsx`):**
- Mapbox metrics collection is disabled via the `performanceMetricsCollection={false}` prop on the `<Map>` component to avoid blocked telemetry requests in ad-blocking browsers.

**ResizeObserver (`InteractiveMap.tsx`):**
- A `ResizeObserver` on the map container calls `map.resize()` to tell Mapbox to remeasure when the container size changes (e.g., panel open/close transitions).

`InteractiveMap.tsx` validates all coordinates internally via `normalizeMapCoordinates()` (rejects non-finite, out-of-range, or missing values). `ghost-timeline-adapter.ts` applies equivalent validation via `_normalizeMapCoordinates()` when extracting POIs from strategy sections.

**Fallback center (`InteractiveMap.tsx`):**
- If no valid destination center or map items are available, map initial view falls back to world view (`lat=0`, `lng=0`, `zoom=2`).

**Data Sources:**
- `DayCard.blocks[].coordinates` - Itinerary locations (with `dayNumber` propagated to `MapPOI`)
- `StrategySection.content_added[].coordinates` - Specialist POIs (fallback when no itinerary)

### Invariants

1. **Map updates on scroll** - `IntersectionObserver` in `TimelineThread` tracks visible day headers → `useMapSync.setVisibleDayNumber()`
2. **Click triggers scroll** - `onMarkerClick` → `useMapSync.requestScrollTo()` → `TimelineThread` scrollIntoView (highlight ring defined in store but not currently rendered)
3. **Route overlay optional** - `InteractiveMap` only renders route layer when `routeGeoJson` is provided; current plan flow omits it
4. **Fly-to suppressed during user interaction** - `isUserInteractingRef` prevents jarring fly-to during manual pan/zoom
5. **Coordinate validation** - Both `InteractiveMap` and `ghost-timeline-adapter` validate coordinates before rendering (finite, |lat|<=90, |lng|<=180)
6. **PIN_CONFIG exact-key lookup** - No string-contains matching; unknown types fall back to `DEFAULT_PIN` (`MapPin`, zinc-400)
7. **Marker click debounce** - 500ms via `lastClickRef` prevents rapid-fire scroll requests
8. **ResizeObserver** - Map container resize triggers `map.resize()` so Mapbox remeasures on panel transitions

---

## III.C Constraint Badge Deduplication

> **Status: NOT IMPLEMENTED.** The cross-block constraint dedup described below (`_seenConstraintIds`, `getConstraintDisplayModes`, `constraintDisplayModes` prop) does not exist in the current codebase. `ActivityMiniCard` renders all `block.active_constraints` with full badges — no dedup logic is applied. The planned design is retained here for reference.

When the same constraint appears on multiple blocks in the same day (e.g., the 24h no-fly rule referenced by both an activity and a logistics block), showing the full badge on every block creates visual noise.

**Planned design:**

- `_seenConstraintIds: Set<string>` maintained per render pass across all blocks in all days.
- `getConstraintDisplayModes(block): Map<string, 'full' | 'icon'>` iterates `block.active_constraints`:
  - First occurrence of a `constraint.id` or blocking severity → mode `'full'` (full badge with label).
  - Subsequent occurrences → mode `'icon'` (icon pill only, label in Tooltip on hover).
  - The `Set` accumulates across days so cross-day dedup also applies.
- The resulting `Map` would be passed to `ActivityMiniCard` as the `constraintDisplayModes` prop.

---

## III.D Compact Day Variant

> **Status: NOT IMPLEMENTED.** The compact day variant described below (`getDayVariant`, `variant='compact'` on `ActivityMiniCard`) does not exist in the current codebase. All days render in the default full-card layout. The planned design is retained here for reference.

Days with a single short activity would render in a compact horizontal layout to reduce scroll length.

**Planned design — `getDayVariant(card: DayCard): 'compact' | 'default'`:**

Would return `'compact'` when:
- `card.blocks.length === 1`
- The single block is not a skeleton, buffer, arrival, or departure block
- The block has no booked tile (unbooked compact slot)

Otherwise returns `'default'` (the existing full-card layout).

---

## III.E Depth-1 Undo Stack

Drag-and-drop mutations on the itinerary are reversible via a depth-1 undo stack.

**State (`documentStore.ts`):**
- `UndoEntry`: `{ type: 'drag_move' | 'remove_block' | 'fill_day', label: string, previousDayCards: DayCard[], previousVersion: number, timestamp: number }`.
- `setUndoEntry(entry)` / `clearUndoEntry()` manage the single slot.
- `executeUndo()` calls `POST /api/document/restore-snapshot` with `previousDayCards` and `previousVersion`, then clears the entry.

**Flow:**
1. `ItineraryDndWrapper.tsx` captures `previousDayCards` + `previousVersion` snapshot before applying a drag arrangement.
2. After successful apply, calls `setUndoEntry(...)` and `showMutationToast(label, toast)` to display a toast with an Undo CTA.
3. `useUndoStack.ts` (mounted in `ItineraryDndWrapper`) auto-expires the `undoEntry` after 8s via `useEffect` + `setTimeout`.
4. If user clicks Undo within 8s, `executeUndo()` restores the previous day_cards via the backend endpoint.

**Invariant:** Only one undo entry exists at a time (depth-1). A new mutation overwrites the previous entry.

---

## IV. Visual Islands Protocol (Chat)

All complex responses must follow the "Islands" format to ensure scannability.

**Structure:**

1. **The Hook:** Emotional acknowledgement ("**Dubai** sounds incredible!").
2. **The Logic:** (Optional) Warnings/Constraints anchored by Emojis.
   * "⚠️ **Safety:** 24h No-Fly Buffer applied."
   * "ℹ️ **Weather:** It is Ramadan, so hours differ."
3. **The Action:** Clear next step ("Shall we look at **Hotels**?").

**Formatting:**

* Use Double Line Breaks between islands.
* **Bold** key variables (Dates, Places, Prices).
* Use standard Markdown.

---

## IV.A Exploration Mode Response Format

When users ask generic travel questions (before planning), the system enters **Exploration Mode**. These responses have a distinct format optimized for information delivery and natural conversation flow.

### Response Structure

**Exploration responses use 3 parts:**

1. **The Answer:** Comprehensive, factual answer (4-5 sentences with bullet points)
2. **The Ending:** Progressive nudge based on question count
3. **Suggestion Chips:** Contextual follow-up questions + "Plan trip" CTA

### Markdown Formatting Rules

| Element | Format | Example |
|---------|--------|---------|
| **Section headers** | `**Bold:**` | `**Best time to visit:**` |
| **Key facts** | Bullet points with `-` | `- Great for: Beach lovers, Divers` |
| **Destination name** | Capitalized | `Bali`, not `bali` |
| **Numbers/prices** | Inline with units | `$50-80/day`, `7-10 days` |
| **Lists in context** | Comma-separated | `Apr, May, Jun, Jul, Aug, Sep` |
| **Paragraph breaks** | Double newline `\n\n` | Between answer sections |

### Question-Based Endings

| Question # | Ending Style | Example |
|-----------|--------------|---------|
| 1st | Open exploration | "What else would you like to know?" |
| 2nd | Soft nudge | "When are you thinking of going?" |
| 3rd+ | Planning invitation | "I can help plan your trip when you're ready. Just let me know your dates!" |

### Example Exploration Response

```markdown
Bali is fantastic for couples! Island of the Gods where ancient traditions meet surf culture.

**What makes it special:**

- Great for: Beach lovers, Divers, Culture seekers
- The vibe is relaxed and romantic
- Most couples spend 7-10 days to experience everything

What else would you like to know?
```

### Suggestion Chips (Registry-Driven)

Suggestion chips are generated by `chip_generator._generate_chips_from_state()` during coordinator complete-envelope assembly. The function derives up to 3 template-based chips from current state fields — no LLM call needed.

**Chip Structure:** Each chip is a `SuggestionChip` (see `schemas.py`) with fields:
`message`, `action_type` (`"send_message"` | `"open_pill"` | `"trigger_action"`),
`action_target` (pill/trigger target, e.g. `"dates"`, `"activities"`, `"budget"`, `"confirm_reset"`),
`chip_type` (`"cta"` | `"follow_up"` | `"setting"`),
`category`, and `icon` (Lucide name). Chips are stored in `persistent_meta.suggestion_chips`
and passed through coordinator `_build_envelope()` into the complete SSE event.

**Actionability Invariant:** Every chip must either open a pill (`open_pill`), trigger a setting (`trigger_action`), or send a plan-modifying command (`send_message` with `chip_type` of `"cta"` or `"follow_up"`). No passive/informational chips — questions, "show me", and "surprise me" are prohibited.

| State | Example Chips | Action Types |
|-------|---------------|--------------|
| No destination | "Pick a destination", "Choose dates first", "Set travelers" | `open_pill` → destination, dates, travelers |
| Has destination, no dates | "{Mon DD} - {Mon DD}", "{Mon DD} - {Mon DD}", "Set dates" | `send_message` (CTA), `open_pill` → dates |
| Dest + dates, no categories | "Choose activities", "Add departure city" / "Set budget", "Set travelers" | `open_pill` → activities, origin/budget, travelers |
| Has tiles, no itinerary | "Build my itinerary", "Browse activities", "Refine {cat} plan" / "Get local tips" | `send_message` (CTA/follow_up), `open_pill` → activities |
| Post-itinerary (day_cards exist) | "Browse activities", "Add departure city" (no origin) / "Change hotel" (has origin), "Set budget" (no budget) | `open_pill` → activities, origin/stays, budget |
| Dest + categories | "Refine {category} plan", "Get local tips" | `send_message` (CTA) |
| Blocking violation | Violation-specific fix from `suggested_action`, then type-specific pill: "Adjust dates" / "Adjust budget" / "Change activities" | `send_message` (CTA), `open_pill` → dates/budget/activities |

**S2+ Plan Progression:** Once dates are set, chips shift from exploration pill-openers to plan-refinement actions.
`_generate_chips_from_state()` in `chip_generator.py` checks which trip fields are missing and generates
corresponding chips. As preferences are set, those chips are replaced with next-step suggestions.

### Soft Transition → Planning (Priority Rule)

**Input parameters have highest priority.** When users provide actionable input (dates OR activities), the system routes directly to PLANNING mode instead of asking more exploration questions:

| User Input | Action |
|------------|--------|
| `"bali Mar 1-9"` (destination + dates) | → Routes to PLANNING with `local_expert` |
| `"bali diving"` (destination + activity) | → Routes to PLANNING with `diving` specialist |
| `"bali"` (destination only) | → Exploration response (needs more info) |

**Flow:**
```
soft_transition + (dates OR activities) → PLANNING mode immediately
soft_transition + neither → Exploration response (ask for dates/activities)
```

This ensures users who provide concrete parameters aren't blocked by exploration questions.

### Planning Readiness Detection

Exploration mode exits when user provides actionable parameters:

| Signal Type | Examples | Action |
|-------------|----------|--------|
| **Dates provided** | "bali Mar 1-9", "next week" | → Enter PLANNING mode (local_expert) |
| **Activity provided** | "bali diving", "hiking trip" | → Enter PLANNING mode (specialist) |
| **Both provided** | "diving in February", "hiking next month" | → Enter PLANNING mode (specialist) |
| **Explicit signal** | "plan my trip", "help me plan" | → Enter PLANNING mode |

### Implementation Reference

**Backend:** The assistant response is the terminal (no-tool-call) model turn of the `create_agent` loop — there is no separate `conversationalist` step. `router_extraction.classify_change()` (invoked via the `extract_trip_fields` tool) handles intent + change parsing.
**State tracking:** `turn_meta["short_circuit_type"]` is derived from routing context before envelope assembly.

### UI Components for Exploration → Planning Transition

> **Note:** `ExplorationProgress` and `ReadyToPlanBanner` have been deleted from the codebase. The exploration-to-planning transition is now handled entirely by suggestion chips generated by `chip_generator.py` (see chip state table above). Suggestion chips shift from exploration questions to plan-refinement actions once dates are set.

---

## V. Critical Data Serialization

To support the Map and Cards in "Bridge Mode," the backend MUST serialize this data even if `tiles` are empty:

1. **Coordinates:** `[lng, lat]` for every Activity.
2. **Images:** High-res URLs for every Strategy Card.
3. **Content Blocks:** The "Day 1", "Day 2" sequence for the Sample Timeline.

---

## V.A Trip Validation (Inline in NextStepBar)

Date/destination validation is computed inline — there is no `useTripValidation` hook.

### Overview

`NextStepBar` reads `tripInputs` directly from `useDocumentStore` and computes date display and validation inline. There is no shared validation hook; each consumer that needs trip input state reads from the store directly.

### Validation States

| Reason Code | Condition | User Message | CTA Action |
|-------------|-----------|--------------|------------|
| `no_destination` | Destination missing | "Add a destination to start planning" | "Add Destination" |
| `no_dates` | No start date | "Add dates to build your itinerary" | "Add Dates" |
| `no_return_date` | Start date only | "Add a return date to continue" | "Add Return Date" |
| `same_day` | Start == End | "Trip must be at least 2 days" | "Adjust Dates" |
| `too_short` | Duration < 1 day | "Trip must be at least 2 days" | "Adjust Dates" |
| `valid` | All requirements met | (empty) | "Build Itinerary" |

### Usage Pattern

```typescript
// NextStepBar reads tripInputs directly from the store
const { tripInputs } = useDocumentStore();

// Date display and validation are computed inline
// No shared hook — components read from useDocumentStore as needed
```

### Consumers

| Component | Usage |
|-----------|-------|
| `NextStepBar` | Reads `tripInputs` from `useDocumentStore`, computes date display/validation inline |
| `ChatInput` | Build button gating (reads store directly) |

---

## VI. State Transitions & Input Requirements

The UI must enforce strict data requirements before promoting the user to the next phase.

### Transition Table

| Transition | From | To | Required Data | User Action | System Response |
| --- | --- | --- | --- | --- | --- |
| **Inspiration** | Setup (S0) | Bridge (S2) | `destination` | Mention "Diving in Dubai" | **Show Strategy Cards** (Bridge Mode) |
| **Feasibility** | Bridge (S2) | Plan (S2) | `start_date` | Set dates via chip/chat | **1. Switch to Plan Tab**<br>**2. AUTO-TRIGGER TILE SEARCH**<br>**3. Show Loading Skeleton** |
| **Commitment** | Plan (S2) | Book (S3) | `tiles` selected | Click **"Finalize & Book"** | **Lock Plan & Show Checkout** |
| **Payment** | Book (S3) | Receipt | `guest_names`, `payment` | Click **"Confirm & Pay"** | **Process Payment** |

### Gate Types

- **SOFT Gate (Automatic):** Transition happens automatically when data conditions are met. User doesn't need to click anything—just provide the data (via chat or chips).
- **HARD Gate (Explicit Click):** Transition requires an explicit button click. Even if all data is present, the user must consciously confirm intent.

### The "Dates = Search" Rule

**CRITICAL:** When the user provides valid dates, the system MUST automatically trigger the Logistics search (flights/hotels). Do NOT wait for a "Build" button click.

**Rationale:** "Tomorrow" is specific intent. Users expect to see availability immediately. The "Finalize & Book" button is for **committing** to a plan, not for **seeing** one.

**Flow:**
```
User: "from Rome to Dubai tomorrow for two days"
  ↓
Backend extracts: start_date=2024-02-01, trip_duration=2
  ↓
Backend AUTO-ROUTES to `search_tiles` tool (no click needed)
  ↓
Frontend shows: Loading Skeleton ("Searching live availability...")
  ↓
Tiles arrive → Plan populates immediately
```

### Implementation

**Frontend (`useViewNavigation.ts`):**
```typescript
// SOFT GATE: Dates unlock Plan automatically
const canViewPlan = hasDates || isGenerating;

// HARD GATE: Explicit click required for Book
const canViewBook = isPlanFinalized && (hasTiles || inBookableState);
```

**Backend (agent tool loop):**
```python
# The create_agent loop has no deterministic step schedule — the model selects
# tools each round. With destination + dates present it calls search_tiles
# (and get_specialist_advice for Tier 1 topics); agent_runner._should_autobuild
# then builds the itinerary after the loop when destination+dates+options are
# ready. The conversational response is the terminal (no-tool-call) model turn.
```

### Critical Invariants

1. **Dates = Search Trigger:** Providing valid dates MUST automatically trigger `search_tiles`. Do NOT wait for a secondary click.
2. **No Empty Plan:** If Plan tab is active but tiles are loading, display **Timeline Skeleton** + "Searching live availability..." state. Never show whitespace.
3. **Finalize ≠ Search:** The "Finalize & Book" button is exclusively for **Transitioning to Checkout**. It is NOT for triggering search.

### Mirror Loader Strategy

**Rule:** "Never auto-switch to an empty container."

When the system auto-transitions to Plan tab (after dates are set), it MUST show loading feedback in **BOTH** panels:

| Panel | Loader Type | Purpose |
| --- | --- | --- |
| **Chat (Left)** | Status Pill / Living Void | "I heard you" - Agent is working |
| **Plan (Right)** | Timeline Skeleton | "Results landing HERE" - Data anticipation |

**Implementation:**
```tsx
// In StrategyStageRenderer - show skeleton when generating with dates
// (computed in displayLogic memo: isShowingMirrorLoader = generating && hasDates && !hasTiles)
if (isShowingMirrorLoader) {
  return (
    <div className="p-4 space-y-6">
      <div className="flex items-center gap-2">
        <div className="w-2 h-2 bg-emerald-500 rounded-full animate-pulse" />
        <span className="text-sm text-muted-foreground">
          Searching live availability...
        </span>
      </div>
      <TimelineSkeleton />
      <p className="text-xs text-muted-foreground text-center">
        Finding flights and hotels for your {tripDuration}-day trip
      </p>
    </div>
  );
}
```

**Why:** Auto-switching forces user's eyes to the Plan tab. If they see empty space, they think it's broken. The skeleton masks API latency (2-3s) and makes the app feel instant.

**`TimelineSkeleton` Progressive Preview:** The `<TimelineSkeleton />` component reads `_specialistPreview` and `strategy_sections` from `documentStore` to display real specialist preview content in skeleton cards instead of pure shimmer placeholders. When preview data is available:
- Cards show specialist type labels, activity titles, and descriptions
- Cards use a solid border style (emerald accent) instead of dashed shimmer borders
- Bottom text says "Loading live availability around specialist picks" instead of generic "Creating your personalized itinerary"

---

## VII. Data Density Levels

The renderer uses data density to determine what to show:

| Density | Condition | Renders |
| --- | --- | --- |
| `empty` | P0 + no specialist content | Topo background + "Build Your Itinerary" tagline (PlanHeader, desktop only) |
| `ghost` | Specialist content + dates + no tiles (P0 or P1) | `PlanMirrorLoader` skeleton surface while logistics catches up |
| `bridge` | Specialist content + no dates + no tiles (P0 or P1) | Landing layout (`SplitLayoutView` treats bridge as landing; plan panel hidden) |
| `full` | P1+ with tiles, or P3 | Strategy cards + real timeline + tiles + full map |

> **Note:** When dates are present but tiles have not arrived yet, density resolves to `ghost` (not `bridge`) so `PlanMirrorLoader` remains visible while logistics catches up.

> **Generation override:** `computeLayoutDataDensity()` in `useLandingPlanState.ts` returns `'ghost'` density when `generation.active === true`, regardless of other conditions. This ensures skeleton/loading states show during active generation.

**Map POI extraction:** Only runs when `dayCardsFingerprint` changes (content-based proxy encoding `cards.length` plus per-card `day_number:blocks.length:block.id,...`). `strategyStagePoi.ts` now keeps a stable pre-stream snapshot while a graph turn is in flight, so partial `day_cards` updates do not thrash map bounds/POI extraction; once streaming ends, the latest fingerprinted cards become the next stable snapshot. Map uses `fitBounds` with responsive padding (desktop: 60px, mobile: 30px) and `maxZoom: 14` / `minZoom: 5`.

---

## VII.A. Session Persistence (Refresh Survival)

The planning session survives page refreshes via database persistence. All session state is stored in the `plan_documents.document` JSON column.

### Database Schema

**Table:** `plan_documents`
- `id`: Primary key
- `session_id`: Foreign key to sessions table
- `document`: JSONB column containing `PlanDocumentData`
- `version`: Optimistic locking counter (enforced on PATCH - returns 409 if stale)
- `updated_by`: "user" | "planner"
- `updated_at`: Timestamp

**Concurrency Protection:**
- Frontend uses Promise-based mutex to prevent concurrent PATCH requests
- Backend validates `patch.version == doc.version` before applying changes
- On 409 Conflict, frontend refetches document and retries once

### Full Document Structure (`PlanDocumentData`)

```
plan_documents.document (JSONB)
├── trip_context_id: int                    # FK to trip contexts
├── trip_inputs: DocumentTripInputs         # ✅ PERSISTED
│   ├── destination: string                 # "Bali"
│   ├── origin: string                      # "New York"
│   ├── start_date: date                    # "2026-02-16"
│   ├── end_date: date                      # "2026-02-19"
│   ├── adults: int                         # 2
│   ├── children: int                       # 0
│   ├── requires_assistance: bool           # false
│   ├── budget: float                       # 5000
│   ├── currency: string                    # "USD"
│   ├── hotel_settings: HotelSettings       # { min_stars, amenities, ... }
│   └── activity_settings: ActivitySettings # { categories, activities_per_day }
├── branches: List[DocumentBranch]          # ✅ PERSISTED
│   └── [branch]
│       ├── id: string                      # UUID
│       ├── destination, origin, dates...   # Mirrors trip_inputs
│       ├── is_primary: bool
│       ├── tiles: { stays[], flights[], activities[] }
│       └── selections: { stay_id, flight_ids[], activity_ids[] }
├── tiles: Dict[str, Tile]                  # ✅ PERSISTED
│   └── [tile_id]: Tile
│       ├── id, type, title, description
│       ├── price, currency
│       ├── image_url, provider
│       └── metadata (varies by type)
│
│ ─── ViewModel Fields (Refresh Survival) ─────────────────
│
├── plan_view_state: PlanViewState          # ✅ PERSISTED
│   # S0_BOOTSTRAP | S2_STRATEGY_READY | S2_BLOCKED | S3_* (S3_ITINERARY_READY / EDITING / PARTIAL_CONFLICT / BLOCKED)
├── strategy_sections: List[StrategySection] # ✅ PERSISTED
│   └── [section]
│       ├── specialist_type: string         # "diving" | "hiking" | "general"
│       ├── title: string                   # "Diving Expert"
│       ├── bullets: List[str]              # Advice points
│       ├── local_expert_tips: List[str]
│       └── constraints: Dict               # Safety rules
├── executed_strategy_topics: List[str]     # ✅ PERSISTED ["diving", "hiking"]
├── pending_strategy_topics: List[str]      # ✅ PERSISTED ["skiing"]
├── day_cards: List[DayCard]                # ✅ PERSISTED
│   └── [day_card]
│       ├── day_number: int
│       ├── date: string
│       ├── label: string                   # "Arrival + light activity"
│       ├── subtitle?: string              # Client-side only, computed from blocks
│       └── blocks: List[Block]             # Activities, logistics
├── can_expand_to_itinerary: bool           # ✅ PERSISTED
│
│ ─── Constraint Validation State ───────────────────────────
│
├── constraints_validated: List[Dict]       # ❌ Response only (Trip DNA badges, empty on refresh)
│   └── [{ rule, specialist, satisfied_at }]  # Constraints that passed
├── constraint_violations: List[Dict]       # ❌ Response only (Trip DNA badges, empty on refresh)
│   └── [{ rule, specialist, category, severity, message }]  # Failed constraints
│
│ ─── Response-Only Fields (NOT Persisted) ────────────────
│
├── assistant_message: string               # ❌ Response only
├── suggested_responses: List[str]          # ❌ Response only
├── plan_state: PlanState                   # ❌ Computed at response time
├── ui_phase: UIPhase                       # ❌ Computed at response time
├── destination_card: DestinationCard       # ❌ Computed (Unsplash fetch)
├── booking_status: BookingStatus           # ❌ Computed from tiles
├── readiness: List[ReadinessItem]          # ❌ Computed from trip_inputs
└── resolver: ResolverState                 # ❌ Streaming only
```

### Persistence Matrix

| Field | Stored in DB | Survives Refresh | Source |
|-------|--------------|------------------|--------|
| `trip_inputs` | ✅ Yes | ✅ Yes | User input / LLM extraction |
| `branches` | ✅ Yes | ✅ Yes | Graph plan generation |
| `tiles` | ✅ Yes | ✅ Yes | Curated/Google Places/Mock providers |
| `strategy_sections` | ✅ Yes | ✅ Yes | Specialist nodes |
| `day_cards` | ✅ Yes | ✅ Yes | Itinerary builder |
| `plan_view_state` | ✅ Yes | ✅ Yes | State machine (backend-authoritative on hydration) |
| `executed_strategy_topics` | ✅ Yes | ✅ Yes | Graph execution |
| `can_expand_to_itinerary` | ✅ Yes | ✅ Yes | Stage 3 gate |
| `preferred_tile_ids` | ✅ Yes | ✅ Yes | Heart actions (PATCH /api/document) |
| `constraints_validated` | ❌ No | ❌ No | ConstraintGuard node |
| `constraint_violations` | ❌ No | ❌ No | ConstraintGuard node |
| `assistant_message` | ❌ No | ❌ No | LLM response |
| `destination_card` | ❌ No | ❌ No | Unsplash API |
| `booking_status` | ❌ No | ❌ No | Computed from tiles |

### Frontend Hydration Flow

```
Page Load
    │
    ▼
useSessionHydration() runs
    │
    ├── (no client-side expiry) Always proceed to fetchDocument()
    │   └── Backend cookie (Max-Age 14d) + persisted doc are the sole
    │       validity source; a stale localStorage timestamp must never
    │       blank out a still-valid backend document (the 200/204 decides)
    │
    ├── Fire-and-forget `useUserStore.fetchUser()`
    │   └── Auth chrome can render current user/recent trips without waiting for document hydration
    │
    ├── GET /api/document
    │   └── Returns full PlanDocumentData from DB
    │
    ├── fetchDocument() hydration
    │   └── Backend document is stored directly (no frontend view-state promotion)
    │
    ├── documentStore.set({ document })
    │   └── Zustand store populated with backend `plan_view_state`
    │
    └── StrategyStageRenderer reads from store
        ├── viewModel = useDocumentStore(s => s.document)
        ├── tiles = useDocumentStore(s => s.document?.tiles)
        └── Renders: Specialists → Tiles → Timeline
```

**`itinerary_day_cards` mapping:** The backend `_build_envelope()` returns `itinerary_day_cards` when the itinerary was built inside the agent turn (model `build_itinerary` tool call or `agent_runner` auto-build). `setFromPlanResponse()` maps this to `day_cards` for frontend consumption (`rawDoc.itinerary_day_cards` -> `rawDoc.day_cards`).

### Backend Persistence Points

| Endpoint | Function | When Called | Fields Persisted |
|----------|----------|-------------|------------------|
| `POST /api/graph_plan/stream` | `apply_planner_update()` | Streaming chat | All |
| `POST /api/expand-itinerary` | `apply_planner_update()` | Build Itinerary CTA | `day_cards`, `plan_view_state` |
| `PATCH /api/document` | `apply_user_patch()` | Tile selection, settings sheets | `branches.selections`, `trip_inputs.*_settings` |

### Implementation Files

| Layer | File | Function |
|-------|------|----------|
| Schema | `backend/app/schemas.py` | `PlanDocumentData` class |
| Persistence | `backend/app/crud_document.py` | `apply_planner_update()` |
| Endpoints | `backend/app/main.py` | Graph plan SSE stream |
| Hydration | `frontend/components/layout/hooks/useSessionHydration.ts` | Session restore hook |
| Store | `frontend/state/documentStore.ts` | `fetchDocument()` |

### Session Lifecycle

```
1. First Visit
   └── No session cookie → Backend creates session + empty document

2. Chat Interaction
   └── graph_plan/stream → apply_planner_update() → DB write

3. Build Itinerary
   └── expand-itinerary → apply_planner_update(day_cards) → DB write

4. Page Refresh
   └── GET /api/document → Full document from DB → Hydrate UI

5. Session Validity (backend-decided)
   └── Hydration never expires a session client-side; `GET /api/document` returns 204/null when the backend session/doc is gone → tryAutoResume (authenticated users resume most recent saved trip) → fresh start fallback

6. No Document (authenticated)
   └── GET /api/document returns null → tryAutoResume fetches trips, resumes most recent → fresh start fallback

7. Shared Public Page
   └── `/trip/[slug]` server-prefetches the public snapshot via `fetchSharedTripServer()` in `sharedTripApi.ts`; `SharedTripView` reuses that payload client-side and only creates a session when the user chooses "Copy This Trip"
```

**Authenticated refresh path:** when `/api/auth/me` resolves with a user, desktop/mobile headers may then issue `GET /api/trips` to populate recent-trip resume menus. This account bootstrap is additive; it never mutates the hydrated `PlanDocumentData`.

---

## VIII. Component Responsibilities

| Component | Responsibility |
| --- | --- |
| `StrategyStageRenderer` | Data density computation, conditional rendering, single renderer for all modes. Heavy computation and effects are delegated to `useStrategyStageOrchestration`. |
| `useStrategyStageOrchestration` | Hook centralising all heavy computation, state, and effects for `StrategyStageRenderer` (keeps renderer under ~300 lines). Owns `DataDensity` computation, map POI extraction, infeasibility toast notifications, scroll-position freeze/restore on itinerary arrival, booking drawer state, and the mobile plan scroll container. On mobile it feeds `scrollContainerRef` into `useScrollCollapse`, syncs `uiStore.mobileHeaderCondensed`, and listens for the `nomadic:mobile-plan-scroll-top` event used by the condensed header affordance. |
| `PlanFullDensityView` | Full-density itinerary orchestrator. Receives all props from `StrategyStageRenderer`, delegates heavy derivation (map POIs/center, venue-link actions, travel-intel polling, panel-toggle state) to `usePlanFullDensityData`, then composes the extracted desktop/mobile subsections (`PlanFullDensityDesktopMap`, `PlanFullDensityTilesSection`, `PlanFullDensityTravelAdvice`, `PlanFullDensityMobileSummary`) around the existing timeline and booking summary surfaces. |
| `FullDensityTimeline` | Composes the mobile inline map and `PlanTimelineSection` for `PlanFullDensityView`. Mobile map renders when `!isDesktop && hasItineraryContent && (fullModePOIs.length > 0 \|\| hasDestinationCenter)` at `h-[clamp(220px,35vh,300px)]`. |
| `BookingSummary` | Supplemental booking-links panel rendered by `PlanFullDensityView` under the timeline. Shows deduped booking links for stays (`tiles`), booked flights (`day_cards`), and mapped itinerary activities in Stage 3 states, and rebuilds hotel search URLs from current trip inputs when richer Booking.com / Google Travel search params are available. |
| `PlanDensityViews` | Density loading view (`PlanMirrorLoader`) only. |
| `shouldUsePlanMirrorLoader()` | Gate function in `StrategyStageRenderer.tsx` for showing the mirror/loading state. Returns `false` when `hasPartialItinerary` is true (progressive content should render instead of loader). Also returns `false` when `hasTiles && isPlanGenerationActive` so arriving hotel/activity tiles break the loader early and show real content. Returns `true` when `isShowingMirrorLoader \|\| density === 'ghost'` or when generation is active with `empty`/`bridge` density. |
| `PlanTimelineSection` | Timeline section for full-density view -- handles DnD wrapping (`ItineraryDndWrapper`, `DraggableBlock`, `DroppableDay`), skeleton loading, regeneration overlay, and wraps `TimelineThread` in `ErrorBoundary` for crash isolation. Shows `TimelineSkeleton` during expanding itinerary OR when itinerary content is expected but `day_cards` haven't arrived yet (`showSkeletonTimeline`). Shows a loading overlay on existing real itinerary during regeneration (`showLoadingOverlay`). Disables timeline interactions (`pointer-events-none`, `opacity-25`) during regen OR itinerary expansion. |
| `TimelineBlockList` | Renders one day’s timeline blocks, splitting compact vs full variants and injecting optional DnD/slot render-props for drag/drop and free-day actions. Free-day buffer exclusion chips are derived only from that day’s `bufferBlocks` plus the selected categories (via `useTimelineBufferLogic`), so unrelated `day_cards` mutations do not fan out rerenders across the full timeline subtree. |
| `TimelineDayCard` | Composes a day header, day-level constraints, and block list for one day in both compact and full timeline modes. |
| `MapMarkerItem` | Memoized per-marker renderer used by `InteractiveMap` for POI pins; applies type-based icon/color config, active/hover state visuals, and day-based dimming while limiting marker rerender churn. |
| `useBookingDrawerState` | Hook managing booking drawer open/close state and the fill-day API call triggered when a tile is added to a specific day via the drawer. Extracted from `StrategyStageRenderer`. |
| `PlanHeader` | Sticky header: topo background (no destination), hero image + TripSummaryPills (with destination), collapsed bar (mobile scroll) |
| `TripSummaryPills` | Unified command bar for trip inputs plus module actions: destination/origin/dates/travelers/budget/activities as core segments, plus inline toggle segments for Flights, Stays, and Destination Travel Advice (with pending/badge state). The Activities segment always routes to `ActivitiesSheet`, preserving the original selector flow for category/day/pace preferences instead of participating in the booking-panel toggle contract. On mobile overflow, the actual horizontal scroller owns a right-edge fade that disappears once the reel reaches scroll end. Scheduled activity-day counts and category inference are shared with `ActivitiesSheet` via `tripSummaryUtils.ts`, so inferred counts stay consistent between the command bar and the sheet defaults. |
| `NomadicLanding` | Thin route shell that renders `NomadicLandingContent`; controller/state orchestration now lives in `useNomadicLandingController`, which wires split-layout props, shared sheet props, and render surfaces before handing off to extracted content components. |
| `LandingHeaderContent` | Extracted desktop header content for `SplitLayoutView`. Reads `panelToggleStore` for the Flights/Stays/Travel Advice toggle state that powers the header `TripSummaryPills`, leaves `Activities` on the `openSheet('activities')` selector path, computes live tile counts, and renders the auth popover / recent-trip resume actions without burdening `NomadicLanding`. |
| `MobileModeHeader` | Mobile top bar for the planning route. Owns only the fixed positioning, condensed-summary bar, status pill, and menu trigger; overflow menu contents are rendered by `MobileHeaderMenu`, while action side effects (new trip, share, PDF, login/logout) come from `useHeaderActions`. Entering Plan still blurs the active input/textarea to dismiss the keyboard, and signed-out users still get a reset action inside the overflow menu. |
| `MobileHeaderMenu` | Extracted popover body for the mobile overflow menu. Renders account chrome, recent trips, reset/share/PDF actions, auth actions, and Help & Legal links while `MobileModeHeader` stays focused on layout and scroll behavior. |
| `TimelineThread` | Renders timeline with `variant` prop (`ghost`/`draft`/`real`). Day headers show intensity badge (Relaxed/Balanced/Packed) via `getDayIntensity()` from `lib/dayIntensity.ts`. Accepts the same three optional DnD render props (`blockWrapper`, `dayWrapper`, `freeDayDropSlot`), but browse-sheet state and insert-activity mutations are now delegated to `useTimelineThreadBrowseSheet`, while map observer/scroll-target bridging is delegated to `useTimelineThreadMapSync`. **Constraints:** `ActivityMiniCard` renders all `block.active_constraints` as full badges (no cross-block dedup is implemented; see Section III.C for planned design). **Compact days:** Not implemented (see Section III.D); all days render in the default full-card layout. |
| `ItineraryDndWrapper` | `@dnd-kit/core` `DndContext` wrapper (`closestCorners`, `PointerSensor` with 8px activation distance). Orchestrates drag state, calls `validateArrangement()` then `applyArrangement()` on drop, applies store update via `mergeEnvelope` + `setState({version})`. Uses `claimMutation`/`releaseMutation` for the store mutation gate. Shows `DragOverlay` with `DragPreviewCard`. **Undo on drag:** Before applying arrangement, captures `previousDayCards` + `previousVersion` snapshot, sets `documentStore.setUndoEntry({ type: 'drag_move', label, previousDayCards, previousVersion })`, and calls `showMutationToast(label, toast)` to display an Undo CTA. Mounts `useUndoStack` for auto-expire side effect (clears `undoEntry` after 8s). |
| `DraggableBlock` | Wraps each block with `useDraggable`. Locked blocks (`arrival`/`departure`/`check-in`/`check-out`/`is_buffer`) show a `Lock` icon and disable drag. When `block.id` is absent, renders a plain passthrough (no drag handle). Applies `opacity-30 scale-95` while dragging. |
| `DroppableDay` | Wraps activity-day block lists with `useDroppable` (`id: "day-{dayNumber}"`). Two-div structure: outer div (`ref={setNodeRef}`, `min-h-[80px]`) owns the hit area; inner div owns ring + highlight styles. Highlights with `ring-1 ring-emerald-500/25 bg-emerald-500/[0.04]` when dragging over. Not used for free/empty days — those use `FreeDayDropSlot` instead. |
| `FreeDayDropSlot` | Dedicated drop zone rendered inside `FreeDayCard` via the `freeDayDropSlot` render prop. Avoids highlighting the entire free-day card. Uses `useDroppable` with the same `day-{dayNumber}` id. |
| `PdfExportButton` | Plan surface CTA that appears when itinerary day cards exist and triggers client-side export. Lazily imports `@react-pdf/renderer` and `file-saver`, calls `extractTripPdfData()`, and saves `TripPdfDocument` output with a destination/date filename. |
| `BrowseActivitiesSheet` | Bottom sheet displayed on free/buffer days. Fetches categorized activity tiles from `POST /api/activities/browse` using the partner-backed cascade (Viator first, GYG supplement/dedupe, Google Places fallback/supplement). Shows category filter chips (cultural/food/nature/spa/tours/shopping). Calls `POST /api/document/insert-activity-block` to add selected tiles directly into the day. Reads pre-stashed tiles from `documentStore.browseableActivities` if available (avoids repeat API call). Located in `frontend/components/plan/BrowseActivitiesSheet.tsx`. |
| `DragPreviewCard` | Ghost card shown in `DragOverlay` during drag. Renders `block.summary || block.activity_type`, specialist label via `getTopicLabel(block.specialist_type)`, and price from `block.booked_tile?.price_estimate`. |
| `ChatPanel` | Barrel export for the chat surface. The actual implementation lives in `ChatPanelContent`, which delegates controller wiring to `useChatPanelController` and keeps the public import path stable for the rest of the app. |
| `ChatPanelContent` | Render-only chat shell composing `ChatStatusHeader`, `ChatMessageList`, `ChatSuggestionBar`, `ChatInputHandler`, and `ChatModuleSheets` from the controller object returned by `useChatPanelController`. |
| `chatPanelLayout.ts` | Pure layout-decision module extracted from `ChatPanelContent.tsx` for testability. `shouldUseLandingChatLayout()`: returns true for desktop + bootstrap state when not framing/generating. `shouldShowBootstrapHero()`: returns true when landing chat layout is active AND setup header is not collapsed. |
| `ChatBootstrapHero` | Scroll-away desktop bootstrap header used by `ChatPanel` during landing/bootstrap states. Renders the terminal-style status label plus `UnifiedChipRow`, and opens either trip-input sheets or module sheets from the shared chat shell. |
| `ChatStatusHeader` | Renders the desktop trip status hero/mini bar above chat content using `getChatStatusConfig(planViewState, planState, ...)` to keep chrome visible and consistent across planning states. |
| `ChatModuleSheets` | Renders the three module sheets (FlightsSheet, StaysSheet, ActivitiesSheet) that live inside ChatPanel. Extracted to keep ChatPanel under 200 lines. A single discriminated `openModuleSheet` state (`'flights' | 'stays' | 'activities' | null`) guarantees only one module sheet is open at a time. Tracks `activityUserSaved` session state so ActivitiesSheet inference does not override an explicit user clear (`[]`). In active itinerary states it now sets the regeneration overlay immediately on save, before `commitTripInputs()` returns. Category changes in active plan states trigger the full graph pipeline (`GENERATE_PLAN_TRIGGER`) so specialists re-dispatch instead of relying on expand-itinerary tile refresh alone. **D3 preferred-tile prune:** When ActivitiesSheet saves with fewer categories, `onSaveSettings` computes `removedCats`, filters `planDocument.preferred_tile_ids` to drop tiles from removed categories (matched via `tile.meta.specialist_type`, `tile.meta.category`, or `tile.tags`), and calls `patchDocument({ preferred_tile_ids: pruned })` as a best-effort fire-and-forget. Backend Phase 5.25 provides a second authoritative filter. |
| `useChatMessagePipeline` | Chat rendering hook that memoizes the stable-vs-streaming message derivation path. It sanitizes backend-escaped content, drops system/ack-line messages, and splits long assistant replies into multiple visible bubbles via pure helpers in `chatMessageProcessing.ts`. |
| `useChatSend` | Hook orchestrating message send, SSE streaming lifecycle (`useChatSse` internally), node status, suggestion state, and active-status updates. Extracted from ChatPanel. Returns `sendMessageCore`, `addAssistantMessage`, `handleStopStreaming`, plus state (`isLoading`, `nodeStatus`, etc.). Before a send proceeds it now waits up to 5s for pending document mutations to settle; if that gate times out the draft is restored to the input and the request is blocked with retry copy. Includes an advisory **multi-tab guard** (`isActiveTab()` / `claimActiveTab()` from `tabGuard.ts`) — blocks send with a toast when another tab is active, preventing concurrent SSE conflicts. Provides an `onRetry` callback to `useChatSse` that re-invokes `sendMessageCore` for watchdog/degraded retry buttons. Safe tail-extension prompts may optimistically extend `trip_inputs.end_date`/`trip_duration` and `day_cards` before the stream starts, then roll that preview back on stale/error/abort outcomes. On `complete`, if the returned document regresses to the pre-extension end date, the optimistic end date and placeholder day cards are re-applied so the UI does not snap backward while the canonical rebuild catches up. Stop/abort cleanup reads the active assistant message through a ref so stream interruption remains correct across callback re-renders. New `shouldStartPlanGeneration()` detection auto-triggers `onGeneratePlanStart()` when date cues are present and destination/trip context exists, even without an explicit "Generate" button click. Accepts a `readyToGenerate` prop plumbed through from the controller. |
| `useChatEffects` | Hook centralising ChatPanel side effects: scroll-on-load, ready-to-generate detection, input focus, node-status → activeStatus mapping, history loading. Extracted from ChatPanel. |
| `useChatScrolling` | Hook managing scroll container ref, auto-scroll-to-bottom, user-scrolled-up detection, and mobile setup header collapse. Extracted from ChatPanel. Forced bottom scrolls now snap immediately, then re-settle at 80/180/320ms to absorb late layout growth from streaming content or image loads; that follow-up settle work is only cancelled when a real user scroll occurs outside the short programmatic-scroll window. |
| `useChatSse` | Hook owning the `streamGraphPlan` call and all SSE callbacks (`onToken`, `onNodeStatus`, `onPartial`, `onComplete`, `onError`, `onHeartbeat`). Extracted from ChatPanel. Returns `executeStream` function. No JSX. Tracks parallel node statuses via an `activeNodeStatuses` Map -- when a parallel step completes, the next active node is promoted rather than clearing all status. **Connection watchdog:** a 15s timer (`watchdogTimerRef`) resets on every received event (token, node_status, partial, heartbeat, feasibility_warning); on timeout the stream is aborted and a "Connection lost" toast with Retry action is shown. **Degraded response handling:** on `complete`, if `response_degraded=true`, shows a warning toast with Retry action (via `onRetry` callback). Handles partial kinds: `specialist_preview` (normalizes preview payload, stores activities in `_specialistPreview`, defers the following `strategy_sections` merge by one RAF), `tile_enrichment` (merges via `mergeTileEnrichment()`), and enriched `day_cards` (merges via `setPartialDayCards()`). Emits builder warnings as toasts via `useToast()`. Tile partials honor `tiles_replaced` immediately, complete-envelope reconciliation now tolerates response-only no-op turns that return tiles without fresh strategy payload while bootstrap is already complete, and 64KB session-state backend failures are mapped to a refresh-and-retry user message. Cleans up deferred RAF frames (`deferredStrategySectionsFrameId`), `_specialistPreview`, `activeNodeStatuses`, and `watchdogTimerRef` on complete/error/stale. `executeStream()` resolves `'complete' | 'error' | 'stale'` so `useChatSend` can decide whether to keep or roll back optimistic extensions. |
| `useHeaderActions` | Shared header action hook used by the mobile overflow menu. Owns new-trip, share-link, PDF export, and auth callbacks plus the local `pdfState` / `shareState` UI state that `MobileModeHeader` and `MobileHeaderMenu` render. |
| `useLocalExpertPolling` | Local Expert enrichment hook used by `PlanFullDensityView`. Reads/writes the shared destination-intel cache, dedupes concurrent poll loops by destination, aborts polling when a new graph turn starts, and pushes travel-advice counts/pending state into `panelToggleStore`. |
| `ChatMessageList` | Scrollable message list renderer — owns scroll container div and all message rendering. |
| `ChatInputHandler` | Thin wrapper around `ChatInputBar` converting ChatPanel-level callbacks to form-submit signatures. Extracted from ChatPanel. |
| `ChatSuggestionBar` | Thin wrapper around `ChatSuggestionChips` for ChatPanel integration. Extracted from ChatPanel. Forwards trigger-action callbacks including `onConfirmReset` (`confirm_reset` target). |
| `ChatSuggestionChips` | Renders the actual suggestion-chip reel. Keeps chips in a single horizontal overflow row (never wrapped), resolves actions from structured chip metadata (`action_type`, `action_target`, `chip_type`, `category`) with category/text fallbacks for legacy chips, and treats `date_prompt` / `date_contextual` chips as executable send-message prompts instead of opening the date sheet. Also renders an optional `DateFlexChip` when `dateFlexSuggestion` is set and the user hasn't already opted into `date_flex`. |
| `DateFlexChip` | Chip in the suggestion reel offering a cheaper nearby departure date from Aviasales grouped_prices. Shows savings amount/percentage and formats the alternative date range. On click, sends a date-change message and clears the suggestion. |
| `ChatMessageRenderer` | Renders individual chat messages: user bubbles and assistant bubbles with markdown/specialist deep links/streaming pulse/retry button and color-marked activity mentions. |
| `computeTimelineVariant(state, hasPartialItinerary?)` | Maps PlanViewState to TimelineVariant (see table below). Returns `'draft'` when `hasPartialItinerary` is true even if `plan_view_state` hasn't reached S3. |
| `ghost-timeline-adapter` | Transforms specialist content to DayCard[] for preview |
| `BookingSection` | Renders booking tiles when available; supports controlled expand/collapse for stays and flights from the command controls rendered in `TripSummaryPills`. Destination travel advice remains mutually exclusive with those secondary panels through `panelToggleStore`, while `Activities` is configured through `ActivitiesSheet` rather than a command-bar toggle. |
| `NextStepBar` | CTA bar — accepts `nextAction` prop, early-returns null for `expand_itinerary` (handled by auto-expand), renders only for `finalize_plan` action. Currently `getNextAction()` never returns `finalize_plan`, so NextStepBar does not render in practice. |
| `OriginPromptCard` | Inline prompt to set origin (shown in S2 when destination+dates set but no origin, 2+ specialists) |
| `ItineraryProgressIndicator` | Progress indicator for multi-specialist auto-trigger itinerary generation |
| `BookingDrawer` | Side sheet for tile browsing, triggered by FreeDayCard "Browse" or GhostSlot clicks. Supports `pinnedDayNumber` for per-day tile placement via fill-day API. Flight lists de-dupe logical duplicates before rendering, using `partner_product_id`, then deeplink, then `title/subtitle` as the stable identity fallback. |
| `TripSettingsSheet` | Relay sheet for destination/origin/dates/travelers/budget editors. Uses an unmount-safe delayed sheet open (`setTimeout` + `mountedRef`) to avoid opening a child sheet after parent unmount. |
| `useItineraryGeneration` | Barrel hook re-exporting `useItineraryGenerationController.ts`, which encapsulates the full expand-itinerary flow: `proceedWithItineraryGeneration` (NDJSON streaming), auto-trigger logic for multi-specialist trips (Path A), `handleExpandToItinerary` (validation-gated expand), and `handleSelectNights`. Before POSTing `/api/expand-itinerary`, it normalizes `trip_inputs`: empty activity categories are sent as `categories=[] + booking_types.activities='off'` so builder semantics match sheet intent. Manual "Build itinerary" clicks still surface `isRegenerating` as a user-facing wait gate, but the scheduler/auto-trigger path relies on `currentRunId` and `expandInProgress` as the actual mutexes so visual overlay state does not block queued expands. Returns `{proceedWithItineraryGeneration, handleExpandToItinerary, handleSelectNights, hasItineraryContent}`. |
| `useLandingDerived` | Hook extracted from `NomadicLanding` computing all derived values (`viewModel`, `uiGeneration`, `hasDates`, `isRegenerating`, etc.) from store data and local state using `useMemo`. **Hard gate:** `planViewState` returns `null` when `hasPlanPrerequisites` is false (destination + dates required), preventing the plan surface from rendering. When prerequisites are met, backend `plan_view_state` is authoritative. Also derives `isFraming` (local boolean, not a plan_view_state) for UI loading feedback when generation is in flight but no backend state has arrived yet. Generation state priority: live UI generation (`uiGeneration.active`) now takes precedence over store generation when both are present. `planTabEnabled` returns true during active generation (`generation?.active === true`) even before plan prerequisites like branches are ready. Pure computation — no side effects. |
| `useLandingEffects` | Hook extracted from `NomadicLanding` grouping side effects unrelated to itinerary generation: destination image fetching, `hasEverHadPlan` detection, topic tracking for mobile badges, specialist deep link handling. State is owned by the parent and passed in as params + setters. |
| `useLandingHandlers` | Hook extracted from `NomadicLanding` for action wiring: reset/finalize/build callbacks, plan result receipt handling, mobile send/stop forwarding, gear-sheet state, and topic-diff detection for plan-related user input. |
| `useBranchManager` | Session/branch management hook for reset flows, local context clearing, and post-reset session handoff. Plan results are now applied to document and branch state immediately, even while the 5s generating loader animation is still visible, so dates, deeplinks, and branch selections stay in sync with the completed assistant turn. Follow-up tile refreshes, including the missing-flight auto-fetch path, pause only until that first result is applied. After a successful reset it still performs a hard reload so the browser picks up the newly issued session cookie before hydration resumes. |
| `useSessionHydration` | Planning-route hydration hook. Restores `/api/document`, enforces session-age reset behavior, and primes `useUserStore.fetchUser()` so auth chrome hydrates alongside plan state. |
| `SharedTripView` | Public read-only trip surface for `/trip/[slug]`. Consumes server/client fetch helpers from `sharedTripApi.ts`, renders the main shell, and delegates the error/loading/header/hero/strategy/map subsections to `SharedTripSections` before exposing the fork CTA that primes a session and POSTs `/api/share/fork/{slug}`. |
| `ReadOnlyTimeline` | Shared-trip-only itinerary renderer. Displays persisted `day_cards` without DnD, mutation controls, or booking actions. |
| `specialist-colors.ts` | SSoT for specialist-to-color text class mappings (`SPECIALIST_TEXT_COLOR: Record<string, string>`). Used by `DragPreviewCard` and `ActivityMiniCard` for specialist label badges. Hue assignments match the DS constraint-priority palette. |
| `useMapSync` | Zustand store (`frontend/hooks/useMapSync.ts`) for map↔timeline two-way sync. State: `visibleDayNumber` (set by TimelineThread scroll observer), `scrollTargetDayNumber` (set by InteractiveMap pin click or `useChatSse` after an off-screen itinerary update), `highlightedCardId`. Actions: `setVisibleDayNumber()`, `requestScrollTo(dayNumber, itemId)`. Not persisted — resets on mount. |
| `useUndoStack` | Hook (`frontend/hooks/useUndoStack.ts`) mounted in `ItineraryDndWrapper`. Returns `{ undoEntry, executeUndo }` and auto-expires `undoEntry` after 8s via `useEffect` + `setTimeout`. |
| `showMutationToast` | Utility (`frontend/lib/showMutationToast.ts`) that shows a toast notification with an Undo CTA after drag/remove mutations. Calls `toast({ description: label, action: { label: 'Undo', onClick: documentStore.executeUndo } })`. |
| `TripPdfDocument` | PDF template (`@react-pdf/renderer`) in `frontend/components/plan/pdf/TripPdfDocument.tsx`. Renders itinerary header, day sections, block metadata, and venue link list for offline PDF sharing. |
| `extractTripPdfData` | Data adapter in `frontend/lib/pdfData.ts` that converts `DocumentTripInputs`, `DayCard[]`, and tile maps into `TripPdfData` used by `TripPdfDocument`; handles traveler/date/budget formatting, block normalization, and deduped activity links. |

**Deleted Components (no longer in codebase):**
- `ConflictResolutionBanner` -- conflict resolution now chat-driven via suggestion chips
- `TripHealthDashboard` -- deleted; no dedicated inventory-health dashboard remains in the current density-driven strategy surface
- `TripHealthBar` -- deleted; compact inventory counts are no longer rendered as a dedicated S2 strategy bar
- `ReadyToPlanBanner` -- removed
- `ExplorationProgress` -- removed
- `SelectionsBar` -- hearted tile preferences now feed auto-regen directly (no separate UI bar)
- `SuggestionBlock` -- timeline block for suggested bookables removed
- `useChatStateMachine` -- chat state machine hook removed
- `PlanDocument`, `DocumentHeader`, `DaySection`, `Segment` -- legacy plan document components
- `OnboardingChips`, `PlanningProgress`, `OptionalRefinementsSection` -- legacy plan widgets
- `S1FramingView`, `S2BlockedView`, `S3BlockedView`, `S3EditingView` -- legacy stage views (deleted)
- `S3ItineraryView` -- deleted (was unused in unified `StrategyStageRenderer` flow)
- `StartupSequence` -- deleted; startup animation layer removed from current route tree
- `TripStatusBar` -- deleted; status chrome consolidated into `ChatStatusHeader` / route headers
- `CoreChip` -- deleted; chip rendering is consolidated under `ChipGroup` and related helpers
- `TripChromeBar` -- deleted; route/header controls now own reset/share/account actions directly
- `S2StrategyView` -- deleted; strategy rendering now stays in the main density-driven surface instead of a separate stage view file
- `CollapsedSetupSummary` -- deleted (setup collapse feature removed; `collapseSetupMessages` removed from chatStore)
- `LocationBadge`, `TruncatedDestinationList` -- legacy pill components
- `TileSectionHeader` -- tile section header
- `features-section` -- marketing features section
- `components/chat/HoldToDeleteButton.tsx` -- moved to `components/plan/timeline/blocks/HoldToDeleteButton.tsx`
- `SuggestionClickEvent` (schema) / `/api/suggestions/click` (endpoint) -- suggestion-click analytics removed
- `PlanSpecialistsSection` -- removed; destination intel controls moved into `PlanFullDensityView`
- `StrategyConstraintBar` -- removed; command controls for flights/stays/travel-advice now live in the unified `TripSummaryPills` bar inside `PlanFullDensityView`
- `TripAlertBanner` -- removed from plan surfaces

### TimelineVariant Mapping

The timeline variant is computed from `PlanViewState` to control badge display:

| PlanViewState | TimelineVariant | Badge |
| --- | --- | --- |
| Itinerary-ready states (`P3_FINALIZED`, legacy `S3_ITINERARY_READY`) | `real` | None (finalized itinerary) |
| Any state when `hasPartialItinerary` is true (day_cards exist but state not yet S3_ITINERARY_READY) | `draft` | None (partial itinerary override — takes precedence over state-based mapping below) |
| Editing or strategy-ready states (`P3_EDITING`, legacy `S3_EDITING`, `P1_ENRICHED`, legacy `S2_STRATEGY_READY`) | `draft` | None (no badge — draft variant is distinguished by timeline styling only) |
| All others (`S0_*`, `S1_*`, `S2_BLOCKED`, `S3_BLOCKED`, `S3_PARTIAL_CONFLICT` without day_cards) | `ghost` | "Specialist Preview" (emerald) |

**Invariant:** Regeneration is triggered via chat auto-regen, preference auto-regen, or the Build Itinerary CTA. Neither `draft` nor `real` variants display a badge — only `ghost` shows "Specialist Preview".

### State Helper Functions (`planStateHelpers.ts`)

| Function | Purpose | Status |
| --- | --- | --- |
| `isBootstrap(state)` | Normalizes state to `P0_MINIMAL` and returns true when matched. Matches `S0_EMPTY`, `S0_BOOTSTRAP`, `S1_FRAMING`, `P0_MINIMAL`. Returns true when state is null/undefined. | Active |
| `isStrategyReady(state)` | Normalizes state to `P1_ENRICHED` and returns true when matched, excluding `S2_BLOCKED`. Used by `getNextAction()` and `shouldAutoTriggerItinerary()`. | Active |
| `isItineraryReady(state)` | Normalizes state and returns true only when the plan is finalized (`P3_FINALIZED`, legacy `S3_ITINERARY_READY`). Used by timeline and booking renderers to suppress draft-mode UI. | Active |
| `isEditing(state)` | Normalizes state and returns true only for itinerary-edit states (`P3_EDITING`, legacy `S3_EDITING`). Used alongside `isItineraryReady()` so S3 editing stays draft-like without widening strategy-ready checks. | Active |
| `isGenerating(generation)` | Checks if any generation is in progress (`generation?.active === true`) | Active |
| `shouldAutoTriggerItinerary(state, topics, hasDates, generation, hasItinerary)` | Path A: auto-trigger for multi-specialist trips (2+ topics, S2, has dates, no existing itinerary) | Active |
| `isMultiSpecialistTrip(executedTopics)` | Returns true when 2+ topics executed | Active |
| `getNextAction(state, generation, _hasTripContext?)` | Returns `'expand_itinerary'` when `isStrategyReady(state)`, `null` otherwise. Does NOT gate on dates. Third param `_hasTripContext` is deprecated (NextStepBar reads tripInputs from store). | Active |

**Deleted functions (no longer in planStateHelpers.ts):**
- `isFraming()` -- removed (was: returns true only for `S1_FRAMING`). Note: `isFraming` still exists as a helper in some chat/landing components but is no longer in `planStateHelpers.ts`.
- `isReady()` -- removed (was: checks if plan is in ready state)
- `hasStrategy()` -- replaced by narrower `isStrategyReady()`, `isItineraryReady()`, and `isEditing()` helpers
- `shouldShowLeftPanelGenerateCTA()` -- removed (was: returns true for S0/S1)
- `canShowTilesPreview()` -- removed, mode is the SSoT for tile rendering
- `canShowBookingTiles()` -- removed, mode is the SSoT for tile rendering
- `canExpandToItinerary()` -- removed from helpers (gating now handled by renderer/store state)
- `getStageFromState()` -- removed (PlanHeader no longer consumes stage labels)

**IMPORTANT:** `getNextAction()` returns action type based on state alone. `NextStepBar` accepts the result as its `nextAction` prop. It filters out `expand_itinerary` (auto-expand handles that) and only renders when `nextAction` is `finalize_plan`.

```typescript
// planStateHelpers.ts
export function getNextAction(
  state: PlanViewState,
  generation?: GenerationState | null,
  _hasTripContext?: boolean // Deprecated - NextStepBar reads tripInputs from useDocumentStore
): 'expand_itinerary' | 'finalize_plan' | null {
  if (isGenerating(generation)) return null;
  // isStrategyReady() checks strategy-ready state for S2
  if (isStrategyReady(state)) return 'expand_itinerary';
  return null;
}
```

---

## IX. Invariants

1. **Right Panel Never Empty:** After first user message, always show *something* (hero, cards, or full plan).
2. **No View Swapping:** Single renderer (`StrategyStageRenderer`) adapts via `computeDataDensity()`; don't mount/unmount entire view components.
3. **No UI Chrome Removal:** Elements that appear during setup (status header, chip rows) must **transform through states**, not disappear. Layout shift breaks spatial memory. Status content is now centralized in `ChatStatusHeader.tsx` via `getChatStatusConfig`.
4. **Backend is SSoT:** `plan_view_state` from backend determines rendering mode. Frontend does not fabricate it except for `S0_EMPTY` (reset intent). `S3_PARTIAL_CONFLICT` is emitted by both the coordinator `_compute_coordinator_s3_state()` (graph plan flow) and the `/api/expand-itinerary` endpoint when the builder produces partial results with conflicts. `S1_DESTINATION_SET` exists only in the frontend `VIEW_STATE_ORDER` for downgrade protection ordering.
5. **Coordinates Flow:** `[lng, lat]` format preserved from specialist → strategy_sections → DayBlock.
6. **Plan Tab Unlock:** Plan tab unlocks when `planTabEnabled = hasPlanPrerequisites && (hasBranchesReady || !isBootstrap(planViewState))`. `hasPlanPrerequisites` requires both `hasDestination` AND `hasDateRange` (start_date + end_date). Strategy content alone does NOT unlock the plan tab -- dates are required. Desktop `canViewPlan` in `useViewNavigation` gates on dates (`hasDates || isGenerating`) but is marked `@deprecated` and only used by legacy API. Implementation: `useLandingDerived.ts`.
7. **Specialist Display Labels:** All user-facing specialist names (toasts, badges, drag previews) use `getTopicLabel()` from `StrategyHeroUtils.tsx` — never raw `specialist_type`/`activity_type` strings (which are snake_case internal keys like `wildlife_safari`).

---

## X. Mobile Topology & Adaptation

The "Split Screen" desktop architecture translates to a **horizontal swipe layout** on mobile (<1024px). Chat and Plan are two full-screen pages using CSS `scroll-snap`. Desktop is unchanged.

### Implementation

| Component | File | Purpose |
| --- | --- | --- |
| `MobileSwipeLayout` | `components/layout/MobileSwipeLayout.tsx` | CSS scroll-snap horizontal container with tab bar |
| `MobileChatInput` | `components/chat/MobileChatInput.tsx` | Detached chat input below swipe container (visible on both pages); textarea stays at `text-[16px]` to prevent iOS Safari zoom on focus |
| `MobileModeHeader` | `components/layout/MobileModeHeader.tsx` | Mobile top chrome for reset/share/pdf/account actions, compact trip status, and scroll-driven condensed trip summary |
| `mobileNavStore` | `state/mobileNavStore.ts` | Zustand store: `activePage`, `hasNewPlanContent` badge |
| `useIsDesktop` | `hooks/useIsDesktop.ts` | Viewport detection hook (`useSyncExternalStore` + `matchMedia`) |

### Layout Stack

```
┌──────────────────────────┐
│  MobileModeHeader     48px│
│  [Chat]  [Plan ●]   ~36px│  ← tab bar inside MobileSwipeLayout
├──────────────────────────┤
│                          │
│  MobileSwipeLayout       │  ← flex-1 (scroll-snap-x mandatory)
│  Page 0: Chat messages   │
│  Page 1: Plan content    │
│                          │
├──────────────────────────┤
│  MobileChatInput     ~56px│  ← OUTSIDE swipe container
│  + safe area              │
└──────────────────────────┘
```

### Spatial Translation

| Desktop Concept | Mobile Translation | Behavior |
| --- | --- | --- |
| **Right Panel** | **Plan Page (Page 1)** | Swipe right or tap "Plan" tab. Same component tree as desktop right panel. |
| **Instant Update** | **Badge Dot** | Emerald dot on Plan tab when content updates while user is on Chat page. |
| **Bridge Mode** | **Auto-navigate** | First plan content arrival auto-swipes to Plan page. Subsequent updates use badge only. |
| **Navigation** | **Tab Bar + Swipe** | Compact segmented control `[Chat] [Plan ●]` above swipe container. |
| **Chat Input** | **Shared bottom input** | `MobileChatInput` is outside the swipe container — visible on both pages. |

### Auto-Navigation Rules

| Event | User on Chat | User on Plan |
|-------|-------------|--------------|
| First strategy/tiles arrive | **Auto-swipe to Plan** | Stay |
| Itinerary completes | Badge dot on Plan tab | Stay, content updates live |
| User sends new message | Stay on Chat | Stay on Plan |
| Session reset | Go to Chat | Go to Chat |
| User manually swipes | Follow user | Follow user |

**Key principle:** Auto-navigate ONCE (first plan content), then respect user choice. Badge dot for subsequent updates.

### Height Chain (Critical for Mobile)

The mobile flex chain MUST be fully constrained to prevent input clipping:

```
ROOT div         h-[100dvh] overflow-hidden
  └─ <main>      flex-1 flex-col overflow-hidden min-h-0
       ├─ MobileModeHeader   (intrinsic)
       ├─ MobileSwipeLayout  (flex-1 min-h-0)
       │    ├─ Tab bar            (~36px)
       │    └─ Snap container     (flex-1 min-h-0 overflow-y-hidden)
       │         ├─ Chat page     (h-full overflow-y-auto)
       │         └─ Plan page     (h-full overflow-y-auto)
       └─ MobileChatInput    (shrink-0)
```

**Rules:** Every flex level needs `min-h-0` (prevents implicit `min-height: auto` from expanding). Each page scrolls independently via `overflow-y-auto` — `overflow-y-hidden` on the snap container prevents cross-axis stretching to tallest sibling.

### Chat Message Anchoring (Mobile)

Messages anchor to the **bottom** of the scroll area so the last message sits near the input:
- Scroll container: `flex flex-col` (mobile only)
- Inner message wrapper: `mt-auto` when messages exist (mobile only)
- Empty state: Uses `mt-[42vh]` for globe positioning at ~55-60% viewport

### Plan Tab Locking

Plan tab is **locked** until first real plan content arrives:
- Tab button: `disabled={!planTabEnabled}` with `cursor-not-allowed` styling
- Swipe blocked: `handleScroll` snaps back to page 0 if user swipes while locked
- Programmatic navigation: Skipped when `activePage === 1 && !planTabEnabled`

### Mobile Invariants

1. **Notification of Change:** Every significant state change MUST trigger a **Badge Dot** on the Plan tab (via `mobileNavStore.setHasNewPlanContent(true)`). Badge clears when user views Plan page.
2. **State Persistence:** Each page has independent vertical scroll. Both pages stay in DOM — scroll position survives page switches.
3. **Touch Targets:** All interactive elements minimum 44x44px per `design-system.md`.
4. **Safe Areas:** Chat input uses `pb-[max(0.5rem,calc(env(safe-area-inset-bottom)+var(--keyboard-offset,0px)))]` — `MobileChatInput` tracks the iOS virtual keyboard height via `window.visualViewport` and sets `--keyboard-offset` on the document element. Header uses `pt-[env(safe-area-inset-top)]`.
5. **Chat Input Always Visible:** Users can type commands from either page without swiping back.
6. **Height Constraint:** Root div MUST use fixed `h-[100dvh]` (NOT `min-h-[100dvh]`) to prevent input clipping below viewport.
7. **Status Pill:** `MobileModeHeader` STABLE state has empty text (pill hidden). Only RESOLVING ("Planning...") shows a visible pill, and the pill is suppressed while the condensed summary bar is visible.
8. **Mobile Header Chrome:** `MobileModeHeader` owns the compact status pill, condensed summary bar, and overflow actions for reset, share, PDF export, sign in/out, and recent-trip resume without adding extra vertical chrome above the swipe layout.
9. **Keyboard Dismissal:** Entering the Plan page blurs the active input/textarea so the keyboard does not obscure the timeline.
10. **Reset must rotate the session cleanly:** reset UX is only complete after the browser has adopted the new session cookie. `useBranchManager` therefore reloads the page after clearing local state instead of relying on toast-only confirmation.

### Deleted Components (replaced by swipe layout)

- `MobileModeContext` → replaced by `useIsDesktop()` hook + `mobileNavStore`
- `MobilePlanFooter` → replaced by `MobileChatInput` (shared across pages)
- `MinimizedChatInput` → replaced by `MobileChatInput`
- `SetupDrawer` / `SetupProgressIndicator` → removed (dead code)

### Cross-Reference

* **Visual Specs:** See `design-system.md` Sections 11 & 12 for mobile styling (touch targets, safe areas, sticky headers).
* **This Document:** Handles **behavior** (state mapping, notification logic).

---

## XI. Primary Interaction Controls (Buttons)

We separate **Conversation** (Talking to the Architect) from **Commitment** (Locking the Plan).

### 1. Chat Input Button (The Conversation)

| Property | Value |
| --- | --- |
| **Icon** | Always **"Send"** (Arrow/Paper Plane) |
| **Location** | Chat Panel (Bottom Right) |
| **Behavior** | Context-aware based on text content |

**Flow by Phase:**
- **Setup Phase:** Sends intent → Triggers Bridge Mode
- **Feasibility Phase:** Sends dates → Triggers Auto-Search (Plan Mode)
- **Plan Phase:** Sends refinements → Updates tiles/timeline

**Invariant:** This button NEVER changes to "Build Plan". It is strictly for communication.

### 2. Canvas Action Buttons (Two-Button Architecture)

The canvas uses two distinct action buttons for different phases:

#### A. Regeneration Triggers (Distributed Architecture)

The standalone RefreshButton FAB has been removed. Regeneration is now handled by multiple distributed mechanisms:

| Trigger | Method | Component |
| --- | --- | --- |
| **Chat messages** | Auto-regen on structural plan changes | `ChatPanel.tsx` → `onAutoExpandItinerary` |
| **Preference changes** | Instant auto-regen via module-level subscription | `startPreferenceAutoRegen()` in `usePreferenceAutoRegen.ts` |
| **Build Itinerary CTA** | Manual click to generate itinerary | `StrategyStageRenderer.tsx` |
| **GENERATE_PLAN_TRIGGER** | Full regeneration via chat system | `useItineraryGeneration.ts` → `proceedWithItineraryGeneration` |

**Implementation:**
```typescript
// useItineraryGenerationController.ts - proceedWithItineraryGeneration handles all regen paths
// Reads FRESH state via useDocumentStore.getState() (avoids stale closures)
// Supports forceFullRebuild flag for structural changes
```

**Invariant:** Tiles stay visible until backend returns new data. Regeneration paths are event-driven, not gated behind a single FAB.

#### B. NextStepBar (Finalization CTA)

| Property | Value |
| --- | --- |
| **Label** | "Finalize & Book" |
| **Location** | Right Panel (Sticky Footer - "Command Island") |
| **Visibility** | Currently does not render in production flow |
| **Action** | Transitions to Checkout/Booking phase |
| **Component** | `NextStepBar.tsx` |

**How it works:**
- `NextStepBar` accepts a `nextAction` prop (from `getNextAction()`)
- `getNextAction()` returns `'expand_itinerary'` for `S2_STRATEGY_READY`, `null` otherwise
- NextStepBar filters out `expand_itinerary` (auto-expand handles it) and only renders for `finalize_plan`
- Because `getNextAction()` never emits `finalize_plan` today, NextStepBar is currently unreachable in normal flow

**Context Display:**
- Left side shows "TIMELINE" label with date range (e.g., "Feb 5 — Feb 12")
- Badge shows trip duration in days
- Green emerald styling when ready

**Invariant:** Do not treat NextStepBar as an active Booking gate until `getNextAction()` emits `finalize_plan`.

#### Path A: Auto-Trigger for Multi-Specialist Trips

For multi-specialist trips (diving + hiking, skiing + hiking, etc.), the itinerary generation **auto-triggers** when dates are set. This removes the need for a manual FAB click.

**Auto-Trigger Conditions:**
1. `isStrategyReady(state)` returns true for `S2_STRATEGY_READY`, excludes `S2_BLOCKED`
2. `executed_strategy_topics.length >= 2` (multi-specialist)
3. `hasDates === true` (start + end date set)
4. `!isGenerating` (not currently generating)
5. `!hasItineraryContent` (no existing itinerary)

**Implementation:**
```typescript
// planStateHelpers.ts
export function shouldAutoTriggerItinerary(
  state: PlanViewState,
  executedTopics: string[] | undefined,
  hasDates: boolean,
  generation?: GenerationState | null,
  hasItineraryContent?: boolean
): boolean {
  // Must be in strategy-ready state
  if (!isStrategyReady(state)) return false;
  if (isGenerating(generation)) return false;
  if (!hasDates) return false;
  if ((executedTopics?.length ?? 0) < 2) return false;
  if (hasItineraryContent) return false;
  return true;
}

// useItineraryGeneration.ts (extracted from NomadicLanding)
useEffect(() => {
  if (shouldAutoTrigger) {
    hasAutoTriggeredRef.current = true;
    setTimeout(() => proceedWithItineraryGeneration(), 500);
  }
}, [planViewState, executedTopics, hasDates, ...]);
```

**Frontend dates-build gate (`planStateHelpers.ts`):** `hasTripDates(...)` is the single source of truth for "can we BUILD a plan yet?" so every `GENERATE_PLAN_TRIGGER` fire site stays consistent — a plan must never be built without dates (a dateless build produces a phantom itinerary against unpersisted default dates). The gate helper, on missing dates, opens the Dates sheet (`openDates`) and shows `MISSING_DATES_NUDGE` in chat instead of silently firing `sendBuild` — used by the Dates-sheet save path so a dateless build is deferred, not dropped.

**Backend Gates (`/api/expand-itinerary`):**
The endpoint rejects early if prerequisites aren't met (prevents wasted ItineraryBuilder calls during S0_BOOTSTRAP):
1. **Both dates required:** Returns `MISSING_DATES` error if `start_date` or `end_date` is null
2. **Strategy sections required:** Returns `NO_STRATEGY` error if `strategy_sections` is empty
3. **Minimum trip length:** Returns `TRIP_TOO_SHORT` error if trip < 2 days

**Why Multi-Specialist Only:**
- Single-specialist trips (diving only) may have simple constraints - user may want to explore tiles first
- Multi-specialist trips (diving + hiking) have complex constraint interactions - user benefits from seeing the constraint-validated timeline immediately
- The 24h altitude buffer between diving and hiking is best understood through the visual timeline

**UX Flow:**
```
User: "Plan diving and hiking Bali March 1-5"
       ↓
[S2_STRATEGY_READY] Tiles appear + Strategy cards visible
       ↓
[Auto-detect] 2+ specialists + dates set
       ↓
[Auto-trigger] ItineraryBuilder runs (500ms delay for UX)
       ↓
[Show Progress] ItineraryProgressIndicator appears
       ↓
[Success] Timeline appears with constraint buffers
   OR
[Conflict] Partial day_cards render at S3_PARTIAL_CONFLICT + resolution chips via chip_generator
```

**UI Components:**

1. **ItineraryProgressIndicator** - Shows generation progress
   - States: `analyzing`, `checking`, `building`, `success`, `error`
   - Message: "Analyzing diving + hiking requirements..."
   - Progress bar animation

2. **Inline Conflict Handling** (replaced former ConflictResolutionBanner)
   - Partial `day_cards` auto-render at `S3_PARTIAL_CONFLICT` showing what CAN fit
   - Blocking violations re-surface on next chat turn via `turn_meta.builder_result` metadata
   - `chip_generator._generate_chips_from_state()` generates actionable resolution chips: "Extend to Mar 12", "Remove hiking"
   - **Unschedulable block styling:**
     - `opacity-60` with dashed amber border (`border-2 border-dashed border-amber-500/50`)
     - "Cannot schedule" warning badge with AlertTriangle icon
     - Activity title shown with strikethrough
     - `unschedulable_reason` displayed as italic amber text

**Single-Specialist Behavior:**
For single-specialist trips, users trigger generation via:
1. `FloatingBuildButton` / Build Itinerary CTA - Initial plan generation (S0 → S2)
2. Chat auto-regen / preference auto-regen - Regeneration when inputs or preferences change

### 3. Button Separation Rationale

| Action | Old Behavior | New Behavior |
| --- | --- | --- |
| **Typing Dates** | Did nothing visible | **Triggers Search** (Logistics Node). Populates Plan tab immediately. |
| **Clicking "Build"** | Triggered Search (Loading...) | **N/A** - "Build" removed from chat input. |
| **Clicking "Finalize"** | N/A | **Triggers Booking.** Moves user from Plan → Checkout Forms. |

**Why:** "Build" in the chat input was a relic of the "Form-Filler" mental model. In a Conversational Agent, users *talk* to the system—they don't *submit forms*. The Send arrow is universally understood as "send this message."

---

## XII. Component Rendering Strategies ("The Magazine")

The Strategy Section adapts its visual presentation based on Data Density (see Section VII). This is the "Magazine Style" transformation.

### 1. Strategy Section Variants

| Density | Variant | Visual | Purpose |
| --- | --- | --- | --- |
| `bridge` / `ghost` / `full` | **Vertical Stack** | Compact rounded image + `TripSummaryPills` below (desktop); hidden on mobile | Clean, scannable |

#### A. Vertical Stack Mode ("Image + Pills")

Used when destination image is available. Clean separation of image and text.

* **Image:** `max-h-[15vh] min-h-[120px]` rounded card (`rounded-2xl shadow-2xl ring-1`)
* **No overlay:** Image stands alone — no gradients, no text on image
* **No title/subtitle:** Pills below serve as the sole trip summary
* **Pills:** `TripSummaryPills variant="default"` using CSS custom property theming
* **No specialist pills:** Trip DNA bar below already shows specialist info
* **Mobile:** Hero hidden entirely — `MobileModeHeader` and `TripSummaryPills` carry the compact trip context

**Rationale:** Moving text below the image eliminates readability issues across varying photo backgrounds while keeping the layout clean and scannable.

#### B. Compact Mode ("Trip DNA Bar")

Used in Full Mode when tiles exist, and **always in S3 (itinerary ready)**. The goal is to **get out of the way** so the timeline and booking tiles are prominent.

* **Height:** `h-14` (~56px)
* **Layout:** `flex items-center gap-2` with horizontal scroll for multiple specialists
* **Structure:** Label "Trip DNA:" + specialist pills
* **Specialist Pill:** Icon + title + constraint count badge
* **Background:** `bg-zinc-50 dark:bg-white/[0.02] border border-zinc-200 dark:border-white/5`
* **Interaction:** Clickable pills (future: opens `BottomSheet` with full details)

**S3 Rendering Rule:**
```tsx
// StrategyStageRenderer.tsx - Section 1: Specialists
{fullModeSections.length > 0 && (
  <>
    {/* Specialist cards stay in the density-driven plan surface pre-itinerary
        and can remain visible post-itinerary behind the same renderer path */}
    {!hasItineraryContent ? <StrategyHeroSurface ... /> : <>{showConstraints && <StrategyHeroSurface ... />}</>}
    {/* Trip DNA bar - constraint pills from niche specialists */}
    {engineConstraints.length > 0 && <TripDNABar ... />}
  </>
)}
```

**Visual Layout:**
```
┌─────────────────────────────────────────────────────────┐
│ SPECIALIST ANALYSIS (hidden by default in S3)           │
│ (User clicks "Details" in Trip DNA bar to reveal)       │
├─────────────────────────────────────────────────────────┤
│ TRIP DNA BAR (flex-wrap pills, constraint-forward)      │
│ Trip DNA:  [AlertTriangle 24H No-fly Buffer]  [Clock Morning only]  [Details] │
├─────────────────────────────────────────────────────────┤
│ ITINERARY                                               │
│ Day 1: Arrival                                          │
│ Day 2: Diving at Crystal Bay                            │
└─────────────────────────────────────────────────────────┘
```

**Key Behavior:** In S3 (itinerary ready), specialist cards are **hidden by default** and toggled via the "Details" link in the Trip DNA bar. Pre-itinerary (S2), specialist cards are always visible. Trip DNA bar is always visible when niche specialist constraints exist.

<!-- REVIEW: StrategyHero appears unmounted — possible dead code, confirm with team.
     The "Self-Contained Expansion", "Rationale", "Local Expert fetch-on-open", and
     "Specialist-Specific Layouts" subsections below describe `StrategyHero` /
     `StrategyHeroContent` / `StrategyHeroCompact` and their BottomSheet, but those
     components have NO external JSX consumer in the live render path (only
     `StrategyHeroUtils` utility exports are imported elsewhere). The live strategy
     surface is `PlanFullDensityView` and its subsections. Confirm whether this BottomSheet
     behavior was reimplemented there or is genuinely dead. -->

**Self-Contained Expansion:** The `StrategyHero` component internally manages its own expansion state via `useState`. When clicked, it opens a `BottomSheet` containing:
1. Hero image with specialist badge
2. Strategy Logic (one-liner)
3. Applied Constraints (with icons and reasons)
4. Key Principles (checkmark list)
5. Recommendations (with thumbnails)

**Rationale:** Self-contained state management avoids prop-drilling and ensures the expand behavior works regardless of where `StrategyHero` is rendered inside the density-driven renderer path.

**Local Expert fetch-on-open path:** `StrategyHero` also owns a second enrichment entry point for `local_expert` sections. Opening the sheet triggers `useStrategyHeroEnrichment()`, which first checks the in-memory destination-intel cache, then long-polls `GET /api/specialist/{sectionId}/enrichment` until the backend returns `ready`, `failed`, or repeated `pending` responses age out. The sheet surfaces `loading` / `pending` / `failed` notice states plus a retry action, so compact/hero variants can fetch fresh travel intelligence even before `PlanFullDensityView`'s destination-level polling has populated the section.

**Invariant:** Constraint details must remain accessible in Plan Mode. The DNA Bar acts as a summary with drill-down capability.

### 2. Booking Section ("The Marketplace")

**Critical Logic:** Check for tiles FIRST, then dates.

```tsx
const hasTiles = tiles && Object.values(tiles).length > 0;
const hasDates = !!tripInputs?.start_date;

// 1. If tiles exist, SHOW THEM (no lock message)
if (hasTiles) return <BookingTilesGrid />;

// 2. Only show lock if NO tiles AND NO dates
if (!hasDates) return <LockMessage />;

// 3. Searching state (dates set, tiles loading)
return <SearchingSkeleton />;
```

**Rationale:** If backend sent tiles, frontend should display them regardless of date state. The "unlock" message only appears when both conditions are false.

### 3. Visual Hierarchy in Full Mode

```
┌─────────────────────────────────────────────────────┐
│ HEADER (Hero + Stepper)                             │
├─────────────────────────────────────────────────────┤
│ TRIP DNA BAR (flex-wrap pills) - Compact Strategy   │
├─────────────────────────────────────────────────────┤
│ BOOKING TILES (Primary Focus - 85% of screen)       │
└─────────────────────────────────────────────────────┘
```

**Invariant:** In Full Mode, booking tiles must be visible without scrolling. Strategy compacts to make room.

### 4. Component Implementation

| Component | File | Responsibility |
| --- | --- | --- |
| `StrategyHero` | `components/plan/stages/StrategyHero.tsx` | <!-- REVIEW: appears unmounted — no external JSX consumer; possible dead code. --> Historically rendered both Hero and Compact variants with **self-contained** `BottomSheet` expansion. NOT mounted in the live render path. |
| `useStrategyHeroEnrichment` | `components/plan/stages/useStrategyHeroEnrichment.ts` | Fetch-on-open `local_expert` enrichment hook for StrategyHero sheets; reuses destination-intel cache, then drives `loading` / `pending` / `failed` / `ready` sheet states from `/api/specialist/{sectionId}/enrichment`. <!-- REVIEW: only consumed by StrategyHero, which is unmounted; confirm. --> |
| `PlanFullDensityView` | `components/plan/PlanFullDensityView.tsx` | Live full-density surface for BOTH the P1 strategy view and the P3 itinerary view. Delegates derivation to `usePlanFullDensityData` and composes subsections: `PlanFullDensityMobileSummary`, `PlanFullDensityTravelAdvice`, `FullDensityTimeline` (→ `PlanTimelineSection` → `TimelineThread`), `BookingSummary`, `PlanFullDensityDesktopMap`, and `PlanFullDensityTilesSection`. |
| `BookingSection` | `components/plan/BookingSection.tsx` | Tiles-first rendering logic |
| `BottomSheet` | `components/ui/bottom-sheet.tsx` | Reusable slide-up sheet with drag-to-dismiss |

### 5. Specialist-Specific Layouts (BottomSheet)

The `StrategyHero` BottomSheet renders different layouts based on `specialist_type`:

#### A. General Strategy Layout

For `specialist_type === 'general'` (Trip Overview):

```
┌────────────────────────────────────────────────────┐
│ TRIP SUMMARY STATS (3-column grid)                 │
│ ┌────────┐ ┌────────┐ ┌────────┐                   │
│ │📍 Dest │ │📅 Dates│ │👥 Trav │                   │
│ │ Dubai  │ │Feb 1-5 │ │ 2 pax  │                   │
│ └────────┘ └────────┘ └────────┘                   │
├────────────────────────────────────────────────────┤
│ VIBE GRID (2x2 images from content_added)          │
│ ┌──────────┐ ┌──────────┐                          │
│ │ Beach    │ │ Skyline  │                          │
│ └──────────┘ └──────────┘                          │
│ ┌──────────┐ ┌──────────┐                          │
│ │ Desert   │ │ Souks    │                          │
│ └──────────┘ └──────────┘                          │
├────────────────────────────────────────────────────┤
│ ONE-LINER (italic quote style)                     │
│ "A perfect blend of adventure and culture..."      │
├────────────────────────────────────────────────────┤
│ TRIP HIGHLIGHTS (principles as checklist)          │
│ ✓ Diving + City combo                              │
│ ✓ Desert safari experience                         │
└────────────────────────────────────────────────────┘
```

**Data Sources:**
- `trip_summary.destination`, `trip_summary.dates`, `trip_summary.travelers`
- `content_added[].image_url` for Vibe Grid
- `one_liner` for quote
- `principles[]` for highlights

#### B. Local Expert Layout (Trip Overview / Trip DNA)

**Purpose:** Provides destination context, vibes, and local tips as the visual anchor for all trips.

**Applies to:** `specialist_type === 'local_expert'` OR `specialist_type === 'general'`

**Visual Layout:**
```
┌────────────────────────────────────────────────────┐
│ TRIP SUMMARY STATS (3-column grid)                 │
│ ┌────────────� ┌────────────┐ ┌────────────┐       │
│ │ 📍 Dest    │ │ 📅 Dates   │ │ 👥 Travelers│      │
│ │ Bali      │ │ Feb 1-5    │ │ 2 pax      │       │
│ └────────────┘ └────────────┘ └────────────┘       │
├────────────────────────────────────────────────────┤
│ DESTINATION GALLERY (horizontal scroll carousel)   │
│ ┌──────────┐ ┌──────────┐ ┌──────────┐            │
│ │ Vibe 1   │ │ Vibe 2   │ │ Vibe 3   │            │
│ │ h-32     │ │ h-32     │ │ h-32     │            │
│ └──────────┘ └──────────┘ └──────────┘            │
├────────────────────────────────────────────────────┤
│ LOCAL INSIGHT (one_liner - italic quote style)     │
│ "Your adventure in Bali awaits..."                 │
├────────────────────────────────────────────────────┤
│ KEY PRINCIPLES (checklist with ✓ icons)            │
│ ✓ Cover shoulders at temples                       │
│ ✓ Best diving visibility May-Nov                   │
├────────────────────────────────────────────────────┤
│ LOCAL RECOMMENDATIONS (cards with thumbnails)      │
│ ┌─────────────────────────────────────────────────┐│
│ │ [img] Dive Sites                                ││
│ │       World-class diving at Tulamben...         ││
│ └─────────────────────────────────────────────────┘│
└────────────────────────────────────────────────────┘
```

**Required Data Fields:**
| Field | Type | Source | Description |
|-------|------|--------|-------------|
| `id` | string | Backend | Unique section ID (e.g., `strategy_local_expert`) |
| `specialist_type` | string | Backend | `"local_expert"` or `"general"` |
| `title` | string | Backend | Card title (e.g., "Bali Trip Overview") |
| `one_liner` | string | Backend | Insight quote for italic display |
| `trip_summary` | object | Backend | `{destination, dates, travelers}` for stats grid |
| `destination_gallery` | array | Backend | Vibe Trio images: `[{label, image_url}]` |
| `principles` | array | Backend | Checklist items (strings) |
| `constraints_applied` | array | Backend | `[{rule, type, reason, severity}]` for warnings. Frontend filters to blocking+strong only (excludes soft/info) for the strategy badge count, constraint list, and Trip DNA bar. (The blocking+strong filter lives in the `StrategyHero` family, which is no longer mounted — see REVIEW notes; confirm where it is enforced on the live surface.) |
| `content_added` | array | Backend | Recommendations: `[{title, description, type, logic_hook, image_url?}]` |
| `must_dos` | array | Backend | Quick list of recommendation titles |
| `logistics_notes` | array | Backend | Additional notes (strings) |

**Styling:**
- Trip Summary: 3-column grid, `text-xs` labels, `text-sm font-medium` values
- Gallery Images: `h-32` fixed height, `rounded-lg`, `object-cover`
- One-liner: `italic text-muted-foreground`
- Principles: `✓` checkmark icon, `text-sm`
- Recommendations: Card with `w-16 h-16` thumbnail, title, description

**Icon:** Building (from Lucide)

---

#### C. Activity Specialist Layout (Niche Experts)

**Purpose:** Provides domain-specific strategy, safety constraints, and expert recommendations.

**Applies to ALL niche specialists - IDENTICAL UI for each:**

| `specialist_type` | Label | Icon | Fallback Image |
|-------------------|-------|------|----------------|
| `diving` | Diving | Waves | Underwater coral reef |
| `hiking` | Hiking | Mountain | Mountain trail |
| `skiing` | Skiing | Snowflake | Ski slopes |
| `cycling` | Cycling | Bike | Cycling road |
| `surfing` | Surfing | Waves | Surfer on wave |
| `climbing` | Climbing | Mountain | Rock face |
| `sailing` | Sailing | Sailboat | Yacht at sea |
| `wildlife_safari` | Wildlife Safari | Binoculars | Safari landscape |

**Visual Layout:**
```
┌────────────────────────────────────────────────────┐
│ HERO IMAGE (FIXED HEIGHT - h-48 mobile, h-64 desk) │
│ ┌────────────────────────────────────────────────┐ │
│ │                                                │ │
│ │                   [image]                      │ │
│ │                                                │ │
│ │ ┌──────────────────┐                           │ │
│ │ │ 🤿 Diving        │  (frosted glass badge)    │ │
│ │ └──────────────────┘                           │ │
│ └────────────────────────────────────────────────┘ │
├────────────────────────────────────────────────────┤
│ STRATEGY LOGIC (one_liner)                         │
│ "Safe depths for warm-water diving in Bali"        │
├────────────────────────────────────────────────────┤
│ APPLIED CONSTRAINTS (safety/temporal rules)        │
│ ┌─────────────────────────────────────────────────┐│
│ │ ⚠️ 24h No-Fly Buffer after final dive          ││
│ │    Prevents decompression sickness              ││
│ └─────────────────────────────────────────────────┘│
│ ┌─────────────────────────────────────────────────┐│
│ │ ⏱️ Minimum 2h surface interval                 ││
│ │    Between repetitive dives                     ││
│ └─────────────────────────────────────────────────┘│
├────────────────────────────────────────────────────┤
│ KEY PRINCIPLES (checklist with ✓ icons)            │
│ ✓ Book PADI-certified operators                    │
│ ✓ Check equipment before each dive                 │
├────────────────────────────────────────────────────┤
│ EXPERT RECOMMENDATIONS (cards with thumbnails)     │
│ ┌─────────────────────────────────────────────────┐│
│ │ [img] USAT Liberty Wreck                        ││
│ │       Famous WWII shipwreck at 30m depth...     ││
│ └─────────────────────────────────────────────────┘│
└────────────────────────────────────────────────────┘
```

**Required Data Fields:**
| Field | Type | Source | Description |
|-------|------|--------|-------------|
| `id` | string | Backend | Unique section ID (e.g., `specialist_diving`) |
| `specialist_type` | string | Backend | One of: `diving`, `hiking`, `skiing`, `cycling`, `surfing`, `climbing`, `sailing`, `wildlife_safari` |
| `title` | string | Backend | Card title (e.g., "Diving Strategy") |
| `one_liner` | string | Backend | Strategy logic summary (auto-generated from top constraint if missing, see below) |
| `hero_image` | string | Backend | Primary image URL (or use fallback) |
| `constraints_applied` | array | Backend | `[{rule, type, reason, severity}]` - CRITICAL for safety. `severity` field added by local_expert. |
| `principles` | array | Backend | Checklist items (strings) |
| `content_added` | array | Backend | Recommendations: `[{title, description, type, logic_hook, image_url?, coordinates?}]` |
| `must_dos` | array | Backend | Quick list of key activities |
| `optional_upgrades` | array | Backend | Nice-to-have suggestions |
| `feasibility_status` | string | Backend | `"feasible"`, `"caveat"`, or `"infeasible"` |
| `feasibility_reason` | string | Backend | Explanation if not fully feasible |

**One-Liner Auto-Generation (`coordinator.py`):**
When `one_liner` is missing, the backend generates a headline from the top constraint:

```python
# Defensive field mapping: constraint fields vary between Pydantic and serialized formats
SEVERITY_ORDER = {"blocking": 0, "strong": 1, "soft": 2}
SEVERITY_KEYWORDS = set(SEVERITY_ORDER.keys())

def _get_constraint_headline(c: dict) -> str:
    """Extract human-readable text, skipping severity keywords."""
    for field in ("label", "reason", "rule"):
        val = (c.get(field) or "").strip()
        if val and val.lower() not in SEVERITY_KEYWORDS:
            # Clean machine-readable names: "min_24h_buffer" → "Min 24H Buffer"
            if "_" in val and " " not in val:
                val = val.replace("_", " ").title()
            return val
    return ""

# Sort by severity (blocking first), extract headline from top constraint
sorted_constraints = sorted(constraints, key=_get_constraint_severity)
headline = _get_constraint_headline(sorted_constraints[0])
extra = f" (+{len(constraints)-1} more)" if len(constraints) > 1 else ""
section["one_liner"] = f"{headline[:100]}{extra}"
```

**Constraint Icons by Type:**
| `type` | Icon | Color |
|--------|------|-------|
| `safety` | AlertTriangle | `text-amber-500` |
| `temporal` | Clock | `text-blue-500` |
| `certification` | Award | `text-purple-500` |
| `equipment` | Wrench | `text-zinc-500` |
| `weather` | CloudRain | `text-cyan-500` |
| `budget` | DollarSign | `text-green-500` |

**Styling:**
- Hero Image: `h-48 md:h-64` FIXED HEIGHT (not aspect ratio!), `object-cover`, `rounded-xl`
- Badge: `bg-white/20 backdrop-blur-md text-white border border-white/20`, positioned bottom-left
- Gradient Overlay: `bg-gradient-to-t from-black/60 to-transparent`
- One-liner: `text-sm text-muted-foreground`
- Constraints: Warning box with icon, `text-sm font-medium` rule, `text-xs text-muted-foreground` reason
- Principles: `✓` checkmark, `text-sm`
- Recommendations: Card with `w-16 h-16 rounded-lg` thumbnail

**INVARIANT:** All niche specialists render with IDENTICAL layout. Only the icon, label, and content differ.

### 6. Multi-Card Strategy Stack

When niche specialists run alongside Local Expert (see Section III.A), the UI renders MULTIPLE strategy cards:

```
┌─────────────────────────────────────────────────────┐
│ STRATEGY STACK (vertical list)                      │
├─────────────────────────────────────────────────────┤
│ ┌─────────────────────────────────────────────────┐ │
│ │ CARD 1: Trip Overview (local_expert)            │ │
│ │ "Bali - Island Paradise"                        │ │
│ │ 📍 Bali │ 📅 Feb 1-5 │ 👥 2 travelers            │ │
│ └─────────────────────────────────────────────────┘ │
├─────────────────────────────────────────────────────┤
│ ┌─────────────────────────────────────────────────┐ │
│ │ CARD 2: Diving Strategy (diving specialist)     │ │
│ │ 🤿 "Safe depths for warm-water diving"          │ │
│ │ ⚠️ 24h No-Fly Buffer │ 🌡️ 28°C water temp       │ │
│ └─────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────┘
```

**Rendering Order:**
1. **Trip Overview** (local_expert) - ALWAYS first, the visual anchor
2. **Niche Specialists** (diving, hiking, etc.) - Stacked below in queue order

**Invariant:** Trip Overview is NEVER replaced by niche specialists - they are ADDITIVE.

### 7. Viewport-Relative Image Sizing

**Problem:** Using `aspect-video` or fixed pixel heights causes images to either dominate small screens or look tiny on large screens.

**Solution:** Use viewport-height-relative sizing with min/max bounds:

| Context | Sizing | Rationale |
|---------|--------|-----------|
| **Hero image** (PlanHeader) | `max-h-[15vh] min-h-[120px]` | Compact card, never dominates |
| **Topo background** (PlanHeader) | `h-[clamp(180px,25vh,280px)]` | Scales with screen height |
| **Strategy card images** | `max-h-[30vh]` | Never exceed ~30% viewport |

**Implementation:**
```tsx
// Hero: Compact rounded card
<div className="mx-4 mt-4 rounded-2xl overflow-hidden">
  <img className="w-full max-h-[15vh] min-h-[120px] object-cover" />
</div>
```

**Invariant:** No image should exceed ~30% of vertical viewport space.

### 8. Anchor Card Safety Net

**Problem:** If LocalExpert fails or returns empty, the UI loses its context anchor (Destination/Dates/Travelers).

**Solution (current agent path):** The old DAG `_format_result()` synthesis (`strategy_general_anchor` inserted at index 0) was **removed with the coordinator DAG**. The current equivalent is in the `build_itinerary` tool: when there are no activity tiles, it adds a placeholder `local_expert` "Trip Overview" section via `section_builder.build_local_expert_section()` (`{destination} Trip Overview`, build_itinerary.py:100 / section_builder.py:257). Note this is a build-time anchor, not a per-turn safety net — and section order is not pinned to index 0 on the agent path (see [III.A](#iiia-local-expert-trip-dna-anchor)).

**Invariant (weaker than legacy):** The build guarantees a `local_expert` Trip Overview card when a destination exists and no activity tiles were produced; it is not forced to be the first card.

### 9. Complete Strategy Section Schema

**TypeScript Interface (Frontend):**
```typescript
interface StrategySection {
  // Identity
  id: string;                           // e.g., "strategy_local_expert", "specialist_diving"
  specialist_type: string;              // "local_expert" | "general" | "diving" | "hiking" | "skiing" | "cycling" | "surfing" | "climbing" | "sailing" | "wildlife_safari"
  title: string;                        // e.g., "Bali Trip Overview", "Diving Strategy"
  subtitle?: string;                    // Optional secondary title

  // Content
  one_liner: string;                    // Strategy summary / insight quote
  bullets: string[];                    // Short constraint summaries (3 max)
  principles: string[];                 // Checklist items
  must_dos: string[];                   // Key recommendation titles
  optional_upgrades: string[];          // Nice-to-have suggestions
  logistics_notes: string[];            // Additional notes

  // Structured Data
  constraints_applied: Constraint[];    // Safety/temporal rules
  content_added: ContentItem[];         // Recommendations with details

  // Visuals
  hero_image?: string;                  // Primary image URL
  destination_gallery?: GalleryImage[]; // Vibe Trio for local_expert
  trip_summary?: TripSummary;           // Stats grid for local_expert

  // Feasibility
  feasibility_status?: "feasible" | "caveat" | "infeasible";
  feasibility_reason?: string;

  // Metadata
  impact_areas?: string[];              // e.g., ["Safety", "Timing", "Budget"]
}

interface Constraint {
  rule: string;                         // e.g., "24h No-Fly Buffer after final dive"
  type: string;                         // "safety" | "temporal" | "certification" | "equipment" | "weather" | "budget"
  severity?: string;                    // "blocking" | "strong" | "soft" (defaults to "strong")
  reason: string;                       // e.g., "Prevents decompression sickness"
  label?: string;                       // Short human-readable label for Trip DNA bar pills
}

interface ContentItem {
  title: string;                        // e.g., "USAT Liberty Wreck"
  description: string;                  // Full description
  type: string;                         // "activity" | "logistics" | "attraction" | "general"
  logic_hook?: string;                  // Actionable tip (e.g., "Book 2 weeks ahead")
  image_url?: string;                   // Thumbnail
  coordinates?: [number, number];       // [lng, lat] for map
}

interface GalleryImage {
  label: string;                        // e.g., "Destination", "Culture", "Adventure"
  image_url: string;                    // Unsplash or curated URL
}

interface TripSummary {
  destination: string;                  // e.g., "Bali"
  dates: string;                        // e.g., "Feb 1-5" or "Dates TBD"
  travelers: string;                    // e.g., "2 travelers"
}
```

**Backend Generation (Python):**
```python
# In local_expert.py - builds the anchor card
section = {
    "id": "strategy_local_expert",
    "specialist_type": "local_expert",
    "title": f"{plan.destination} Trip Overview",
    "one_liner": f"Your adventure in {plan.destination}",
    "bullets": [...],
    "principles": [...],
    "must_dos": [...],
    "constraints_applied": [...],
    "content_added": [...],
    "destination_gallery": [
        {"label": "Destination", "image_url": "..."},
        {"label": "Culture", "image_url": "..."},
        {"label": "Adventure", "image_url": "..."},
    ],
    "trip_summary": {
        "destination": plan.destination,
        "dates": f"{plan.start_date} - {plan.end_date}",
        "travelers": f"{travelers_count} travelers",
    },
}

# In vertical_specialist.py - builds niche specialist cards
section = {
    "id": f"specialist_{topic}",
    "specialist_type": topic,  # "diving", "hiking", etc.
    "title": f"{topic.title()} Strategy",
    "one_liner": output.one_liner,
    "hero_image": hero_image_url,
    "constraints_applied": [
        {"rule": c.description, "type": c.type, "reason": c.severity}
        for c in output.constraints
    ],
    "principles": output.principles,
    "content_added": [...],
    "feasibility_status": output.feasibility_status,
    "feasibility_reason": output.feasibility_reason,
}
```

### 10. S3 Itinerary View Specification

The S3 Itinerary View (after plan finalization) transforms from raw data dumps into a structured, decision-focused experience with three key layers: **Map (The Anchor)**, **Timeline (The Narrative)**, and **Booking Segments (The Decisions)**.

#### A. Split Screen Layout (Desktop)

| Column | Width | Behavior |
|--------|-------|----------|
| Left | flex-1 (min 480px, max 800px) | Timeline Thread (scrollable) |
| Right | flex-1 (min 350px) | Interactive Map (sticky, height: 100vh - header) |

```
┌─────────────────────────────────────────────────────────────┐
│ DESKTOP (lg:)                                               │
│ ┌─────────────────────────┬─────────────────────────────┐   │
│ │ TIMELINE (50%)          │ MAP (50%)                   │   │
│ │ ┌─────────────────────┐ │ ┌─────────────────────────┐ │   │
│ │ │ Day 1               │ │ │                         │ │   │
│ │ │ ├─ Arrival          │ │ │      [Interactive       │ │   │
│ │ │ ├─ Check-in         │ │ │         Map]            │ │   │
│ │ │ └─ Activity         │ │ │                         │ │   │
│ │ │                     │ │ │   • Hotel pin           │ │   │
│ │ │ Day 2               │ │ │   • Activity POIs       │ │   │
│ │ │ ├─ Activity         │ │ │   • Flight arc          │ │   │
│ │ │ └─ Safety Buffer    │ │ │                         │ │   │
│ │ └─────────────────────┘ │ └─────────────────────────┘ │   │
│ └─────────────────────────┴─────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

**Day Selection Sync:** Hovering a day in the timeline highlights only that day's POIs on the map.

#### B. Mobile Layout (Swipe Pages)

Plan content renders on Page 1 of the `MobileSwipeLayout` scroll-snap container. The same component tree as desktop (StrategyStageRenderer → BookingSection → TimelineThread) renders inside the plan page. See **Section X** for the full mobile architecture.

| Element | Behavior |
|---------|----------|
| Default | Plan page scrolls vertically: strategy cards → tiles → timeline |
| Map | Inline between tiles and timeline (`h-[clamp(220px,35vh,300px)]`), scrolls with content. Only shown when `hasItineraryContent && (fullModePOIs.length > 0 || destinationCenter !== null)` |
| Chat Input | `MobileChatInput` docked below swipe container (always visible) |
| Navigation | Tab bar `[Chat] [Plan ●]` + horizontal swipe between pages |

```
┌─────────────────────────┐
│ MOBILE (Plan Page)      │
│ ┌─────────────────────┐ │
│ │ Strategy Cards      │ │
│ │ Booking Tiles       │ │
│ │ [Map clamp inline]  │ │
│ │ Timeline Thread     │ │
│ └─────────────────────┘ │
│ ┌─────────────────────┐ │
│ │ Chat Input (shared) │ │
│ └─────────────────────┘ │
└─────────────────────────┘
```

#### C. Block Types

| Type | Component | Visual | Purpose |
|------|-----------|--------|---------|
| Arrival/Departure | `LogisticsBlock` | Border-l-4, icon/time + resolved thumbnail (booked tile → tile map/preferred tiles → placeholder fallback) with optional booked-flight deeplink CTA beneath the logistics copy | Hard times (flights) |
| Check-in/out | `LogisticsBlock` | Key icon, hotel name, inline constraints + resilient image fallback on load error | Accommodation logistics |
| Safety Buffer | `SafetyBlock` | Red zone, "No Flights until". **Excludes** arrival/departure anchors (those are `LogisticsBlock`, not `SafetyBlock`) | Constraint visualization |
| Activity | `ActivityMiniCard` | Full-width landscape photo banner, category badge, duration, time of day, description, compact inline-constraint summary row, price badge (`block.booked_tile?.price_estimate`), provider-aware book/map CTA, hold-to-delete. The meta/actions row stacks vertically on narrow screens so partner CTAs cannot force horizontal overflow. Accepts `constraintDisplayModes?: Map<string, 'full' \| 'icon'>` — renders icon-only pill with Tooltip for repeated constraints. Accepts `variant?: 'default' \| 'compact'` — compact renders a horizontal thumbnail+content row (~56px height) for single-activity days. | Rich activity display with metadata |
| Unbooked | `GhostSlot` | Dashed border, "Select X" | Booking prompt |
| Empty Day | `FreeDayCard` | "Free Day" with fill CTA + category picker. Buffer blocks (SafetyBlock) render above FreeDayCard when present. **Suppressed on bookend days only for trips longer than 3 days**; short trips may still place/fill activities on arrival/departure bookends because those count as partial scheduling windows. | Quick-fill with generated activities or browse |

**Fill-Day Flow:** FreeDayCard → `fillDay()` API call → backend generates 1 tile via `generate_experience_tiles_for_day(tiles_per_day=1)` → response includes `day_card` + `tiles` map → frontend calls `replaceDayCard()` for surgical day card update + merges tiles into document store (enables hearting/referencing). Generated tiles are tagged with `meta.pinned_day` so the builder won't redistribute them on rebuild. Backend applies adjacent-day constraint filtering (e.g., no altitude activities next to diving days). Categories are optional — when omitted, the generator picks destination-appropriate activities. **Concurrency:** Per-day mutex (`claimFillDay`/`releaseFillDay` in documentStore) prevents concurrent fill-day calls on the same day, frontend stream/regeneration gates (`currentRunId`/generation flags) block fill-day while itinerary updates are in flight, and burst guards throttle repeat calls (1.5s cooldown via `fillDayGuards.ts`) in both timeline and browse-to-pin paths. `fillDay()` in api.ts syncs the document version from the response (`useDocumentStore.setState({ version })`) to prevent 409 cascades and preserves backend `detail` text for surfaced 429/rejection toasts.

**Remove Block Flow:** ActivityMiniCard shows a `HoldToDeleteButton` (top-right) for removable blocks (non-buffer, non-locked activity types). On touch/mobile layouts the affordance is always visible and uses a `44x44` target; on larger screens it still participates in the hover-oriented overlay treatment. Press-and-hold 1s triggers `removeBlock(blockId, dayNumber)` in documentStore → POST `/api/document/remove-block`. Backend removes the block; if no activities remain in the day, inserts a `free_day` placeholder. Frontend replaces the affected `day_card` in store, bumps `version`, and shows an info toast. Buffer blocks (`arrival`, `departure`, `check-in`, `check-out`) and booked tiles with an active unassign handler are excluded from removal.

**Browse → Pin Flow:** FreeDayCard "Browse" opens `BookingDrawer` with `pinnedDayNumber` set to the day number. When the user clicks "Add to Day N" on a tile, `handleSaveTile` in StrategyStageRenderer calls `fillDay(dayNumber, undefined, [tileId])` — the backend places the existing tile on the target day via `pinned_tile_ids` (no LLM generation). Pinned tiles are persisted to `document_data.user_pinned_tiles` for rebuild survival — the builder's Phase 5.6 Pass 0 places them on their target day, and `itinerary_adapter.py` re-injects them into the tile pool during graph-built itinerary. If `pinnedDayNumber` is null (drawer opened from elsewhere), the default path fires: `toggleTilePreference` (idempotent — only if not already preferred) which triggers the `startPreferenceAutoRegen()` subscription path.

#### C.1 Inline Constraints

Timeline blocks display contextual constraint badges directly within the card. This makes constraint-first optimization **visible** to users.

**Visual Example (current ActivityMiniCard treatment):**
```
┌─────────────────────────────────────┐
│ [landscape photo banner]            │
│ 🌊 MORNING  diving  ⏱ 3.0h          │
│ Crystal Bay                         │
│ ⚠️ 24h No-Fly Buffer · Finish by 2pm│
│ ❤️ You preferred this      Book     │
└─────────────────────────────────────┘
```

**Rendering rule:** Activity cards no longer render boxed severity cards for inline constraints. `ActivityCardConstraints` merges icons/titles/descriptions into a slim neutral-zinc summary row (`text-zinc-500 dark:text-zinc-400`, middot separator, truncated description). Severity remains in `active_constraints[]` for logic and other dedicated warning surfaces, but the per-card treatment is intentionally compact.

**Constraint Data Structure (from backend):**
```typescript
interface ActiveConstraint {
  id: string;                    // 'no_fly_buffer', 'surface_interval'
  severity: 'warning' | 'info' | 'success' | 'blocking';
  icon: string;                  // Emoji: '⚠️', 'ℹ️', '✅', '🚫'
  title: string;                 // '24h No-Fly Buffer'
  description: string;           // Contextual explanation
}

// In DayBlockOutput
active_constraints: ActiveConstraint[]
```

**Diving-Specific Constraints:**
- `no_fly_buffer`: Applied to last dive before departure (24h rule)
- `surface_interval`: Shown between consecutive dive days (18h rule)
- `no_altitude_after_dive`: Cross-domain constraint preventing high-altitude activities (hiking/skiing >2500m) within 24h of diving

**Cross-Domain Constraint Notes:**
The `no_altitude_after_dive` constraint is emitted by the diving specialist but targets hiking/skiing activities. This is enforced in the `ItineraryBuilder._detect_early_conflicts()` method, which detects when a trip is too short to accommodate both diving and high-altitude activities with the required 24h buffer.

**Integration:**
- Backend: `itinerary_builder.py::_apply_constraints_to_blocks()`, `_detect_early_conflicts()`, `_distribute_activities()` (no-fly day placement restriction)
- Frontend: `ActivityMiniCard.tsx`, `LogisticsBlock.tsx`

**Component Files:**
```
frontend/components/plan/timeline/
├── RichBlockRenderer.tsx           # Smart block router + logistics image resolver (booked tile/id/preferred/title-match/placeholder); empty-block guard returns null when no summary/title/activity_type
├── useTimelineFillDay.ts           # Fill-day state + handler hook (per-day mutex, cooldown, generation guards; extracted from TimelineThread)
├── ...                             # DragPreviewCard, DraggableBlock, DroppableDay, FreeDayDropSlot, etc.
└── blocks/
    ├── types.ts                        # DisplayTime, TimeSlot, getDisplayTime()
    ├── LogisticsBlock.tsx              # Arrival/departure/check-in + gear icons; image error fallback to deterministic placeholder
    ├── SafetyBlock.tsx                 # No-fly/rest-day/acclimatization constraints (default: rest_day)
    ├── ActivityMiniCard.tsx            # Rich activity with context menu + hold-to-delete
    ├── HoldToDeleteButton.tsx         # Press-and-hold circular progress delete button
    ├── GhostSlot.tsx                   # Unbooked placeholder
    ├── FreeDayCard.tsx                 # Empty day state with fill-day CTA + inline category picker
    └── PreferenceAttributionBadge.tsx  # "You preferred this" / "AI selected" badge
```

**Settings Gear Icons:**

Gear icons provide quick access to category-wide settings sheets from timeline blocks and tile cards:

| Block/Card Type | Gear Location | Opens Sheet | Callback Prop | Status |
|-----------------|---------------|-------------|---------------|--------|
| `AgentCard` (diving/hiking/skiing/cycling/sailing) | Header right | `ActivitiesSheet` | `onOpenActivitySettings` | Active |
| `SuggestionCard` (hotel) | Image top-right, beside heart | `StaysSheet` | `onOpenStaysSettings` | Hidden |
| `LogisticsBlock` (arrival/departure) | Top-right | `FlightsSheet` | `onOpenFlightsSettings` | Active |
| `LogisticsBlock` (check-in) | Top-right | `StaysSheet` | `onOpenStaysSettings` | Active |
| `TileCard` (hotel) | Image overlay, beside heart | `StaysSheet` | `onOpenStaysSettings` | Hidden |
| `MiniCard` (hotel) | Thumbnail corner | `StaysSheet` | `onOpenStaysSettings` | Hidden |

> **Note:** Hotel/stays gear icons are currently hidden (commented out in `SuggestionCard.tsx`) as the filtering modal is not yet wired up. Non-functional controls are worse than no controls for demo purposes.

**Behavior:**
- Gear icons are **always visible** for discoverability (when active)
- Click triggers sheet open → user adjusts settings → sheet closes → auto-regen triggers
- Settings changes propagate via `documentStore.commitTripInputs()`
- Changes trigger `LOGISTICS` strategy regen (~500ms, no LLM)

**Visual:**
```
┌─────────────────────────────────────┐
│ ✈️ Arrival       [⚙️]  ← always visible│
│ 08:00 AM                            │
│ Direct from SFO                     │
└─────────────────────────────────────┘
```

#### D. Time Display

| Data State | Display | Example |
|------------|---------|---------|
| `scheduled_time` exists | Monospace exact time | "08:00 AM" |
| Only `period` exists | Badge pill uppercase | "MORNING" |
| Neither exists | Synthesize from block index | "MORNING" / "AFTERNOON" / "EVENING" |

**Implementation:**
```typescript
function getDisplayTime(block: DayBlock, blockIndex: number): DisplayTime {
  if (block.scheduled_time) return { type: 'exact', value: block.scheduled_time };
  if (block.period) return { type: 'slot', value: block.period.toUpperCase() };
  const slots = ['MORNING', 'AFTERNOON', 'EVENING'];
  return { type: 'slot', value: slots[Math.min(blockIndex, 2)] };
}
```

#### E. Booking Drawer

| Platform | Behavior |
|----------|----------|
| Desktop | Side sheet (right, 480px, glass blur `bg-white/80 backdrop-blur-xl`) |
| Mobile | Same side sheet (full width on small screens) |

**Trigger:** Clicking GhostSlot, "Book" button on ActivityMiniCard, or "Browse" on FreeDayCard (passes `dayNumber` for pinned placement).

**Content:** Filtered tiles by category (hotel/flight/activity).

**Close behavior:** Selecting tile adds it to `preferredTileIds` (idempotent — only if not already preferred) via `handleSaveTile` in StrategyStageRenderer, then closes drawer. This triggers the `startPreferenceAutoRegen()` subscription path to regenerate the itinerary with the new preference.

#### F. Edit/Remove Interactions

Booked activities show a context menu (visible on hover) with:
- **Change Selection:** Reopens booking drawer
- **Remove from Itinerary:** Reverts to GhostSlot

### 11. Booking Suggestions Component Architecture

This section documents the mode-aware tile components used for suggestions and booking.

#### A. Mode-Aware Tile Cards

| Component | Mode | Purpose | Location |
|-----------|------|---------|----------|
| `SuggestionCard` | PLANNING | AI-recommended tiles with reasoning (vertical stack) | `components/plan/tiles/SuggestionCard.tsx` |
| `TileRailCard` | PLANNING | Compact horizontal rail card for Stays and Flights sections | `components/plan/tiles/TileRailCard.tsx` |
| `TileCard` | BOOKING | Tile details + single external deeplink action | `components/tiles/TileCard.tsx` |

#### B. SuggestionCard (PLANNING Mode)

Shows AI-suggested tiles with reasoning and action buttons.

```
┌────────────────────────────────────────────────────┐
│ [Image]                              [♡ Save]      │
│ ⭐ SUGGESTED                                        │
│ Hotel Tugu Bali                                    │
│ $75/night • 4.8★ • Seminyak Beach                  │
│                                                    │
│ ┌──────────────────────────────────────────────┐  │
│ │ ⭐ Why this suggestion?              [▼]      │  │
│ │ "Close to dive shop, within budget, highly   │  │
│ │  rated for couples..."                        │  │
│ └──────────────────────────────────────────────┘  │
│                                                    │
│ [🔄 Change]  [View Details]  [✓ Save to Trip]     │
└────────────────────────────────────────────────────┘
```

**Variants:**
- `expanded`: Full card with image and reasoning (default)
- `compact`: Single-row with thumbnail for tight spaces

**Props:**
- `tile: Tile` - The suggested tile
- `reasoning?: string` - AI explanation (from `tile.meta.reasoning`)
- `isSaved?: boolean` - Whether tile is saved to trip
- `onSave?: (tile: Tile) => void` - Save/unsave callback
- `onViewAlternatives?: () => void` - Opens AlternativesModal

#### C. TileCard (BOOKING Mode)

Shows tile details with internal selection state plus a single effective deeplink action derived from the tile and current trip inputs.

```
┌────────────────────────────────────────────────────┐
│ [Image]                             ✓ BOOKED       │
│ Hotel Tugu Bali • 4.8★                             │
│                                                    │
│ [View Details]             [Book Now →]           │
└────────────────────────────────────────────────────┘
```

**Props:**
- `tile: Tile` - The bookable tile
- `isSelected?: boolean` - Selection state for the current booking surface
- `onToggleSelect?: (tile: Tile) => void` - Selection callback for the current booking surface
- `isSaved?: boolean` - Saved/preferred state for auxiliary booking chrome
- Deeplink behavior is internal: the card opens `getEffectiveTileDeeplinkUrl(tile, tripInputs)` from its details action rather than accepting a separate `onBook` prop

#### D. AlternativesModal (Change Selection)

Side sheet for comparing alternative options when user clicks "Change".

```
┌──────────────────────────────────────┐
│ Change Hotel                      ✕  │
├──────────────────────────────────────┤
│ CURRENT SELECTION                    │
│ ┌──────────────────────────────────┐ │
│ │ [✓] Hotel Tugu Bali  $75  4.8★  │ │
│ └──────────────────────────────────┘ │
│                                      │
│ Sort: [Price] [Rating] [Name]        │
│                                      │
│ ALTERNATIVES (5)                     │
│ ┌──────────────────────────────────┐ │
│ │ [img] Maya Seminyak              │ │
│ │       $65 (-$10) 4.6★ (−0.2)     │ │
│ └──────────────────────────────────┘ │
│ ┌──────────────────────────────────┐ │
│ │ [img] W Bali                     │ │
│ │       $95 (+$20) 4.9★ (+0.1)     │ │
│ └──────────────────────────────────┘ │
└──────────────────────────────────────┘
```

**File:** `components/plan/modals/AlternativesModal.tsx`

**Features:**
- Shows current selection with highlight
- Displays price/rating differences from current
- Sort controls (price, rating, name)
- Click alternative to select and close

#### E. Cart State (documentStore)

Cart state for BOOKING mode checkout flow.

```typescript
// In documentStore.ts
cartTileIds: Set<string>;
addToCart: (tileId: string) => void;
removeFromCart: (tileId: string) => void;
clearCart: () => void;

// Selector hooks
useCartTileIds(): Set<string>
// Cart actions accessed directly from store (no separate useCartActions hook)
```

#### E.1 Destination Change Handling

**Destination Lock:** Once a destination is set, `setFromPlanResponse()` and `mergeEnvelope()` both block LLM-initiated destination changes (case-insensitive comparison). The incoming destination is silently replaced with the current value. Only `updateTripInputs()` (user-explicit action via chips/sheets) can change the destination, and doing so clears `preferredTileIds`.

When a destination or date change does occur (via `updateTripInputs` + subsequent graph run), stale content must be cleared. This is handled in TWO code paths in `documentStore.ts`:

**RAF buffering (Layer 1 jank reduction):** `mergeEnvelope` buffers consecutive SSE events within the same ~16ms animation frame using `requestAnimationFrame`. Module-level `_pendingEnvelope` accumulates events; `deepMergeEnvelopes()` collapses tiles, trip_inputs, and tiles_replaced flags. The RAF callback flushes once per paint frame, reducing 6 SSE events → 2-3 React renders.

**1. `mergeEnvelope()` - Streaming updates from SSE:**
```typescript
// Detect destination change
const prevDest = currentDoc.trip_inputs?.destination?.toLowerCase().trim();
const newDest = envelope.trip_inputs?.destination?.toLowerCase().trim();
const destinationChanged = prevDest && newDest && prevDest !== newDest;
const datesChanged = prevStartDate !== newStartDate || prevEndDate !== newEndDate;

if (destinationChanged || datesChanged) {
  console.log(`[mergeEnvelope] 🌍 Destination changed: "${prevDest}" → "${newDest}"`);
  // Clear chat messages
  useChatStore.getState().resetChat();
  // Tiles: REPLACE (not merge)
  tilesToMerge = envelope.tiles;
  // Strategy sections: REPLACE (not merge)
  sectionsToMerge = envelope.strategy_sections;
  // Day cards: CLEAR when destination/date changed and no fresh cards provided
  dayCardsToMerge = envelope.day_cards ?? [];
}
```

**2. `setFromPlanResponse()` - Full API response:**
```typescript
// View state ordering for downgrade protection
const VIEW_STATE_ORDER = {
  S0_EMPTY: 0, S0_BOOTSTRAP: 0,
  S1_DESTINATION_SET: 1, S1_FRAMING: 1,
  S2_BLOCKED: 1.5, S2_STRATEGY_READY: 2,
  S3_BLOCKED: 2.5, S3_EDITING: 2.5, S3_PARTIAL_CONFLICT: 2.5,
  S3_ITINERARY_READY: 3,
};

// GUARD: Never downgrade view state when itinerary exists
// EXCEPTIONS:
// - S0_EMPTY = genuine RESET intent (user said "start over"), always accept
// - Lateral S3 transitions are valid (e.g., S3_ITINERARY_READY → S3_EDITING)
function shouldBlockViewStateDowngrade(prev, next, hasDayCards) {
  if (!hasDayCards || !next || next === 'S0_EMPTY') return false;
  if (isS3ViewState(prev) && isS3ViewState(next)) return false; // Lateral S3 OK
  return VIEW_STATE_ORDER[next] < VIEW_STATE_ORDER[prev ?? 'S0_EMPTY'];
}

const wouldDowngrade = shouldBlockViewStateDowngrade(prevViewState, newViewState, hasDayCards);
const finalViewState = wouldDowngrade ? prevViewState : newViewState;

// Tile merge: replace when `tiles_replaced` flag set or destination changed,
// otherwise additive merge (preserves old tiles)
const shouldReplace = response.document.tiles_replaced || destinationChanged;
const mergedTiles = shouldReplace
  ? response.document.tiles
  : { ...currentDoc?.tiles, ...response.document.tiles };

// Day cards: graph-sent cards always win; clear stale cards on date change
const graphSentCards = response.document.day_cards;
const hasGraphSentCards = graphSentCards && graphSentCards.length > 0;
const finalDayCards = hasGraphSentCards
  ? graphSentCards
  : (datesChanged ? [] : (currentDayCards ?? []));
```

**View State Downgrade Protection:**
Backend may return S2 for benign reasons (e.g., "from rome" only runs trip-field enrichment via `search_tiles`). Previously this cleared day_cards. Now the frontend blocks S3→S2 downgrade when itinerary exists:
- `S3 → S2` with day_cards → **Blocked** (itinerary preserved)
- `S3 → S0` (RESET) → **Allowed** (user explicit intent)
- Destination/date change → **Tiles replaced**, day_cards cleared (clean slate)

**Hydration Behavior (fetchDocument):**
On page refresh, `fetchDocument()` hydrates backend `plan_view_state` directly. Frontend no longer performs upward reconciliation promotions during fetch; only downgrade-protection guards apply in merge paths (`setFromPlanResponse`, `mergeEnvelope`).

**Expand-In-Progress Mutex:**
```typescript
// documentStore state
expandInProgress: boolean;
setExpandInProgress: (inProgress: boolean) => void;

// Guards in triggerRegeneration() / startPreferenceAutoRegen()
if (expandInProgress) return;  // Sole hard mutex for preference regen

// isRegenerating is display state only; it may already be true before commit/expand starts
// and must not be used as a blocker here.

// proceedWithItineraryGeneration wraps expand call
setExpandInProgress(true);
try { await expandItinerary(); }
finally { setExpandInProgress(false); }
```
This prevents the cascade: expand-itinerary → markPreferencesAsApplied → preference PATCH → preference auto-regen → expand-itinerary loop.

Manual CTA clicks may still show an informational "Plan is updating" toast when `isRegenerating=true`, but that flag is explicitly UI-only. Auto-triggered expands and queued preference regen continue to key off `currentRunId` / `expandInProgress`, not the overlay state.

**Debug Logs (expected sequence):**
```
[documentStore.setFromPlanResponse] 🛡️ Blocked view state downgrade: S3_ITINERARY_READY → S2_STRATEGY_READY (day_cards exist: 5)
[documentStore.setFromPlanResponse] 📅 Day cards: PRESERVED (itinerary exists: 5 cards)
[documentStore.mergeEnvelope] 🔄 Tiles: MERGED (same destination)
```

**Destination change sequence:**
```
[documentStore.mergeEnvelope] 🌍 Destination changed: "bali" → "london"
[documentStore.mergeEnvelope] 💬 Chat: CLEARED (destination changed)
[documentStore.mergeEnvelope] 🔄 Tiles: REPLACED (destination changed)
[documentStore.mergeEnvelope] 📝 Strategy: REPLACED (destination changed)
[documentStore.mergeEnvelope] 📅 Day Cards: CLEARED (destination changed)
[documentStore.mergeEnvelope] 📅 Day Cards: CLEARED (dates changed)
```

#### F. BookingSection Mode Awareness

The `BookingSection` component adapts rendering based on `mode` prop:

```tsx
<BookingSection
  mode="planning"  // Uses SuggestionCard, hides checkout
  // OR
  mode="booking"   // Uses TileCard, shows checkout sidebar
  ...
/>
```

| Mode | Tile Component | Checkout | Actions |
|------|----------------|----------|---------|
| PLANNING | SuggestionCard | Hidden | Save, Change, Details |
| BOOKING | TileCard | Visible | Book, Cart, Details |

**Activity Tile Metadata Display:** `TileCard`, `MiniCard`, and `TileDetailsModal` render activity-specific metadata from `tile.meta` when `tile.type === 'activity'`: category badge (uppercase pill), duration hours (clock icon), time of day (sun/sunset/moon icon), and one-sentence description (from `meta.description`). The description field is generated by `experience_generator.py` and propagated via `meta.description`.

**Smart Tab Auto-Switch:** When new tiles arrive from a backend response, the active category tab automatically switches to the tab with the biggest growth (e.g., user says "yoga and nightlife" → Activities tab auto-selects). Respects manual selection: once a user clicks a tab, auto-switch is disabled for that session. First load always defaults to Stays. Implementation: `useEffect` comparing `prevCountsRef` with current tile counts per category.

**isBooked Semantics (Planning vs Booking):**
- **PLANNING mode:** Green checkmark (`CheckCircle`) only appears for `user_preferred` tiles or user-saved tiles (via `savedTileIds`). AI-placed tiles (`booked_tile` present but no user preference) do NOT show the checkmark.
- **BOOKING mode:** Green checkmark appears when `booked_tile` exists or tile is in `savedTileIds` (legacy behavior).

#### F.1 Mode-Based Conditional Rendering (SSoT)

**CRITICAL:** Mode (`effectiveMode`) is the Single Source of Truth for which tile variant to render. State (S2, S3, etc.) should NOT be used to determine tile UI.

**The Wrong Pattern (Deprecated):**
```tsx
// DON'T: State-based conditionals
if (canShowBookingTiles(state)) {
  return <BookingManifest />  // Triggers on S3 state regardless of mode
}
```

**The Correct Pattern:**
```tsx
// DO: Mode-based conditionals
if (effectiveMode === 'planning' && totalTiles > 0 && !isGenerating(generation)) {
  return <SuggestionCards />  // PLANNING mode: hearts, no checkout
}

if (effectiveMode === 'booking') {
  return <BookingManifest />  // BOOKING mode: cart, checkout sidebar
}
```

**Why This Matters:**
- A user can have a complete itinerary (S3_ITINERARY_READY) but still be in PLANNING mode
- They're refining, comparing options, not ready to commit
- Showing checkout UI (cart, "Add to Trip", sidebar totals) is premature
- Mode transition requires explicit user action (clicking "Finalize & Unlock Booking")

**State vs Mode:**
| Concept | Purpose | Examples |
|---------|---------|----------|
| **State** (S0-S3) | Data density indicator | S3 = itinerary exists |
| **Mode** (planning/booking) | User intent indicator | booking = ready to purchase |

**Invariant:** Itinerary existence (S3 state) does NOT imply booking intent. Mode is the only valid gate for checkout UI.

#### F.3 CategorySection Mode Awareness

**File:** `components/plan/booking/CategorySection.tsx`

The `CategorySection` component (used in the manifest view) adapts its UI based on mode:

```typescript
interface CategorySectionProps {
  // ... other props
  mode?: 'planning' | 'booking';  // Determines UI variant
}
```

**Mode-Specific Behavior:**

| Element | PLANNING Mode | BOOKING Mode |
|---------|---------------|--------------|
| **Status Badge** | "❤️ Preferred" (emerald) | Cart traffic-light badge (`Available`, `In Cart`, `Booked`) |
| **Non-preferred Badge** | Hidden | "Available" badge shown |
| **Action Button (saved)** | "Preferred ❤️" | "Remove from Cart" |
| **Action Button (unsaved)** | "Add to Trip ♡" | "Add to Cart" |

**StatusBadge Logic:**
```typescript
function StatusBadge({ status, mode }) {
  if (mode === 'planning') {
    // Only show badge for preferred items
    if (status === 'hold') return <div>❤️ Preferred</div>;
    return null;  // No badge for non-preferred in planning
  }
  // Booking mode: show traffic-light cart status
  return <div>{/* inline dot + label badge ("Available" / "In Cart" / "Booked") */}</div>;
}
```

**Invariant:** Hearts (♡/❤️) are PLANNING preference signals; BOOKING mode uses cart status badges/actions.

---

## XI.G Additional Mode-Aware Components

The following components also support the two-mode system:

### 1. PlanHeader (Vertical Stack)

**File:** `components/plan/PlanHeader.tsx`

Three-state header for the right panel (desktop only — hidden on mobile).

**States:**
| State | Condition | Renders |
|-------|-----------|---------|
| Collapsed | `isCollapsed=true` | Compact bar: title + date range + status pill |
| Topo | No destination image | Animated topographic bg + "Build Your Itinerary" |
| Vertical Stack | Destination image ready | Rounded image card + `TripSummaryPills` below |

**Key props:** `destinationCard`, `planViewState`, `tripInputs`, `onOpenSheet`, `isStreaming`, `isCollapsed`

**Rules:**
- No text overlaid on images — pills below are the sole summary
- No specialist pills — Trip DNA bar handles that
- Image height: `max-h-[15vh] min-h-[120px]` (viewport-relative)
- Pills use `variant="default"` with CSS custom property theming

### 2. UnifiedChipRow (Mode-Aware Disabled State)

**File:** `components/plan/UnifiedChipRow.tsx`

Three-row semantic layout for trip inputs:

```
┌──────────────────────────────────────────────────┐
│ ROW 1: [ Destination ] [ Origin ] [ Dates ]      │  ← Trip params (h-8 desktop, h-10 mobile)
│ ROW 2: [ Travelers ] [ Budget (opt) ]             │  ← Travelers   (h-8 desktop, h-10 mobile)
│ ROW 3: [ Flights ] [ Stays ] [ Activities ]       │  ← Booking types (h-9 desktop, h-11 mobile)
└──────────────────────────────────────────────────┘
```

All chips respect the mode prop.

```typescript
interface UnifiedChipRowProps {
  // ... existing props ...
  mode?: ViewMode;  // 'planning' | 'booking'
}
```

**Behavior:**
- PLANNING mode: All chips interactive, can open sheets to edit
- BOOKING mode: All chips read-only with 60% opacity, `cursor-not-allowed`

### 3. TileDetailsModal (Mode-Specific Sections)

**File:** `components/tiles/TileDetailsModal.tsx`

Shows different content sections based on mode.

```typescript
interface TileDetailsModalProps {
  // ... existing props ...
  mode?: ViewMode;                    // 'planning' | 'booking'
  onBook?: (tile: Tile) => void;
}
```

**Behavior:**
- PLANNING mode: Shows "Why this suggestion?" section with AI reasoning and "AI Pick" badge
- BOOKING mode: Uses single external booking action (no partner comparison matrix yet)
- Deeplink CTA copy is provider-aware: Google/Maps links keep map-oriented labels, while partner links switch to booking-oriented labels (`Book`, `Book on Viator`, `Book on GYG`) and `ExternalLink` iconography.

### 4. StrategyStageRenderer (Mode Prop)

**File:** `components/plan/StrategyStageRenderer.tsx`

Main orchestrator derives mode from view navigation or accepts explicit override.

```typescript
interface StrategyStageRendererProps {
  // ... existing props ...
  mode?: ViewMode;  // Explicit override (if not using view navigation)
}
```

**Mode Derivation:**
```typescript
// Two-mode system: use activeMode from hook, allow explicit override
const effectiveMode: ViewMode = explicitMode ?? activeMode;
```

Passes `mode` to BookingSection for mode-aware tile rendering.

---

---

## XIII. Tile Provider Architecture

This section documents the provider routing strategy for fetching tiles (hotels, activities, flights).

### Overview

Both first-time requests (`logistics_node`) and regeneration (`tile_service`) use identical provider routing:

| Priority | Provider | Data Quality | Use Case |
|----------|----------|--------------|----------|
| 1 | **CuratedProvider** | 4K images, hand-picked hotels, accurate prices | Hero destinations (Dubai, Rome, Chamonix) |
| 2 | **GooglePlacesProvider** | Real place names, photos, ratings, coordinates | Live data for hotels and activities |
| 3 | **MockProvider** | Generic data, Unsplash images | Development fallback |

### Provider Files

```
backend/app/tile_service/
├── service.py            # Provider routing orchestrator
├── curated_provider.py   # Hero destination content (DEMO_MANIFEST)
├── google_places_provider.py  # Google Places integration (real names/photos)
├── mock_provider.py      # Mock data with Unsplash images
└── provider_base.py      # Provider ABC interface
```

### Routing Logic

```python
# In both logistics_node.py and tile_service/service.py:

def get_providers(destination: str) -> List[Provider]:
    dest_key = destination.lower().strip()

    # 1. CURATED FIRST - Hero destinations with perfect demo content
    if dest_key in DEMO_MANIFEST:
        return [CuratedProvider(dest_key)]

    # 2. GOOGLE PLACES SECOND - Real place names, photos, ratings
    if settings.use_google_places_provider:
        return [GooglePlacesHotelProvider(), MockFlightProvider(), GooglePlacesActivityProvider()]

    # 3. MOCK FALLBACK - Development/offline mode
    return [MockHotelProvider(), MockFlightProvider(), MockActivityProvider()]
```

### Activities are vendor-primary; hotels stay Google-Places by design

The table above is the hotel/flight base-provider order. For **activities**, partner vendors are
PRIMARY and Google Places (GP) is a fallback/gap-filler — GP is expensive, so it is minimized:

- **Activity source (logistics_node):** when a vendor is enabled (`settings.viator_enabled` /
  `get_your_guide_enabled` + key), `_safe_browse()` runs the partner cascade
  (**Viator → GYG → GP fallback**, in `activity_browser.browse_activities`) in parallel with the
  hotel fetch. If browse returns ≥ `settings.google_places_browse_min_threshold` (default 4) tiles,
  that pool becomes the base activities and the paid GP base-activity fetch is **skipped**; below the
  threshold it falls back to the GP fetch so a vendor-sparse destination never loses activities.
  GP is the base provider only when **no** vendor is enabled.
- **The LLM experience-generator tailors content to the user's request** independently of the fixed
  `TIER2_BROWSE_CATEGORIES` browse rotation — e.g. a "nightlife in Madrid" trip yields nightlife
  tiles even though `nightlife` isn't in the rotation. So the rotation does NOT need to enumerate
  every user-selectable category.
- **Hotels remain GP-primary by design.** There is no vendor hotel *search* provider (only
  `GooglePlacesHotelProvider` + `MockHotelProvider`); Booking.com is a **booking-time deeplink** only,
  not a search API. So GP stays the hotel provider.
- **GP enrichment is minimal + post-vendor.** Inline GP enrichment was removed; GP enrichment now runs
  only post-build (`coordinator._post_build_enrich_placed_activities`) on placed blocks still missing
  data after partner matching, and a GP photo URL is minted only when no vendor image exists
  (`_has_vendor_media`). Net effect: GP calls per planning turn dropped 3 → 2.

### Provider Comparison

| Aspect | CuratedProvider | GooglePlacesProvider | MockProvider |
|--------|-----------------|-----------------|--------------|
| **Hotel Names** | Hand-picked (e.g., "Atlantis The Royal") | Real API data (e.g., "Hilton Dubai Creek") | Generic (e.g., "Mock Hotel 1") |
| **Images** | Hand-picked Unsplash URLs | Signed Places photos with deterministic placeholder fallback | Auto-generated Unsplash |
| **Prices** | Curated estimates | None (Hotel List API) | Calculated mock prices |
| **Coordinates** | Hand-picked [lng, lat] | Real API data | Generated |
| **Availability** | Always "available" | "unknown" (needs separate API) | Always "available" |

### Image Strategy (Provider-First with Safe Fallbacks)

Tile and activity surfaces are no longer Unsplash-only. Hotels still fall back to deterministic placeholders, but live Google Places and partner activity images are preserved whenever the provider supplies them.

| Provider | Image Source | How |
|----------|--------------|-----|
| **Curated** | Hand-picked Unsplash URLs in DEMO_MANIFEST | `hotel.get("image")` |
| **Google Places** | Signed Places photo URL (with deterministic fallback placeholder) | Google Places provider + `get_placeholder_image(category, seed)` fallback |
| **Partner-enriched activities** | Viator/Tripadvisor or GYG CDN URL | Partner browse/enrichment preserves provider `image_url` on tiles and placed day blocks |
| **Mock** | Auto-generated Unsplash via placeholder | `get_placeholder_image(category, seed)` |

```python
# Placeholder path used when a provider does not supply an image:
from app.placeholders import get_placeholder_image

# Curated image if provided, otherwise deterministic Unsplash placeholder
image_url = hotel.get("image") or get_placeholder_image(
    category="hotel",
    seed=hotel_id,  # Same hotel ID = same Unsplash photo
)
```

**Guarantees:**
1. **Never null** - Every tile/day block should have either provider media or a deterministic placeholder URL
2. **Provider-first** - Google Places photos and partner CDN images (Tripadvisor/Viator, GetYourGuide) are preserved when available
3. **Allowlisted hosts** - Frontend image guards accept signed Places URLs plus `media.tacdn.com`, `media-cdn.tripadvisor.com`, `hare-media-cdn.tripadvisor.com`, and `cdn.getyourguide.com`
4. **Deterministic fallback** - Same tile ID/category = same placeholder image when live media is missing

### Hero Destinations (DEMO_MANIFEST)

Curated content is defined in `backend/app/data/demo_curation.py`:

| Destination | Focus | Content |
|-------------|-------|---------|
| **Dubai** | Diving | Deep Dive Dubai, Jumeirah Beach dives, luxury resorts |
| **Rome** | Culture | Historical tours, food experiences, boutique hotels |
| **Chamonix** | Skiing | Ski runs, mountain activities, alpine lodges |

Each entry includes:
- `curated_hotels[]` - Hand-picked hotels with 4K images
- `curated_flights[]` - Demo-ready flight options
- `specialist_content{}` - Activities by specialist type (diving, hiking, etc.)
- `destination_gallery[]` - Vibe Trio images for Trip DNA card

### Consistency Guarantee

| Flow | Hotels | Activities | Flights |
|------|--------|------------|---------|
| First Request (logistics_node) | Curated → Google Places → Mock | Curated → Google Places → Mock | Curated → Mock |
| Regeneration (tile_service) | Curated → Google Places → Mock | Curated → Google Places → Mock | Curated → Mock |

**Invariant:** Both flows use identical routing logic, ensuring tiles have consistent data regardless of how they were fetched.

---

## XIV. Implementation Wiring Summary

This section provides a quick reference for how the key systems are wired across the codebase.

### Provider Routing Files

| File | Purpose | Routing Logic |
|------|---------|---------------|
| `backend/app/tile_service/service.py:47-107` | Tile regeneration | `_get_providers()` - 3-tier cascade |
| `backend/app/planner/nodes/logistics_node.py` | First-time fetch | Same 3-tier cascade |
| `backend/app/tile_service/curated_provider.py` | Hero destinations | Dubai, Rome, Chamonix |
| `backend/app/tile_service/google_places_provider.py` | Real hotel/activity names | Place photos and ratings |
| `backend/app/tile_service/mock_provider.py` | Development fallback | Auto-generated Unsplash |

### Mode-Aware UI Components

| Component | File | Mode Prop | Planning UI | Booking UI |
|-----------|------|-----------|-------------|------------|
| **CategorySection** | `frontend/components/plan/booking/CategorySection.tsx:53` | `mode?: 'planning' \| 'booking'` | ❤️ Preferred / ♡ Add to Trip | In Cart / Remove from Cart |
| **BookingSection** | `frontend/components/plan/BookingSection.tsx:570` | `mode={effectiveMode}` | SuggestionCard | TileCard |
| **StatusBadge** | `frontend/components/plan/booking/CategorySection.tsx:60-102` | `mode` param | "Preferred" with heart | Traffic light badges |

### Date Validation Wiring

| Check | File | Logic |
|-------|------|-------|
| `hasDates` | `frontend/components/layout/hooks/useLandingDerived.ts` | `hasStartDate && hasEndDate` (via `hasDateRange`) |
| `canGeneratePlan` | `frontend/components/layout/hooks/useLandingDerived.ts` | `hasDestination && hasDateRange` (via `hasPlanPrerequisites`) |

### Tile Type Normalization

| Input Type | Normalized | Mapping Location |
|------------|------------|------------------|
| hotel, stay, accommodation, lodging, resort | `'hotel'` | `frontend/lib/tileSelectors.ts:123-132` |
| flight, air | `'flight'` | `frontend/lib/tileSelectors.ts:133-135` |
| activity, experience, tour, attraction, excursion | `'activity'` | `frontend/lib/tileSelectors.ts:136-144` |

### Image Fallback Chain

| Component | File | Fallback Logic |
|-----------|------|----------------|
| **TileThumbnail** | `frontend/components/plan/modals/AlternativesModal.tsx:35-58` | `onError` → `placeholderImageForTile()` |
| **CategorySection** | `frontend/components/plan/booking/CategorySection.tsx:14-35` | `onError` → `placeholderImageForTile()` |

### Title Normalization

Backend data may contain snake_case identifiers (e.g., `usat_liberty_wreck`). These MUST be normalized to natural language Title Case for display.

**Function:** `normalizeTitle()` in `frontend/lib/utils.ts`

| Input | Output |
|-------|--------|
| `usat_liberty_wreck` | USAT Liberty Wreck |
| `manta_point_nusa_penida` | Manta Point Nusa Penida |
| `crystal_bay` | Crystal Bay |
| `Already Title Case` | Already Title Case (unchanged) |

**Components applying normalization:**

| Component | Field | Location |
|-----------|-------|----------|
| `ActivityMiniCard` | `block.activity_type`, `block.summary` | `timeline/blocks/ActivityMiniCard.tsx:126` |
| `LogisticsBlock` | `hotelName` | `timeline/blocks/LogisticsBlock.tsx:105` |

**Invariant:** All user-facing titles in the itinerary timeline MUST pass through `normalizeTitle()`.

### Debug Logging

| Location | Trigger | Output |
|----------|---------|--------|
| `frontend/lib/tileSelectors.ts:161` | `type === null/undefined` | `[normalizeTileType] Received null/undefined type` |
| `frontend/lib/tileSelectors.ts:188` | Unknown type | `[normalizeTileType] Unknown type: "X"` |
| `frontend/components/plan/booking/BookingDrawer.tsx:48-52` | Dev mode filter | `[BookingDrawer] Category: X, Total: N, Matched: M` |

### Itinerary Builder Debug Flow

When debugging the S2 → S3 transition (BUILD ITINERARY flow), trace these logs:

**Backend (terminal):**

| Log | File | Indicates |
|-----|------|-----------|
| `✅ [expand-itinerary] Session & doc found` | `main.py` | Generator started successfully |
| `📊 [expand-itinerary] Input data: sections=N` | `main.py` | Data received from frontend |
| `🔥 [expand-itinerary] BUILDER CALLED` | `main.py` | Builder is about to execute |
| `[ItineraryBuilder] 🏗️ Starting build` | `itinerary_builder.py` | Builder received input |
| `[ItineraryBuilder] Extracted: activities=N` | `itinerary_builder.py` | Content parsed from sections |
| `[ItineraryBuilder] Success: N day cards` | `itinerary_builder.py` | Build completed |
| `📤 [expand-itinerary] Emitting envelope` | `main.py` | Envelope sent to frontend |

**Frontend (browser console):**

| Log | File | Indicates |
|-----|------|-----------|
| `[expand-itinerary] Received event: envelope` | `useItineraryGenerationController.ts` | Stream parser received envelope |
| `[expand-itinerary] Merging envelope` | `useItineraryGenerationController.ts` | Hook forwarding the streamed envelope into `documentStore.mergeEnvelope()` |
| `[documentStore.mergeEnvelope] 📥 Received envelope` | `documentStore.ts` | Envelope being processed |
| `hasDayCards: true, dayCardsCount: N` | `documentStore.ts` | day_cards present in envelope |
| `[documentStore.mergeEnvelope] 📤 Updated document` | `documentStore.ts` | State updated |

**Common Issues:**

| Symptom | Likely Cause | Check |
|---------|--------------|-------|
| No 🔥 log | Early return (dates/session/doc) | Check for ❌ logs before 🔥 |
| 🔥 shows but no Success | Builder error | Check `itinerary_builder.py` exception logs |
| Success but UI unchanged | Frontend state sync | Check browser console for `mergeEnvelope` logs |
| `dayCardsCount: 0` in envelope | Empty `strategy_sections` | Check 📊 log for `sections=0` |
| No `[expand-itinerary] Merging envelope` log | Frontend stream-handling issue before store merge | Check `useItineraryGenerationController.ts` logs and stale-run guards |

**Enable Debug Logging:**

Set `DEBUG=full` in `backend/.env` to see all `_debug()` output. Logs are suppressed in `demo` and `off` modes.

```bash
# backend/.env
DEBUG=full  # Shows [DEBUG] prefixed logs
```

### Zustand Selector Pattern (Critical)

When accessing store data in React components, **always use selectors** to ensure reactivity:

```typescript
// ❌ WRONG - No subscription, won't trigger re-render on changes
const documentStore = useDocumentStore();
const storeDocument = documentStore.document;

// ✅ CORRECT - Selector establishes subscription, re-renders on changes
const storeDocument = useDocumentStore((state) => state.document);
```

**Why this matters:** Without a selector, Zustand doesn't know which slice of state you're using. When `mergeEnvelope()` updates `store.document`, the component won't re-render because there's no subscription on that specific property.

**Files using this pattern:**
- `useLandingControllerStores.ts` - Aggregates granular `documentStore` and `userStore` selectors for the landing route
- `useLandingPlanState.ts` - Consumes those derived slices instead of subscribing to the whole document blob

---

### 12. Performance: Render Optimization

#### Granular Zustand Selectors (`useLandingControllerStores`)

**Problem:** A single `state.document` selector causes re-renders when ANY document field changes (tiles, day_cards, strategy_sections, etc.), cascading to all children.

**Solution:** Replace with granular selectors that subscribe to individual fields:

```typescript
// ❌ BEFORE: Single fat selector - re-renders on ANY document change
const storeDocument = useDocumentStore((state) => state.document);

// ✅ AFTER: One shallow selector object for document slices + a dedicated equality fn
const documentStore = useDocumentStore(
  useShallow((s) => ({
    storeTripInputs: s.document?.trip_inputs,
    docPlanViewState: s.document?.plan_view_state,
    docStrategySections: s.document?.strategy_sections,
    docTiles: s.document?.tiles,
    docDayCards: s.document?.day_cards,
    docGeneration: s.generation,
  }))
);
const preferredTileIds = useStoreWithEqualityFn(
  useDocumentStore,
  (s) => s.preferredTileIds,
  (a, b) => a.size === b.size && [...a].every((id) => b.has(id))
);
```

**Benefit:** When `mergeEnvelope` updates tiles, only components using `docTiles` re-render. Strategy cards and day cards remain untouched.

#### Sub-Memos in StrategyStageRenderer

**Problem:** The `planContent` useMemo has 26+ dependencies. Any dependency change recomputes 575 lines of JSX.

**Solution:** Pre-compute expensive operations in focused sub-memos:

```typescript
// MEMO 1: Display logic - changes when view state/density changes
const displayLogic = useMemo(() => {
  const hasDatesLocal = hasDates;
  const hasTilesLocal = effectiveTiles && Object.keys(effectiveTiles).length > 0;
  const density = computeDataDensity(state, viewModel.strategy_sections, effectiveTiles, hasDates);
  const isShowingMirrorLoader = generating && hasDatesLocal && !hasTilesLocal;
  return { hasDates: hasDatesLocal, hasTiles: hasTilesLocal, density, isShowingMirrorLoader, tripDuration };
}, [state, viewModel.strategy_sections, effectiveTiles, effectiveTripInputs, generating, hasDates]);

// MEMO 2: Specialist data - changes when strategy_sections change
const specialistData = useMemo(() => {
  const fullModeSections = (viewModel.strategy_sections ?? []).filter(
    section => section.feasibility_status !== 'infeasible' && section.feasibility_status !== 'caveat'
  );
  const totalConstraints = fullModeSections.reduce((acc, s) => acc + (s.constraints_applied?.length ?? 0), 0);
  return {
    fullModeSections,
    totalConstraints,
    filteredViewModel: { ...viewModel, strategy_sections: fullModeSections },
  };
}, [viewModel]);

// MEMO 3: POI extraction - MUST be isolated from planContent
// Uses fingerprint-based dependency for true content stability
const fullModePOIs = useMemo(() => {
  const destination = effectiveTripInputs?.destination ?? destinationCard?.title;
  return extractPOIsFromDayCards(
    effectiveDayCards,
    specialistData.fullModeSections,
    destination,
    dayCardsFingerprint
  );
  // eslint-disable-next-line react-hooks/exhaustive-deps
}, [dayCardsFingerprint, specialistData.fullModeSections, effectiveTripInputs?.destination, destinationCard?.title]);
```

**Benefit:**
- Density calculation only runs when state/tiles/tripInputs change
- Specialist filtering only runs when strategy_sections change
- POI extraction only runs when fingerprint changes (~3-4 times, not ~50)
- `extractPOIsFromDayCards()` adds a second-level memo cache (`fingerprint + destination`) to reuse computed POIs across repeated renders
- planContent uses pre-computed values → fewer unnecessary recomputes

#### Content-Based Fingerprints for Stable Dependencies

**Problem:** Zustand selectors like `s.document?.day_cards` return new array references on every `mergeEnvelope` update, even when array contents are unchanged. `useShallow` doesn't help because it compares array element **references**, not content.

**Solution:** Create a content-based "fingerprint" selector that only changes when actual content changes:

```typescript
// ❌ BEFORE: useShallow doesn't help - elements are new objects on each update
const storeDayCards = useDocumentStore(useShallow((s) => s.document?.day_cards));

// ✅ AFTER: Fingerprint logic extracted to strategyStagePoi.ts
const dayCardsFingerprint = useMemo(
  () => buildDayCardsFingerprint(storeDayCardsRaw),
  [storeDayCardsRaw]
);

// Use fingerprint as dependency, actual data in computation
const fullModePOIs = useMemo(() => {
  if (!dayCardsFingerprint) return [];
  const destination = effectiveTripInputs?.destination ?? destinationTitle;
  return extractPOIsFromDayCards(
    effectiveDayCards,
    specialistData.fullModeSections,
    destination,
    dayCardsFingerprint,
    destinationCoords
  );
}, [
  dayCardsFingerprint,
  effectiveTripInputs?.destination,
  destinationTitle,
  effectiveDayCards,
  specialistData,
  destinationCoords,
]);
```

**Key Insight:** `useShallow` alone is NOT sufficient. If the memoized computation is inside a larger `useMemo` with many dependencies, it still runs on every dependency change. Extract expensive operations into their OWN `useMemo` with minimal deps, and move reusable fingerprint/snapshot logic into helpers such as `strategyStagePoi.ts`.

#### Callback Stability

Callbacks passed to planContent's dependency array should be stable:

| Callback | Source | Stability |
|----------|--------|-----------|
| `onExpandToItinerary` | `useCallback` in `useLandingPlanState` / `useItineraryGeneration` | ✅ Stable |
| `onBuildPlan` | `useCallback` in `useLandingPlanState` | ✅ Stable |
| `onFinalizePlan` | `useCallback` in `useLandingPlanState` | ✅ Stable |
| `onSelectNights` | `useCallback` in `useLandingPlanState` / `useItineraryGeneration` | ✅ Stable |
| `toggleTilePreference` | Zustand store action | ✅ Stable |
| `openSheet` | `useSheetManager` hook | ✅ Stable |

**Rule:** Do NOT add new inline arrow functions to StrategyStageRenderer props unless they're excluded from planContent dependencies.

---

### 13. Cross-Reference

* **Visual Tokens:** See `design-system.md` for colors, typography, and materials.
* **Data Density:** See Section VII for density computation logic.
* **Backend SSoT:** See `plan_graph_analysis.md` for node architecture.
* **Performance:** See Section 12 for render optimization patterns.
