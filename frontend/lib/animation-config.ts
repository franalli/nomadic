/**
 * Animation configuration for Progressive Disclosure Strategy.
 * Centralized timing constants for coordinated UI reveals.
 *
 * @see docs/ux_unified_architecture.md - Progressive Disclosure
 */

// Timing constants in milliseconds
export const REVEAL_TIMING = {
  // Specialist cards
  SPECIALIST_EXPAND: 400, // Height spring for card expansion
  SPECIALIST_PULSE: 1000, // Pulse once to draw attention
  SPECIALIST_STAGGER: 500, // Delay between card expansions

  // Tiles section
  TILES_FADE: 300, // Opacity 0→1 fade in

  SELECTIONS_SLIDE: 250, // Slide down from top

  // Timeline
  TIMELINE_FADE: 500, // Fade + scroll into view

  // Map
  MAP_SLIDE: 400, // Slide right→left (desktop only)
  MAP_STAGGER_DELAY: 200, // Delay after timeline starts

  // Loading states
  MIN_LOADING: 600, // Minimum loading duration to prevent flash
  SKELETON_CROSSFADE: 300, // Skeleton → real content crossfade
} as const;

// Spring physics configurations for Framer Motion
export const SPRING_CONFIG = {
  // Card expansion - softer, more deliberate
  EXPAND: { stiffness: 300, damping: 25 },

  // Slide animations - snappier
  SLIDE: { stiffness: 400, damping: 30 },

  // Bouncy elements (buttons, badges)
  BOUNCE: { stiffness: 500, damping: 35 },
} as const;
