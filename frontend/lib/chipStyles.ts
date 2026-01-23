/**
 * Shared chip styles - import in TileFilterBar + BookingSection + header pills
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

/** Active/selected chip - Amber-900 for light mode readability */
export const chipActive =
  'bg-amber-500/15 text-amber-900 border-amber-500/40 dark:text-amber-300 dark:bg-amber-500/10';

/** For pills on hero/banner/photo backgrounds - use WHITE bg for visibility on any photo */
export const chipOnImage =
  'border-slate-400/50 bg-white/85 text-slate-700 backdrop-blur-md shadow-sm hover:bg-white/95 dark:border-white/25 dark:bg-black/40 dark:text-white/85 dark:hover:bg-black/55';

/** Active state for on-image pills (emerald accent on white bg) */
export const chipOnImageActive =
  'border-emerald-600/60 bg-white/90 text-emerald-800 backdrop-blur-md shadow-sm hover:bg-white/95 dark:border-emerald-400/50 dark:bg-black/50 dark:text-emerald-300 dark:hover:bg-black/55';

/** Missing state for on-image pills (amber dashed on white bg) */
export const chipOnImageMissing =
  'border-amber-600/60 border-dashed bg-white/85 text-amber-800 backdrop-blur-md shadow-sm hover:bg-white/95 dark:border-amber-400/50 dark:bg-black/40 dark:text-amber-300 dark:hover:bg-black/55';

/** Optional state for on-image pills (subtle on white bg) */
export const chipOnImageOptional =
  'border-slate-400/40 bg-white/75 text-slate-600 backdrop-blur-md shadow-sm hover:bg-white/90 dark:border-white/20 dark:bg-black/35 dark:text-white/70 dark:hover:bg-black/50';

/** Dropdown container styles */
export const dropdown =
  'bg-popover text-popover-foreground border-border rounded-lg shadow-lg';

/** Dropdown item - default state */
export const dropdownItem = 'text-popover-foreground hover:bg-muted';

/** Dropdown item - active/selected state */
export const dropdownItemActive =
  'bg-amber-500/10 text-amber-600 dark:text-amber-400';

/** Emerald active state (for free cancellation, etc.) */
export const chipActiveEmerald =
  'border-emerald-500/50 bg-emerald-500/10 text-emerald-700 dark:text-emerald-400';
