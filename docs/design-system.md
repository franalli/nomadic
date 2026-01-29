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
| `DS.pills.inactive` | White bg, zinc-200 border, zinc-600 text | Transparent, white/10 border, zinc-400 text | Unselected chips |
| `DS.pills.shape` | px-4 py-2 rounded-lg text-sm | Same | Base pill structure |
| `DS.pills.shapeFull` | px-4 py-2 rounded-full text-sm | Same | Rounded pill structure |

### The Tactile Rule (IMPORTANT)

**Problem:** Inactive elements (unselected pills, stepper buttons) can look "ghostly" or invisible against the white background, making them feel unclickable.

**Solution:** The "Tactile Rule" — inactive elements must have crisp, visible borders that "snap" to black on hover, like physical mechanical buttons.

| State | Light Mode | Dark Mode |
|-------|------------|-----------|
| **Inactive Default** | `bg-white border-2 border-zinc-200 text-zinc-600` | `bg-transparent border-2 border-white/15 text-zinc-400` |
| **Inactive Hover** | `hover:border-zinc-900 hover:bg-zinc-50 hover:text-zinc-900` | `hover:border-white/40 hover:text-white` |
| **Active/Selected** | `bg-zinc-900 text-white border-2 border-zinc-900 shadow-md` | `bg-white text-black border-2 border-white` |

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
    ? 'bg-zinc-900 text-white border-2 border-zinc-900 shadow-md dark:bg-white dark:text-black dark:border-white'
    // Tactile: Crisp border, snap-to-black hover
    : 'bg-white dark:bg-transparent border-2 border-zinc-200 dark:border-white/15 text-zinc-600 dark:text-zinc-400 hover:border-zinc-900 hover:bg-zinc-50 hover:text-zinc-900 dark:hover:border-white/40 dark:hover:text-white'
)}>
  {label}
</button>
```

### Stepper Buttons (Beefier Design)

Stepper buttons (`+`/`-`) follow the Tactile Rule with additional emphasis:

| State | Light Mode | Dark Mode |
|-------|------------|-----------|
| **Enabled Default** | `bg-white border-2 border-zinc-300 text-zinc-700` | `bg-transparent border-2 border-zinc-600 text-zinc-400` |
| **Enabled Hover** | `hover:border-zinc-900 hover:bg-zinc-900 hover:text-white` | `hover:border-white hover:bg-white hover:text-black` |
| **Disabled** | `bg-zinc-50 border-2 border-zinc-200 text-zinc-300` | `bg-transparent border-2 border-zinc-800 text-zinc-700` |

**Code Example:**

```tsx
// Tactile Stepper Button
const buttonEnabled = cn(
  'w-9 h-9 rounded-full flex items-center justify-center',
  'bg-white dark:bg-transparent',
  'border-2 border-zinc-300 dark:border-zinc-600',
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
| `DS.infoBox.container` | `bg-zinc-50 border border-zinc-200 p-5` | `bg-white/[0.02] border border-white/5` | Clean, cool surface |
| `DS.infoBox.icon` | `text-zinc-400` | `text-zinc-500` | Subtle icon, not alarming |
| `DS.infoBox.text` | `text-zinc-600` | `text-zinc-400` | Body text |

**Code Example:**

```tsx
<div className={cn(
  'p-5 rounded-xl flex gap-4 items-start',
  'bg-zinc-50 dark:bg-white/[0.02]',
  'border border-zinc-200 dark:border-white/5'
)}>
  <AlertCircle className="h-5 w-5 text-zinc-400 dark:text-zinc-500" />
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

### BANNED Colors

These colors should NOT be used:

| Color | Hex | Reason |
|-------|-----|--------|
| amber-500 | `#F59E0B` | "Construction zone" look |
| orange-400 | `#FB923C` | Warning sign aesthetic |
| teal-500 | `#14B8A6` | Replaced by emerald |
| Any amber/orange | - | Clashes with premium aesthetic |

---

## 5. Migration Checklist

When applying this system to existing components:

### Eliminate Orange/Amber
- [ ] Remove all `bg-amber-X`, `border-amber-X`, `text-amber-X`
- [ ] Remove all `bg-orange-X`, `border-orange-X`, `text-orange-X`
- [ ] Replace with `DS.actions.primary` (black/emerald)

### Fix Inputs
- [ ] Remove colored focus rings (`focus:ring-amber-500`)
- [ ] Use `DS.materials.input` for background-depth styling
- [ ] Ensure dark mode uses `bg-black/40` (void look)

### Standardize Text
- [ ] Section headers → `DS.text.label` (uppercase, tracking)
- [ ] Modal titles → `DS.text.h1`
- [ ] Body text → `DS.text.body`

### Check Shadows
- [ ] All modals use `DS.materials.glass`
- [ ] Verify `backdrop-blur-xl` is present
- [ ] Light: `shadow-zinc-200/50`, Dark: `shadow-black/80`

### Verify Chips/Pills
- [ ] Selected state uses `DS.pills.active`
- [ ] Unselected uses `DS.pills.inactive`
- [ ] No teal/amber colored selections

### Remove Warning Boxes
- [ ] Replace `bg-amber-500/10 border border-amber-500/30` with `DS.infoBox.container`
- [ ] Use `DS.actions.smallAction` for action buttons inside

---

## 6. Component Mapping

| Component | Key DS Tokens |
|-----------|---------------|
| BaseSheet | `DS.materials.glass`, `DS.text.h1`, `DS.actions.iconBtn` |
| DestinationSheet | `DS.materials.input`, `DS.pills.*`, `DS.text.label` |
| OriginSheet | Same as Destination |
| TravelersSheet | `DS.pills.*`, `DS.stepper.*` |
| BudgetSheet | `DS.materials.inputLarge`, `DS.pills.*` |
| FlightsSheet | `DS.infoBox.*`, `DS.actions.toggle`, `DS.pills.*` |
| StaysSheet | Same as Flights |
| ActivitiesSheet | Same as Flights |
| ChatPanel | `DS.materials.input`, `DS.pills.*` (suggestions) |
| UnifiedChipRow | `DS.pills.*` |
| DatesSheet | `DS.materials.glass`, `DS.pills.*`, `DS.actions.primary` |
| Calendar | Custom (see Calendar section) |

---

## 7. Calendar Component ("White Paper, Black Ink")

The calendar uses a special "Braun/Leica" industrial design approach:

### Design Philosophy

- **Light Mode:** "White Paper, Black Ink" — The calendar is a crisp white architectural sheet. Selected dates are heavy black "ink".
- **Dark Mode:** "Bioluminescent" — Deep glass with emerald glow selections.

### Visual Elements

| Element | Light Mode | Dark Mode |
|---------|------------|-----------|
| **Container** | `bg-white/95 backdrop-blur-xl shadow-[0_20px_50px_rgba(0,0,0,0.1)]` | `bg-zinc-950/95 shadow-2xl shadow-black/80` |
| **Day Text** | `text-zinc-600` | `text-zinc-400` |
| **Day Hover** | `bg-zinc-100 text-zinc-900` | `bg-white/10 text-white` |
| **Selected (Start/End)** | `bg-zinc-900 text-white shadow-lg` | `bg-emerald-500 text-white shadow-glow` |
| **Range Middle** | `bg-zinc-100 text-zinc-900` | `bg-emerald-900/30 text-emerald-200` |
| **Today** | `bg-zinc-100 border-b-2 border-zinc-900` | `bg-zinc-800 border-white/20` |
| **Quick Select Pills** | Same as `DS.pills.active/inactive` | Same |
| **Apply Button** | `bg-zinc-900 text-white` | `bg-emerald-600 + glow` |

### Code Reference

The calendar component is at `frontend/components/ui/calendar.tsx`.
The date picker modal is at `frontend/components/planner/sheets/DatesSheet.tsx`.

```tsx
// Quick Select Pills in DatesSheet
<button
  className={cn(
    'px-3 py-1.5 rounded-lg text-[10px] font-bold uppercase tracking-wide',
    isActive
      ? 'bg-zinc-900 text-white dark:bg-white dark:text-black shadow-md'
      : 'border border-zinc-200 dark:border-white/10 text-zinc-600 dark:text-zinc-400'
  )}
>
  {preset.label}
</button>

// Calendar Day Selection (handled by calendar.tsx classNames)
range_start: 'bg-zinc-900 text-white dark:bg-emerald-500 shadow-lg'
range_end: 'bg-zinc-900 text-white dark:bg-emerald-500 shadow-lg'
range_middle: 'bg-zinc-100 text-zinc-900 dark:bg-emerald-900/30 dark:text-emerald-200'
```

### Why This Matters

The calendar was previously styled as a "dark-only" component. This created visual discord when placed in a light mode interface. The "White Paper, Black Ink" approach:

1. **Maintains brand identity** — Black selections feel premium and technical
2. **Respects physical logic** — Surfaces are white (paper), actions are black (ink)
3. **Works in both modes** — Dark mode retains the emerald glow aesthetic

---

## 8. Dark Mode Rules (IMPORTANT)

### The Glass Fill Rule

**Problem:** In Dark Mode, thin grey outlines (`border-white/10`) tend to disappear on OLED screens or look like glitches. Inactive elements look "ghostly" and fragile.

**Solution:** Use **Glass Fills** (`bg-white/5`) instead of just empty borders. This adds "materiality" to buttons, making them feel like physical objects sitting on the dark surface.

| State | Old (Wrong) | New (Correct) |
|-------|-------------|---------------|
| **Inactive Pill** | `dark:bg-transparent dark:border-white/10` | `dark:bg-white/5 dark:border-white/5` |
| **Inactive Hover** | `dark:hover:border-white/30` | `dark:hover:bg-white/10 dark:hover:text-white` |

**Code Example:**

```tsx
// Glass Fill Pill (Dark Mode)
<button className={cn(
  'px-4 py-2.5 rounded-lg text-sm font-medium',
  'transition-all duration-150',
  isSelected
    ? 'bg-zinc-900 text-white border-2 border-zinc-900 shadow-md dark:bg-white dark:text-black dark:border-white'
    // Glass Fill: visible substance, not just outline
    : cn(
        'bg-white border-2 border-zinc-200 text-zinc-600',
        'hover:border-zinc-900 hover:bg-zinc-50 hover:text-zinc-900',
        // Dark: Glass Fill
        'dark:bg-white/5 dark:border-white/5 dark:text-zinc-400',
        'dark:hover:bg-white/10 dark:hover:text-white'
      )
)}>
  {label}
</button>
```

### The Void Input

**Problem:** Inputs in Dark Mode with thin grey borders look like standard form fields, not premium "data entry zones."

**Solution:** Make inputs a **Void** — darker than the card (`bg-black/50`), no border until focused. Focus adds an emerald glow.

| State | Styling |
|-------|---------|
| **Default** | `dark:bg-black/50 dark:border-transparent` |
| **Focus** | `dark:focus:border-emerald-500/50 dark:focus:bg-black/60` |
| **Focus Glow** | `dark:focus:shadow-[0_0_20px_-5px_rgba(16,185,129,0.15)]` |

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

The budget input should feel like a **luxury price tag** — huge, bold, with an emerald caret in Dark Mode:

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

## 10. Stepper Buttons (Glass Treatment)

Stepper buttons in Dark Mode also need the Glass Fill treatment:

| State | Light Mode | Dark Mode |
|-------|------------|-----------|
| **Enabled** | `bg-white border-2 border-zinc-300 text-zinc-700` | `bg-white/5 border-white/10 text-zinc-400` |
| **Hover** | `hover:border-zinc-900 hover:bg-zinc-900 hover:text-white` | `hover:bg-white hover:border-white hover:text-black` |
| **Disabled** | `bg-zinc-50 border-2 border-zinc-200 text-zinc-300` | `bg-white/[0.02] border-white/5 text-zinc-700` |

**Code Example:**

```tsx
const buttonEnabled = cn(
  'w-10 h-10 rounded-full flex items-center justify-center',
  // Light: White with strong border
  'bg-white border-2 border-zinc-300 text-zinc-700',
  // Dark: Glass Fill - visible substance
  'dark:bg-white/5 dark:border-white/10 dark:text-zinc-400',
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
| **Pills/Chips** | `h-10` or `h-11` | Larger than desktop (`h-9`) |
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

### Mobile-Specific Header Behavior

**Problem:** The "Where to next?" header is large and takes up valuable space on scroll.

**Solution:** Header should collapse/vanish when user scrolls or engages with content.

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
| **Enabled** | `bg-white border-2 border-zinc-400` | `bg-white/5 border-white/15` |
| **Hover** | `bg-zinc-900 border-zinc-900 text-white` | `bg-white border-white text-black` |
| **Disabled** | `bg-zinc-100 border-2 border-zinc-300 text-zinc-400` | `bg-white/[0.02] border-white/5 text-zinc-700` |

**Key Principle:** Borders should be visible without squinting. Use `border-zinc-400` (not `border-zinc-300`) for light mode inactive states.

**Code Example:**

```tsx
const buttonEnabled = cn(
  'w-12 h-12 rounded-full flex items-center justify-center',
  // Light: White with STRONG visible border
  'bg-white border-2 border-zinc-400 text-zinc-700',
  // Dark: Glass Fill
  'dark:bg-white/5 dark:border-white/15 dark:text-zinc-400',
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

## 14. Primary Navigation (Setup / Plan / Book)

The main navigation bar follows the **"Beacon Rule"** to anchor the user's location in the app flow. The active tab must be maximally visible—a glowing white beacon in dark mode.

### Design Philosophy

**Problem:** A dark grey active tab (`bg-zinc-800`) in Dark Mode looks "muddy" and low-confidence. It blends into the surrounding dark UI instead of anchoring the user.

**Solution:** The active tab should be **Solid White** (The Beacon), matching the user chat bubbles and active toggle pills. This creates visual consistency across all "user intent" elements.

### Visual Specifications

| Element | Light Mode | Dark Mode |
|---------|------------|-----------|
| **Container (Track)** | `bg-zinc-100 border-zinc-200 rounded-full` | `bg-black/40 border-white/10 backdrop-blur-xl` |
| **Active Tab** | `bg-white text-zinc-950 ring-1 ring-black/5 shadow-md` | `bg-white text-zinc-950 shadow-[0_0_15px_-3px_rgba(255,255,255,0.4)]` |
| **Inactive Tab** | `text-zinc-500 hover:text-zinc-800 hover:bg-zinc-100/80` | `text-white/60 hover:text-white hover:bg-white/10` |
| **Locked Tab** | `text-zinc-400 opacity-40 cursor-not-allowed` | `text-white/40 opacity-40` |

### Code Example

```tsx
// GlassCommandBar Active State
isActive && [
  // Light: Pure white cutout from grey track
  'bg-white shadow-md ring-1 ring-black/5',
  'text-zinc-950 font-bold',
  // Dark: THE BEACON - Solid white with glow
  'dark:bg-white dark:text-zinc-950 dark:ring-0',
  'dark:shadow-[0_0_15px_-3px_rgba(255,255,255,0.4)]',
]
```

### Why This Works

1. **Anchoring:** The bright white beacon instantly shows the user where they are in the Setup → Plan → Book flow.
2. **Consistency:** Matches the "Solid White = User Intent" pattern used in chat bubbles and active pills.
3. **Contrast:** Maximum contrast against the dark glass container makes the selection unambiguous.

### Implementation Reference

The primary navigation is implemented in `frontend/components/plan/GlassCommandBar.tsx`.
