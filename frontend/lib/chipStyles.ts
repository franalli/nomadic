/**
 * Shared chip styles - import in BookingSection + header pills
 *
 * Uses DS zinc tokens explicitly (Section 23 — Shadcn Token Prohibition).
 * No `bg-muted`, `text-muted-foreground`, or `border-input` allowed here.
 */

/** Base chip structure - add to all chips */
export const chipBase =
  'inline-flex items-center gap-1.5 rounded-full border-2 px-3 py-1.5 text-xs transition-colors';

/** Normal page areas — Tactile Rule: crisp border-2, glass fill in dark, snap-to-black hover */
export const chipInactive =
  'border-zinc-200 bg-white text-zinc-600 hover:border-zinc-900 hover:bg-zinc-50 hover:text-zinc-900 dark:border-white/15 dark:bg-white/5 dark:text-zinc-400 dark:hover:bg-white/10 dark:hover:border-white/40 dark:hover:text-white';

/** Active/selected chip - Solid black/white for maximum contrast (Tactile Rule) */
export const chipActive =
  'bg-zinc-900 text-white border-zinc-900 shadow-md dark:bg-white dark:text-black dark:border-white';
