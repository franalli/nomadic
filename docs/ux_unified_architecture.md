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
  * Map with POI pins from specialist recommendations
* **Tiles:** HIDDEN (no prices without dates)

#### Phase 2: After Dates Added
* **Trigger:** User provides dates (e.g., "April 15-25")
* **UI Shows:**
  * Day-by-day itinerary auto-generates
  * Map shows route with day-by-day pins
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

| Phase | Data State | UI Shows |
|-------|-----------|----------|
| `P0_MINIMAL` | Destination only, no specialists | Hero image, empty timeline |
| `P1_ENRICHED` | Specialists run, strategy sections present | Strategy cards, ghost timeline |
| `P2_LOGISTICS` | Tiles fetched, suggestions available | Full timeline with suggestions |
| `P3_FINALIZED` | Itinerary validated, ready to book | Complete itinerary, "Proceed to Booking" |

### Legacy Mapping (Deprecated)

> **NOTE:** The old S0-S3 states are deprecated. Use P0-P3 for new code.

| Legacy State | Maps To | Reason |
|--------------|---------|--------|
| `S0_BOOTSTRAP` | `P0_MINIMAL` | No data yet |
| `S1_FRAMING` | `P0_MINIMAL` | Merged into P0 |
| `S2_STRATEGY_READY` | `P1_ENRICHED` | Specialists have run |
| `S2_BLOCKED` | `P1_ENRICHED` | Handled by data checks |
| `S3_ITINERARY_READY` | `P3_FINALIZED` | Itinerary complete |

---

## II. The "Single Renderer" Pattern

We do not swap `SetupView` for `PlanView`. We use a single **`UnifiedStageRenderer`** that adapts.

```tsx
<UnifiedStageRenderer>
  {/* TOP: ALWAYS VISIBLE */}
  <StrategyStack />

  {/* MIDDLE: ADAPTIVE TIMELINE */}
  {mode === 'bridge' ? (
    <TimelineThread variant="sample" duration={3} />
  ) : (
    <TimelineThread variant="real" startDate={date} />
  )}

  {/* BOTTOM: DATA DENSITY */}
  {hasTiles && <BookingTilesGrid />}
</UnifiedStageRenderer>
```

---

## III. Backend State Logic (`plan_graph.py`)

The Backend dictates the Planning Phase based on data density.

| Logic Check | Phase Output | Explanation |
| --- | --- | --- |
| `!tiles` AND `!specialist_content` | `P0_MINIMAL` | **Minimal.** Destination only. Show "Inspiration Hero" or default empty state. |
| `specialist_content` AND `!tiles` | `P1_ENRICHED` | **Enriched.** User has intent but no dates. Show Strategy Cards + Sample Timeline. |
| `tiles` EXIST AND `!itinerary` | `P2_LOGISTICS` | **Logistics.** Dates set, suggestions available. Show Full Dashboard. |
| `itinerary` EXIST | `P3_FINALIZED` | **Finalized.** Itinerary complete. Show "Proceed to Booking" button. |

### Itinerary Generation State Transition

When the user has dates and tiles, clicking "BUILD ITINERARY" triggers the `ItineraryBuilder` service:

```
P1_ENRICHED → P2_LOGISTICS → BUILD ITINERARY → P3_FINALIZED
                                    │
                          ItineraryBuilder.build()
                                    │
                          ┌─── Success → day_cards rendered
                          └─── Conflict → ConflictResolutionModal
```

**Conflict Resolution Flow:**

```
ConflictResolutionModal displayed
         │
         ├─── "Extend Trip" → Update trip_plan.end_date → Re-run build()
         │
         ├─── "Keep Specialist" → Disable other specialists → Re-run build()
         │
         └─── "Dismiss" → Render partial itinerary with warnings
```

**Invariant:** User is NEVER left with silently dropped activities. All conflicts are surfaced with actionable resolutions.

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
2. **Multi-specialist support preserved** - multiple niche specialists can still queue after local_expert
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
| `boating` | Indigo | `#6366F1` |

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

Toggle visibility of activity types:
```
[All] [🤿 Diving] [🥾 Hiking] [🏨 Hotels] [✈️ Flights]
```

### Implementation

**Hook:** `useMapSync` manages all map-itinerary state:
```typescript
const {
  mapItems,        // Filtered items to display
  activeItemId,    // From scroll spy
  handleMarkerClick, // Scroll to timeline
  routeGeoJson,    // Route line data
  visibleLayers,   // Layer filter state
  toggleLayer,     // Toggle layer visibility
} = useMapSync({
  dayCards,
  strategySections,
  mode: 'plan',
});
```

**Data Sources:**
- `DayCard.blocks[].coordinates` - Itinerary locations
- `StrategySection.content_added[].coordinates` - Specialist POIs

### Invariants

1. **Map updates on scroll** - IntersectionObserver tracks visible timeline items
2. **Click triggers scroll** - Clicking pin scrolls timeline to matching item
3. **Route only in PLAN mode** - No route line for POI-only views
4. **Day filter persists** - Hovering day filters map to that day's pins only

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

## V. Critical Data Serialization

To support the Map and Cards in "Bridge Mode," the backend MUST serialize this data even if `tiles` are empty:

1. **Coordinates:** `[lng, lat]` for every Activity.
2. **Images:** High-res URLs for every Strategy Card.
3. **Content Blocks:** The "Day 1", "Day 2" sequence for the Sample Timeline.

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
if (isGenerating && hasDates && !hasTiles) {
  return (
    <div className="p-4 space-y-4 animate-pulse">
      <div className="h-6 w-48 bg-muted rounded" />
      <div className="text-sm text-muted-foreground">
        Searching live availability...
      </div>
      <TimelineSkeleton days={tripDuration || 3} />
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
| `empty` | S0 + no specialist content | Hero image only |
| `ghost` | S0 + specialist content | Strategy cards + ghost timeline |
| `bridge` | S2 + specialist + no tiles + no dates | Strategy cards + sample timeline + POI map |
| `full` | S2 + tiles exist | Strategy cards + real timeline + tiles + full map |

---

## VIII. Component Responsibilities

| Component | Responsibility |
| --- | --- |
| `StrategyStageRenderer` | Data density computation, conditional rendering |
| `S2StrategyView` | Strategy cards rendering (delegates to StrategyStack) |
| `TimelineThread` | Renders timeline with `variant` prop (`ghost`/`draft`/`real`) |
| `ghost-timeline-adapter` | Transforms specialist content to DayCard[] for preview |
| `BookingSection` | Renders booking tiles when available |

---

## IX. Invariants

1. **Right Panel Never Empty:** After first user message, always show *something* (hero, cards, or full plan).
2. **No View Swapping:** Single renderer adapts; don't mount/unmount entire view components.
3. **Backend is SSoT:** `plan_view_state` from backend determines rendering mode.
4. **Coordinates Flow:** `[lng, lat]` format preserved from specialist → strategy_sections → DayBlock.
5. **Dates Gate Plan Navigation:** The Plan tab MUST be locked until `start_date` is set. Strategy content alone does NOT unlock Plan.

---

## X. Mobile Topology & Adaptation

The "Split Screen" desktop architecture translates to a "Tabbed View" on mobile.

### Spatial Translation

| Desktop Concept | Mobile Translation | Behavior |
| --- | --- | --- |
| **Right Panel** | **Plan Tab** | The "Canvas" lives behind the "Plan" tab. |
| **Instant Update** | **Toast Notification** | When backend updates Bridge/Plan state, show a Toast: *"Plan Updated: Diving Strategy Added"* |
| **Bridge Mode** | **Preview Sheet** | In Setup phase, tapping the Plan tab shows the Strategy Cards + Ghost Timeline. |
| **Navigation** | **Bottom/Top Bar** | Explicit switching between `Chat` (Commander) and `Plan` (Canvas). |

### Mobile Invariants

1. **Notification of Change:** Since the Canvas is hidden behind a tab, every significant state change (e.g., Strategy Card added) MUST trigger a **Toast** or **Badge Dot** on the Plan tab to alert the user.
2. **State Persistence:** Switching tabs must NEVER lose the scroll position or drafted message.
3. **Touch Targets:** All interactive elements must be minimum 44x44px per `design-system.md`.
4. **Safe Areas:** Respect iOS/Android safe areas for notches and home indicators.

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

### 2. Canvas Action Button (The Commitment)

| Property | Value |
| --- | --- |
| **Label** | **"Finalize & Book"** |
| **Location** | Right Panel (Sticky Footer or Header Action) |
| **Visibility** | Hidden in Setup/Bridge. Visible in Plan (Full Mode with tiles) |
| **Action** | Transitions state from `S2` → `S3` (Checkout) |

**Invariant:** This is the ONLY way to enter the Booking phase. It is a **HARD GATE**.

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
| `bridge` / `ghost` | **Hero** | Full-width image, editorial typography, constraint pills | Maximum inspiration |
| `full` | **Compact** | Single-row bar (~56px), specialist pills, constraint count | Get out of the way |

#### A. Hero Mode ("The Magazine Cover")

Used in Bridge Mode when user has intent but no dates/tiles. The goal is **maximum inspiration**.

* **Image:** `aspect-[16/9]` or `aspect-[2/1]` full-width hero from `destination_gallery` or `content_added[0].image_url`
* **Overlay:** Gradient `from-black/90 via-black/40 to-transparent`
* **Badge:** Frosted glass pill (`bg-white/20 backdrop-blur-md border-white/20`)
* **Title:** White text, `text-2xl md:text-3xl font-bold`
* **Constraints:** Horizontal scroll pills at bottom (`bg-black/40 backdrop-blur-md`)

**Rationale:** In Inspiration mode, we want the user to feel excited about their trip. The Magazine Cover creates emotional connection before logistics.

#### B. Compact Mode ("Trip DNA Bar")

Used in Full Mode when tiles exist. The goal is to **get out of the way** so booking tiles are prominent.

* **Height:** `h-14` (~56px)
* **Layout:** `flex items-center gap-3`
* **Thumbnail:** `w-10 h-10 rounded-lg`
* **Text:** Title + one-liner truncated
* **Badge:** Constraint count (`bg-amber-100 dark:bg-amber-900/30 text-amber-700`)
* **Interaction:** Clickable. Opens `BottomSheet` with full details.

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
│ TRIP DNA BAR (h-14) - Compact Strategy              │
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
| `constraints_applied` | array | Backend | `[{rule, type, reason}]` for warnings |
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
| `boating` | Boating | Sailboat | Sailing yacht |

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
| `specialist_type` | string | Backend | One of: `diving`, `hiking`, `skiing`, `cycling`, `boating` |
| `title` | string | Backend | Card title (e.g., "Diving Strategy") |
| `one_liner` | string | Backend | Strategy logic summary |
| `hero_image` | string | Backend | Primary image URL (or use fallback) |
| `constraints_applied` | array | Backend | `[{rule, type, reason}]` - CRITICAL for safety |
| `principles` | array | Backend | Checklist items (strings) |
| `content_added` | array | Backend | Recommendations: `[{title, description, type, logic_hook, image_url?, coordinates?}]` |
| `must_dos` | array | Backend | Quick list of key activities |
| `optional_upgrades` | array | Backend | Nice-to-have suggestions |
| `feasibility_status` | string | Backend | `"feasible"`, `"caveat"`, or `"infeasible"` |
| `feasibility_reason` | string | Backend | Explanation if not fully feasible |

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

### 7. Fixed-Height Banner Pattern (Image Sizing)

**Problem:** Using `aspect-video` or `aspect-[16/9]` causes hero images to scale with viewport width, creating "giant images" that dominate the screen on desktop.

**Solution:** Use fixed pixel heights instead of aspect ratios:

| Breakpoint | Hero Mode | Compact/BottomSheet |
|------------|-----------|---------------------|
| Mobile (<768px) | `h-56` (224px) | `h-48` (192px) |
| Desktop (≥768px) | `h-72` (288px) | `h-64` (256px) |

**Implementation:**
```tsx
// WRONG: Scales with viewport width
<div className="aspect-video w-full">

// CORRECT: Fixed height, won't exceed ~30% viewport
<div className="h-48 md:h-64 w-full">
  <Image fill className="object-cover" />
</div>
```

**Invariant:** Strategy card images must NEVER exceed ~30% of vertical viewport space.

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
  specialist_type: string;              // "local_expert" | "general" | "diving" | "hiking" | "skiing" | "cycling" | "boating"
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
  reason: string;                       // e.g., "Prevents decompression sickness"
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

#### B. Mobile Layout

| Element | Behavior |
|---------|----------|
| Default | Timeline Thread (full screen with bottom sheet pattern) |
| Action | Floating "View Route" button (bottom-right, above bottom sheet) |
| Map | Opens in 90vh bottom sheet for full pan/zoom |

```
┌─────────────────────────┐
│ MOBILE                  │
│ ┌─────────────────────┐ │
│ │                     │ │
│ │    [Map 50vh]       │ │
│ │                     │ │
│ ├─────────────────────┤ │
│ │ ████ (drag handle)  │ │
│ │                     │ │
│ │ Timeline (bottom    │ │
│ │ sheet, expandable)  │ │
│ │                     │ │
│ │ [View Route] FAB    │ │
│ └─────────────────────┘ │
└─────────────────────────┘
```

#### C. Block Types

| Type | Component | Visual | Purpose |
|------|-----------|--------|---------|
| Arrival/Departure | `LogisticsBlock` | Border-l-4, icon, time | Hard times (flights) |
| Check-in/out | `LogisticsBlock` | Key icon, hotel name | Accommodation logistics |
| Safety Buffer | `SafetyBlock` | Red zone, "No Flights until" | Constraint visualization |
| Activity | `ActivityMiniCard` | Thumbnail, duration, book button | Rich activity display |
| Unbooked | `GhostSlot` | Dashed border, "Select X" | Booking prompt |
| Empty Day | `FreeDayCard` | "Free Day" with browse CTA | Spontaneous exploration |

**Component Files:**
```
frontend/components/plan/timeline/blocks/
├── index.ts              # Barrel export
├── types.ts              # DisplayTime, TimeSlot, getDisplayTime()
├── LogisticsBlock.tsx    # Arrival/departure/check-in
├── SafetyBlock.tsx       # No-fly/rest-day constraints
├── ActivityMiniCard.tsx  # Rich activity with context menu
├── GhostSlot.tsx         # Unbooked placeholder
└── FreeDayCard.tsx       # Empty day state
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

**Trigger:** Clicking GhostSlot or "Book" button on ActivityMiniCard.

**Content:** Filtered tiles by category (hotel/flight/activity).

**Close behavior:** Selecting tile embeds it in timeline and closes drawer.

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
| `SuggestionBlock` | PLANNING | Timeline block for suggested bookables | `components/plan/timeline/blocks/SuggestionBlock.tsx` |

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
- `isBooked?: boolean` - Booking state
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
useCartActions(): { addToCart, removeFromCart, clearCart }
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

---

## XI.G Additional Mode-Aware Components

The following components also support the two-mode system:

### 1. PlanHeader with ModeIndicator

**File:** `components/plan/PlanHeader.tsx`

Supports both legacy GlassCommandBar and new ModeIndicator for the two-mode system.

```typescript
interface PlanHeaderProps {
  // ... existing props ...

  // Two-mode system props
  mode?: ViewMode;                    // 'planning' | 'booking'
  planningPhase?: PlanningPhase;      // Progress tracking
  progress?: number;                  // 0-100
  useModeIndicator?: boolean;         // Toggle new vs legacy nav
  onModeChange?: (mode: ViewMode) => void;
}
```

**Behavior:**
- When `useModeIndicator=true` and `mode`/`planningPhase` provided: Shows PLANNING/BOOKING pills with progress bar
- Otherwise: Shows legacy GlassCommandBar with three tabs

### 2. UnifiedChipRow (Mode-Aware Disabled State)

**File:** `components/plan/UnifiedChipRow.tsx`

All chips (destination, origin, dates, travelers, budget, flights, stays, activities) respect the mode prop.

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
// Derive from activeView or use explicit override
const effectiveMode: ViewMode = explicitMode ?? (activeView === 'book' ? 'booking' : 'planning');
```

Passes `mode` to BookingSection for mode-aware tile rendering.

---

### 12. Cross-Reference

* **Visual Tokens:** See `design-system.md` for colors, typography, and materials.
* **Data Density:** See Section VII for density computation logic.
* **Backend SSoT:** See `plan_graph_analysis.md` for node architecture.
