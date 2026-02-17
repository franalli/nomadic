# Travel Architect Design System

**Goal:** Standardize the UI across Light and Dark modes to achieve a premium "Travel Architect" aesthetic.

* **Light Mode:** "Crisp Technical" — High contrast, white glass, solid black actions, technical typography.
* **Dark Mode:** "Bioluminescent Depth" — Deep zinc/black glass, emerald glowing actions, semi-transparent inputs.

---

## 1. The Core System File

The design system is located at **`frontend/lib/design-system.ts`**.

This object abstracts all Tailwind complexity. Components should reference `DS` properties instead of hardcoded classes.

```typescript
import { DS } from '@/lib/design-system';

// Usage examples:
<div className={DS.materials.glass}>...</div>
<button className={DS.actions.primary}>Save</button>
<span className={DS.text.label}>Section Header</span>
```

---

## 2. Design Tokens Reference

### Materials (Surfaces)

| Token | Light Mode | Dark Mode | Use For |
|-------|------------|-----------|---------|
| `DS.materials.glass` | White/90 + zinc-200 border + soft shadow | Zinc-950/95 + white/10 border + black shadow | Modals, cards, panels |
| `DS.materials.surface` | Zinc-50 + zinc-100 border | White/3% + white/5 border | Inner sections, info boxes |
| `DS.materials.input` | Zinc-50 bg, zinc-900 focus border | Black/40 bg, emerald focus glow | Search, text inputs |
| `DS.materials.inputLarge` | Transparent, 4xl text | Same + white text | Budget "big number" |

### Actions (Buttons)

| Token | Light Mode | Dark Mode | Use For |
|-------|------------|-----------|---------|
| `DS.actions.primary` | Black bg, white text, shadow | Emerald-600 bg + glow | Save, Confirm, Build |
| `DS.actions.primaryDisabled` | Zinc-100 bg, zinc-400 text | Zinc-800 bg, zinc-600 text | Disabled primary |
| `DS.actions.secondary` | Zinc-500 text → zinc-900 on hover | Zinc-500 → white on hover | Cancel, Clear |
| `DS.actions.iconBtn` | Zinc-400 → zinc-900 | Zinc-500 → white | Close X, arrows |
| `DS.actions.toggle` | Emerald-500 checked, zinc-200 unchecked | Same checked, zinc-800 unchecked | Switch toggles |
| `DS.actions.smallAction` | Zinc-800 bg → emerald-600 hover | Zinc-700 bg → emerald-500 hover | Info box buttons |

### Pills (Selection Chips)

| Token | Light Mode | Dark Mode | Use For |
|-------|------------|-----------|---------|
| `DS.pills.active` | Black bg, white text, shadow | White bg, black text | Selected chips |
| `DS.pills.inactive` | White bg, zinc-200 border-2, zinc-600 text | White/5 bg, white/15 border-2, zinc-400 text | Unselected chips |
| `DS.pills.shape` | px-4 py-2 rounded-lg text-sm | Same | Base pill structure |
| `DS.pills.shapeFull` | px-4 py-2 rounded-full text-sm | Same | Rounded pill structure |

> **Note:** `rounded-lg` is overridden in `tailwind.config.mts` from the Tailwind default of `0.5rem` (8px) to `0.75rem` (12px). All `rounded-lg` usage in this system resolves to 12px.

### The Tactile Rule (IMPORTANT)

**Problem:** Inactive elements (unselected pills, stepper buttons) can look "ghostly" or invisible against the white background, making them feel unclickable.

**Solution:** The "Tactile Rule" — inactive elements must have crisp, visible borders that "snap" to black on hover, like physical mechanical buttons.

| State | Light Mode | Dark Mode |
|-------|------------|-----------|
| **Inactive Default** | `bg-white border-2 border-zinc-200 text-zinc-600` | `bg-white/5 border-2 border-white/15 text-zinc-400` |
| **Inactive Hover** | `hover:border-zinc-900 hover:bg-zinc-50 hover:text-zinc-900` | `hover:bg-white/10 hover:border-white/40 hover:text-white` |
| **Active/Selected** | `bg-zinc-900 text-white border-2 border-transparent shadow-md` | `bg-white text-black border-2 border-transparent` |

**Key Principles:**

1. **Use `border-2`** — Single-pixel borders are too subtle. Double-width borders define the button edge clearly.
2. **Snap to black on hover** — Don't use `border-zinc-400` for hover. Go straight to `border-zinc-900` for immediate visual feedback.
3. **Maximum contrast for selected** — Active pills should be solid `bg-zinc-900` (not dark grey), with a visible shadow.
4. **Consistent padding** — Use `py-2.5` or `py-3` for comfortable touch targets.

**Code Example:**

```tsx
// Tactile Pill
<button className={cn(
  'px-4 py-2.5 rounded-lg text-sm font-medium',
  'transition-all duration-150',
  isSelected
    // Selected: Solid Black (maximum contrast)
    ? 'bg-zinc-900 text-white border-2 border-transparent shadow-md dark:bg-white dark:text-black dark:border-transparent'
    // Tactile: Crisp border, snap-to-black hover
    : 'bg-white dark:bg-white/5 border-2 border-zinc-200 dark:border-white/15 text-zinc-600 dark:text-zinc-400 hover:border-zinc-900 hover:bg-zinc-50 hover:text-zinc-900 dark:hover:bg-white/10 dark:hover:border-white/40 dark:hover:text-white'
)}>
  {label}
</button>
```

### Stepper Buttons (Beefier Design)

Stepper buttons (`+`/`-`) follow the Tactile Rule with additional emphasis:

| State | Light Mode | Dark Mode |
|-------|------------|-----------|
| **Enabled Default** | `bg-white border-2 border-zinc-300 text-zinc-700` | `bg-white/5 border-2 border-white/15 text-zinc-400` |
| **Enabled Hover** | `hover:border-zinc-900 hover:bg-zinc-900 hover:text-white` | `hover:border-white hover:bg-white hover:text-black` |
| **Disabled** | `bg-zinc-50 border-2 border-zinc-200 text-zinc-300` | `bg-white/[0.02] border-2 border-white/5 text-zinc-700` |

**Code Example:**

```tsx
// Tactile Stepper Button
const buttonEnabled = cn(
  'w-10 h-10 rounded-full flex items-center justify-center',
  'bg-white dark:bg-white/5',
  'border-2 border-zinc-300 dark:border-white/15',
  'text-zinc-700 dark:text-zinc-400',
  'transition-all duration-150',
  // Hover: Snap to black (invert colors)
  'hover:border-zinc-900 hover:bg-zinc-900 hover:text-white',
  'dark:hover:border-white dark:hover:bg-white dark:hover:text-black',
  'active:scale-95'
);
```

### Typography

| Token | Description | Use For |
|-------|-------------|---------|
| `DS.text.h1` | lg, semibold, zinc-900/white | Modal titles |
| `DS.text.label` | 10px, bold, uppercase, tracking-wider, zinc-400 | Section headers |
| `DS.text.body` | sm, medium, zinc-600/zinc-400 | Body text, descriptions |
| `DS.text.muted` | xs, zinc-500 | Hint text |
| `DS.text.accent` | zinc-900 / emerald-400 | Highlighted text, icons |

### Stepper (Traveler Counts)

| Token | Description |
|-------|-------------|
| `DS.stepper.button` | Enabled +/- button |
| `DS.stepper.buttonDisabled` | Disabled +/- button |
| `DS.stepper.value` | Center number display |

### Info Box (Replaces Warning Boxes)

Info boxes should feel like a **recessed technical panel**, not a warning sign.

| Token | Light Mode | Dark Mode | Description |
|-------|------------|-----------|-------------|
| `DS.infoBox.container` | `bg-zinc-50 border border-zinc-100 p-4` | `bg-white/[0.02] border border-white/5` | Clean, cool surface |
| `DS.infoBox.icon` | `text-zinc-500` | `text-zinc-400` | Subtle icon, not alarming |
| `DS.infoBox.text` | `text-zinc-600` | `text-zinc-400` | Body text |

**Code Example:**

```tsx
<div className={cn(
  'p-4 rounded-xl flex gap-4 items-start',
  'bg-zinc-50 dark:bg-white/[0.02]',
  'border border-zinc-100 dark:border-white/5'
)}>
  <AlertCircle className="h-5 w-5 text-zinc-500 dark:text-zinc-400" />
  <div>
    <p className="text-sm text-zinc-600 dark:text-zinc-400">
      To include flights, set Origin + Destination.
    </p>
    <div className="flex gap-2 mt-4">
      <button className={DS.actions.smallAction}>Set Origin</button>
    </div>
  </div>
</div>
```

### Custom Shadows

These shadow tokens are defined in `tailwind.config.mts` and available as `shadow-soft` / `shadow-card`:

| Token | Value | Use For |
|-------|-------|---------|
| `shadow-soft` | `0 20px 45px rgba(10, 14, 18, 0.08)` | Glass panels, modals, elevated surfaces |
| `shadow-card` | `0 15px 35px rgba(10, 14, 18, 0.08)` | Cards, tiles, smaller elevated elements |

---

## 2.5 Interaction Patterns

### Heart Preference Signals

Hearts indicate user preference for AI weighting, not cart additions.

| State | Visual | Tailwind Classes |
|-------|--------|------------------|
| Unpressed | Outline heart, zinc-400 | `stroke-zinc-400 fill-transparent` |
| Pressed | Filled heart, emerald-500, scale | `fill-emerald-500 stroke-emerald-500 scale-110` |
| Button BG | Semi-transparent dark | `bg-black/40 backdrop-blur-sm` |
| Focus | White ring | `focus-visible:ring-2 focus-visible:ring-white/50` |

**UX Principle:** Hearts are preference signals (weight in AI), not cart additions.

### Sticky Panels

Map panels use sticky positioning during timeline scroll (P3+ only).

Two map panels exist in `StrategyStageRenderer`:
- **Bridge mode map** (S2, destination set): `w-[350px]`, `sticky top-4`, `h-[400px]`
- **Full mode map** (S3, itinerary content): `w-[400px] max-w-[35vw]`, `sticky top-0 h-screen`

| Property | Bridge Mode (S2) | Full Mode (S3) | Mobile |
|----------|-----------------|----------------|--------|
| Map Width | `w-[350px]` | `w-[400px] max-w-[35vw]` | `100%` |
| Map Height | `h-[400px]` | `h-screen` | `h-[300px]` |
| Content Width | N/A (map beside hero) | `flex-1`, min `720px`, max `900px` | `100%` |
| Top offset | `sticky top-4` | `sticky top-0` | Non-sticky (inline) |
| Border | None | None | `border border-border/50` |
| Corner | `rounded-xl overflow-hidden` | None (full-height) | `rounded-xl overflow-hidden` |

**Why Fixed Map Width:**
- 400px (full mode) provides sufficient spatial awareness without dominating content
- Content area (720px min) ensures comfortable 2-column tile grid
- 900px max maintains readability limit
- Fixed width prevents layout shifts during zoom/interactions

**Desktop Usage (Full Mode / S3):**
```tsx
{/* Content + fixed map layout */}
<div className="flex gap-6">
  <div
    className="flex-1 min-w-0"
    style={{ minWidth: 720, maxWidth: 900 }}
  >
    {/* Content: Specialists → Tiles → Timeline */}
  </div>
  <div className="w-[400px] max-w-[35vw] shrink-0">
    <div className="sticky top-0 h-screen overflow-hidden">
      <InteractiveMap className="h-full w-full" />
    </div>
  </div>
</div>
```

**Desktop Usage (Bridge Mode / S2):**
```tsx
<div className="hidden w-[350px] shrink-0 lg:block">
  <div className="sticky top-4 h-[400px] overflow-hidden rounded-xl">
    <InteractiveMap className="h-full w-full" />
  </div>
</div>
```

**Mobile Usage (S3):**
```tsx
{/* Inline before timeline */}
<div className="h-[300px] overflow-hidden rounded-xl border border-border/50">
  <InteractiveMap className="h-full w-full" />
</div>
```

**fitBounds Behavior:**
- Uses responsive padding: desktop 40px, mobile 20px (via `useIsDesktop` hook)
- `maxZoom: 12` prevents over-zoom on single-POI clusters
- `minZoom: 7` prevents zooming out to show the whole globe
- `duration: 1000` for smooth 1s animation

**Map Base Style (Theme-Aware):**

The map switches Mapbox built-in styles based on `prefers-color-scheme`. Do NOT use Mapbox Studio custom styles.

| Mode | Mapbox Style URL |
|------|------------------|
| Light | `mapbox://styles/mapbox/light-v11` |
| Dark | `mapbox://styles/mapbox/dark-v11` |

Detection uses `window.matchMedia('(prefers-color-scheme: dark)')` with a `change` event listener for live theme switching. The `isDark` state drives the `mapStyle` prop on `<Map>`.

| Element | Light | Dark |
|---------|-------|------|
| Container border | `border-zinc-200` | `dark:border-white/10` |
| Route line | `#10b981` (emerald-500) | `#10b981` (emerald-500) |
| Route opacity | `0.7` | `0.7` |

---

## 3. Usage Examples

### A. Creating a Modal

```tsx
import { DS } from '@/lib/design-system';
import { cn } from '@/lib/utils';

export function ExampleModal({ onSave, onCancel }) {
  return (
    <div className={cn(DS.materials.glass, 'w-full max-w-md p-6')}>
      {/* Header */}
      <div className="mb-6">
        <span className={DS.text.label}>Configuration</span>
        <h1 className={DS.text.h1}>Set Trip Budget</h1>
      </div>

      {/* Large Input */}
      <div className="relative py-8">
        <span className="text-2xl text-zinc-500 dark:text-zinc-600 font-medium absolute top-10 left-4">$</span>
        <input
          placeholder="0"
          className={cn(DS.materials.inputLarge, 'pl-10')}
        />
      </div>

      {/* Pills */}
      <div className="flex gap-2 mb-6">
        <button className={cn(DS.pills.shape, DS.pills.active)}>Total Trip</button>
        <button className={cn(DS.pills.shape, DS.pills.inactive)}>Per Person</button>
      </div>

      {/* Footer */}
      <div className="flex justify-end gap-3">
        <button onClick={onCancel} className={DS.actions.secondary}>Cancel</button>
        <button onClick={onSave} className={DS.actions.primary}>Confirm</button>
      </div>
    </div>
  );
}
```

### B. Info Box (Instead of Warning)

```tsx
import { DS } from '@/lib/design-system';
import { Info } from 'lucide-react';

export function RequirementsInfo({ onSetOrigin, onSetDestination }) {
  return (
    <div className={DS.infoBox.container}>
      <Info className={DS.infoBox.icon} />
      <div className="flex flex-col gap-2">
        <p className={DS.infoBox.text}>
          To include flights, set Origin + Destination.
        </p>
        <div className="flex gap-2">
          <button onClick={onSetOrigin} className={DS.actions.smallAction}>
            Set Origin
          </button>
          <button onClick={onSetDestination} className={DS.actions.smallAction}>
            Set Destination
          </button>
        </div>
      </div>
    </div>
  );
}
```

### C. Stepper Component

```tsx
import { DS } from '@/lib/design-system';
import { Minus, Plus } from 'lucide-react';
import { cn } from '@/lib/utils';

export function Stepper({ value, min, max, onChange }) {
  const canDecrement = value > min;
  const canIncrement = value < max;

  return (
    <div className="flex items-center gap-3">
      <button
        onClick={() => canDecrement && onChange(value - 1)}
        className={canDecrement ? DS.stepper.button : DS.stepper.buttonDisabled}
        disabled={!canDecrement}
      >
        <Minus className="h-4 w-4" />
      </button>
      <span className={DS.stepper.value}>{value}</span>
      <button
        onClick={() => canIncrement && onChange(value + 1)}
        className={canIncrement ? DS.stepper.button : DS.stepper.buttonDisabled}
        disabled={!canIncrement}
      >
        <Plus className="h-4 w-4" />
      </button>
    </div>
  );
}
```

---

## 4. Color Rules Summary

### Light Mode Palette

| Element | Color | Tailwind |
|---------|-------|----------|
| Background | White/90 | `bg-white/90` |
| Border | Zinc-200 | `border-zinc-200` |
| Text Primary | Zinc-900 | `text-zinc-900` |
| Text Secondary | Zinc-500 | `text-zinc-500` |
| Primary Action | Black | `bg-zinc-900` |
| Toggle On | Emerald-500 | `bg-emerald-500` |

### Dark Mode Palette

| Element | Color | Tailwind |
|---------|-------|----------|
| Background | Zinc-950/95 | `dark:bg-zinc-950/95` |
| Border | White/10 | `dark:border-white/10` |
| Text Primary | White | `dark:text-white` |
| Text Secondary | Zinc-400 | `dark:text-zinc-400` |
| Primary Action | Emerald-600 | `dark:bg-emerald-600` |
| Primary Glow | Emerald | `shadow-[0_0_20px_-5px_rgba(16,185,129,0.4)]` |
| Input Focus Glow | Emerald | `shadow-[0_0_20px_-5px_rgba(16,185,129,0.1)]` |

### Restricted Colors

| Color | Hex | Rule |
|-------|-----|------|
| amber/orange | `#E86A1F` (accent) | Used ONLY as brand accent (`--accent`), specialist highlight pulse, and semantic warning/rejection states (Logic Guards, constraint badges, NextStepBar validation). Do not introduce new amber/orange usage outside these patterns. |
| teal-500 | `#14B8A6` | BANNED — replaced by emerald |

**Enforcement notes:**
- Rating stars and numeric rating text must use neutral zinc classes (`text-zinc-*`, optional `dark:text-zinc-*`), not amber.
- Booking/cart states that are not warnings should use neutral zinc or success emerald, not amber.

### Specialist Color Palette

Multi-specialist trips use color-coded visual indicators to distinguish activity sources.
All specialist data (colors, icons, keywords, display names) lives in a single registry:
**`frontend/lib/specialists.ts`**

| Specialist | Color Name | Hex | Usage |
|------------|------------|-----|-------|
| `local_expert` | Neutral Gray | `#6B7280` | Foundational content, Trip DNA |
| `diving` | Ocean Blue | `#0EA5E9` | Aquatic activities |
| `hiking` | Forest Green | `#10B981` | Terrestrial activities |
| `skiing` | Snow Blue | `#3B82F6` | Alpine activities |
| `cycling` | Lime | `#84CC16` | Cycling activities |
| `surfing` | Indigo | `#6366F1` | Surfing activities |
| `climbing` | Orange | `#F97316` | Rock/mountain climbing |
| `sailing` | Cyan | `#06B6D4` | Sailing/yacht activities |
| `wildlife_safari` | Amber | `#D97706` | Safari activities |
| `default` | Zinc | `#71717A` | Fallback for unknown types |

> `boating` is a backward-compat alias for `sailing`. Both frontend (`getSpecialistConfig`) and backend (`specialist_registry`) map `boating` to the `sailing` config.

#### Timeline Block Styling

Each activity block in the S3 Itinerary View shows specialist attribution via colored borders. ActivityMiniCard uses **static Tailwind class maps** (not inline styles) to ensure JIT compatibility:

```tsx
// Static Tailwind class lookups per specialist type (JIT needs static strings)
const borderAccentClass: Record<string, string> = {
  diving: 'border-l-cyan-500',
  hiking: 'border-l-emerald-500',
  skiing: 'border-l-blue-500',
  cycling: 'border-l-lime-500',
  surfing: 'border-l-indigo-500',
  sailing: 'border-l-cyan-500',
  climbing: 'border-l-orange-500',
  wildlife_safari: 'border-l-amber-500',
};

<div
  className={cn(
    'group relative flex flex-col lg:flex-row gap-3 p-3 rounded-xl border border-l-4 transition-shadow',
    'bg-white dark:bg-zinc-800/50 hover:shadow-md',
    borderAccentClass[block.specialist_type] || 'border-l-zinc-300 dark:border-l-zinc-600'
  )}
>
```

**Visual Treatment:**
- `border-l-4` colored left-border on each ActivityMiniCard (Tailwind classes, not inline styles)
- Icon color matches specialist via static class maps
- Card background: neutral white/zinc
- Unschedulable activities: `bg-amber-50/50 dark:bg-amber-900/10 border-amber-200` with `border-l-amber-500`

#### Implementation Reference

**Single Source of Truth:** `frontend/lib/specialists.ts`

```typescript
import { getSpecialistColor, getSpecialistConfig, SPECIALIST_IDS } from '@/lib/specialists';

getSpecialistColor('diving')     // '#0EA5E9'
getSpecialistConfig('diving')    // { id, displayName, icon, emoji, color, filterKeywords }
getSpecialistConfig('boating')   // returns sailing config (backward compat)
SPECIALIST_IDS                   // ['diving', 'hiking', 'skiing', 'cycling', 'surfing', 'climbing', 'sailing', 'wildlife_safari']
```

**CSS Topic Color System:** `--topic-color` is set inline via `getSpecialistColorRgb()`, consumed by `.topic-badge`, `.topic-border-left`, `.topic-header-tint` classes in `globals.css`.

**Note:** S2StrategyView uses `getSpecialistColorRgb()` with inline `style` props and CSS custom properties (`--topic-color`). ActivityMiniCard timeline blocks use static Tailwind class maps instead (see Timeline Block Styling above).

#### Trip DNA Bar

The Trip DNA bar shows engine constraints from niche specialists (all entries in `SPECIALIST_IDS`). It appears BELOW the specialist accordion cards and ABOVE the itinerary. Filtering uses `NICHE_SPECIALIST_IDS` from `lib/specialists.ts`.

**Layout Order (StrategyStageRenderer):**
1. Specialist Analysis (collapsed accordion cards, hidden in S3 by default)
2. Trip DNA bar (constraint pills with priority coloring)
3. Day-by-day Itinerary

**Specialist Card Subtitle (one_liner):**
- Uses `line-clamp-2` (not `truncate`) to allow 2-line display on mobile
- Prevents mid-word clipping of destination descriptions

**Constraint Priority Colors:**
| Priority | Keywords | Icon | Border (Light / Dark) | Background (Light / Dark) | Text (Light / Dark) |
|----------|----------|------|-----------------------|---------------------------|---------------------|
| **Blocking** | `no_fly`, `no-fly`, `nofly`, `safety`, `altitude`, `buffer`, `24h`, `24 hour`, `diving`, `dive`, `scuba`, `decompression`, `fly`, `flight` | `AlertTriangle` | `border-red-500/40` / `dark:border-red-500/40` | `bg-red-500/10` / `dark:bg-red-500/15` | `text-red-600` / `dark:text-red-300` |
| **Strong** | `morning`, `footwear`, `gear`, `timing`, `equipment`, `certification` | `Clock` | `border-amber-500/40` / `dark:border-amber-500/40` | `bg-amber-500/10` / `dark:bg-amber-500/15` | `text-amber-600` / `dark:text-amber-300` |
| **Soft** | Default (all others) | `Shield` | `border-zinc-400/40` / `dark:border-zinc-500/40` | `bg-zinc-500/10` / `dark:bg-zinc-500/15` | `text-zinc-600` / `dark:text-zinc-400` |

> **Light Mode Fix:** Text colors use `-600` suffix for light mode visibility (red-600, amber-600, zinc-600) instead of `-300` which is invisible on white backgrounds. Dark mode backgrounds use `/15` opacity (vs `/10` in light) for better visibility against dark surfaces.

**Priority-Based Icons:**
Icons are selected based on constraint keyword matching against the combined `type + rule + reason` text:
```tsx
const blocking = ['no_fly', 'no-fly', 'nofly', 'safety', 'altitude', 'buffer', '24h', '24 hour', 'diving', 'dive', 'scuba', 'decompression', 'fly', 'flight'];
const strong = ['morning', 'footwear', 'gear', 'timing', 'equipment', 'certification'];

if (blocking.some(k => t.includes(k))) return <AlertTriangle />;
if (strong.some(k => t.includes(k))) return <Clock />;
return <Shield />;
```

**Three-State Validation Override:**
When backend populates `constraints_validated` and `constraint_violations`:
- If constraint is **violated** → Amber with ring: `bg-amber-50 dark:bg-amber-900/30 border-amber-400 dark:border-amber-500/60 ring-2 ring-amber-400/60` with `AlertTriangle` icon
- If constraint is **validated** → Emerald: `bg-emerald-50 dark:bg-emerald-900/30 border-emerald-300 dark:border-emerald-600/50` with `CheckCircle` icon
- Otherwise → Priority coloring above (blocking/strong/soft)

**Styling:**
```tsx
<div className="flex items-start gap-2 my-4 mx-4 p-3 rounded-lg bg-zinc-100 dark:bg-zinc-950 border border-zinc-300 dark:border-zinc-700">
  <span className="text-xs uppercase font-semibold text-zinc-500 dark:text-zinc-400 shrink-0 leading-[30px]">Trip DNA:</span>
  <div className="flex-1 min-w-0">
    <div className="flex flex-wrap gap-2">
      {/* Constraint pills with priority-based icons and coloring */}
      <span className={cn(
        "inline-flex items-center gap-2 px-3.5 py-1.5 rounded-full border text-xs font-medium whitespace-nowrap",
        pillClass // Priority-based or three-state: red/amber/zinc/emerald with light/dark variants
      )}>
        {/* Icon by priority: AlertTriangle (blocking), Clock (strong), Shield (soft) */}
        <AlertTriangle className="w-4 h-4 shrink-0" />
        {constraintLabel}
      </span>
    </div>
  </div>
</div>
```

**Visibility:** Only shows when `engineConstraints.length > 0` (niche specialist constraints exist).

**Implementation:** `frontend/components/plan/StrategyStageRenderer.tsx` (search for "Trip DNA")

### Inline Constraint Badge Colors

Activity and logistics blocks display inline constraint badges to show constraint-first optimization. These use a distinct color palette for severity levels.

| Severity | Background | Border | Title | Icon Color |
|----------|------------|--------|-------|------------|
| `warning` | `bg-amber-50 dark:bg-amber-900/10` | `border-amber-200 dark:border-amber-800/40` | `text-amber-700 dark:text-amber-400` | Emoji |
| `info` | `bg-blue-50 dark:bg-blue-900/10` | `border-blue-200 dark:border-blue-800/40` | `text-blue-700 dark:text-blue-400` | Emoji |
| `success` | `bg-emerald-50 dark:bg-emerald-900/10` | `border-emerald-200 dark:border-emerald-800/40` | `text-emerald-700 dark:text-emerald-400` | Emoji |

**Amber here is an approved semantic usage** — constraint severity badges where "caution" connotation is correct (warnings, safety constraints). See Restricted Colors in Section 4.

**Visual Treatment:**
```tsx
<div className={cn(
  'flex items-start gap-2 p-3 rounded-lg text-xs',
  constraint.severity === 'warning' && 'bg-amber-50 dark:bg-amber-900/10 border border-amber-200',
  constraint.severity === 'info' && 'bg-blue-50 dark:bg-blue-900/10 border border-blue-200',
  constraint.severity === 'success' && 'bg-emerald-50 dark:bg-emerald-900/10 border border-emerald-200'
)}>
  <span className="text-base">{constraint.icon}</span>
  <div>
    <div className="font-semibold">{constraint.title}</div>
    <div className="text-zinc-600 dark:text-zinc-400">{constraint.description}</div>
  </div>
</div>
```

**Implementation:** `frontend/components/plan/timeline/blocks/ActivityMiniCard.tsx`, `LogisticsBlock.tsx`

---

## 6. Component Mapping

All sheets live at `frontend/components/plan/sheets/`. Most sheets use raw Tailwind classes that match DS token values rather than importing `DS` directly. The table below reflects actual DS token imports and inline DS-pattern usage.

| Component | Location | Key DS Tokens / Patterns |
|-----------|----------|--------------------------|
| BaseSheet | `plan/sheets/BaseSheet.tsx` | Raw glass pattern (matches `DS.materials.glass`), raw iconBtn pattern |
| DestinationSheet | `plan/sheets/DestinationSheet.tsx` | `DS.text.label`, raw Void Input pattern, raw Tactile pills |
| OriginSheet | `plan/sheets/OriginSheet.tsx` | Raw Void Input pattern, raw Tactile pills (no DS import) |
| TravelersSheet | `plan/sheets/TravelersSheet.tsx` | Raw Tactile pills, inline stepper (w-12 h-12 mobile variant) |
| BudgetSheet | `plan/sheets/BudgetSheet.tsx` | Raw inputLarge pattern (text-5xl), raw Tactile pills |
| FlightsSheet | `plan/sheets/FlightsSheet.tsx` | Raw infoBox pattern, `Switch` component (toggle), raw Tactile pills |
| StaysSheet | `plan/sheets/StaysSheet.tsx` | Same as Flights |
| ActivitiesSheet | `plan/sheets/ActivitiesSheet.tsx` | Same as Flights, `Stepper` from `ui/stepper.tsx` (day preference steppers) |
| TripSettingsSheet | `plan/sheets/TripSettingsSheet.tsx` | BaseSheet, field rows for mobile settings relay |
| DatesSheet | `plan/sheets/DatesSheet.tsx` | Raw glass pattern, raw Tactile pills, raw primary button |
| ChatPanel | `chat/ChatPanel.tsx` | Raw Tactile pills (suggestion chips), Living Void pattern |
| UnifiedChipRow | `plan/UnifiedChipRow.tsx` | `CoreChip` (CSS custom properties, not DS pills) |
| Calendar | `ui/calendar.tsx` | Custom (see Calendar section) |
| StrategyHero | `plan/stages/StrategyHero.tsx` | `DS.text.label`, `DS.text.body`, `DS.infoBox.container` (3 variants: `hero`, `compact`, `accordion`) |
| Stepper (shared) | `ui/stepper.tsx` | Raw DS.stepper pattern (sm/default size variants) |
| TileCard | `tiles/TileCard.tsx` | Raw glass card pattern, rating stars use neutral zinc scale |
| MiniCard | `tiles/MiniCard.tsx` | Compact glass card pattern, rating stars use neutral zinc scale |
| SuggestionCard | `plan/tiles/SuggestionCard.tsx` | Suggested card variant, neutral zinc rating treatment, emerald save state |
| BookableCard | `plan/tiles/BookableCard.tsx` | Dark booking card, in-cart/border states use zinc, booked uses emerald |
| GatingBlocker | `plan/sheets/GatingBlocker.tsx` | Shared prerequisite-gating notice for module sheets (Flights/Stays/Activities). Raw infoBox pattern (`bg-zinc-50 dark:bg-white/[0.02]`), raw smallAction pattern buttons |
| AlternativesModal | `plan/modals/AlternativesModal.tsx` | Sheet modal with neutral zinc rating stars and diff badges |
| CategorySection | `plan/booking/CategorySection.tsx` | Booking status dots/text with dark-aware zinc/emerald states |

**Out of DS scope:** `consent-manager.tsx`, `legal-page.tsx` — follows shadcn/prose tokens.

---

## 7. Calendar Component ("The Seamless Pill")

The calendar uses a **Seamless Pill** design inspired by Booking.com — a continuous ribbon with emerald "caps" (start/end) and a neutral zinc "bridge" (middle range).

### Design Philosophy

**Problem:** Using emerald for the entire range creates a "muddy" look in light mode. The faint green middle strip becomes invisible against white backgrounds.

**Solution:** The **"Caps & Bridge"** pattern:
- **Caps (Start/End):** Solid emerald endpoints — the "action anchors"
- **Bridge (Middle):** Neutral zinc strip — high contrast, clearly visible
- **Today:** Emerald text + underline only — no background to avoid overlap bugs

### Implementation: Custom DayButton

We use a **custom `DayButton` component** with JavaScript priority logic instead of CSS specificity battles. This eliminates all `!important` hacks and makes styling predictable.

```tsx
// Priority-based styling (JS logic, not CSS specificity)
const getStyles = () => {
  if (isRangeStart) return 'bg-emerald-600 text-white ...';
  if (isRangeMiddle) return 'bg-zinc-200 text-zinc-900 ...';
  if (isToday) return 'text-emerald-600 underline ...';
  return 'text-zinc-900 ...';
};
```

### Visual Elements

| Element | Light Mode | Dark Mode |
|---------|------------|-----------|
| **Day Text** | `text-zinc-900` | `text-zinc-100` |
| **Day Hover** | `bg-zinc-200` (square) | `bg-zinc-800` (square) |
| **Weekday Headers** | `text-zinc-500 font-bold text-[10px] tracking-widest uppercase` | `text-zinc-400` |
| **Caps (Start/End)** | `bg-emerald-600 text-white font-extrabold` | `bg-emerald-500 text-zinc-950` |
| **Bridge (Middle)** | `bg-zinc-200 text-zinc-900` | `bg-zinc-800 text-zinc-100` |
| **Single Selection** | `bg-emerald-600 text-white rounded-md font-extrabold` | `bg-emerald-500 text-zinc-950` |
| **Today** | `text-emerald-600 font-extrabold underline decoration-2` | `text-emerald-400` |
| **Outside Month** | `text-zinc-400 opacity-50` | `text-zinc-600 opacity-50` |
| **Quick Select Pills** | Same as `DS.pills.active/inactive` | Same |
| **Apply Button** | `bg-emerald-600 text-white` | Same + glow |

### The Seamless Pill Strip

The range selection creates a **continuous pill with emerald caps and zinc bridge**:

```
┌─────────────────────────────────────────────────────┐
│  12   13   [14 ░░░░ 15 ░░░░ 16 ░░░░ 17]  18   19   │
│            ╰──┬──╯ ╰───┬───╯ ╰───┬───╯ ╰──┬──╯     │
│           Start    Bridge    Bridge    End         │
│         (emerald)  (zinc)    (zinc)  (emerald)     │
│         (round L)  (flat)    (flat)  (round R)     │
└─────────────────────────────────────────────────────┘
```

### Geometric Precision

| Element | Outer Radius | Inner Radius |
|---------|--------------|--------------|
| **Start Cap** | `rounded-l-md` (4px left) | `rounded-r-none` (0px right) |
| **End Cap** | `rounded-r-md` (4px right) | `rounded-l-none` (0px left) |
| **Bridge** | `rounded-none` (0px all) | Creates gapless ribbon |
| **Single Selection** | `rounded-md` (4px all) | N/A |
| **Hover** | `rounded-none` (0px all) | Square highlight |

### Premium Typography

| Element | Specification |
|---------|---------------|
| **Font Family** | Geometric Sans (Inter, Geist) |
| **Numerical Mode** | `tabular-nums` — prevents layout jitter |
| **Day Headers** | `text-[10px] font-bold uppercase tracking-widest` |
| **Unselected Dates** | `font-medium` (500) |
| **Selected/Today** | `font-extrabold` (800) |
| **Letter Spacing** | `tracking-tight` (-0.02em) for dates |

### Today Indicator ("The Beacon")

**Problem:** A background color on "Today" creates grey-on-emerald overlap when Today is also selected.

**Solution:** Use **text styling only** — emerald text with an underline. No background.

| Property | Light Mode | Dark Mode |
|----------|------------|-----------|
| **Text** | `text-emerald-600` | `text-emerald-400` |
| **Weight** | `font-extrabold` | Same |
| **Underline** | `underline decoration-2 underline-offset-4` | Same |
| **Decoration** | `decoration-emerald-600` | `decoration-emerald-400` |
| **Background** | `bg-transparent` | Same |

### Code Reference

The calendar component is at `frontend/components/ui/calendar.tsx`.

```tsx
// Custom DayButton with priority-based styling
function CustomDayButton({ day, modifiers, className, ...props }: DayButtonProps) {
  const isRangeStart = modifiers?.range_start;
  const isRangeEnd = modifiers?.range_end;
  const isRangeMiddle = modifiers?.range_middle;
  const isSelected = modifiers?.selected;
  const isToday = modifiers?.today;
  const isOutside = modifiers?.outside;
  const isDisabled = modifiers?.disabled;

  const getStyles = () => {
    if (isDisabled) return 'text-zinc-400 opacity-50 cursor-not-allowed';
    if (isOutside) return 'text-zinc-400 dark:text-zinc-600 opacity-50';

    // PRIORITY 1: Range endpoints (Caps)
    if (isRangeStart && isRangeEnd) {
      return 'bg-emerald-600 text-white dark:bg-emerald-500 dark:text-zinc-950 rounded-md font-extrabold';
    }
    if (isRangeStart) {
      return 'bg-emerald-600 text-white dark:bg-emerald-500 dark:text-zinc-950 rounded-l-md rounded-r-none font-extrabold';
    }
    if (isRangeEnd) {
      return 'bg-emerald-600 text-white dark:bg-emerald-500 dark:text-zinc-950 rounded-r-md rounded-l-none font-extrabold';
    }

    // PRIORITY 2: Range middle (Bridge)
    if (isRangeMiddle) {
      return 'bg-zinc-200 text-zinc-900 dark:bg-zinc-800 dark:text-zinc-100 rounded-none';
    }

    // PRIORITY 3: Single selection
    if (isSelected) {
      return 'bg-emerald-600 text-white dark:bg-emerald-500 dark:text-zinc-950 rounded-md font-extrabold';
    }

    // PRIORITY 4: Today (Emerald text + underline, NO background)
    if (isToday) {
      return 'text-emerald-600 dark:text-emerald-400 font-extrabold underline decoration-2 decoration-emerald-600 dark:decoration-emerald-400 underline-offset-4 bg-transparent';
    }

    // Default
    return 'text-zinc-900 dark:text-zinc-100';
  };

  return (
    <button
      {...props}
      className={cn(
        'h-9 w-9 p-0 font-medium inline-flex items-center justify-center',
        'rounded-none text-sm tracking-tight tabular-nums',
        'transition-all duration-150 ease-in-out',
        !isRangeStart && !isRangeEnd && !isSelected && !isRangeMiddle && 'hover:bg-zinc-200 dark:hover:bg-zinc-800',
        getStyles(),
        className
      )}
    />
  );
}
```

### Why This Works

1. **No CSS Specificity Wars:** JavaScript priority logic determines styles — no `!important` needed.
2. **High Contrast Bridge:** Zinc-200/Zinc-800 is clearly visible against white/dark backgrounds.
3. **Emerald Anchors:** Start/End caps use emerald to signal "selection boundaries."
4. **Today Beacon:** Underline-only styling avoids background collision bugs.
5. **Tabular Numbers:** Prevents layout jitter when selecting different dates.
6. **Premium Typography:** Extra-bold weights for high-intent elements (selected, today).

---

## 8. Dark Mode Rules (IMPORTANT)

### The Glass Fill Rule

**Problem:** In Dark Mode, thin grey outlines (`border-white/10`) tend to disappear on OLED screens or look like glitches. Inactive elements look "ghostly" and fragile.

**Solution:** Use **Glass Fills** (`bg-white/5`) instead of just empty borders. This adds "materiality" to buttons, making them feel like physical objects sitting on the dark surface.

| State | Old (Wrong) | New (Correct) |
|-------|-------------|---------------|
| **Inactive Pill** | `dark:bg-transparent dark:border-white/10` | `dark:bg-white/5 dark:border-white/15` |
| **Inactive Hover** | `dark:hover:border-white/30` | `dark:hover:bg-white/10 dark:hover:text-white` |

**Code Example:**

```tsx
// Glass Fill Pill (Dark Mode)
<button className={cn(
  'px-4 py-2.5 rounded-lg text-sm font-medium',
  'transition-all duration-150',
  isSelected
    ? 'bg-zinc-900 text-white border-2 border-transparent shadow-md dark:bg-white dark:text-black dark:border-transparent'
    // Glass Fill: visible substance, not just outline
    : cn(
        'bg-white border-2 border-zinc-200 text-zinc-600',
        'hover:border-zinc-900 hover:bg-zinc-50 hover:text-zinc-900',
        // Dark: Glass Fill
        'dark:bg-white/5 dark:border-white/15 dark:text-zinc-400',
        'dark:hover:bg-white/10 dark:hover:text-white'
      )
)}>
  {label}
</button>
```

### The Void Input

**Problem:** Inputs in Dark Mode with thin grey borders look like standard form fields, not premium "data entry zones."

**Solution:** Make inputs a **Void** — darker than the card, no border until focused. Focus adds an emerald glow.

> **Note:** `DS.materials.input` uses `dark:bg-black/40 dark:border-white/5`. Sheet-level search inputs (e.g. DestinationSheet) use the deeper variant: `dark:bg-black/50 dark:border-transparent`. Both are valid -- sheets override for a more dramatic void effect.

| State | DS Token (`DS.materials.input`) | Sheet Override (DestinationSheet) |
|-------|------|---------|
| **Default** | `dark:bg-black/40 dark:border-white/5` | `dark:bg-black/50 dark:border-transparent` |
| **Focus** | `dark:focus:border-emerald-500/50` | `dark:focus:border-emerald-500/50 dark:focus:bg-black/60` |
| **Focus Glow** | `dark:focus:shadow-[0_0_20px_-5px_rgba(16,185,129,0.1)]` | `dark:focus:shadow-[0_0_20px_-5px_rgba(16,185,129,0.15)]` |

**Code Example:**

```tsx
<input
  className={cn(
    'w-full h-14 pl-12 pr-4 rounded-xl',
    // Light: Hollow grey field
    'bg-zinc-50 border border-zinc-200',
    'focus:border-zinc-900 focus:bg-white',
    // Dark: THE VOID - darker than the card
    'dark:bg-black/50 dark:border-transparent',
    'dark:focus:border-emerald-500/50 dark:focus:bg-black/60',
    // Text
    'text-zinc-900 dark:text-white text-base font-medium',
    'placeholder:text-zinc-400 dark:placeholder:text-zinc-600',
    // Focus effects
    'focus:outline-none focus:ring-0',
    'focus:shadow-lg focus:shadow-zinc-200/50 dark:focus:shadow-[0_0_20px_-5px_rgba(16,185,129,0.15)]',
    'transition-all duration-200'
  )}
/>
```

### The Emerald Glow (Save Buttons)

All primary action buttons in Dark Mode should have the **Emerald Glow** effect:

```tsx
// Primary Button (Dark Mode)
canSave
  ? cn(
      'bg-zinc-900 text-white shadow-lg shadow-zinc-900/10 hover:bg-zinc-800',
      // Dark: Glowing Emerald
      'dark:bg-emerald-600 dark:hover:bg-emerald-500',
      'dark:shadow-[0_0_20px_-5px_rgba(16,185,129,0.4)]'
    )
  : 'bg-zinc-100 dark:bg-zinc-800 text-zinc-400 dark:text-zinc-600 cursor-not-allowed'
```

### Budget Input (Big Number)

The budget input should feel like a **luxury price tag** — huge, bold, with an emerald caret in Dark Mode.

> **Note:** `DS.materials.inputLarge` uses `text-4xl`. The actual `BudgetSheet` uses `text-5xl` for extra impact. Use `text-5xl` for budget inputs.

```tsx
<input
  className={cn(
    'bg-transparent',
    // HUGE and BOLD
    'text-5xl font-bold text-center tracking-tight',
    'text-zinc-900 dark:text-white',
    'border-none focus:ring-0 w-full',
    'placeholder:text-zinc-300 dark:placeholder:text-zinc-700',
    'focus:outline-none',
    // Matrix caret effect
    'caret-zinc-900 dark:caret-emerald-500'
  )}
/>
```

---

## 9. Chat Bubbles ("Signal vs Noise")

**Problem:** In Dark Mode, both user and assistant bubbles look similar (grey on grey), creating a "Wall of Grey" that flattens the hierarchy. It looks like a monologue, not a dialogue.

**Solution:** Create maximum contrast between **The Commander (User)** and **The Machine (Assistant)**.

### User Bubble: "The Signal"

The user's input is the **Active Intent**. It should be bright and solid.

| Mode | Styling |
|------|---------|
| **Light** | `bg-zinc-900 text-white` (Solid Black) |
| **Dark** | `bg-white text-zinc-950` (Solid White) + white glow shadow |

### Assistant Bubble: "The System"

The assistant is the **Infrastructure**. It should feel like part of the dashboard surface.

| Mode | Styling |
|------|---------|
| **Light** | `bg-white/80 backdrop-blur-sm border border-zinc-200` (Glass) |
| **Dark** | `bg-white/5 border-white/10 text-zinc-300` (Dark Glass) |

**Code Example:**

```tsx
<div className={
  isUserMessage
    ? cn(
        'rounded-2xl rounded-br-md px-4 py-2.5 text-left transition-all',
        // Light: Solid Black (The Commander)
        'bg-zinc-900 text-white border border-zinc-900',
        'shadow-md hover:shadow-lg hover:-translate-y-0.5',
        'hover:bg-zinc-800 hover:border-zinc-800',
        // Dark: Solid White (Maximum Contrast Signal)
        'dark:bg-white dark:text-zinc-950 dark:border-white',
        'dark:shadow-[0_0_20px_-5px_rgba(255,255,255,0.3)]',
        'dark:hover:bg-zinc-100'
      )
    : cn(
        'rounded-2xl rounded-bl-sm px-4 py-2.5 transition-all',
        // Light: Glass effect
        'bg-white/80 backdrop-blur-sm border border-zinc-200',
        'shadow-sm hover:shadow-md hover:-translate-y-0.5',
        // Dark: Dark Glass (The System)
        'dark:bg-white/5 dark:backdrop-blur-sm',
        'dark:border-white/10 dark:shadow-none',
        // Text
        'text-zinc-700 dark:text-zinc-300'
      )
}>
```

### Why This Works

1. **Readability:** Black text on White (User) vs. Grey text on Black (Assistant) creates perfect rhythm. Your eyes instantly know who is talking.
2. **Premium Feel:** The "Solid White" user bubble feels like a poker chip or a high-end physical key. It has weight.
3. **Brand Alignment:** It matches the pill logic (Active = White/Black, Inactive = Glass).

---

## 9.A Exploration Mode Response Styling

Exploration mode responses (generic travel Q&A) use enhanced markdown rendering within the assistant bubble. These responses are information-dense and require careful typography.

### Content Typography

| Element | Light Mode | Dark Mode | Tailwind Classes |
|---------|------------|-----------|------------------|
| **Section Headers** | Zinc-900, semibold | White, semibold | `font-semibold text-zinc-900 dark:text-white` |
| **Body Text** | Zinc-700 | Zinc-300 | `text-zinc-700 dark:text-zinc-300` |
| **Bullet Points** | Zinc-600 | Zinc-400 | `text-zinc-600 dark:text-zinc-400` |
| **Ending Prompt** | Zinc-500, italic | Zinc-400, italic | `italic text-zinc-500 dark:text-zinc-400` |

### Markdown Rendering Rules

The exploration responses use markdown that must render cleanly:

```tsx
// Markdown content styling within assistant bubble
<div className="prose prose-sm dark:prose-invert max-w-none">
  {/* Headers: Bold labels */}
  <strong className="text-zinc-900 dark:text-white">
    What makes it special:
  </strong>

  {/* Lists: Compact with proper spacing */}
  <ul className="mt-2 space-y-1 text-zinc-600 dark:text-zinc-400">
    <li>Great for: Beach lovers, Divers</li>
    <li>The vibe is relaxed and romantic</li>
  </ul>

  {/* Ending: Softer, inviting tone */}
  <p className="mt-4 italic text-zinc-500 dark:text-zinc-400">
    What else would you like to know?
  </p>
</div>
```

### Spacing Rules

| Between | Spacing | Purpose |
|---------|---------|---------|
| Intro → Headers | `mt-4` (16px) | Clear separation |
| Headers → Lists | `mt-2` (8px) | Grouped content |
| List items | `space-y-1` (4px) | Compact but readable |
| Content → Ending | `mt-4` (16px) | Visual break before CTA |

### Suggestion Chips (Exploration Context)

Exploration responses show contextual follow-up chips. These use the standard pill styling but with semantic grouping:

| Chip Type | Purpose | Example |
|-----------|---------|---------|
| **Follow-up question** | Continue exploration / post-plan topic query | "Best romantic spots?", "Where should I stay?" |
| **Planning nudge** | Soft transition | "When to visit?" |
| **Plan CTA** | Exit exploration | "Plan Bali trip" |

Question chips are always visible (never suppressed). Post-planning, they route through
`question_answer` short-circuit to produce section-specific content (accommodation, weather, etc.).

**Visual distinction:**
- Follow-up chips: Raw Tactile Rule pattern (`bg-white border-2 border-zinc-200` / `dark:bg-white/5 dark:border-white/15`)
- Planning trigger chips: Emerald highlight (`bg-emerald-50 border-2 border-emerald-500/40 text-emerald-700`) with `Sparkles` icon prefix

```tsx
// Suggestion chips in ChatPanel
<button className={cn(
  'px-4 py-2.5 rounded-lg text-xs font-bold uppercase tracking-wide',
  isPlanningTrigger ? [
    'bg-emerald-50 dark:bg-emerald-950/30',
    'border-2 border-emerald-500/40 dark:border-emerald-500/30',
    'text-emerald-700 dark:text-emerald-400',
    'shadow-[0_0_12px_-3px_rgba(16,185,129,0.2)]',
  ] : [
    'bg-white dark:bg-white/5',
    'border-2 border-zinc-200 dark:border-white/15',
    'text-zinc-600 dark:text-zinc-400',
  ]
)}>
  {isPlanningTrigger && <Sparkles className="w-3 h-3 mr-1.5 inline-block" />}
  {suggestion}
</button>
```

---

## 10. Stepper Buttons (Glass Treatment)

Stepper buttons in Dark Mode also need the Glass Fill treatment.

Two implementations exist:
- **DS token** (`DS.stepper.button`): `w-10 h-10` — used directly or in `ui/stepper.tsx` (default size)
- **TravelersSheet inline**: `w-12 h-12` — larger touch target for mobile (see Section 12)
- **`ui/stepper.tsx`**: Shared component with `size="sm"` (w-8 h-8) and `size="default"` (w-10 h-10) variants

| State | Light Mode | Dark Mode |
|-------|------------|-----------|
| **Enabled** | `bg-white border-2 border-zinc-300 text-zinc-700` | `bg-white/5 border-white/15 text-zinc-400` |
| **Hover** | `hover:border-zinc-900 hover:bg-zinc-900 hover:text-white` | `hover:bg-white hover:border-white hover:text-black` |
| **Disabled** | `bg-zinc-50 border-2 border-zinc-200 text-zinc-300` | `bg-white/[0.02] border-white/5 text-zinc-700` |

**Code Example (DS token, w-10 h-10):**

```tsx
const buttonEnabled = cn(
  'w-10 h-10 rounded-full flex items-center justify-center',
  // Light: White with strong border
  'bg-white border-2 border-zinc-300 text-zinc-700',
  // Dark: Glass Fill - visible substance
  'dark:bg-white/5 dark:border-white/15 dark:text-zinc-400',
  'transition-all duration-150',
  // Hover: Snap to black (Light) / white (Dark)
  'hover:border-zinc-900 hover:bg-zinc-900 hover:text-white',
  'dark:hover:bg-white dark:hover:border-white dark:hover:text-black',
  'active:scale-95'
);
```

---

## 11. Mobile Specifics

Mobile has physics that Desktop does not: Safe Areas, Touch Targets, Slide Gestures. This section covers mobile-specific patterns.

### The Sticky Header Strategy ("Collapse & Glass")

On mobile, screen real estate is critical. We do NOT keep the full pill stack sticky—it eats too much space.

**The Logic:** When the user scrolls past `y > 50`, transform the header into a **Single Slim Bar**.

| State | Behavior | Visual |
|-------|----------|--------|
| **Top (Idle)** | Full Pill Stack | All parameters visible in horizontal scroll reel |
| **Scrolled** | Condensed Bar | `h-14`, `bg-zinc-950/80`, `backdrop-blur-xl`, `border-b border-white/5` |

**Condensed Bar Content:**
- Left: "Dubai • Jan 29 - Feb 4" (White, Font Bold)
- Right: "Tune" icon (Equalizer style) to expand back to full mode

**Code Example:**

```tsx
// Condensed Sticky Header
<div className={cn(
  'fixed top-0 inset-x-0 z-40',
  'h-14 px-4 flex items-center justify-between',
  'bg-zinc-950/80 backdrop-blur-xl',
  'border-b border-white/5',
  'transition-all duration-300'
)}>
  <span className="text-sm font-bold text-white truncate">
    Dubai • Jan 29 - Feb 4
  </span>
  <button className="p-2 text-zinc-400 hover:text-white">
    <SlidersHorizontal className="h-5 w-5" />
  </button>
</div>
```

---

### The Safe Area Rule (iOS)

**Problem:** Action buttons at the bottom of the screen conflict with the iOS Home Indicator (the white bar at the bottom). Users try to click "Save" and accidentally swipe the app away.

**Solution:** All bottom-fixed elements (Floating Action Buttons, Save Buttons in Sheets) must respect `safe-area-inset-bottom`.

**Code Example:**

```tsx
// The "Save" bar in a mobile sheet
<div className={cn(
  'p-4 border-t border-white/5 bg-zinc-950',
  // Critical: Respect iOS safe area
  'pb-[calc(1rem+env(safe-area-inset-bottom))]'
)}>
  <button className={DS.actions.primary}>Save Changes</button>
</div>
```

**Tailwind Config (if using `pb-safe`):**

```js
// tailwind.config.js
theme: {
  extend: {
    padding: {
      'safe': 'env(safe-area-inset-bottom)',
    }
  }
}
```

---

### Touch Targets

Mobile fingers are imprecise. Every interactive element needs adequate hit area.

| Element | Minimum Size | Notes |
|---------|--------------|-------|
| **Pills/Chips** | `h-10` or `h-11` | Larger than desktop (core: `h-8`, module: `h-9`) |
| **Buttons** | `h-12` (48px) | Apple's minimum recommendation |
| **Close X** | `p-4` hit area | Even if icon is small |
| **Stepper +/-** | `w-12 h-12` | Bigger than desktop (`w-10 h-10`) |

---

### Horizontal Scroll (The "Pill Reel")

**Problem:** Stacking pills vertically eats screen space and looks messy when they wrap.

**Solution:** Use a horizontal scroll carousel. Keep pills on ONE line. Let users swipe left/right.

**Code Example:**

```tsx
// Horizontal Pill Reel
<div className={cn(
  'flex items-center gap-2',
  'overflow-x-auto no-scrollbar',
  'px-4 -mx-4',  // Bleed to edges
  'py-2'         // Vertical padding for touch
)}>
  <PillChip label="Dubai" active />
  <PillChip label="Jan 29 - Feb 4" />
  <PillChip label="2 Adults" />
  <PillChip label="$5k Budget" />
  {/* More pills... */}
</div>
```

**CSS for `no-scrollbar`:**

```css
.no-scrollbar::-webkit-scrollbar {
  display: none;
}
.no-scrollbar {
  -ms-overflow-style: none;
  scrollbar-width: none;
}
```

---

### Sheet Anatomy (Mobile Bottom Sheets)

Mobile sheets slide up from the bottom. They need specific affordances.

**Components:**

1. **Drag Handle:** Always include at the top center. Tells users "You can swipe me down."
2. **Backdrop:** Semi-transparent overlay behind the sheet.
3. **Safe Footer:** Buttons respect the Home Indicator area.

**Code Example:**

```tsx
// Mobile Bottom Sheet Structure
<>
  {/* Backdrop */}
  <div className="fixed inset-0 z-40 bg-black/60 backdrop-blur-sm" />

  {/* Sheet */}
  <div className={cn(
    'fixed inset-x-0 bottom-0 z-50',
    'bg-zinc-950 rounded-t-3xl',
    'max-h-[90vh] overflow-y-auto'
  )}>
    {/* Drag Handle */}
    <div className="flex justify-center pt-3 pb-2">
      <div className="w-12 h-1.5 bg-zinc-700/50 rounded-full" />
    </div>

    {/* Content */}
    <div className="px-4 pb-4">
      {/* Sheet content... */}
    </div>

    {/* Footer with Safe Area */}
    <div className="p-4 border-t border-white/5 pb-[calc(1rem+env(safe-area-inset-bottom))]">
      <button className={DS.actions.primary}>Save</button>
    </div>
  </div>
</>
```

---

### Chat Message Alignment (Mobile)

On mobile's narrow screen, create a stronger "Conversation" feel with strict alignment.

| Message Type | Alignment | Rationale |
|--------------|-----------|-----------|
| **User** | Right (`justify-end`) | Standard messaging app behavior |
| **Assistant** | Left (`justify-start`) | Creates visual rhythm |

**Code Example:**

```tsx
<div className={cn(
  'flex',
  isUserMessage ? 'justify-end' : 'justify-start'
)}>
  <div className={cn(
    'max-w-[85%]',
    isUserMessage
      ? 'rounded-2xl rounded-br-md'  // Sharp bottom-right
      : 'rounded-2xl rounded-bl-sm'  // Sharp bottom-left
  )}>
    {content}
  </div>
</div>
```

---

### Chat Status Header (Persistent Progress Indicator)

**Principle:** Never remove UI chrome mid-session. Elements that disappear create layout shift and break spatial memory. **Transform, don't remove.**

The chat status header is a persistent element at the top of the chat panel that evolves through planning phases:

| Phase | Status Text | Label | Indicator |
|-------|------------|-------|-----------|
| S0 (no destination) | "Where to next?" | AWAITING INPUT | blinking cursor |
| S0 (destination, no dates) | "When would you like to go?" | SET DATES | blinking cursor |
| S0 (all fields set) | "Ready to build your plan" | GENERATING PLAN | blinking cursor |
| S1 / Generating | "Building your trip..." | GENERATING | spinning loader |
| S2 / P1 (plan ready) | "Your trip is taking shape" | REFINE PLAN | pulsing dot |
| S3 / P3 (itinerary) | "Itinerary complete" | READY | check icon |

**Desktop rendering:**
- **S0:** Full hero banner with topographic background pattern; collapses to compact glassmorphism bar on scroll
- **Post-S0:** Compact 56px glassmorphism bar (`h-14`, `backdrop-blur-md`) with status dot/icon + text + label
- Transition between S0 hero and post-S0 compact bar uses `AnimatePresence mode="wait"` crossfade

**Mobile:** Header collapse behavior remains — full "Where to next?" visible initially, collapses on scroll.

### Mobile-Specific Header Behavior

| State | Header Visibility |
|-------|-------------------|
| **Initial (no interaction)** | Full "Where to next?" visible |
| **Scrolled / Focused on input** | Header collapses, only condensed bar visible |

---

### Summary: Mobile Checklist

When building mobile UI, verify:

- [ ] **Safe Areas:** Bottom buttons use `pb-[calc(1rem+env(safe-area-inset-bottom))]`
- [ ] **Touch Targets:** All interactive elements are at least 44px
- [ ] **Pill Reel:** Parameters use horizontal scroll, not vertical stacking
- [ ] **Drag Handle:** All bottom sheets have `w-12 h-1.5 bg-zinc-700/50` drag indicator
- [ ] **Sticky Header:** Transforms to condensed bar on scroll
- [ ] **Chat Alignment:** User right, Assistant left
- [ ] **No Scrollbars:** Horizontal scrollers use `no-scrollbar` class

---

## 12. Mobile Layout Constraints

### The "Thumb Zone" Rule

Primary actions (Save, Build) must be comfortably reachable and safe from system gestures.

| Constraint | Value | Notes |
|------------|-------|-------|
| **Bottom Padding** | `pb-[calc(1rem+env(safe-area-inset-bottom))]` | Respects iOS Home Indicator |
| **Minimum Button Height** | `h-12` or `h-14` | Easy tapping on mobile |
| **Stepper Button Size** | `w-12 h-12` | Larger than desktop (`w-10 h-10`) |

**Code Example:**

```tsx
// Mobile sheet footer
<div className={cn(
  'p-4 border-t border-white/5 bg-zinc-950',
  'pb-[calc(1rem+env(safe-area-inset-bottom))]'
)}>
  <button className="w-full h-14 rounded-xl bg-emerald-600 text-white font-bold">
    Save Changes
  </button>
</div>
```

---

### The "Carousel" Rule

Never stack configuration pills vertically on mobile. It eats up reading space.

| Property | Value | Reason |
|----------|-------|--------|
| **Layout** | `flex-nowrap overflow-x-auto` | Single row, slides off-screen |
| **Gutters** | `-mx-4 px-4` | Bleed pills to screen edges |
| **Scroll** | `no-scrollbar` | Hide scrollbar for clean look |
| **Gap** | `gap-2` | Consistent spacing |

**Code Example:**

```tsx
// Horizontal Pill Carousel
<div className={cn(
  'flex items-center gap-2',
  'overflow-x-auto no-scrollbar',
  '-mx-4 px-4 py-2'  // Bleed to edges with vertical touch padding
)}>
  <PillChip label="Dubai" active />
  <PillChip label="Jan 29 - Feb 4" />
  <PillChip label="2 Adults" />
  <PillChip label="$5k Budget" />
</div>
```

---

### The "Tactile Button" Rule

Stepper buttons and interactive controls must look like physical buttons, not ghost outlines.

| State | Light Mode | Dark Mode |
|-------|------------|-----------|
| **Enabled** | `bg-white border-2 border-zinc-300 text-zinc-700` | `bg-white/5 border-white/15 text-zinc-400` |
| **Hover** | `hover:border-zinc-900 hover:bg-zinc-900 hover:text-white` | `hover:bg-white hover:border-white hover:text-black` |
| **Disabled** | `bg-zinc-50 border-2 border-zinc-200 text-zinc-300` | `bg-white/[0.02] border-white/5 text-zinc-700` |

**Key Principle:** Borders should be visible without squinting. Both mobile (`TravelersSheet`, `w-12 h-12`) and desktop (`DS.stepper.button`, `w-10 h-10`) steppers use `border-zinc-300`. The `ui/stepper.tsx` shared component also uses `border-zinc-300`.

**Code Example:**

```tsx
const buttonEnabled = cn(
  'w-12 h-12 rounded-full flex items-center justify-center',
  // Light: White with STRONG visible border
  'bg-white border-2 border-zinc-300 text-zinc-700',
  // Dark: Glass Fill
  'dark:bg-white/5 dark:border-2 dark:border-white/15 dark:text-zinc-400',
  'transition-all duration-150',
  // Hover: Snap to black/white
  'hover:border-zinc-900 hover:bg-zinc-900 hover:text-white',
  'dark:hover:bg-white dark:hover:border-white dark:hover:text-black',
  'active:scale-95'
);
```

---

### Sheet "Grabber"

Mobile bottom sheets must have a visible handle to indicate they can be swiped down.

| Property | Value |
|----------|-------|
| **Width** | `w-12` (48px) |
| **Height** | `h-1.5` (6px) |
| **Color (Light)** | `bg-zinc-300` |
| **Color (Dark)** | `bg-zinc-700/50` |
| **Shape** | `rounded-full` |
| **Position** | Centered, `pt-3 pb-2` spacing |

**Code Example:**

```tsx
<div className="flex justify-center pt-3 pb-2">
  <div className="w-12 h-1.5 rounded-full bg-zinc-300 dark:bg-zinc-700/50" />
</div>
```

---

## 13. Toasts (System Signals)

Toasts should feel like **Technical Status Updates**, not generic pop-ups. We follow the **"Inversion Rule"** to ensure they stand out against the background.

### Visual Design

| Feature | Light Mode ("The Black Chip") | Dark Mode ("The Emerald Signal") |
|---------|-------------------------------|----------------------------------|
| **Concept** | High-contrast technical signal | Bioluminescent data packet |
| **Background** | **Solid Zinc-900** (Black) | **Zinc-950/90** (Deep Glass) |
| **Border** | `border-zinc-800` | `border-emerald-500/20` |
| **Text** | `text-white` | `text-white` |
| **Shadow** | `shadow-2xl` | `shadow-[0_0_20px_-5px_rgba(16,185,129,0.3)]` (Glow) |
| **Icon** | Emerald-400 (success), Zinc-400 (info), Amber-400 (warning) | Same |

### Positioning Strategy

Positioning changes based on device to avoid interaction conflicts (keyboards, chat inputs, sticky headers).

| Device | Position | Logic |
|--------|----------|-------|
| **Desktop** | **Bottom-Right** (`bottom-8 right-8`) | Standard system tray area. Avoids covering the main itinerary header or top-right profile controls. |
| **Mobile** | **Top-Center** (`top-[calc(env(safe-area-inset-top)+16px)]`) | "Heads-Up Display." Avoids the bottom "Thumb Zone," virtual keyboard, and chat input. |

### Code Implementation

**1. Toast Styling (Tailwind)**

```tsx
const toastStyles = cn(
  // Base shape
  'flex items-center gap-3 px-4 py-3 rounded-xl shadow-2xl',
  'font-medium text-sm tracking-wide',

  // Light Mode: "The Black Chip" - Solid zinc-900
  'bg-zinc-900 text-white border border-zinc-800',

  // Dark Mode: "The Emerald Signal" - Deep glass with glow
  'dark:bg-zinc-950/90 dark:backdrop-blur-md dark:text-white',
  'dark:border dark:border-emerald-500/20',
  'dark:shadow-[0_0_20px_-5px_rgba(16,185,129,0.3)]'
);
```

**2. Container Positioning**

```tsx
// Toast container position
<div className={cn(
  'fixed z-[9999] pointer-events-none',
  // Desktop: bottom-right (system notification tray area)
  'md:bottom-8 md:right-8 md:top-auto md:left-auto md:translate-x-0',
  // Mobile: top-center, safe-area aware (avoids keyboard/chat input)
  'top-[calc(env(safe-area-inset-top)+16px)] left-1/2 -translate-x-1/2'
)}>
  {/* Toast items */}
</div>
```

### Iconography

Do not use default library icons. Use **Lucide React** to match the UI.

| Type | Icon | Color |
|------|------|-------|
| **Success** | `<CheckCircle2 className="w-4 h-4 text-emerald-400" />` | Emerald-400 |
| **Error** | `<AlertCircle className="w-4 h-4 text-red-400" />` | Red-400 |
| **Warning** | `<AlertCircle className="w-4 h-4 text-amber-400" />` | Amber-400 |
| **Info** | `<Info className="w-4 h-4 text-zinc-400" />` | Zinc-400 |

### Visual Example

```
Light Mode:
┌────────────────────────────────────────┐
│ (✓) Trip saved successfully            │  ← Black box, white text, green icon
└────────────────────────────────────────┘

Dark Mode:
┌────────────────────────────────────────┐
│ (✓) Trip saved successfully      ✕     │  ← Black glass, white text, emerald glow
└────────────────────────────────────────┘
      ↑ Subtle emerald border glow
```

### Implementation Reference

The toast system is implemented in `frontend/components/ui/toast.tsx`.

---

## 14. Primary Navigation (Chat / Plan)

Mobile uses a horizontal swipe layout with a compact tab bar. Desktop uses a split panel layout (no tabs — both Chat and Plan are visible simultaneously).

### Mobile Tab Bar

The tab bar sits between the header and the swipe container in `MobileSwipeLayout`. It uses CSS variable-based colors (`foreground`, `muted-foreground`) for theme compatibility.

| Element | Active State | Inactive State | Locked State |
|---------|-------------|----------------|--------------|
| **Tab** | `bg-foreground/10 text-foreground` | `text-muted-foreground hover:text-foreground` | `text-muted-foreground/40 cursor-not-allowed` |
| **Shape** | `px-3 py-1 rounded-full text-xs font-medium` | Same | Same |
| **Plan badge** | Emerald dot (`w-2 h-2 rounded-full bg-emerald-500`) when new content + not on Plan page | — | — |

### Code Example

```tsx
// MobileSwipeLayout tab bar
<div className="flex items-center gap-1 px-3 py-1 border-b border-white/10">
  <button
    className={cn(
      'px-3 py-1 rounded-full text-xs font-medium transition-colors',
      activePage === 0
        ? 'bg-foreground/10 text-foreground'
        : 'text-muted-foreground hover:text-foreground'
    )}
  >
    Chat
  </button>
  <button
    disabled={!planTabEnabled}
    className={cn(
      'px-3 py-1 rounded-full text-xs font-medium transition-colors relative',
      !planTabEnabled
        ? 'text-muted-foreground/40 cursor-not-allowed'
        : activePage === 1
          ? 'bg-foreground/10 text-foreground'
          : 'text-muted-foreground hover:text-foreground'
    )}
  >
    Plan
    {planTabEnabled && hasNewPlanContent && activePage !== 1 && (
      <span className="absolute -top-0.5 -right-0.5 w-2 h-2 rounded-full bg-emerald-500" />
    )}
  </button>
</div>
```

### Desktop Layout

On desktop, both Chat and Plan panels are visible side-by-side in `SplitLayoutView`. No tab bar is needed.

### Implementation Reference

- Mobile tabs + swipe: `frontend/components/layout/MobileSwipeLayout.tsx`
- Mobile header (branding/status): `frontend/components/layout/MobileModeHeader.tsx`
- Desktop split: `frontend/components/layout/SplitLayoutView.tsx`

---

## 15. Stop Button (Streaming Interrupt)

When the AI is generating a response, the user can interrupt the stream with a "Stop" button. This button must NOT use red styling, as red is reserved exclusively for errors in the design system.

### Design Philosophy

**Problem:** A red stop button (`bg-red-500`) looks like an error state or danger warning. In our "Travel Architect" aesthetic, red = error only.

**Solution:** The stop button should be **minimal and monochromatic**—a subtle control that doesn't scream "DANGER" but clearly communicates "you can click me to stop."

### Visual Specifications

| Element | Light Mode | Dark Mode |
|---------|------------|-----------|
| **Background** | `bg-zinc-200` | `bg-white/10` |
| **Border** | `border-zinc-300` | `border-white/10` |
| **Hover** | `bg-zinc-300` | `bg-white/20` |
| **Icon** | Solid `bg-zinc-900` square | Solid `bg-white` square |

### Code Example

```tsx
// Stop Streaming Button (Inside Input Capsule)
<button
  type="button"
  onClick={handleStopStreaming}
  className={cn(
    'h-11 w-11 flex items-center justify-center rounded-[22px] transition-all hover:scale-105 active:scale-95',
    // Light: Subtle grey
    'bg-zinc-200 hover:bg-zinc-300 border border-zinc-300',
    // Dark: Glass button
    'dark:bg-white/10 dark:hover:bg-white/20 dark:border-white/10'
  )}
  title="Stop"
>
  {/* Minimal square icon - matches theme */}
  <div className="w-3 h-3 bg-zinc-900 dark:bg-white rounded-[2px]" />
</button>
```

### Why This Works

1. **No False Alarms:** The button doesn't look like an error, just a neutral control.
2. **Consistency:** Uses the same monochromatic palette as the rest of the input area.
3. **Minimal:** The small square icon is universally understood as "stop" without being aggressive.

### Implementation Reference

The stop button is implemented in `frontend/components/chat/ChatPanel.tsx`.

---

## 16. The Living Void (AI Processing State)

When the AI is processing, the input field transforms into an active status indicator—we call this "The Living Void." Instead of a separate floating pill showing status, the input itself becomes the status.

### Design Philosophy

**Problem:** A floating green pill above the input looks like a generic notification badge. It's disconnected from the action (the input where user submitted their message).

**Solution:** The input field becomes the status indicator. During AI processing:
1. The input glows with emerald border/shadow
2. Status text appears inside the input (replacing placeholder)
3. The whole capsule pulses subtly

This creates a direct visual link: "What I typed → is being processed."

### Visual Specifications

| State | Light Mode | Dark Mode |
|-------|------------|-----------|
| **Border** | `border-emerald-500/50` | `border-emerald-500/40` |
| **Shadow** | `shadow-[0_0_20px_-5px_rgba(16,185,129,0.2)]` | `shadow-[0_0_25px_-5px_rgba(16,185,129,0.3)]` |
| **Animation** | `animate-pulse` (subtle) | Same |
### Code Example

```tsx
// Input Capsule with Living Void State
<div
  className={cn(
    'relative flex items-center w-full min-h-14 rounded-[28px] transition-all duration-300',
    'bg-zinc-50 dark:bg-black/40',

    // Priority 1: "Living Void" - AI Processing
    isLoading && nodeStatus?.node
      ? [
          'border border-emerald-500/50 dark:border-emerald-500/40',
          'shadow-[0_0_20px_-5px_rgba(16,185,129,0.2)] dark:shadow-[0_0_25px_-5px_rgba(16,185,129,0.3)]',
          'animate-pulse',
        ]
      // Default state
      : 'border border-zinc-200 dark:border-white/10'
  )}
>
  {/* Input field — placeholder changes contextually */}
  <textarea
    placeholder={isInputDisabledByPlanState ? 'Updating...' : 'Where to?'}
    ...
  />
</div>
```

### Why This Works

1. **Direct Feedback:** The input that received the message now shows it's being processed.
2. **Spatial Logic:** Status appears where the action happened, not in a disconnected floating element.
3. **Premium Feel:** The emerald glow matches the "Bioluminescent" dark mode aesthetic.
4. **Subtle Animation:** The pulse is noticeable but not distracting.

### Implementation Reference

The Living Void is implemented in `frontend/components/chat/ChatPanel.tsx`.

---

## 17. System Status Text ("Awaiting Input" Pattern)

The "Awaiting Input" terminal-style text reinforces the "Architect/AI" persona. It must follow the **Bifurcated Aesthetic**—distinct styling for Light and Dark modes.

### Design Philosophy

**Problem:** Using the same color in both modes creates visual inconsistency. Grey text (`text-zinc-400`) in Light Mode looks weak; emerald on white looks cheap.

**Solution:**
- **Light Mode:** "Typewriter Ink" — Jet Black (`text-zinc-950`), solid and permanent like an architectural label.
- **Dark Mode:** "System Pulse" — Emerald (`text-emerald-500`) with a glow, like a retro terminal or flight computer.

### Visual Specifications

| Element | Light Mode ("Typewriter Ink") | Dark Mode ("System Pulse") |
|---------|-------------------------------|----------------------------|
| **Text Color** | `text-zinc-950` | `text-emerald-500` |
| **Glow** | None | `drop-shadow-[0_0_8px_rgba(16,185,129,0.5)]` |
| **Font** | `font-mono text-[9px] uppercase tracking-[0.12em] font-bold` | Same |
| **Cursor Color** | `bg-zinc-950` | `bg-emerald-500` |
| **Cursor Glow** | None | `shadow-[0_0_6px_rgba(16,185,129,0.6)]` |
| **Cursor Animation** | `animate-terminal-blink` (defined in `globals.css`) | Same |

### Code Example

```tsx
// System Status Text (Awaiting Input, Parameters Updated, etc.)
<div className="flex items-center gap-1.5">
  {/* The Text */}
  <span className={cn(
    // Base Typography: Technical Monospace
    "font-mono text-[9px] uppercase tracking-[0.12em] font-bold",
    // Light Mode: "Typewriter Ink" (Solid, Dark, Permanent)
    "text-zinc-950",
    // Dark Mode: "System Pulse" (Glowing, Emerald, Digital)
    "dark:text-emerald-500 dark:drop-shadow-[0_0_8px_rgba(16,185,129,0.5)]"
  )}>
    Awaiting Input
  </span>

  {/* The Blinking Cursor */}
  <div className={cn(
    "w-1 h-1.5 animate-terminal-blink rounded-sm",
    // Light: Solid black ink
    "bg-zinc-950",
    // Dark: Emerald with glow
    "dark:bg-emerald-500 dark:shadow-[0_0_6px_rgba(16,185,129,0.6)]"
  )} />
</div>
```

### Why This Works

1. **Light Mode:** The jet black text looks like a typewriter label or architectural blueprint annotation—professional and permanent.
2. **Dark Mode:** The emerald glow creates a "heartbeat" effect, reinforcing the AI/system persona. It matches the bioluminescent design language.
3. **Consistency:** The cursor shares the same color as the text, creating a unified visual element.

### Implementation Reference

- `frontend/components/chat/ChatPanel.tsx` (S0 hero banner)

---

## 17.5. Hero Header ("Vertical Stack")

The hero header uses a **vertical stack** layout: compact image above, summary pills below on the solid app background. No text overlays on images.

### Design Philosophy

**Problem:** Overlaying text/chips on destination photos creates readability issues across varying light/dark areas. Gradient overlays "fight the image" and reduce visual impact.

**Solution:** Separate image and text into distinct layers. The image stands alone; pills below it serve as the sole trip summary (no title, no subtitle).

### Visual Specifications

**Three states:**

| State | Condition | Rendering |
|-------|-----------|-----------|
| **Collapsed** | Mobile scroll / compact mode | `bg-secondary` bar with title + date range text |
| **Topo** | No destination image | Animated topographic background + "Build Your Itinerary" |
| **Vertical Stack** | Destination image ready | Compact image + pill row below |

**Vertical Stack layout:**
```tsx
{/* Compact rounded image */}
<div className="mx-4 mt-4 rounded-2xl overflow-hidden shadow-2xl ring-1 ring-black/10 dark:ring-white/10">
  <img className="w-full max-h-[15vh] min-h-[120px] object-cover" />
</div>

{/* Pills ARE the summary — no title, no subtitle */}
<div className="px-6 py-2">
  <TripSummaryPills variant="default" />
</div>
```

**Key rules:**
- Image height: `max-h-[15vh] min-h-[120px]` — viewport-relative, never dominates
- No title or subtitle rendered — pills contain all trip info
- No specialist pills — Trip DNA bar below already shows specialists
- Hero hidden on mobile — `TripStatusBar` provides trip context instead

### CoreChip Sizing (default variant)

| Property | Value |
|----------|-------|
| Height | `h-8` |
| Padding | `px-3.5` |
| Font | `text-sm` |
| Icon | `h-3.5 w-3.5` |
| Gap | `gap-1.5` |
| Shape | `rounded-full border` |

**Active state:** Uses CSS custom properties `--chip-active-*` for theming.
**Budget pill:** Always `italic` class, `tone="optional"`.

### Implementation Reference

- Hero header: `frontend/components/plan/PlanHeader.tsx`
- Chip components: `frontend/components/plan/TripSummaryPills.tsx`
- CoreChip: `frontend/components/plan/CoreChip.tsx`

---

## 17.6. Spacing Standard

### Spacing Tiers

All spacing (gap, padding, margin) MUST snap to one of three tiers for consistent vertical and horizontal rhythm. This applies globally — not just the right panel.

| Tier | Values | Use For |
|------|--------|---------|
| **Within** | `gap-2`, `space-y-2`, `p-2`, `px-2`, `py-2` | Related elements inside a section (icon+text, chip rows, inline groups) |
| **Between** | `gap-4`, `space-y-4`, `p-4`, `px-4`, `py-4`, `mt-4`, `mb-4` | Between sections (cards, tile groups, content blocks) |
| **Major** | `gap-6`, `space-y-6`, `p-6`, `px-6`, `py-6`, `mt-6`, `mb-6` | Major boundaries (hero→content, grid columns, panel sections) |

**Banned in-between values:** `gap-3`, `space-y-3`, `gap-5`, `space-y-5`, `pb-8`, `gap-7`, `gap-9`, `mt-3`, `mb-3`, `mt-5`, `mb-5`. Round to the nearest tier.

**Exception:** Action button rows (Cancel/Save pairs) use `gap-3` for touch-target spacing.

### Allowed Exceptions

| Value | Context |
|-------|---------|
| `py-2.5`, `py-3` | Pill/button internal padding (touch target sizing, per Tactile Rule) |
| `px-3`, `px-3.5` | Pill/chip horizontal padding (per `DS.pills.shape`) |
| `gap-1`, `gap-1.5` | Icon-to-label micro-spacing inside compact elements (badges, chips) |
| `p-3` | Compact cards (constraint badges, inline alerts) |
| `py-1`, `py-1.5` | Tight vertical rhythm inside dense lists |
| `mt-2`, `mb-2` | Within-tier margin variants |
| `-mx-4 px-4` | Bleed-to-edge pattern for horizontal scroll (documented in Pill Reel section) |

### Container Padding Minimums

| Container Type | Minimum | Preferred |
|----------------|---------|-----------|
| Modal / Sheet | `p-4` | `p-6` |
| Card | `p-4` | `p-4` |
| Inline alert / badge | `p-3` | `p-3` |
| Top-level page section | `px-4` | `px-6` (desktop), `px-4` (mobile) |

**Rule:** Container padding must be ≥ one tier above its child gap. A `p-2` container with `space-y-4` children is a violation.

### Desktop vs Mobile Spacing Scale

| Element | Desktop | Mobile | Notes |
|---------|---------|--------|-------|
| Page/panel horizontal | `px-6` to `px-8` | `px-4` | Tighter on small screens |
| Card internal | `p-4` to `p-6` | `p-4` | Never reduce below `p-4` |
| Section vertical gap | `gap-6` | `gap-4` | Tighter stacking on mobile |
| Grid gap | `gap-6` | `gap-4` or `gap-3` | Narrower gutters |

Desktop-scale spacing (`px-8`, `gap-8`, `p-8`) requires a responsive mobile override or `useIsDesktop` gate.

### Margin Direction Consistency

Within a single parent container, use ONE spacing strategy:

- **Best:** Parent uses `space-y-*` or `gap-*` (children have no margins)
- **Acceptable:** All children use `mt-*` (top margin only) OR all use `mb-*` (bottom margin only)
- **Violation:** Mix of `mt-*` and `mb-*` on siblings — creates unpredictable double-spacing

### Sibling Symmetry

Elements at the same hierarchy level must use the same spacing tier. Mismatched margins between same-level siblings (e.g., `mt-4` then `mt-6` then `mt-4`) break visual rhythm.

---

## 17.7. Text-on-Background Contrast

All text must be legible against its resolved background in both light and dark modes. When `design-system.md` specifies a text/bg pair for an element, use it exactly. For unlisted combinations, use WCAG AA as the floor: **4.5:1 for body text, 3:1 for large text (≥18px or ≥14px bold).**

### Known-Good Pairs (Light Mode)

| Background | Approved Text Colors |
|------------|----------------------|
| `bg-white`, `bg-white/90` | `text-zinc-900`, `text-zinc-800`, `text-zinc-700`, `text-zinc-600` |
| `bg-zinc-50` | `text-zinc-900`, `text-zinc-800`, `text-zinc-700`, `text-zinc-600`, `text-zinc-500` |
| `bg-zinc-900`, `bg-black` | `text-white`, `text-zinc-100`, `text-zinc-200` |
| `bg-emerald-600` | `text-white` |
| `bg-amber-50` | `text-amber-700`, `text-amber-800` |
| `bg-blue-50` | `text-blue-700`, `text-blue-800` |
| `bg-emerald-50` | `text-emerald-700`, `text-emerald-800` |
| `bg-red-500/10` | `text-red-600`, `text-red-700` |

### Known-Good Pairs (Dark Mode)

| Background | Approved Text Colors |
|------------|----------------------|
| `bg-zinc-950`, `bg-zinc-950/95` | `text-white`, `text-zinc-100`, `text-zinc-200`, `text-zinc-300`, `text-zinc-400` |
| `bg-white/5`, `bg-white/[0.02]` | `text-white`, `text-zinc-100`, `text-zinc-200`, `text-zinc-300`, `text-zinc-400` |
| `bg-white`, `bg-zinc-100` | `text-black`, `text-zinc-900`, `text-zinc-800` |
| `bg-emerald-500`, `bg-emerald-600` | `text-white`, `text-zinc-950` |
| `bg-amber-900/10` | `text-amber-400`, `text-amber-300` |
| `bg-blue-900/10` | `text-blue-400`, `text-blue-300` |
| `bg-emerald-900/10` | `text-emerald-400`, `text-emerald-300` |

### Failing Pairs (Never Use)

| Pair | Why It Fails | Correct Alternative |
|------|--------------|---------------------|
| `text-zinc-300` on `bg-white` | Light-on-light, ~2:1 | `text-zinc-500` minimum |
| `text-zinc-400` on `bg-white` (body text) | Too faint for body | `text-zinc-500` (muted), `text-zinc-600` (body) |
| `text-zinc-600` on `bg-zinc-900` | Dark-on-dark, ~3:1 | `dark:text-zinc-400` or lighter |
| `text-zinc-700` on `bg-zinc-800` | Adjacent shades, ~1.5:1 | `dark:text-zinc-300` or lighter |
| `text-white` on `bg-zinc-100` | Near-invisible in light | `text-zinc-900` |
| `text-emerald-400` on `bg-white` | Low contrast pastel | `text-emerald-600` in light |
| `text-red-300` on `bg-white` | Invisible light-mode red | `text-red-600` in light |
| `text-amber-300` on `bg-white` | Invisible light-mode amber | `text-amber-600` in light |
| `text-zinc-500` on `bg-zinc-600` | Mid-range clash | `text-zinc-200` or `text-white` |

### Evaluation Rules

1. **Spec wins.** If this doc defines the text/bg pair for that element, use it exactly.
2. **Check BOTH modes.** A pair that works in light may fail in dark (e.g., `text-zinc-600` on zinc-950).
3. **Trace inheritance.** If a text element has no `bg-*`, walk up to the nearest ancestor. For glass surfaces (`DS.materials.glass`), resolve as `bg-white/90` (light), `bg-zinc-950/95` (dark).
4. **Semi-transparent backgrounds** (e.g., `bg-black/40`, `bg-white/5`) — evaluate against the likely parent. For overlays on images/maps, assume a mid-tone backdrop and require `text-white` or `text-black`.
5. **Placeholder text** (`placeholder:text-*`) must meet 3:1 minimum against input background.
6. **Disabled text** may use lower contrast intentionally (`zinc-400` on white is acceptable for disabled states only).

---

## 18. Reset Button ("Fresh Sheet" Pattern)

The Reset button allows users to start over with a fresh planning session. It must NOT use red styling, as red is reserved for critical errors in the design system.

### Design Philosophy

**Problem:** A red "Reset Trip" button (`text-red-600`) looks like a "Self-Destruct" warning. In our "Travel Architect" aesthetic, an architect crumpling up a draft doesn't set off alarms—they just grab a fresh sheet of paper.

**Solution:** Use **monochrome styling** to make Reset feel like a professional utility, not a danger warning.

### Visual Specifications

| Element | Light Mode | Dark Mode |
|---------|------------|-----------|
| **Text** | `text-zinc-500 → zinc-900` on hover | `text-zinc-500 → white` on hover |
| **Background** | `hover:bg-zinc-100` | `hover:bg-white/5` |
| **Font** | `text-[10px] font-bold uppercase tracking-widest` | Same |
| **Icon** | `RotateCcw` from Lucide, `w-3 h-3` | Same |

### Code Example (Web)

```tsx
// Desktop Reset Button (Top-Right Header)
<button className={cn(
  "flex items-center gap-2 px-3 py-2 rounded-lg transition-colors",
  // Typography: Technical Uppercase
  "text-[10px] font-bold uppercase tracking-widest",
  // Light: Zinc-500 → Black
  "text-zinc-500 hover:text-zinc-900 hover:bg-zinc-100",
  // Dark: Zinc-500 → White
  "dark:text-zinc-500 dark:hover:text-white dark:hover:bg-white/5"
)}>
  <RotateCcw className="w-3 h-3" />
  Reset
</button>
```

### Code Example (Mobile)

```tsx
// Mobile Dropdown Menu Item
<button className={cn(
  "flex items-center gap-2 px-2 py-2.5 rounded-md transition-colors text-left",
  // Typography: Technical Uppercase
  "text-[10px] font-bold uppercase tracking-widest",
  // Light: Solid Black (High Intent)
  "text-zinc-900 hover:bg-zinc-100",
  // Dark: Solid White (High Intent)
  "dark:text-white dark:hover:bg-white/10"
)}>
  <RotateCcw className="h-3.5 w-3.5" />
  Reset Trip
</button>
```

### Why This Works

1. **No False Alarms:** The button doesn't look like an error—it's just a neutral utility control.
2. **Architect Metaphor:** Grabbing a fresh sheet of paper is a calm, professional action—not an emergency.
3. **Typography Consistency:** The `tracking-widest uppercase` style links it to other technical UI elements like "Awaiting Input."

### BANNED Patterns

| Pattern | Why It's Wrong |
|---------|----------------|
| `text-red-600 dark:text-red-400` | Red = Error only. Reset is not an error state. |
| Large button size | Reset should be subtle, not prominent. It's a utility, not a primary action. |
| Confirmation modal | An architect doesn't need a "Are you sure?" popup to crumple paper. Trust the user. |

### Implementation Reference

- Web: `frontend/components/layout/NomadicLanding.tsx`
- Mobile: `frontend/components/layout/MobileModeHeader.tsx`

---

## 19. Chat Interaction: Command & Receipt

**Core Philosophy:** Never hide the user's intent. The chat is the **Audit Log** of the trip construction.

* **Old Way:** Replace user text with "Updated Destination". (Bad: Destroys context).
* **Architect Way:** Keep user text visible → Append technical "System Receipt" below it.

### Component Anatomy

#### A. The Commander (User Message)
- **Visual:** High-contrast solid "Poker Chip." Maximum visibility.
- **Light Mode:** `bg-zinc-900 text-white`
- **Dark Mode:** `bg-white text-zinc-950` + white glow shadow

#### B. The System Receipt (The Log)
- **Visual:** Tiny monospaced status line below user message.
- **Typography:** `font-mono text-[10px] uppercase tracking-widest font-bold`
- **Light Mode:** `text-zinc-600`
- **Dark Mode:** `text-emerald-500` + `drop-shadow-[0_0_8px_rgba(16,185,129,0.5)]`

#### C. The Smart Loader (Loading State)

**Purpose:** A single mutating status line that shows the current processing node. Cleaner than a scrolling log for consumer apps.

**Layout:**
- Single-line container: icon + text, left-aligned as assistant placeholder
- No glass bubble, no scrolling log

**Icon:** Dynamic Lucide icon mapped from backend `icon_key` (Brain, Building2, Plane, Shield, PenTool, Star, MapPin). Defaults to `Loader2` spinner.
- Icon color: `text-zinc-500 dark:text-emerald-500 animate-pulse`

**Text:**
- Typography: `font-mono text-[10px] uppercase tracking-widest font-bold`
- Color: `text-zinc-600 dark:text-emerald-500/80`
- Animate on change: `animate-in fade-in slide-in-from-left-1 duration-300`

**Example Output:**
```
🧠 ROUTING_TO_SPECIALIST
```

#### D. The Architect (Assistant Response)
- **Visual:** Glass surface, part of the infrastructure.
- **Light Mode:** `bg-white/80 border-zinc-200`
- **Dark Mode:** `bg-white/5 border-white/10`

### Behavior by Mode

| Mode | Verb | Example |
|------|------|---------|
| **SETUP** | EXTRACTED | `>> EXTRACTED: DESTINATION · DATES · BUDGET` |
| **PLAN** | MODIFIED | `>> MODIFIED: DAY_03_DINNER_SLOT` |
| **BOOK** | UPDATED | `>> UPDATED: OUTBOUND_FLIGHT_SELECTION` |

### Implementation Reference
- SystemReceipt: `frontend/components/chat/SystemReceipt.tsx`
- SmartLoader: `frontend/components/chat/SmartLoader.tsx`
- Integration: `frontend/components/chat/ChatPanel.tsx`
- Backend telemetry: `backend/app/plan_graph.py` (emits `logic_reveal` events)

---

## 20. NextStepBar CTA States (Command Island)

The NextStepBar ("Command Island") is a sticky footer CTA that appears when the plan is ready to finalize. It only renders for the `finalize_plan` action; `expand_itinerary` is handled by auto-expand in ChatPanel.

### Visual States

| State | Background | Text | Shadow | Usage |
|-------|------------|------|--------|-------|
| **Ready** | `bg-emerald-500` | `text-white` | Emerald glow | Plan ready, "Finalize & Book" |
| **Processing** | `bg-zinc-200 dark:bg-zinc-800` | `text-zinc-500 dark:text-zinc-400` | None | Finalization in progress, "Scanning..." |

### Code Example

```tsx
// NextStepBar.tsx - Button styling
<button
  className={cn(
    'h-10 px-5 rounded-full font-bold text-xs tracking-wide uppercase',
    // Ready: Green with glow
    isActionReady &&
      'bg-emerald-500 hover:bg-emerald-400 text-white shadow-[0_0_15px_-3px_rgba(16,185,129,0.4)] active:scale-95',
    // Processing: Gray with spinner
    isFinalizing &&
      'bg-zinc-200 dark:bg-zinc-800 text-zinc-500 dark:text-zinc-400 cursor-not-allowed'
  )}
>
  {isFinalizing ? 'Scanning...' : 'Finalize & Book'}
</button>
```

### Context Display (Left Side)

| Element | Valid | Incomplete |
|---------|-------|------------|
| **Badge** | `"X days"` (emerald) | `"needs dates"` or `"past dates"` (amber) |
| **Date Range** | `"Feb 5 — Feb 12"` | `"Feb 5 → ?"` |
| **Text Color** | `text-zinc-800 dark:text-white` | `text-amber-600 dark:text-amber-400` |

### Implementation Reference

- Component: `frontend/components/plan/NextStepBar.tsx`
- Validation logic: Inline in `NextStepBar.tsx` (reads `tripInputs` from `documentStore`)

---

## 20.5 Plan Regeneration Triggers

There is no standalone "Refresh" button. Plan regeneration is triggered automatically or via existing CTAs:

- **Chat auto-regen:** Structural plan changes trigger automatic itinerary rebuild
- **Preference auto-regen:** Heart changes trigger via `usePreferenceAutoRegen` hook
- **Manual build:** "Build Itinerary" CTA in `StrategyStageRenderer.tsx`
- **Branch manager:** Trip input changes tracked by `useBranchManager` / `useTripInputsEditor` hooks

### Implementation Reference

- Preference auto-regen: `frontend/hooks/usePreferenceAutoRegen.ts`
- Build CTA: `frontend/components/plan/StrategyStageRenderer.tsx`
- Trip input editing: `frontend/components/layout/hooks/useTripInputsEditor.ts`
- Branch management: `frontend/components/layout/hooks/useBranchManager.ts`
- Generation logic: `frontend/components/layout/NomadicLanding.tsx` (`proceedWithItineraryGeneration`)
- UX Flow: `docs/ux_unified_architecture.md` (Regeneration Flow section)

---

## 21. Logic Guards (Amber Rejection Pattern)

**Core Philosophy:** The Architect does not crash; it rejects invalid parameters and asks for correction. We use the **"Reject & Correct"** pattern.

* **Banned:** Red error alerts, blocking popups, or silent failures.
* **Architect Way:** A "Rejected" System Receipt (Amber) + Explanatory Assistant Message.

> **Note:** Amber is intentionally used for semantic rejection/warning states. This is an approved pattern per the Restricted Colors rule in Section 4.

### Visual Specifications ("The Amber Warning")

| Element | Light Mode | Dark Mode |
|---------|------------|-----------|
| **Status Dot** | `bg-amber-500 animate-pulse` | `bg-amber-500 animate-pulse` |
| **Status Text** | `text-amber-600` | `text-amber-500` |
| **Text Glow** | None | `drop-shadow-[0_0_8px_rgba(245,158,11,0.5)]` |
| **Font** | `font-mono text-[10px] uppercase tracking-widest font-bold` | Same |

### Behavior Patterns

**Example 1: Same City Error**
1. **User Input:** "From Rome to Rome"
2. **System Action:** Detects `origin === destination`
3. **Receipt:** Displays `>> REJECTED: ROUTE` (amber)
4. **Assistant:** "I cannot build an itinerary where the Origin and Destination are the same..."

**Example 2: Unknown Destination**
1. **User Input:** "Take me to Atlantis"
2. **System Action:** `validate_place_exists("Atlantis")` returns `false`
3. **Receipt:** Displays `>> REJECTED: ROUTE` (amber)
4. **Assistant:** "I couldn't verify 'Atlantis' as a valid destination. Could you check the spelling?"

### Implementation Reference
- SystemReceipt: `frontend/components/chat/SystemReceipt.tsx`
- ConstraintGuard: `backend/app/planner/nodes/constraint_guard.py`

---

## 22. Animation & Progressive Disclosure

**Core Philosophy:** UI elements appear at the right moment with coordinated animations. State transitions (P0→P3) and user interactions (first heart, build click) trigger reveals.

### Timing Constants

All animation timings are centralized in `frontend/lib/animation-config.ts`:

| Animation | Duration | Purpose |
|-----------|----------|---------|
| `SPECIALIST_EXPAND` | 400ms | Height spring for card expansion |
| `SPECIALIST_PULSE` | 1000ms | Pulse once to draw attention |
| `SPECIALIST_STAGGER` | 500ms | Delay between card expansions |
| `TILES_FADE` | 300ms | Opacity 0→1 fade in |
| `SELECTIONS_SLIDE` | 250ms | Slide down from top |
| `TIMELINE_FADE` | 500ms | Fade + scroll into view |
| `MAP_SLIDE` | 400ms | Slide right→left (desktop) |
| `MAP_STAGGER_DELAY` | 200ms | Delay after timeline starts |
| `MIN_LOADING` | 600ms | Minimum loading duration |
| `SKELETON_CROSSFADE` | 300ms | Skeleton → real content |

### Spring Physics

Framer Motion spring configurations for natural motion:

```typescript
SPRING_CONFIG = {
  EXPAND: { stiffness: 300, damping: 25 },  // Card expansion - softer
  SLIDE: { stiffness: 400, damping: 30 },   // Slide animations - snappier
  BOUNCE: { stiffness: 500, damping: 35 },  // Buttons, badges
}
```

### State-Based Reveals

| Transition | Element | Animation |
|------------|---------|-----------|
| P1 → P2 | Tiles section | Fade in (300ms) |
| P1 → P2 | NextStepBar | Slide up from bottom |
| P2 → P3 | Timeline | Fade in + auto-scroll (500ms) |
| P2 → P3 | Desktop map | Slide in from right (400ms, 200ms delay) |

### Interaction-Based Reveals

| Trigger | Element | Animation |
|---------|---------|-----------|
| Build click | Tiles section | Dim to 60% opacity |
| Build complete | Timeline | Fade in, auto-scroll after 300ms |

### Motion & Transitions

`animation-config.ts` exports only `REVEAL_TIMING` (timing constants) and `SPRING_CONFIG` (spring physics). Components define motion variants inline using these values directly.

### Mobile Optimization

**Rule:** Skip complex animations on mobile for performance.

- Specialists: No auto-expand on mobile
- Map: Inline on mobile plan page (250px, scrolls with content)
- Consider `prefers-reduced-motion` for accessibility
- **Layout:** Horizontal swipe (`MobileSwipeLayout` with CSS `scroll-snap`). See `ux_unified_architecture.md` Section X.
- **Viewport detection:** Use `useIsDesktop()` hook from `hooks/useIsDesktop.ts`

### Loading States

| State | Visual | Behavior |
|-------|--------|----------|
| Building itinerary | Tiles dim (60% opacity) | `pointer-events-none` |
| Loading spinner | Emerald `Loader2` | Centered in timeline area |
| Minimum duration | 600ms | Prevents jarring flash |

### Implementation Reference

- Animation Config: `frontend/lib/animation-config.ts`
- Progressive Disclosure: `frontend/components/plan/StrategyStageRenderer.tsx`
- UX Architecture: `docs/ux_unified_architecture.md`
