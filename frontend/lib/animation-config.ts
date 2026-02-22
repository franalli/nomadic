/**
 * Animation configuration for Progressive Disclosure Strategy.
 * Centralized timing constants for coordinated UI reveals.
 *
 * Rules:
 * 1. Opacity only — no Y-axis slides on content reveals.
 * 2. Stagger by group (hero → cards → map), 200ms between groups.
 * 3. One transition per state change (popLayout crossfade).
 *
 * @see docs/ux_unified_architecture.md - Progressive Disclosure
 */

// Material Design standard easing: fast start, long gentle tail.
// Use instead of spring physics for content reveals.
export const EASE_STANDARD = [0.4, 0, 0.2, 1] as const;

// Timing constants in milliseconds
export const REVEAL_TIMING = {
  // Specialist cards
  SPECIALIST_EXPAND: 400, // Height spring for card expansion
  SPECIALIST_PULSE: 1000, // Pulse once to draw attention
  SPECIALIST_STAGGER: 500, // Delay between card expansions

  // Tiles section
  TILES_FADE: 400, // Opacity 0→1 fade in

  SELECTIONS_SLIDE: 250, // Slide down from top (kept for non-streaming contexts)

  // Timeline — group 2 in the reveal sequence
  TIMELINE_FADE: 400,  // Opacity 0→1, easeOut
  TIMELINE_DELAY: 200, // Group stagger: day cards appear 200ms after hero

  // Map — group 3 in the reveal sequence
  MAP_FADE: 400,       // Opacity 0→1
  MAP_DELAY: 400,      // Group stagger: map appears 400ms after hero

  // Legacy aliases (kept for code that hasn't been migrated)
  MAP_SLIDE: 400,
  MAP_STAGGER_DELAY: 200,

  // Loading states
  MIN_LOADING: 600, // Minimum loading duration to prevent flash
  SKELETON_CROSSFADE: 300, // Skeleton → real content crossfade
} as const;

// Spring physics — ONLY for user-initiated interactions (drag & drop).
// Do NOT use for content reveals or streaming animations.
export const SPRING_CONFIG = {
  // Card expansion - softer, more deliberate
  EXPAND: { stiffness: 300, damping: 25 },

  // Slide animations - snappier
  SLIDE: { stiffness: 400, damping: 30 },

  // Bouncy elements (buttons, badges)
  BOUNCE: { stiffness: 500, damping: 35 },
} as const;
