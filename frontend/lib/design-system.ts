/**
 * Unified Design System for Nomadic
 *
 * Light Mode: "Crisp Technical" - Black actions, zinc grays, soft shadows
 * Dark Mode: "Bioluminescent" - Emerald glows, transparent blacks, max contrast
 *
 * Usage: import { DS } from '@/lib/design-system';
 *        className={DS.materials.glass}
 */

export const DS = {
  // ---------------------------------------------------------------------------
  // 1. MATERIALS (The Physical Surfaces)
  // ---------------------------------------------------------------------------
  materials: {
    /**
     * THE HERO CARD (Modals, Panels, Floating Islands)
     * Light: White glass with soft grey shadow.
     * Dark: Deep Zinc-950/Glass with laser-cut white borders.
     */
    glass: `
      bg-white/90 dark:bg-zinc-950/95
      backdrop-blur-xl
      border border-zinc-200 dark:border-white/10
      shadow-2xl shadow-zinc-200/50 dark:shadow-black/80
      rounded-2xl
    `,

    /**
     * SECONDARY SURFACES (Inner Cards, Info Boxes)
     * Light: Very faint grey to define area.
     * Dark: Almost transparent (white/3%), allowing texture to bleed through.
     */
    surface: `
      bg-zinc-50 dark:bg-white/[0.03]
      border border-zinc-100 dark:border-white/5
      rounded-xl
    `,

    /**
     * THE INPUT VOID (Search bars, Budget inputs)
     * Light: Hollow, clean grey field.
     * Dark: A dark "hole" (black/40). No borders until focused.
     */
    input: `
      w-full rounded-xl
      bg-zinc-50 dark:bg-black/40
      border border-zinc-200 dark:border-white/5
      focus:border-zinc-900 dark:focus:border-emerald-500/50
      text-zinc-900 dark:text-white
      placeholder:text-zinc-400 dark:placeholder:text-zinc-600
      focus:ring-0 focus:shadow-lg focus:shadow-zinc-200/50
      dark:focus:shadow-[0_0_20px_-5px_rgba(16,185,129,0.1)]
      transition-all duration-200
    `,

    /**
     * LARGE INPUT (Budget "Big Number" style)
     */
    inputLarge: `
      bg-transparent
      text-4xl font-bold text-center
      text-zinc-900 dark:text-white
      border-none focus:ring-0 w-full
      placeholder:text-zinc-300 dark:placeholder:text-zinc-700
    `,
  },

  // ---------------------------------------------------------------------------
  // 2. ACTIONS (Buttons & Triggers)
  // ---------------------------------------------------------------------------
  actions: {
    /**
     * PRIMARY BUTTON (Save, Build, Confirm)
     * Light: Solid Black (High Contrast, Technical).
     * Dark: Glowing Emerald (Bioluminescent).
     * RULE: Do not use Amber/Orange for primary actions.
     */
    primary: `
      inline-flex items-center justify-center gap-2
      px-6 py-3 rounded-xl
      font-bold text-sm
      transition-all duration-200 active:scale-[0.98]
      bg-zinc-900 text-white shadow-lg shadow-zinc-900/10 hover:bg-zinc-800
      dark:bg-emerald-600 dark:text-white dark:shadow-[0_0_20px_-5px_rgba(16,185,129,0.4)] dark:hover:bg-emerald-500
    `,

    /**
     * PRIMARY BUTTON (Disabled state)
     */
    primaryDisabled: `
      inline-flex items-center justify-center gap-2
      px-6 py-3 rounded-xl
      font-bold text-sm
      bg-zinc-100 dark:bg-zinc-800
      text-zinc-400 dark:text-zinc-600
      cursor-not-allowed
    `,

    /**
     * SECONDARY BUTTON (Cancel, Clear)
     * Light: Grey text, darkens on hover.
     * Dark: Grey text, whitens on hover.
     */
    secondary: `
      inline-flex items-center justify-center
      px-6 py-3 rounded-xl
      font-medium text-sm
      transition-colors duration-200
      text-zinc-500 hover:text-zinc-900 hover:bg-zinc-100
      dark:text-zinc-500 dark:hover:text-white dark:hover:bg-white/5
    `,

    /**
     * ICON BUTTONS (Close 'X', Back Arrows)
     */
    iconBtn: `
      p-2 rounded-full transition-colors
      text-zinc-400 hover:bg-zinc-100 hover:text-zinc-900
      dark:text-zinc-500 dark:hover:bg-white/10 dark:hover:text-white
    `,

    /**
     * TOGGLE SWITCH (Radix/Headless UI compatible)
     */
    toggle: `
      data-[state=checked]:bg-emerald-500 data-[state=checked]:border-emerald-500
      data-[state=unchecked]:bg-zinc-200 data-[state=unchecked]:border-zinc-300
      dark:data-[state=unchecked]:bg-zinc-800 dark:data-[state=unchecked]:border-zinc-700
    `,

    /**
     * SMALL ACTION BUTTON (Inside info boxes)
     */
    smallAction: `
      text-[10px] font-bold uppercase tracking-wide
      bg-zinc-800 dark:bg-zinc-700 text-white
      px-3 py-1.5 rounded-lg
      hover:bg-emerald-600 dark:hover:bg-emerald-500
      transition-colors
    `,
  },

  // ---------------------------------------------------------------------------
  // 3. PILLS & CHIPS (Selection Logic)
  // ---------------------------------------------------------------------------
  pills: {
    /**
     * SELECTED STATE
     * Light: Solid Black.
     * Dark: Solid White (Max Readability).
     */
    active: `
      bg-zinc-900 text-white border-transparent shadow-md
      dark:bg-white dark:text-black dark:border-transparent
      font-semibold
    `,

    /**
     * UNSELECTED STATE (Tactile Rule + Glass Fill Rule)
     * Light: White paper with crisp border-2 that snaps to black on hover.
     * Dark: Glass fill (bg-white/5) with visible substance, not ghost outline.
     */
    inactive: `
      bg-white border-2 border-zinc-200 text-zinc-600
      dark:bg-white/5 dark:border-2 dark:border-white/15 dark:text-zinc-400
      hover:border-zinc-900 hover:bg-zinc-50 hover:text-zinc-900
      dark:hover:bg-white/10 dark:hover:border-white/40 dark:hover:text-white
      transition-all duration-150
    `,

    /**
     * Common container shape for pills
     */
    shape: 'px-4 py-2 rounded-lg text-sm transition-all',

    /**
     * Rounded full pill shape
     */
    shapeFull: 'px-4 py-2 rounded-full text-sm transition-all',
  },

  // ---------------------------------------------------------------------------
  // 4. TYPOGRAPHY (The Schematic Look)
  // ---------------------------------------------------------------------------
  text: {
    /**
     * MODAL TITLES (e.g. "Destination")
     */
    h1: 'text-lg font-semibold text-zinc-900 dark:text-white',

    /**
     * SECTION HEADERS (e.g. "POPULAR DESTINATIONS")
     * Technical, small, uppercase, spaced out.
     */
    label: 'text-[10px] font-bold uppercase tracking-wider text-zinc-400 dark:text-zinc-500',

    /**
     * BODY TEXT
     */
    body: 'text-sm font-medium text-zinc-600 dark:text-zinc-400',

    /**
     * MUTED/HINT TEXT
     */
    muted: 'text-xs text-zinc-500 dark:text-zinc-500',

    /**
     * ACCENT COLOR (Icons, Highlights)
     */
    accent: 'text-zinc-900 dark:text-emerald-400',
  },

  // ---------------------------------------------------------------------------
  // 5. STEPPER (Traveler count +/- buttons)
  // ---------------------------------------------------------------------------
  stepper: {
    /**
     * STEPPER BUTTON (Tactile Rule for mobile touch targets)
     * w-10 h-10 for comfortable 40px touch target
     * Glass fill in dark mode, snap-to-black/white on hover
     */
    button: `
      w-10 h-10 rounded-full
      flex items-center justify-center
      bg-white dark:bg-white/5
      border-2 border-zinc-300 dark:border-white/15
      text-zinc-700 dark:text-zinc-400
      hover:border-zinc-900 hover:bg-zinc-900 hover:text-white
      dark:hover:bg-white dark:hover:border-white dark:hover:text-black
      transition-all duration-150
      active:scale-95
    `,
    buttonDisabled: `
      w-10 h-10 rounded-full
      flex items-center justify-center
      bg-zinc-50 dark:bg-white/[0.02]
      border-2 border-zinc-200 dark:border-white/5
      text-zinc-300 dark:text-zinc-700
      cursor-not-allowed
    `,
    value: 'w-10 text-center text-lg font-bold text-zinc-900 dark:text-white',
  },

  // ---------------------------------------------------------------------------
  // 6. INFO BOX (Replaces amber warning boxes)
  // ---------------------------------------------------------------------------
  infoBox: {
    container: `
      p-4 rounded-xl flex gap-4 items-start
      bg-zinc-50 dark:bg-white/[0.02]
      border border-zinc-100 dark:border-white/5
    `,
    icon: 'w-5 h-5 text-zinc-500 dark:text-zinc-400 shrink-0',
    text: 'text-sm text-zinc-600 dark:text-zinc-400',
  },
} as const;
