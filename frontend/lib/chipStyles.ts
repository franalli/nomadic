/**
 * Shared chip styles - import in BookingSection + header pills
 *
 * CONTRAST FLOOR RULES (apply in Phase 2 migrations):
 * - Body/meta text: use `text-muted-foreground`
 * - Tertiary only: use `text-muted-foreground/70`
 * - NEVER: `opacity-*` on containers that include text
 * - NEVER: `text-muted-foreground` + `opacity-*` on same element
 */

/** Base chip structure - add to all chips */
export const chipBase =
  'inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs transition-colors';

/** Normal page areas - use bg-muted/40 NOT bg-background */
export const chipInactive =
  'border-input bg-muted/40 text-muted-foreground hover:bg-muted';

/** Active/selected chip - Solid black/white for maximum contrast (Tactile Rule) */
export const chipActive =
  'bg-zinc-900 text-white border-zinc-900 shadow-md dark:bg-white dark:text-black dark:border-white';
