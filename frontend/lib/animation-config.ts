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

  // SelectionsBar
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

// Framer Motion variant presets
export const MOTION_VARIANTS = {
  // Fade in from below (tiles, timeline)
  fadeInUp: {
    initial: { opacity: 0, y: 20 },
    animate: { opacity: 1, y: 0 },
    exit: { opacity: 0, y: 20 },
  },

  // Slide down from top (SelectionsBar)
  slideDown: {
    initial: { y: -50, opacity: 0 },
    animate: { y: 0, opacity: 1 },
    exit: { y: -50, opacity: 0 },
  },

  // Slide up from bottom (NextStepBar)
  slideUp: {
    initial: { y: 100, opacity: 0 },
    animate: { y: 0, opacity: 1 },
    exit: { y: 100, opacity: 0 },
  },

  // Slide in from right (Map)
  slideInRight: {
    initial: { x: 100, opacity: 0 },
    animate: { x: 0, opacity: 1 },
    exit: { x: 100, opacity: 0 },
  },

  // Simple fade (tiles section)
  fade: {
    initial: { opacity: 0 },
    animate: { opacity: 1 },
    exit: { opacity: 0 },
  },
} as const;

// Transition presets combining timing + spring
export const TRANSITIONS = {
  // For content reveals (tiles, timeline)
  reveal: {
    duration: REVEAL_TIMING.TILES_FADE / 1000,
    ease: 'easeOut',
  },

  // For interactive slides (SelectionsBar, NextStepBar)
  spring: {
    type: 'spring' as const,
    ...SPRING_CONFIG.SLIDE,
  },

  // For staggered reveals (map after timeline)
  staggered: {
    type: 'spring' as const,
    ...SPRING_CONFIG.SLIDE,
    delay: REVEAL_TIMING.MAP_STAGGER_DELAY / 1000,
  },
} as const;
