# Unified UX Architecture & Rendering Protocol

**Version:** 2.0 (The "Grand Unification")
**Philosophy:** Single Adaptive Renderer. No more swapping entire views. The UI reveals depth progressively based on data density.

---

## I. The Three Phases of Engagement

The application is a continuous flow, not disjointed "pages." The Right Panel (Canvas) must NEVER be empty once the conversation starts.

### 1. SETUP PHASE ("The Inspiration")
* **Goal:** Capture Intent (Where + What). Inspire confidence.
* **Backend State:** `S0_BOOTSTRAP` (Initial) -> `S2_STRATEGY_READY` (Bridge Mode).
* **Trigger:** User mentions a destination or activity (e.g., "Diving in Dubai") but *no dates yet*.
* **Chat:** Warm, inquisitive. Uses "Visual Islands" to separate hook from questions.
* **Right Panel (Bridge Mode):**
    * **Strategy Cards:** Visible immediately (Deep Dive Dubai, etc.).
    * **Timeline:** **"Sample Sequence" (Draft)**. Shows a relative 3-day flow (Day 1, Day 2) to prove logic (e.g., "Dive then Fly"). Grayscale styling.
    * **Map:** **POIs Only**. Pins for the activities mentioned.
    * **Tiles:** HIDDEN. (No prices without dates).

### 2. PLAN PHASE ("The Logistics")
* **Goal:** Prove Feasibility. Compare Options. Refine.
* **Backend State:** `S2_STRATEGY_READY` (Full Mode).
* **Trigger:** User provides **Dates**. Backend fetches Flight/Hotel availability.
* **Chat:** Ultra-terse, notification-style. "Found 5 hotels. Check the panel."
* **Right Panel (Full Mode):**
    * **Strategy Cards:** Remains visible but compact.
    * **Timeline:** **"Real Itinerary"**. Specific dates (Mon, Feb 12). Colored styling. Shows Safety Buffers (Red Zones).
    * **Map:** **Full Logistics**. Hotels + Activities + Routes.
    * **Tiles:** **VISIBLE**. Real-time availability with prices.

### 3. BOOK PHASE ("The Commitment")
* **Goal:** Transaction.
* **Backend State:** `S3_ITINERARY_READY` / Checkout.
* **Trigger:** User clicks "Build Plan" or "Book".
* **Chat:** Reassuring. "Locked in your selection."
* **Right Panel:**
    * **Checkout Flow:** Passenger Details, Payment, Final Review.
    * **Summary:** Receipt-style view of selected items.

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

The Backend dictates the View State.

| Logic Check | State Output | Explanation |
| --- | --- | --- |
| `!tiles` AND `!specialist_content` | `S0_BOOTSTRAP` | **Blank Slate.** Show "Inspiration Hero" or default empty state. |
| `specialist_content` AND `!tiles` | `S2_STRATEGY_READY` | **Bridge State.** User has intent but no dates. Show Strategy Cards + Sample Timeline. |
| `tiles` EXIST | `S2_STRATEGY_READY` | **Plan State.** User has dates & prices. Show Full Dashboard. |

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

| Transition | From | To | Required Data | User Action | Gate Type |
| --- | --- | --- | --- | --- | --- |
| **Inspiration** | Setup (S0) | Bridge (S2) | `destination` | Mention "Diving in Dubai" | **SOFT** (Auto) |
| **Feasibility** | Bridge (S2) | Plan (S2) | `start_date` | Set dates via chip/chat | **SOFT** (Auto) |
| **Commitment** | Plan (S2) | Book (S3) | `tiles` selected | Click **"Build Plan"** | **HARD** (Explicit) |
| **Payment** | Book (S3) | Receipt | `guest_names`, `payment` | Click **"Confirm & Pay"** | **HARD** (Explicit) |

### Gate Types

- **SOFT Gate (Automatic):** Transition happens automatically when data conditions are met. User doesn't need to click anything—just provide the data (via chat or chips).
- **HARD Gate (Explicit Click):** Transition requires an explicit button click. Even if all data is present, the user must consciously confirm intent.

### Implementation in `useViewNavigation.ts`

```typescript
// SOFT GATE: Dates unlock Plan automatically
const canViewPlan = hasDates || isGenerating;

// HARD GATE: Explicit click required for Book
const canViewBook = isPlanFinalized && (hasTiles || inBookableState);
```

### Critical Invariants

1. **Dates are the Soft Gatekeeper:** Plan tab unlocks automatically when `start_date` is set. Strategy content alone (Bridge Mode) does NOT unlock Plan.
2. **Build Plan is the Hard Gatekeeper:** Moving to Book requires explicit click on "Build Plan". This is NEVER auto-triggered by chat or data.

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
