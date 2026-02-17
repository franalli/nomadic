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

#### Phase 1: Initial Input (Destination Only)
* **Trigger:** User mentions destination (e.g., "I want to go to Bali")
* **UI Shows:**
  * Hero image of destination
  * Specialist strategy cards (diving, local expert, etc.)
  * Progress indicator: "Add dates to see itinerary"
  * Map with static destination pin (POIs from specialists deferred)
* **Tiles:** HIDDEN (no prices without dates)

#### Phase 2: After Dates Added
* **Trigger:** User provides dates (e.g., "April 15-25")
* **UI Shows:**
  * Day-by-day itinerary auto-generates
  * Map shows day markers (route lines deferred to post-MVP)
  * Suggested hotels/flights/activities appear in timeline
  * Strategy cards compact into "Trip DNA" bar
  * "Proceed to Booking" button appears at bottom
* **Tiles:** VISIBLE as suggestions (not for booking yet)

#### Phase 3: Refinement
* **User Can:**
  * Modify suggestions ("Change hotel")
  * Adjust itinerary via chat
  * Save items to shortlist
* **Exit:** Click "Proceed to Booking" to enter BOOKING mode

### BOOKING Mode ("The Commitment")

* **Goal:** Transaction + price comparison
* **Trigger:** User clicks "Proceed to Booking" (HARD gate - explicit action required)
* **UI Shows:**
  * Read-only itinerary summary
  * Price comparison across booking partners (Booking.com, Expedia, etc.)
  * "Book Now" CTAs for each item
  * Checkout flow with guest details + Stripe payment
* **Tiles:** BOOKABLE with partner deeplinks

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
│  SECTION 1: Specialist Strategy Cards           │  ← Phase 1+
│  (Collapsed by default, expandable)             │
├─────────────────────────────────────────────────┤
│  SECTION 2: Tile Browser (full width)           │  ← Phase 2+
│  Hotels, Flights, Activities with heart actions │
│  Heart = preference signal for AI weighting     │
│  Component: BookingSection.tsx                  │
├─────────────────────────────────────────────────┤
│  Build Itinerary CTA                           │  ← Shows when dates set
│  Triggers itinerary generation                 │
│  Component: StrategyStageRenderer.tsx          │
└─────────────────────────────────────────────────┘
```

**Post-Generation (P3+) - Desktop: Content + Fixed Map Sidebar**
```
┌─────────────────────────────────┬──────────────┐
│  LEFT COLUMN (flex-1)           │  RIGHT       │
│  min: 720px, max: 900px         │  fixed 400px │
│  ┌────────────────────────────┐ │  max: 35vw   │
│  │ SECTION 1: Specialists     │ │  ┌─────────┐ │
│  │ (Collapsed cards)          │ │  │         │ │
│  ├────────────────────────────┤ │  │   MAP   │ │
│  │ SECTION 2: Tile Browser    │ │  │  sticky │ │
│  │ (Hotels, Flights, etc.)    │ │  │  top-20 │ │
│  ├────────────────────────────┤ │  │  400px  │ │
│  │ SECTION 3: Timeline        │ │  │  height │ │
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
│  MAP (300px height, inline, non-sticky)         │
├─────────────────────────────────────────────────┤
│  SECTION 3: Timeline                            │
└─────────────────────────────────────────────────┘
```

### Supporting Hooks

| Component | File | Purpose |
|-----------|------|---------|
| usePreferenceAutoRegen | `hooks/usePreferenceAutoRegen.ts` | Auto-triggers itinerary regeneration when preferences (hearts) change (1.5s debounce to batch rapid toggles, AbortController cancels stale regens, deferred during active streaming) |

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
| With Destination (full mode) | Fixed 400px width (max 35vw), sticky `top-0`, full viewport height (`h-screen`), destination pin centered | 300px height, inline before timeline (only when POIs exist) |
| With Destination (bridge mode) | Fixed 350px width, sticky `top-4`, 400px height, destination pin or POIs | Hidden |
| No Destination | Hidden | Hidden |

**Map Content:**
- Map centered on POIs via `calculateMapCenter()` (zoom derived from POI spread)
- Falls back to world view (`lat: 20, lng: 0, zoom: 2`) when no POIs available
- Falls back to `DestinationMapPlaceholder` in bridge mode when no POIs found
- **POI Pins:** Activity markers from `extractPOIsFromSections()` in `ghost-timeline-adapter.ts`
  - Extracts coordinates from strategy section tiles and activities
  - **Destination fallback chain:** `effectiveTripInputs?.destination ?? destinationCard?.title`
  - **Demo Fallback:** Uses curated `DEMO_POIS` from `destination-coords.ts` when no POIs extracted
    - Normalization: `destination.split(',')[0].trim().toLowerCase()` then capitalize
    - Bali has 5 demo pins: 3 dive sites + 2 hiking trails
  - POI format: `{ lat, lng }` object (not array)
  - All POI coordinates validated via `_normalizeMapCoordinates()` (rejects non-finite or out-of-range values)

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
| Tiles fade-in | Tiles fetched | 300ms | Opacity 0→1 |
| Timeline fade-in | Itinerary ready (day_cards exist) | 500ms | Opacity + translateY 20→0 |
| Map fade-in | Destination set | 300ms | Opacity 0→1 (simple fade) |
| NextStepBar slide-up | S2+ | Spring | Slide up from bottom |

#### Spring Physics
All interactive animations use spring physics:
- **SLIDE config:** `{ stiffness: 400, damping: 30 }` - for slide animations
- **EXPAND config:** `{ stiffness: 300, damping: 25 }` - for card expansions

#### State-Based Reveals

> **Note:** In practice, the backend emits S* states (not P* directly), and `computeDataDensity()` maps to `empty`/`ghost`/`bridge`/`full` density levels. The P* phases below are conceptual guides for what renders at each density.

```
empty (no specialist content)
├─ Hero + chips (PlanHeader topo background)
└─ Map hidden

ghost (specialist content, no tiles)
├─ Hero + chips
├─ Specialists (collapsed by default)
├─ Ghost timeline (specialist preview)
└─ Map (fade in, desktop only, destination pin) ← AnimatePresence

bridge (specialist content, no tiles, S2_STRATEGY_READY)
├─ Strategy cards
└─ Map (bridge mode: 350px fixed, desktop only) ← AnimatePresence

full (tiles exist or P3)
├─ Strategy cards (collapsible in S3)
├─ Tiles (fade in, 300ms) ← AnimatePresence
├─ Timeline (fade in, 500ms) ← AnimatePresence + auto-scroll (when day_cards exist)
└─ Map (full mode: 400px fixed, desktop, h-screen sticky) ← AnimatePresence
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
- **Map:** 300px inline block, no slide animation

#### Loading States

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
- `StrategyStageRenderer.tsx` uses conditional layout:
  - **No Destination:** Single column `<div className="flex flex-col w-full">`
  - **With Destination (Desktop):** Content (flex-1, min 720px, max 900px) + Map (fixed 400px, max 35vw)
  - **With Destination (Mobile):** Single column with inline map (300px height, shown after itinerary)
- Desktop map visibility controlled by `showDesktopMap = isDesktop && fullModeMapItems.length > 0` (shows when POIs exist from day_cards or strategy sections)
- Mobile map only shows when `hasItineraryContent && fullModePOIs.length > 0` (not just destination pin)
- Timeline section conditionally renders when `hasItineraryContent === true`
- Mode prop threads through TimelineThread → ActivityMiniCard for Book button visibility
- Preference attribution uses `preferredTileIds` to show "You preferred this" badge
- Legacy stage views (S3ItineraryView, S1FramingView, etc.) removed from unified flow
- Only S2StrategyView used for specialist cards in all phases

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
1. User hearts tiles via `SuggestionCard`, `TileCard`, or `BookableCard`
2. All heart clicks route through `documentStore.toggleTilePreference()`
3. For hotels: clears existing hotel preference (single-select enforcement)
4. `preferredTileIds` stored in Zustand + persisted to DB via PATCH `/api/document` (with 409 conflict retry)
5. On page refresh, `fetchDocument()` hydrates `preferredTileIds` from DB
6. On auto-regen trigger (instant after preference change via `usePreferenceAutoRegen`):
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
│  Frontend: NomadicLanding.tsx (proceedWithItineraryGeneration)  │
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
2. Backend graph runs (IntentRouter → LogisticsNode/Specialist → Synthesizer)
3. Graph completes → SSE `onComplete` handler checks:
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

**Graph-Built Itinerary Skip:** When the graph response includes `day_cards` (builder ran inside `format_result` during graph execution), the SSE `onComplete` handler skips `expand-itinerary` entirely (`expandPath = 'GRAPH_BUILT'`). The itinerary is already up-to-date — a redundant expand would waste a round-trip. `structuralRebuildTriggered` is still set to `true` so downstream logic (e.g., scroll-to-itinerary) fires correctly.

**Example flows:**
- "from rome" with existing plan → Flights added (tiles only) → **No auto-expand** → Itinerary preserved
- "add hiking" with itinerary → Hiking specialist runs (structure change) → Itinerary auto-updates
- "thanks" acknowledgment → No plan changes → No auto-expand
- "tell me about diving" with dates → Graph builds itinerary → `GRAPH_BUILT` skip → No expand needed

**Origin-only handling:**
- "from rome" without destination → Sets origin, prompts for destination (IntentRouter)
- "from rome" with destination → Sets origin, routes to LogisticsNode, fetches flights immediately

**FAB Suppression for Chat Changes:**
Chat-originated changes update `trip_inputs` (e.g., origin from "from rome"). The chat auto-regeneration flow handles these changes automatically without manual user intervention.

**trip_inputs in POST body:**
Every chat message includes `trip_inputs` in the POST body (not just generate triggers). The backend
hydrates session state from the document before graph execution, using the document as SSoT for
user-owned settings (`activity_settings`, `hotel_settings`, `flight_settings`, `transport_settings`,
`booking_types`). Session values cannot override these fields.
See `plan_graph_analysis.md` > Settings Ownership & Document Merge.

**Files:**
- `ChatPanel.tsx` - Calls `onChatTripInputsUpdated` in SSE `onComplete`; always sends `trip_inputs` in POST
- `NomadicLanding.tsx` - Handles regeneration via `proceedWithItineraryGeneration`

#### Chip/Settings Regeneration

**Trigger:** User changes destination, dates, origin, or settings via chip bar or settings sheets

**Flow:**
1. User modifies trip inputs (e.g., changes destination chip from "Bali" to "Paris")
2. `updateTripInputs()` writes to store **synchronously** (tiles NOT cleared - old content stays visible)
3. GENERATE_PLAN_TRIGGER sent via chat system
4. Backend forces tile cache clear → fetches fresh tiles
5. New itinerary generates automatically

**Preference sheet auto-regeneration:**
When the user saves activity or hotel preferences via the Activities/Stays sheets while a plan is active
(S2/S3), the sheet save handler:
1. Calls `documentStore.updateTripInputs()` immediately (bypasses 300ms debounce)
2. Sends `GENERATE_PLAN_TRIGGER` to re-run the graph with updated preferences
3. Backend detects constraint hash change → specialists re-run with new settings

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

**Component:** `usePreferenceAutoRegen` - Hook managing auto-regeneration for preference changes

**Flow:**
1. User hearts a hotel → preference change detected
2. **1.5s debounce** to batch rapid heart toggles into a single expand call
3. Auto-calls `/api/expand-itinerary` with current preferences
4. Itinerary rebuilds with new preference weighting
5. `markPreferencesAsApplied()` updates last-generated state

**Cascade Prevention Guards:**
```typescript
// Guard 1: Skip if regeneration already running (in triggerRegeneration)
if (useDocumentStore.getState().isRegenerating) return;

// Guard 2: Skip if expand-itinerary already running (in triggerRegeneration)
if (useDocumentStore.getState().expandInProgress) return;

// Guard 3: Skip in useEffect if expand or streaming in progress (queued, not dropped)
if (expandInProgress || isStreamingResponse) {
  pendingRegenRef.current = true;
  lastPrefsRef.current = new Set(preferredTileIds);
  return;  // Queue for later, flush when mutex releases
}
```

**State tracking:**
- `documentStore.preferredTileIds` - Current preferences (Set)
- `documentStore.lastGeneratedPreferences` - Preferences at last generation
- `documentStore.expandInProgress` - Mutex flag for expand-itinerary calls
- `markPreferencesAsApplied()` - Snapshots current preferences after regeneration (compares `preferredTileIds` vs `lastGeneratedPreferences` inline to detect changes)

**Visual feedback:**
- Specialist section shows "Updating itinerary..." overlay during regeneration (`isRegenUpdating`)
- Timeline dims with black overlay + "Updating with N preferences..." spinner
- Attribution badges show preference vs AI selection

**Selective regeneration (backend):**
- @see `docs/plan_graph_analysis.md` Section 11 - Selective Regeneration
- Preference-only changes use `BUILDER` strategy (~100ms)
- Trip input changes trigger appropriate strategy based on changed fields

**Backend cache invalidation:**
When GENERATE_PLAN_NOW trigger is received, `intent_router.py` forces tile cache clear:
```python
# intent_router.py - on GENERATE_PLAN_NOW (Refresh button)
elif is_generate_trigger:
    state.intent = "booking"
    # FORCE clear tiles on GENERATE_PLAN_NOW (Refresh button)
    state.tiles = {}
    state.metadata["tiles_destination"] = None
    logger.info("[Router] 🔥 GENERATE_PLAN_NOW - forced tile cache clear")
```

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

### Empty Specialist Card Filtering

**Problem:** When a specialist (e.g., skiing) runs but returns no useful content for a destination (e.g., Bali), an empty card appears in the UI. This looks broken.

**Solution:** Filter specialist cards on **output** (content_added), not **input** (specialist requested). This is destination-agnostic and handles every case.

**Location:** `S2StrategyView.tsx`

```typescript
// Filter out domain specialists with no content (e.g., skiing in tropical destinations)
const strategy_sections = rawStrategySections.filter((section) => {
  // Always show general/local_expert sections (they have context even without activities)
  const isGeneralType = ['general', 'local_expert'].includes(section.specialist_type || '');
  if (isGeneralType) return true;
  // For niche specialists, only show if they returned content
  return section.content_added && section.content_added.length > 0;
});
```

**Why frontend filtering?** A backend hardcoded `SKIING_EXCLUDED_DESTINATIONS` set creates a maintenance trap — silently fails for any destination not in the list. Frontend filter on output works everywhere.

**Verify:** Search "Bali hiking and skiing" → skiing card should NOT appear (no skiing content for Bali).

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
  severity: 'warning' | 'info' | 'success';
  icon: string;                         // Emoji (⚠️, ℹ️, ✅)
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

**File:** `frontend/components/plan/StrategyStageRenderer.tsx`

### Architecture (Consolidated)
```
┌─────────────────────────────────────────────────────────────────┐
│  UI Components                                                   │
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐               │
│  │SuggestionCard│ │  TileCard   │ │BookableCard │               │
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

### In BOOKING Mode: Price Comparison
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

## I.C Planning Phases (Progressive Density)

The backend emits **planning phases** (not UI modes) based on data density:

### Planning Phase Progression

| Phase | Data State | UI Shows | Chat Status Header |
|-------|-----------|----------|--------------------|
| `P0_MINIMAL` | Destination only, no specialists | Hero image, empty timeline | "Your trip is taking shape" · REFINE PLAN |
| `P1_ENRICHED` | Specialists run, strategy sections present | Strategy cards, ghost timeline | "Your trip is taking shape" · REFINE PLAN |
| `P2_LOGISTICS` | Tiles fetched, suggestions available | Tile browser + strategy cards | "Your trip is taking shape" · REFINE PLAN |
| `P3_FINALIZED` | Itinerary validated, ready to book | Complete itinerary, "Proceed to Booking" | "Itinerary complete" · READY |

> **Note:** `P2_LOGISTICS` is defined in the `PlanViewState` type but never emitted by the backend or used in rendering logic. The frontend's `computeDataDensity()` function determines rendering based on data availability (tiles, specialist content), not on P2 explicitly. `P2.5_PREFERENCE` was a conceptual phase and does not exist in code.

### Legacy Mapping (Coexistence)

> **NOTE:** The S0-S3 states coexist with P0-P3 for pragmatic reasons.
> Backend emits S* states; frontend maps them to P* for rendering decisions.
> This avoids a large migration while keeping the mental model clear.

| Legacy State | Maps To | Reason |
|--------------|---------|--------|
| `S0_EMPTY` | *(falls through to default)* | Reset state (frontend-only, used for "start over" intent). Not handled by `normalizePlanViewState` -- stays as `S0_EMPTY`. |
| `S0_BOOTSTRAP` | `P0_MINIMAL` | No data yet |
| `S1_FRAMING` | `P0_MINIMAL` | Merged into P0 |
| `S1_DESTINATION_SET` | *(falls through to default)* | Frontend-only state in `VIEW_STATE_ORDER` for downgrade protection. Not mapped by `normalizePlanViewState`. |
| `S2_STRATEGY_READY` | `P1_ENRICHED` | Specialists have run |
| `S2_BLOCKED` | `P1_ENRICHED` | Handled by data checks |
| `S3_ITINERARY_READY` | `P3_FINALIZED` | Itinerary complete |
| `S3_EDITING` | `P3_EDITING` | User editing itinerary |
| `S3_BLOCKED` | `P3_BLOCKED` | Itinerary blocked |
| `S3_PARTIAL_CONFLICT` | `P3_BLOCKED` | Partial timeline with unschedulable blocks. Emitted by backend itinerary build paths on partial-failure results. |

---

## II. The "Single Renderer" Pattern

We do not swap `SetupView` for `PlanView`. We use a single **`StrategyStageRenderer`** that adapts based on data density (`computeDataDensity()`).

```tsx
<StrategyStageRenderer>
  {/* SECTION 1: SPECIALISTS (via S2StrategyView) */}
  <S2StrategyView ... />

  {/* SECTION 2: TILE BROWSER */}
  {hasTiles && <BookingSection ... />}

  {/* SECTION 3: TIMELINE (conditional on hasItineraryContent) */}
  {hasItineraryContent && <TimelineThread variant={computeTimelineVariant(state)} />}
</StrategyStageRenderer>
```

> **Note:** The component file is `StrategyStageRenderer.tsx`, not `UnifiedStageRenderer`. There is no `UnifiedStageRenderer` component in the codebase.

---

## III. Backend State Logic (`response_envelope.py`)

The backend dictates the Planning Phase based on data density. The primary function is `_compute_plan_view_state()` in `response_envelope.py`.

**Primary envelope base logic (`_compute_plan_view_state`):**

| Logic Check | State Output | Explanation |
| --- | --- | --- |
| `tiles` exist (any category non-empty) | `S2_STRATEGY_READY` | **Full logistics mode.** Dates set, real prices available. |
| `specialist_content` exists (non-general/null sections) | `S2_STRATEGY_READY` | **Bridge State.** Strategy cards + ghost timeline before dates. |
| Neither tiles nor specialist content | `S0_BOOTSTRAP` | **Blank slate.** Setup checklist, no specialist content. |

> **Note:** `_compute_plan_view_state()` still emits the base states (`S0_BOOTSTRAP`, `S2_STRATEGY_READY`). Stage-3 states are then resolved from itinerary output shape: `S3_ITINERARY_READY` (success/no conflicts), `S3_EDITING` (success/with conflicts), `S3_PARTIAL_CONFLICT` (failure/partial with conflicts). This applies to both graph shadow-builder output and NDJSON itinerary endpoints.

### Itinerary Generation State Transition

When the user has dates and tiles, clicking "BUILD ITINERARY" triggers the `ItineraryBuilder` service:

```
P1_ENRICHED → P2_LOGISTICS → BUILD ITINERARY → P3_FINALIZED
                                    │
                          ItineraryBuilder.build()
                                    │
                          ┌─── Success → day_cards rendered (S3_ITINERARY_READY)
                          └─── Conflict → partial day_cards rendered (S3_PARTIAL_CONFLICT)
```

**Conflict Resolution Flow (Chat-Driven):**

When the builder fails (trip too short for all specialists), `response_envelope` stores `last_builder_success = False` + `last_builder_resolutions` in state metadata. On the next chat turn, the constraint guard re-surfaces the blocking violation (instead of suppressing it), and the synthesizer generates resolution suggestion chips (e.g., "Extend to Mar 12", "Remove hiking"). Partial `day_cards` (what CAN fit) auto-render at `S3_PARTIAL_CONFLICT` immediately.

**Invariant:** User is NEVER left with silently dropped activities. All conflicts are surfaced via suggestion chips with actionable resolutions.

---

## III.A Local Expert Always First (Trip DNA Anchor)

**CRITICAL INVARIANT:** The Local Expert node MUST always run FIRST, regardless of whether niche specialists (diving, hiking, skiing) are also active.

### Rationale

The Local Expert generates the "Trip Overview" card (Trip DNA) which provides:
1. **Destination Context:** Vibes, culture, local tips
2. **Visual Anchor:** Images for the Magazine Layout (Vibe Grid)
3. **Trip Parameters:** Destination, Dates, Travelers summary

Without this anchor, the UI shows only niche specialist content (e.g., diving constraints) without the broader destination context.

### Specialist Queue Pattern

When a user says "diving in Bali tomorrow":

```
IntentRouter detects: diving
Queue built: [local_expert, diving]  ← Local Expert FIRST

Flow:
1. Router → Local Expert (generates Trip Overview)
2. Local Expert → Vertical Specialist (generates Diving Strategy)
3. Specialist → Logistics (fetches tiles)
```

**Result:** UI shows TWO strategy cards:
1. **Trip Overview** (general): Bali destination vibes, local tips
2. **Diving Strategy** (niche): Safety constraints, dive site recommendations

### Implementation

```python
# In intent_router.py - ALWAYS prepend local_expert to specialist queue
if specialist_hints:
    if "local_expert" not in specialist_hints:
        all_specialists = ["local_expert"] + specialist_hints
    else:
        all_specialists = ["local_expert"] + [s for s in specialist_hints if s != "local_expert"]

    state.pending_specialists = all_specialists[1:]  # Rest of queue
    state.active_specialist = all_specialists[0]     # Should be "local_expert"
```

### Invariants

1. **Local Expert runs before ANY niche specialist** - even if user only mentions "diving"
2. **Multi-specialist batch processing** - all niche specialists are processed in a single graph entry via `_merge_specialist_into_state()` loop (no graph re-entry per specialist)
3. **Trip Overview card is NEVER missing** - this is the visual anchor for the right panel

### Multi-Specialist Display

When multiple specialists run (e.g., "diving and hiking in Bali"), the frontend renders:

**Strategy Card Stack:**
```
┌─────────────────────────────────────────┐
│ 🏝️ Local Expert • 5 Rules              │ ← Always first (Trip DNA anchor)
├─────────────────────────────────────────┤
│ 🤿 Diving • 3 Rules                     │ ← Specialist 1
├─────────────────────────────────────────┤
│ 🥾 Hiking • 2 Rules                     │ ← Specialist 2
└─────────────────────────────────────────┘
```

**Staggered Auto-Expand Animation:**
- T+0ms: Diving card slides in, auto-expands (2.5s)
- T+2.5s: Diving card collapses
- T+3.0s: Hiking card slides in, auto-expands (2.5s)
- T+5.5s: Hiking card collapses

**Key:** Stagger animations - don't expand both simultaneously (visual chaos).

**Timeline Color-Coding:**

Each activity block shows a 4px colored left-border indicating its specialist source:

| Specialist | Border Color | Hex |
|------------|--------------|-----|
| `local_expert` | Neutral Gray | `#6B7280` |
| `diving` | Ocean Blue | `#0EA5E9` |
| `hiking` | Forest Green | `#10B981` |
| `skiing` | Snow Blue | `#3B82F6` |
| `cycling` | Lime | `#84CC16` |
| `surfing` | Indigo | `#6366F1` |
| `climbing` | Orange | `#F97316` |
| `sailing` | Cyan | `#06B6D4` |
| `wildlife_safari` | Amber | `#D97706` |

**Visual Treatment:**
- 4px colored left-border on each block
- Icon color matches specialist
- Card background remains neutral white

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
Timeline auto-scrolls to Day 4
↓
Day 4 card briefly highlights (ring-2 ring-emerald-500)
↓
Highlight fades after 2 seconds
```

### Route Visualization

**GeoJSON LineString** connects day locations:
- Color: `#10b981` (emerald-500)
- Style: Dashed (`line-dasharray: [2, 1]`)
- Opacity: 0.7
- Day-based coloring (optional)

### Layer Filters

> **Deleted:** `MapLayerFilter.tsx` has been removed. Layer filtering is now handled internally by `InteractiveMap.tsx` via the `visibleLayers` prop (a `Set<string>` passed by the parent). No standalone filter UI component exists currently.

### Implementation

`InteractiveMap.tsx` validates all coordinates internally via `normalizeMapCoordinates()` (rejects non-finite, out-of-range, or missing values). `ghost-timeline-adapter.ts` applies equivalent validation via `_normalizeMapCoordinates()` when extracting POIs from strategy sections.

**Data Sources:**
- `DayCard.blocks[].coordinates` - Itinerary locations
- `StrategySection.content_added[].coordinates` - Specialist POIs

### Invariants

1. **Map updates on scroll** - IntersectionObserver tracks visible timeline items
2. **Click triggers scroll** - Clicking pin scrolls timeline to matching item
3. **Route only in PLAN mode** - No route line for POI-only views
4. **Day filter persists** - Hovering day filters map to that day's pins only
5. **Coordinate validation** - Both `InteractiveMap` and `ghost-timeline-adapter` validate coordinates before rendering (finite, |lat|<=90, |lng|<=180)

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

Suggestion chips are generated by `generate_suggestions()` in `synthesizer.py`, which reads
router capability registries (`SPECIALIST_KEYWORDS`, `QUESTION_TYPE_MAPPING`, `SuggestionPool`)
and derives up to 3 executable suggestions based on current state. No hardcoded question-type
mappings — adding a new question type to `SUGGESTABLE_QUESTION_TYPES` in `intent_router.py`
automatically generates the corresponding chip.

**Chip Metadata (`suggested_response_meta`):** Each chip has a parallel `SuggestionChipMeta` entry
with `chip_type` (`"cta"` | `"follow_up"` | `"setting"`), `category`, and optional `icon` (Lucide name).
The frontend uses metadata for CTA styling (emerald accent) with regex fallback for backward compatibility.
Metadata is stored on `state.metadata["suggestion_chip_meta"]` during generation and passed through
`response_envelope.py` as `suggested_response_meta`.

**Structured Chips (`suggestion_chips`):** A parallel `SuggestionChip[]` array with action routing. Each chip includes `action_type` (`"send_message"` | `"open_pill"` | `"trigger_action"`) and `action_target` (e.g., `"dates"`, `"budget"`, `"travelers"`). The `PILL_ACTION_MAP` in `synthesizer.py` maps chip categories to actions: date chips open the date picker, booking chips open their respective sheets, and direct-flight preference chips can trigger `set_direct_flights_only` without sending chat text. Frontend `ChatPanel` reads `suggestion_chips` for action routing when available, falling back to `suggested_responses` + `suggested_response_meta` for backward compatibility.

| State | Example Chips |
|-------|---------------|
| No destination | "I want a beach vacation", "mountain adventure", "city break" |
| Has destination, no dates | Concrete date ranges: "{Mon DD}-{DD}", "{Mon DD}-{DD}", "{Mon DD}-{DD}" (next weekend, next month week, mid-month week) |
| Has destination, month detected | "{Month} 1-8", "{Month} 10-17", "I'm flexible on dates" |
| S2+ (active plan, dates set) | "5-star hotels only", "Direct flights only", "What are must-do activities?" |
| After specialist ran | Cross-sell other specialists, plan progression, question chips |
| Budget blocking violation | "Increase budget to $X", "Find cheaper {category}", "Fewer activity days" |
| Route violation | "Back to {destination}", "Different city", "Help me choose" |
| Blocking violation | "Extend to {date}", "Add buffer day between activities", "Remove {specialist}" |
| Day preference overflow | "Reduce {activity} to N days" (from `DAY_PREFERENCE_EXCEEDS_CAPACITY`) |

**S2+ Plan Progression:** Once dates are set, chips shift from exploration questions to plan-refinement actions.
`_build_plan_progression_suggestions()` checks which settings are unconfigured (hotel stars, flight preferences,
activity categories) and generates corresponding chips at priority 4 — above exploration questions (P6) but below
specialist cross-sell (P3). As preferences are set, those chips are removed and exploration questions backfill.

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

**Backend:** `intent_router.py` - `generate_comprehensive_answer()`, `_format_section_answer()`
**State tracking:** `state.metadata["short_circuit_type"] = "exploration"` or `"soft_transition"`

### UI Components for Exploration → Planning Transition

> **Note:** `ExplorationProgress` and `ReadyToPlanBanner` have been deleted from the codebase. The exploration-to-planning transition is now handled entirely by suggestion chips generated by the synthesizer (see chip state table above). Suggestion chips shift from exploration questions to plan-refinement actions once dates are set.

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
Backend AUTO-ROUTES to LogisticsNode (no click needed)
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

**Backend (`plan_graph.py`):**
```python
# NOTE: Conceptual simplification. The actual implementation in plan_graph.py
# handles additional cases including specialist dispatch, local expert rules,
# and speculative intent routing.
def route_after_architect(state: GraphState) -> str:
    # If dates were just extracted, auto-trigger logistics search
    if state.trip_inputs_changed and state.trip_plan.start_date:
        return "logistics"  # AUTO-FETCH flights/hotels
    return "synthesizer"
```

### Critical Invariants

1. **Dates = Search Trigger:** Providing valid dates MUST automatically trigger the `LogisticsNode`. Do NOT wait for a secondary click.
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

---

## VII. Data Density Levels

The renderer uses data density to determine what to show:

| Density | Condition | Renders |
| --- | --- | --- |
| `empty` | P0 + no specialist content | Topo background + "Build Your Itinerary" tagline (PlanHeader, desktop only) |
| `ghost` | P0 + specialist content | Strategy cards + ghost timeline |
| `bridge` | P1 + specialist + no tiles | Strategy cards + POI map (no ghost timeline in bridge mode) |
| `full` | P1+ with tiles, or P3 | Strategy cards + real timeline + tiles + full map |

> **Note:** Bridge mode does NOT require "no dates". The dates condition was deliberately removed (see `computeDataDensity()` CRITICAL FIX comment) so that strategy cards remain visible while waiting for tile fetch after dates are set but before origin triggers logistics. Bridge mode persists until tiles arrive.

**Map POI extraction:** Only runs when `dayCardsFingerprint` changes (content-based proxy using block IDs with coordinates). The `effectiveDayCards` reference is stabilized via a ref that only updates on fingerprint change, preventing spurious re-renders from `mergeEnvelope` creating new DayCard objects. Map uses `fitBounds` with responsive padding (desktop: 40px, mobile: 20px) and `maxZoom: 12` / `minZoom: 7`.

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
│   └── activity_settings: ActivitySettings # { categories, skill_level }
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
│   # S0_BOOTSTRAP | S1_FRAMING | S2_STRATEGY_READY | S3_ITINERARY_READY | ...
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
│       ├── title: string                   # "Arrival Day"
│       ├── subtitle?: string              # Explanatory context (e.g., buffer_reason)
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
| `tiles` | ✅ Yes | ✅ Yes | Amadeus/Curated providers |
| `strategy_sections` | ✅ Yes | ✅ Yes | Specialist nodes |
| `day_cards` | ✅ Yes | ✅ Yes | Itinerary builder |
| `plan_view_state` | ✅ Yes | ✅ Yes | State machine (reconciled on hydration) |
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
    ├── Check session expiration (24hr max)
    │   └── If expired → Clear state, start fresh
    │
    ├── GET /api/document
    │   └── Returns full PlanDocumentData from DB
    │
    ├── fetchDocument() upward reconciliation
    │   ├── day_cards exist + state < S3:
    │   │   ├── constraint_violations empty → promote to S3_ITINERARY_READY
    │   │   └── constraint_violations present → promote to S3_EDITING
    │   ├── strategy_sections exist + state < S2 → promote to S2_STRATEGY_READY
    │   └── Guards: skip BLOCKED states, skip existing S3 variants
    │
    ├── documentStore.set({ document: reconciledDocument })
    │   └── Zustand store populated (with reconciled plan_view_state)
    │
    └── StrategyStageRenderer reads from store
        ├── viewModel = useDocumentStore(s => s.document)
        ├── tiles = useDocumentStore(s => s.document?.tiles)
        └── Renders: Specialists → Tiles → Timeline
```

**`itinerary_day_cards` mapping:** The backend `format_result()` returns `itinerary_day_cards` when the graph-built itinerary runs during `format_result`. `setFromPlanResponse()` maps this to `day_cards` for frontend consumption (`rawDoc.itinerary_day_cards` -> `rawDoc.day_cards`).

### Backend Persistence Points

| Endpoint | Function | When Called | Fields Persisted |
|----------|----------|-------------|------------------|
| `POST /api/graph_plan/stream` | `apply_planner_update()` | Streaming chat | All |
| `POST /api/expand-itinerary/stream` | `apply_planner_update()` | Build Itinerary CTA | `day_cards`, `plan_view_state` |
| `PATCH /api/document` | `apply_user_patch()` | Tile selection, settings sheets | `branches.selections`, `trip_inputs.*_settings` |

### Implementation Files

| Layer | File | Function |
|-------|------|----------|
| Schema | `backend/app/schemas.py` | `PlanDocumentData` class |
| Persistence | `backend/app/crud_document.py` | `apply_planner_update()` |
| Endpoints | `backend/app/main.py` | Graph plan SSE stream |
| Hydration | `frontend/.../useSessionHydration.ts` | Session restore hook |
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

5. 24hr Expiration
   └── useSessionHydration detects age → Clear + fresh start
```

---

## VIII. Component Responsibilities

| Component | Responsibility |
| --- | --- |
| `StrategyStageRenderer` | Data density computation, conditional rendering, single renderer for all modes |
| `PlanHeader` | Sticky header: topo background (no destination), hero image + TripSummaryPills (with destination), collapsed bar (mobile scroll) |
| `S2StrategyView` | Strategy cards rendering (delegates to StrategyStack/StrategyHero) |
| `TimelineThread` | Renders timeline with `variant` prop (`ghost`/`draft`/`real`). Day headers show intensity badge (Relaxed/Balanced/Packed) via `getDayIntensity()` from `lib/dayIntensity.ts` |
| `ChatPanel` | Chat orchestration for SSE runs and suggestion chips. Input area (chips + SmartLoader + text input) is pinned below the scroll container via `shrink-0` (not inside it), ensuring chips are always visible. Applies send burst guards (1s regular message cooldown, 3s generate-trigger cooldown) and handles `trigger_action` chips (e.g., direct flights only). Delegates individual message rendering to `ChatMessageRenderer` |
| `ChatMessageRenderer` | Renders individual chat messages: system ack lines, user bubbles with SystemReceipt, assistant bubbles with markdown/specialist deep links/streaming pulse/retry button (extracted from ChatPanel) |
| `computeTimelineVariant(state)` | Maps PlanViewState to TimelineVariant (see table below) |
| `ghost-timeline-adapter` | Transforms specialist content to DayCard[] for preview |
| `BookingSection` | Renders booking tiles when available |
| `NextStepBar` | CTA bar — accepts `nextAction` prop, early-returns null for `expand_itinerary` (handled by auto-expand), renders only for `finalize_plan` action. Currently `getNextAction()` never returns `finalize_plan`, so NextStepBar does not render in practice. |
| `OriginPromptCard` | Inline prompt to set origin (shown in S2 when destination+dates set but no origin, 2+ specialists) |
| `ItineraryProgressIndicator` | Progress indicator for multi-specialist auto-trigger itinerary generation |
| `BookingDrawer` | Side sheet for tile browsing, triggered by FreeDayCard "Browse" or GhostSlot clicks. Supports `pinnedDayNumber` for per-day tile placement via fill-day API |
| `TripHealthBar` | Compact inventory bar showing tile counts (hotels, flights, activities) for General/Local Expert sections in `S2StrategyView` |

**Deleted Components (no longer in codebase):**
- `ConflictResolutionBanner` -- conflict resolution now chat-driven via suggestion chips
- `TripHealthDashboard` -- replaced by `TripHealthBar.tsx` (compact bar variant, still active in `S2StrategyView`)
- `ReadyToPlanBanner` -- removed
- `ExplorationProgress` -- removed
- `SelectionsBar` -- hearted tile preferences now feed auto-regen directly (no separate UI bar)
- `SuggestionBlock` -- timeline block for suggested bookables removed
- `useChatStateMachine` -- chat state machine hook removed
- `PlanDocument`, `DocumentHeader`, `DaySection`, `Segment` -- legacy plan document components
- `OnboardingChips`, `PlanningProgress`, `OptionalRefinementsSection` -- legacy plan widgets
- `S1FramingView`, `S2BlockedView`, `S3BlockedView`, `S3EditingView` -- legacy stage views (deleted)
- `S3ItineraryView` -- deleted (was unused in unified `StrategyStageRenderer` flow)
- `CollapsedSetupSummary` -- deleted (setup collapse feature removed; `collapseSetupMessages` removed from chatStore)
- `LocationBadge`, `TruncatedDestinationList` -- legacy pill components
- `TileSectionHeader` -- tile section header
- `features-section` -- marketing features section

### TimelineVariant Mapping

The timeline variant is computed from `PlanViewState` to control badge display:

| PlanViewState | TimelineVariant | Badge |
| --- | --- | --- |
| `S3_ITINERARY_READY` | `real` | None (finalized itinerary) |
| `S3_EDITING`, `S2_STRATEGY_READY` | `draft` | "Draft Itinerary" (amber) |
| All others (`S0_*`, `S1_*`, `S2_BLOCKED`, `S3_BLOCKED`, `S3_PARTIAL_CONFLICT`) | `ghost` | "Specialist Preview" (emerald) |

**Invariant:** Regeneration is triggered via chat auto-regen, preference auto-regen, or the Build Itinerary CTA. The "Draft Itinerary" badge should NOT appear when itinerary is finalized (`S3_ITINERARY_READY`).

### State Helper Functions (`planStateHelpers.ts`)

| Function | Purpose | Status |
| --- | --- | --- |
| `getNextAction(state, generation, _hasTripContext?)` | Returns `'expand_itinerary'` for S2, `null` otherwise. Does NOT gate on dates. Third param `_hasTripContext` is deprecated (NextStepBar reads tripInputs from store). | Active |
| `isGenerating(generation)` | Checks if any generation is in progress (`generation?.active === true`) | Active |
| `shouldAutoTriggerItinerary(state, topics, hasDates, generation, hasItinerary)` | Path A: auto-trigger for multi-specialist trips (2+ topics, S2, has dates, no existing itinerary) | Active |
| `isMultiSpecialistTrip(executedTopics)` | Returns true when 2+ topics executed | Active |

**Deleted functions (no longer in codebase):**
- `isReady()` -- removed (was: checks if plan is in ready state)
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
  if (state === 'S2_STRATEGY_READY') return 'expand_itinerary';
  return null;
}
```

---

## IX. Invariants

1. **Right Panel Never Empty:** After first user message, always show *something* (hero, cards, or full plan).
2. **No View Swapping:** Single renderer (`StrategyStageRenderer`) adapts via `computeDataDensity()`; don't mount/unmount entire view components.
3. **No UI Chrome Removal:** Elements that appear during setup (status header, chip rows) must **transform through states**, not disappear. Layout shift breaks spatial memory. See `getChatStatusConfig` in `ChatPanel.tsx`.
4. **Backend is SSoT:** `plan_view_state` from backend determines rendering mode. Frontend does not fabricate it except for the frontend-only state `S0_EMPTY` (reset intent). `S3_PARTIAL_CONFLICT` is emitted by the backend `/api/expand-itinerary` endpoint when the builder produces partial results. `S1_DESTINATION_SET` exists only in the frontend `VIEW_STATE_ORDER` for downgrade protection ordering.
5. **Coordinates Flow:** `[lng, lat]` format preserved from specialist → strategy_sections → DayBlock.
6. **Plan Tab Unlock:** Mobile plan tab unlocks when `planTabEnabled = hasBranchesReady || planViewState !== 'S0_BOOTSTRAP'` (specialist content, tiles, or branches exist — no dates required). Desktop `canViewPlan` in `useViewNavigation` gates on dates (`hasDates || isGenerating`) but is marked `@deprecated` and only used by legacy API. Strategy content alone DOES unlock the plan tab on mobile.

---

## X. Mobile Topology & Adaptation

The "Split Screen" desktop architecture translates to a **horizontal swipe layout** on mobile (<1024px). Chat and Plan are two full-screen pages using CSS `scroll-snap`. Desktop is unchanged.

### Implementation

| Component | File | Purpose |
| --- | --- | --- |
| `MobileSwipeLayout` | `components/layout/MobileSwipeLayout.tsx` | CSS scroll-snap horizontal container with tab bar |
| `MobileChatInput` | `components/chat/MobileChatInput.tsx` | Detached chat input below swipe container (visible on both pages) |
| `TripStatusBar` | `components/chat/TripStatusBar.tsx` | Two-tier expand/collapse trip summary above swipe container |
| `mobileNavStore` | `state/mobileNavStore.ts` | Zustand store: `activePage`, `hasNewPlanContent` badge |
| `useIsDesktop` | `hooks/useIsDesktop.ts` | Viewport detection hook (`useSyncExternalStore` + `matchMedia`) |

### Layout Stack

```
┌──────────────────────────┐
│  MobileModeHeader     48px│
│  TripStatusBar      ~40px│  ← two-tier: plain text (tap to expand detail rows)
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
       ├─ TripStatusBar      (intrinsic)
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
4. **Safe Areas:** Chat input uses `pb-[max(0.5rem,env(safe-area-inset-bottom))]`. Header uses `pt-[env(safe-area-inset-top)]`.
5. **Chat Input Always Visible:** Users can type commands from either page without swiping back.
6. **Height Constraint:** Root div MUST use fixed `h-[100dvh]` (NOT `min-h-[100dvh]`) to prevent input clipping below viewport.
7. **Status Pill:** `MobileModeHeader` STABLE state has empty text (pill hidden). Only RESOLVING ("Planning...") shows a visible pill.
8. **TripStatusBar:** Two-tier expand/collapse. Tier 1: plain text summary (`Bali · Rome · Feb 14-22 · 1 adult`). Tier 2: tap to reveal labeled rows with per-row edit buttons via `onOpenSheet`.

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
| **Preference changes** | Instant auto-regen via hook | `usePreferenceAutoRegen.ts` |
| **Build Itinerary CTA** | Manual click to generate itinerary | `StrategyStageRenderer.tsx` |
| **GENERATE_PLAN_TRIGGER** | Full regeneration via chat system | `NomadicLanding.tsx` → `proceedWithItineraryGeneration` |

**Implementation:**
```typescript
// NomadicLanding.tsx - proceedWithItineraryGeneration handles all regen paths
// Reads FRESH state via useDocumentStore.getState() (avoids stale closures)
// Supports forceFullRebuild flag for structural changes
```

**Invariant:** Tiles stay visible until backend returns new data. Regeneration paths are event-driven, not gated behind a single FAB.

#### B. NextStepBar (Finalization CTA)

| Property | Value |
| --- | --- |
| **Label** | "Finalize & Book" |
| **Location** | Right Panel (Sticky Footer - "Command Island") |
| **Visibility** | Renders when `nextAction` prop is `finalize_plan` |
| **Action** | Transitions to Checkout/Booking phase |
| **Component** | `NextStepBar.tsx` |

**How it works:**
- `NextStepBar` accepts a `nextAction` prop (from `getNextAction()`)
- `getNextAction()` returns `'expand_itinerary'` for `S2_STRATEGY_READY`, `null` otherwise
- NextStepBar filters out `expand_itinerary` (auto-expand handles it) and only renders for `finalize_plan`
- In practice, NextStepBar renders when `finalize_plan` is passed as `nextAction`

**Context Display:**
- Left side shows "TIMELINE" label with date range (e.g., "Feb 5 — Feb 12")
- Badge shows trip duration in days
- Green emerald styling when ready

**Invariant:** NextStepBar is the ONLY way to enter the Booking phase. It is a **HARD GATE**.

#### Path A: Auto-Trigger for Multi-Specialist Trips

For multi-specialist trips (diving + hiking, skiing + hiking, etc.), the itinerary generation **auto-triggers** when dates are set. This removes the need for a manual FAB click.

**Auto-Trigger Conditions:**
1. `plan_view_state === 'S2_STRATEGY_READY'` (strategy complete)
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
  if (state !== 'S2_STRATEGY_READY') return false;
  if (isGenerating(generation)) return false;
  if (!hasDates) return false;
  if ((executedTopics?.length ?? 0) < 2) return false;
  if (hasItineraryContent) return false;
  return true;
}

// NomadicLanding.tsx
useEffect(() => {
  if (shouldAutoTrigger) {
    hasAutoTriggeredRef.current = true;
    setTimeout(() => proceedWithItineraryGeneration(), 500);
  }
}, [planViewState, executedTopics, hasDates, ...]);
```

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
[Conflict] Partial day_cards render at S3_PARTIAL_CONFLICT + resolution chips via synthesizer
```

**UI Components:**

1. **ItineraryProgressIndicator** - Shows generation progress
   - States: `analyzing`, `checking`, `building`, `success`, `error`
   - Message: "Analyzing diving + hiking requirements..."
   - Progress bar animation

2. **Inline Conflict Handling** (replaced former ConflictResolutionBanner)
   - Partial `day_cards` auto-render at `S3_PARTIAL_CONFLICT` showing what CAN fit
   - Blocking violations re-surface on next chat turn via `last_builder_success` metadata
   - Synthesizer generates actionable resolution chips: "Extend to Mar 12", "Remove hiking"
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
* **Mobile:** Hero hidden entirely — `TripStatusBar` provides trip context

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
    {/* Specialist cards: always visible pre-itinerary, togglable post-itinerary */}
    {!hasItineraryContent ? (
      <S2StrategyView ... />
    ) : (
      <>
        {showConstraints && <S2StrategyView ... />}
      </>
    )}
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

**Self-Contained Expansion:** The `StrategyHero` component internally manages its own expansion state via `useState`. When clicked, it opens a `BottomSheet` containing:
1. Hero image with specialist badge
2. Strategy Logic (one-liner)
3. Applied Constraints (with icons and reasons)
4. Key Principles (checkmark list)
5. Recommendations (with thumbnails)

**Rationale:** Self-contained state management avoids prop-drilling and ensures the expand behavior works regardless of where `StrategyHero` is rendered. The parent (`S2StrategyView`) no longer needs to manage modal state.

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
| `StrategyHero` | `components/plan/stages/StrategyHero.tsx` | Renders both Hero and Compact variants; **self-contained** expansion via internal `BottomSheet` |
| `S2StrategyView` | `components/plan/stages/S2StrategyView.tsx` | Computes variant from density, maps sections to StrategyHero |
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
| `constraints_applied` | array | Backend | `[{rule, type, reason, severity}]` for warnings. Frontend filters to blocking+strong only (excludes soft/info) in StrategyHero badge count, constraint list, and Trip DNA bar. |
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

**One-Liner Auto-Generation (plan_graph.py):**
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

**Solution:** In `_format_result()`, guarantee a Trip Overview section exists:

```python
# Safety net: If no anchor card exists, synthesize one
anchor_types = {"general", "local_expert"}
has_anchor = bool(anchor_types & {s.get("specialist_type") for s in strategy_sections})

if not has_anchor and plan.destination:
    # Synthesize Trip Overview from TripPlan data
    anchor_section = {
        "id": "strategy_general_anchor",
        "specialist_type": "local_expert",
        "title": f"{plan.destination} Trip Overview",
        "trip_summary": {...},
        "destination_gallery": [unsplash_images],
    }
    strategy_sections.insert(0, anchor_section)  # INDEX 0 = Trip DNA anchor
```

**Invariant:** Strategy sections list must ALWAYS contain at least one `general` or `local_expert` card if destination exists.

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
| Left | 50% | Timeline Thread (scrollable) |
| Right | 50% | Interactive Map (sticky) |

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
| Map | Inline between tiles and timeline (300px height), scrolls with content. Only shown when `hasItineraryContent && fullModePOIs.length > 0` |
| Chat Input | `MobileChatInput` docked below swipe container (always visible) |
| Navigation | Tab bar `[Chat] [Plan ●]` + horizontal swipe between pages |

```
┌─────────────────────────┐
│ MOBILE (Plan Page)      │
│ ┌─────────────────────┐ │
│ │ Strategy Cards      │ │
│ │ Booking Tiles       │ │
│ │ [Map 300px inline]  │ │
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
| Arrival/Departure | `LogisticsBlock` | Border-l-4, icon, time | Hard times (flights) |
| Check-in/out | `LogisticsBlock` | Key icon, hotel name, inline constraints | Accommodation logistics |
| Safety Buffer | `SafetyBlock` | Red zone, "No Flights until" | Constraint visualization |
| Activity | `ActivityMiniCard` | Thumbnail, category badge, duration, time of day, description, constraints, book button | Rich activity display with metadata |
| Unbooked | `GhostSlot` | Dashed border, "Select X" | Booking prompt |
| Empty Day | `FreeDayCard` | "Free Day" with fill CTA + category picker. Buffer blocks (SafetyBlock) render above FreeDayCard when present | Quick-fill with generated activities or browse |

**Fill-Day Flow:** FreeDayCard → `fillDay()` API call → backend generates 1 tile via `generate_experience_tiles_for_day(tiles_per_day=1)` → response includes `day_card` + `tiles` map → frontend calls `replaceDayCard()` for surgical day card update + merges tiles into document store (enables hearting/referencing). Generated tiles are tagged with `meta.pinned_day` so the builder won't redistribute them on rebuild. Backend applies adjacent-day constraint filtering (e.g., no altitude activities next to diving days). Categories are optional — when omitted, the generator picks destination-appropriate activities. **Concurrency:** Per-day mutex (`claimFillDay`/`releaseFillDay` in documentStore) prevents concurrent fill-day calls on the same day, frontend stream/regeneration gates (`currentRunId`/generation flags) block fill-day while itinerary updates are in flight, and burst guards throttle repeat calls (1.5s cooldown via `fillDayGuards.ts`) in both timeline and browse-to-pin paths. `fillDay()` in api.ts syncs the document version from the response (`useDocumentStore.setState({ version })`) to prevent 409 cascades and preserves backend `detail` text for surfaced 429/rejection toasts.

**Browse → Pin Flow:** FreeDayCard "Browse" opens `BookingDrawer` with `pinnedDayNumber` set to the day number. When the user clicks "Add to Day N" on a tile, `handleSaveTile` in StrategyStageRenderer calls `fillDay(dayNumber, undefined, [tileId])` — the backend places the existing tile on the target day via `pinned_tile_ids` (no LLM generation). Pinned tiles are persisted to `document_data.user_pinned_tiles` for rebuild survival — the builder's Phase 5.6 Pass 0 places them on their target day, and `itinerary_adapter.py` re-injects them into the tile pool during graph-built itinerary. If `pinnedDayNumber` is null (drawer opened from elsewhere), the default path fires: `toggleTilePreference` (idempotent — only if not already preferred) which triggers `usePreferenceAutoRegen`.

#### C.1 Inline Constraints

Timeline blocks display contextual constraint badges directly within the card. This makes constraint-first optimization **visible** to users.

**Visual Example:**
```
┌─────────────────────────────────────┐
│ 🌊 MORNING  diving  ⏱ 3.0h          │
│ Crystal Bay                         │
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

**Constraint Severities:**

| Severity | Background | Border | Title Color | Use Case |
|----------|------------|--------|-------------|----------|
| `warning` | `bg-amber-50` | `border-amber-200` | `text-amber-700` | Safety constraints (no-fly buffer) |
| `info` | `bg-blue-50` | `border-blue-200` | `text-blue-700` | Informational (surface interval) |
| `success` | `bg-emerald-50` | `border-emerald-200` | `text-emerald-700` | Positive confirmations |

**Constraint Data Structure (from backend):**
```typescript
interface ActiveConstraint {
  id: string;                    // 'no_fly_buffer', 'surface_interval'
  severity: 'warning' | 'info' | 'success';
  icon: string;                  // Emoji: '⚠️', 'ℹ️', '✅'
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
frontend/components/plan/timeline/blocks/
├── types.ts                        # DisplayTime, TimeSlot, getDisplayTime()
├── LogisticsBlock.tsx              # Arrival/departure/check-in + gear icons
├── SafetyBlock.tsx                 # No-fly/rest-day/acclimatization constraints (default: rest_day)
├── ActivityMiniCard.tsx            # Rich activity with context menu
├── GhostSlot.tsx                   # Unbooked placeholder
├── FreeDayCard.tsx                 # Empty day state with fill-day CTA + inline category picker
└── PreferenceAttributionBadge.tsx  # "You preferred this" / "AI selected" badge
```

**Settings Gear Icons:**

Gear icons provide quick access to category-wide settings sheets from timeline blocks and tile cards:

| Block/Card Type | Gear Location | Opens Sheet | Callback Prop | Status |
|-----------------|---------------|-------------|---------------|--------|
| `AgentCard` (diving/hiking/skiing/cycling/sailing) | Header right | `ActivitiesSheet` | `onOpenActivitySettings` | Active |
| `SuggestionCard` (hotel) | Image top-right, beside heart | `StaysSheet` | `onOpenStaysSettings` | **Hidden** (TODO) |
| `LogisticsBlock` (arrival/departure) | Top-right | `FlightsSheet` | `onOpenFlightsSettings` | Active |
| `LogisticsBlock` (check-in) | Top-right | `StaysSheet` | `onOpenStaysSettings` | Active |
| `TileCard` (hotel) | Image overlay, beside heart | `StaysSheet` | `onOpenStaysSettings` | **Hidden** (TODO) |
| `MiniCard` (hotel) | Thumbnail corner | `StaysSheet` | `onOpenStaysSettings` | **Hidden** (TODO) |

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

**Close behavior:** Selecting tile adds it to `preferredTileIds` (idempotent — only if not already preferred) via `handleSaveTile` in StrategyStageRenderer, then closes drawer. This triggers `usePreferenceAutoRegen` to regenerate the itinerary with the new preference.

#### F. Edit/Remove Interactions

Booked activities show a context menu (visible on hover) with:
- **Change Selection:** Reopens booking drawer
- **Remove from Itinerary:** Reverts to GhostSlot

### 11. Booking Suggestions Component Architecture

This section documents the mode-aware tile components used for suggestions and booking.

#### A. Mode-Aware Tile Cards

| Component | Mode | Purpose | Location |
|-----------|------|---------|----------|
| `SuggestionCard` | PLANNING | AI-recommended tiles with reasoning | `components/plan/tiles/SuggestionCard.tsx` |
| `BookableCard` | BOOKING | Price comparison + partner CTAs | `components/plan/tiles/BookableCard.tsx` |

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

#### C. BookableCard (BOOKING Mode)

Shows tile with price comparison across booking partners.

```
┌────────────────────────────────────────────────────┐
│ [Image]                             ✓ BOOKED       │
│ Hotel Tugu Bali • 4.8★                             │
│                                                    │
│ $365                  from 3 partners              │
│                                                    │
│ ┌──────────────────────────────────────────────┐  │
│ │ 🏢 Booking.com    $365  ★ BEST   [Book →]    │  │
│ └──────────────────────────────────────────────┘  │
│ ┌──────────────────────────────────────────────┐  │
│ │ 🏢 Expedia        $375           [Book →]    │  │
│ └──────────────────────────────────────────────┘  │
│                                                    │
│ [View Details]           [Add to Cart]            │
└────────────────────────────────────────────────────┘
```

**Props:**
- `tile: Tile` - The bookable tile
- `partnerPrices?: PartnerPrice[]` - Multi-partner pricing
- `isInCart?: boolean` - Cart state
- `isBooked?: boolean` - Booking state (PLANNING mode: only true for `user_preferred` tiles; BOOKING mode: true when `booked_tile` exists)
- `onBook?: (tile, partner) => void` - External booking redirect
- `onCartToggle?: (tile) => void` - Cart toggle callback

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
Backend may return S2 for benign reasons (e.g., "from rome" only runs LogisticsNode). Previously this cleared day_cards. Now the frontend blocks S3→S2 downgrade when itinerary exists:
- `S3 → S2` with day_cards → **Blocked** (itinerary preserved)
- `S3 → S0` (RESET) → **Allowed** (user explicit intent)
- Destination/date change → **Tiles replaced**, day_cards cleared (clean slate)

**View State Upward Reconciliation (fetchDocument):**
On page refresh, `fetchDocument()` applies upward reconciliation to repair stale persisted state. If the data in the document contradicts the stored `plan_view_state`, it promotes:
- `day_cards` exist + state below S3:
  - `constraint_violations` empty → promote to `S3_ITINERARY_READY`
  - `constraint_violations` present → promote to `S3_EDITING`
- `strategy_sections` exist + state below S2 → promote to `S2_STRATEGY_READY`

Guards prevent false promotion:
- Already S3 variant (S3_BLOCKED, S3_EDITING, S3_PARTIAL_CONFLICT) → **Not promoted** (lateral states respected)
- BLOCKED states (S2_BLOCKED) → **Not promoted** (blocking violation preserved)

**Expand-In-Progress Mutex:**
```typescript
// documentStore state
expandInProgress: boolean;
setExpandInProgress: (inProgress: boolean) => void;

// Guards in usePreferenceAutoRegen
if (expandInProgress) return;  // Skip preference regen during expand

// proceedWithItineraryGeneration wraps expand call
setExpandInProgress(true);
try { await expandItinerary(); }
finally { setExpandInProgress(false); }
```
This prevents the cascade: expand-itinerary → markPreferencesAsApplied → preference PATCH → preference auto-regen → expand-itinerary loop.

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
  mode="booking"   // Uses BookableCard, shows checkout sidebar
  ...
/>
```

| Mode | Tile Component | Checkout | Actions |
|------|----------------|----------|---------|
| PLANNING | SuggestionCard | Hidden | Save, Change, Details |
| BOOKING | BookableCard | Visible | Book, Cart, Details |

**Activity Tile Metadata Display:** `TileCard`, `MiniCard`, and `TileDetailsModal` render activity-specific metadata from `tile.meta` when `tile.type === 'activity'`: category badge (uppercase pill), duration hours (clock icon), time of day (sun/sunset/moon icon), and one-sentence description (from `meta.description`). The description field is generated by `experience_generator.py` and propagated via `meta.description`. `TileDetailsModal` additionally shows `skill_level` (if not beginner).

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
| **Status Badge** | "❤️ Preferred" (emerald) | "In Cart" (amber dot) |
| **Non-preferred Badge** | Hidden | "Available" (gray dot) |
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
  // Booking mode: Show traffic-light cart status
  return <CartStatusBadge status={status} />;
}
```

**Invariant:** Hearts (♡/❤️) in PLANNING mode, Cart badges in BOOKING mode. Never mixed.

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
  partnerPrices?: PartnerPrice[];     // For booking mode
  onBook?: (tile: Tile, partner: string) => void;
}
```

**Behavior:**
- PLANNING mode: Shows "Why this suggestion?" section with AI reasoning and "AI Pick" badge
- BOOKING mode: Shows partner price comparison table with Book buttons for each partner

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
| 2 | **AmadeusProvider** | Real hotel names, chain codes, coordinates | Live data with placeholder images |
| 3 | **MockProvider** | Generic data, Unsplash images | Development fallback |

### Provider Files

```
backend/app/tile_service/
├── service.py            # Provider routing orchestrator
├── curated_provider.py   # Hero destination content (DEMO_MANIFEST)
├── amadeus_provider.py   # Amadeus API integration (real hotel names)
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

    # 2. AMADEUS SECOND - Real hotel names, placeholder images
    if settings.use_amadeus_provider:
        return [AmadeusHotelProvider(), AmadeusFlightProvider()]

    # 3. MOCK FALLBACK - Development/offline mode
    return [MockHotelProvider(), MockFlightProvider(), MockActivityProvider()]
```

### Provider Comparison

| Aspect | CuratedProvider | AmadeusProvider | MockProvider |
|--------|-----------------|-----------------|--------------|
| **Hotel Names** | Hand-picked (e.g., "Atlantis The Royal") | Real API data (e.g., "Hilton Dubai Creek") | Generic (e.g., "Mock Hotel 1") |
| **Images** | Hand-picked Unsplash URLs | Auto-generated Unsplash | Auto-generated Unsplash |
| **Prices** | Curated estimates | None (Hotel List API) | Calculated mock prices |
| **Coordinates** | Hand-picked [lng, lat] | Real API data | Generated |
| **Availability** | Always "available" | "unknown" (needs separate API) | Always "available" |

### Image Strategy (Always Unsplash)

**ALL tile images come from Unsplash** - never null, never broken:

| Provider | Image Source | How |
|----------|--------------|-----|
| **Curated** | Hand-picked Unsplash URLs in DEMO_MANIFEST | `hotel.get("image")` |
| **Amadeus** | Auto-generated Unsplash via placeholder | `get_placeholder_image(category, seed)` |
| **Mock** | Auto-generated Unsplash via placeholder | `get_placeholder_image(category, seed)` |

```python
# All providers use the same pattern:
from app.placeholders import get_placeholder_image

# Curated image if provided, otherwise deterministic Unsplash placeholder
image_url = hotel.get("image") or get_placeholder_image(
    category="hotel",
    seed=hotel_id,  # Same hotel ID = same Unsplash photo
)
```

**Guarantees:**
1. **Never null** - Every tile has a valid Unsplash image URL
2. **Deterministic** - Same tile ID = same placeholder image
3. **Category-aware** - Hotels get hotel photos, activities get activity photos. Supported categories: `diving`, `hiking`, `skiing`, `cycling`, `surfing`, `sailing`, `climbing`, `hotel`, `yoga`, `nightlife`, `cooking`, `wellness`, `activity` (generic fallback)

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
| First Request (logistics_node) | Curated → Amadeus → Mock | Curated → Mock | Curated → Mock |
| Regeneration (tile_service) | Curated → Amadeus → Mock | Curated → Mock | Curated → Mock |

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
| `backend/app/tile_service/amadeus_provider.py` | Real hotel names | Placeholder images fallback |
| `backend/app/tile_service/mock_provider.py` | Development fallback | Auto-generated Unsplash |

### Mode-Aware UI Components

| Component | File | Mode Prop | Planning UI | Booking UI |
|-----------|------|-----------|-------------|------------|
| **CategorySection** | `frontend/components/plan/booking/CategorySection.tsx:53` | `mode?: 'planning' \| 'booking'` | ❤️ Preferred / ♡ Add to Trip | In Cart / Remove from Cart |
| **BookingSection** | `frontend/components/plan/BookingSection.tsx:570` | `mode={effectiveMode}` | SuggestionCard | BookableCard |
| **StatusBadge** | `frontend/components/plan/booking/CategorySection.tsx:60-102` | `mode` param | "Preferred" with heart | Traffic light badges |

### Date Validation Wiring

| Check | File | Logic |
|-------|------|-------|
| `hasDates` | `frontend/components/layout/NomadicLanding.tsx:676-678` | `(start_date && end_date) \|\| (date_flex && trip_duration)` |
| `canGeneratePlan` | `frontend/components/layout/NomadicLanding.tsx:679` | `hasDestination && hasDates` |

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
| `[expand-itinerary] Received event: envelope` | `NomadicLanding.tsx` | Stream parser received envelope |
| `[documentStore.mergeEnvelope] 📥 Received envelope` | `documentStore.ts` | Envelope being processed |
| `hasDayCards: true, dayCardsCount: N` | `documentStore.ts` | day_cards present in envelope |
| `[documentStore.mergeEnvelope] 📤 Updated document` | `documentStore.ts` | State updated |
| `[NomadicLanding] 🔄 Building planViewModel` | `NomadicLanding.tsx` | React re-rendering with new data |

**Common Issues:**

| Symptom | Likely Cause | Check |
|---------|--------------|-------|
| No 🔥 log | Early return (dates/session/doc) | Check for ❌ logs before 🔥 |
| 🔥 shows but no Success | Builder error | Check `itinerary_builder.py` exception logs |
| Success but UI unchanged | Frontend state sync | Check browser console for `mergeEnvelope` logs |
| `dayCardsCount: 0` in envelope | Empty `strategy_sections` | Check 📊 log for `sections=0` |
| No `[NomadicLanding] 🔄` log | Zustand reactivity issue | See "Zustand Selector Pattern" below |

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
- `NomadicLanding.tsx:501` - Granular selectors for document fields (see Performance section below)
- `NomadicLanding.tsx:125` - `storeTripInputs` selector for trip input changes

---

### 12. Performance: Render Optimization

#### Granular Zustand Selectors (NomadicLanding)

**Problem:** A single `state.document` selector causes re-renders when ANY document field changes (tiles, day_cards, strategy_sections, etc.), cascading to all children.

**Solution:** Replace with granular selectors that subscribe to individual fields:

```typescript
// ❌ BEFORE: Single fat selector - re-renders on ANY document change
const storeDocument = useDocumentStore((state) => state.document);

// ✅ AFTER: Granular selectors - each only triggers on its own field
const docPlanState = useDocumentStore((s) => s.document?.plan_state);
const docDestinationCard = useDocumentStore((s) => s.document?.destination_card);
const docPlanViewState = useDocumentStore((s) => s.document?.plan_view_state);
const docStrategySections = useDocumentStore((s) => s.document?.strategy_sections);
const docTiles = useDocumentStore((s) => s.document?.tiles);
const docExecutedTopics = useDocumentStore((s) => s.document?.executed_strategy_topics);
const docPendingTopics = useDocumentStore((s) => s.document?.pending_strategy_topics);
const docDayCards = useDocumentStore((s) => s.document?.day_cards);
const docGeneration = useDocumentStore((s) => s.generation);
// ... etc
```

**Benefit:** When `mergeEnvelope` updates tiles, only components using `docTiles` re-render. Strategy cards and day cards remain untouched.

#### Sub-Memos in StrategyStageRenderer

**Problem:** The `planContent` useMemo has 26+ dependencies. Any dependency change recomputes 575 lines of JSX.

**Solution:** Pre-compute expensive operations in focused sub-memos:

```typescript
// MEMO 1: Display logic - changes when view state/density changes
const displayLogic = useMemo(() => {
  const hasDates = !!effectiveTripInputs?.start_date;
  const hasTiles = effectiveTiles && Object.keys(effectiveTiles).length > 0;
  const density = computeDataDensity(state, viewModel.strategy_sections, effectiveTiles);
  const isShowingMirrorLoader = generating && hasDates && !hasTiles;
  return { hasDates, hasTiles, density, isShowingMirrorLoader, tripDuration };
}, [state, viewModel.strategy_sections, effectiveTiles, effectiveTripInputs, generating]);

// MEMO 2: Specialist data - changes when strategy_sections change
const specialistData = useMemo(() => {
  const fullModeSections = (viewModel.strategy_sections ?? []).filter(
    section => section.feasibility_status !== 'infeasible' && section.feasibility_status !== 'caveat'
  );
  const totalConstraints = fullModeSections.reduce((acc, s) => acc + (s.constraints_applied?.length ?? 0), 0);
  const ghostDayCards = generateGhostDayCards(fullModeSections, tripDuration);
  return { fullModeSections, totalConstraints, ghostDayCards, filteredViewModel };
}, [viewModel, effectiveTripInputs?.trip_duration]);

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

// ✅ AFTER: Fingerprint based on content, not references
const dayCardsFingerprint = useDocumentStore((s) => {
  const cards = s.document?.day_cards;
  if (!cards || cards.length === 0) return null;
  // Fingerprint: count + IDs of blocks with coordinates (the ones that affect POIs)
  const blockIds = cards
    .flatMap(c => c.blocks || [])
    .filter(b => b.coordinates?.lat != null && b.coordinates?.lng != null)
    .map(b => b.id)
    .join(',');
  return `${cards.length}:${blockIds}`;
});

// Use fingerprint as dependency, actual data in computation
const fullModePOIs = useMemo(() => {
  return extractPOIsFromDayCards(
    effectiveDayCards,
    sections,
    destination,
    dayCardsFingerprint
  );
  // eslint-disable-next-line react-hooks/exhaustive-deps
}, [dayCardsFingerprint, sections, destination]); // fingerprint, not effectiveDayCards
```

**Key Insight:** `useShallow` alone is NOT sufficient. If the memoized computation is inside a larger `useMemo` with many dependencies, it still runs on every dependency change. Extract expensive operations into their OWN `useMemo` with minimal deps.

#### Callback Stability

Callbacks passed to planContent's dependency array should be stable:

| Callback | Source | Stability |
|----------|--------|-----------|
| `onExpandToItinerary` | `useCallback` in NomadicLanding | ✅ Stable |
| `onBuildPlan` | `useCallback` in NomadicLanding | ✅ Stable |
| `onFinalizePlan` | `useCallback` in NomadicLanding | ✅ Stable |
| `onSelectNights` | `useCallback` in NomadicLanding | ✅ Stable |
| `toggleTilePreference` | Zustand store action | ✅ Stable |
| `scrollToTile` | `useCallback` in StrategyStageRenderer | ✅ Stable |
| `openSheet` | `useSheetManager` hook | ✅ Stable |
| `shortlist.toggleItem` | `useShortlist` hook | ✅ Stable |

**Rule:** Do NOT add new inline arrow functions to StrategyStageRenderer props unless they're excluded from planContent dependencies.

---

### 13. Cross-Reference

* **Visual Tokens:** See `design-system.md` for colors, typography, and materials.
* **Data Density:** See Section VII for density computation logic.
* **Backend SSoT:** See `plan_graph_analysis.md` for node architecture.
* **Performance:** See Section 12 for render optimization patterns.
