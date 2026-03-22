/**
 * Document mutation API functions.
 *
 * Split from api.ts — these functions handle document-level mutations
 * (tile refresh, fill-day, arrangement validation/apply, block removal).
 */

import { debugLog } from '@/lib/debug';
import { useDocumentStore } from '@/state/documentStore';
import type { DayCard } from '@/types/plan-envelope';
import type { Tile } from '@/types/tile';

import { apiFetch, fetchWithRetry } from './api';

// ─────────────────────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Tile data returned from API.
 * Matches the Tile type from types/tile.ts.
 */
interface ApiTile {
  id: string;
  type: string;
  title: string;
  subtitle?: string;
  image_url?: string;
  price_estimate?: number;
  currency: string;
  deeplink_url: string;
  rating?: number;
  location_label?: string;
  meta?: Record<string, unknown>;
}

/**
 * Response from the tile refresh endpoint.
 */
interface TileRefreshResponse {
  tiles: ApiTile[];
  refreshed_at: string;
  verticals_refreshed: string[];
}

// ─────────────────────────────────────────────────────────────────────────────
// Functions
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Refresh tiles for a branch with current settings.
 *
 * Use this when user preferences (hotel_settings, flight_settings,
 * activity_settings) change to get updated tiles reflecting the new filters.
 *
 * @param branchId - The branch to refresh tiles for
 * @param verticals - Optional list of verticals to refresh. If not provided, refreshes all.
 * @returns The refreshed tiles and metadata
 */
export async function refreshTiles(
  branchId: string,
  verticals?: ('hotel' | 'flight' | 'activity')[]
): Promise<TileRefreshResponse> {
  const res = await fetchWithRetry(
    '/api/tiles/refresh',
    {
      method: 'POST',
      body: JSON.stringify({
        branch_id: branchId,
        verticals: verticals,
      }),
    },
    {
      maxRetries: 2,
      baseDelay: 500,
    }
  );

  if (!res.ok) {
    const errorText = await res.text().catch(() => 'Unknown error');
    throw new Error(`Failed to refresh tiles: ${res.status} - ${errorText}`);
  }

  return res.json();
}

/**
 * Fill a free day with activity tiles (no LangGraph execution).
 *
 * Calls experience_generator directly to produce Tier 2 tiles,
 * replaces the free_day block with activity blocks, and persists.
 */
export async function fillDay(
  dayNumber: number,
  categories?: string[],
  pinnedTileIds?: string[],
): Promise<{
  day_number: number;
  tiles_added: number;
  day_card?: DayCard;
  tiles?: Record<string, Tile>;
  version: number;
  rejected?: boolean;
  rejection_reason?: string;
  rejection_code?: string;
  rejection_suggestion?: string;
}> {
  debugLog(`[fillDay] sending day=${dayNumber} categories=${JSON.stringify(categories)} pinnedTiles=${pinnedTileIds?.length ?? 0}`);
  const res = await apiFetch('/api/document/fill-day', {
    method: 'POST',
    body: JSON.stringify({
      day_number: dayNumber,
      categories,
      pinned_tile_ids: pinnedTileIds,
    }),
  });
  if (!res.ok) {
    debugLog(`[fillDay] failed: status=${res.status} day=${dayNumber}`);
    const errorText = await res.text().catch(() => '');
    let detail = errorText;
    try {
      const parsed = JSON.parse(errorText) as { detail?: string };
      if (parsed?.detail) detail = parsed.detail;
    } catch {
      // keep raw text detail
    }
    throw new Error(
      detail ? `fill-day failed: ${res.status} - ${detail}` : `fill-day failed: ${res.status}`
    );
  }
  const result = await res.json();
  // Sync version to prevent 409 cascade on subsequent calls
  if (result.version) {
    useDocumentStore.setState({ version: result.version });
  }
  return result;
}

/**
 * Validate a proposed block arrangement before applying it.
 * Returns whether the moves are valid and any violations.
 */
export async function validateArrangement(
  moves: Array<{ block_id: string; from_day: number; to_day: number; to_position?: number }>
): Promise<{
  valid: boolean;
  violations: Array<{
    block_id: string;
    violation_code: string;
    severity: 'blocking' | 'warning';
    message: string;
    target_day: number;
  }>;
}> {
  const res = await apiFetch('/api/document/validate-arrangement', {
    method: 'POST',
    body: JSON.stringify({ moves }),
  });
  if (!res.ok) throw new Error(`validate-arrangement failed: ${res.status}`);
  return res.json();
}

/**
 * Apply a validated block arrangement, persisting the new day order.
 * Throws 'VERSION_CONFLICT' if the document was modified concurrently.
 */
export async function applyArrangement(
  moves: Array<{ block_id: string; from_day: number; to_day: number; to_position?: number }>,
  expectedVersion: number
): Promise<{
  valid: boolean;
  violations: Array<{ block_id: string; violation_code: string; severity: string; message: string; target_day: number }>;
  day_cards?: unknown[];
  version?: number;
}> {
  const res = await apiFetch('/api/document/apply-arrangement', {
    method: 'POST',
    body: JSON.stringify({ moves, expected_version: expectedVersion }),
  });
  if (res.status === 409) {
    throw new Error('VERSION_CONFLICT');
  }
  if (!res.ok) throw new Error(`apply-arrangement failed: ${res.status}`);
  return res.json();
}

/**
 * Remove a single block from the itinerary.
 * No constraint validation needed — removal can only relax constraints.
 */
export async function removeBlock(
  blockId: string,
  dayNumber: number,
  expectedVersion: number
): Promise<{
  day_number: number;
  day_card: DayCard;
  version: number;
  removed_block_id: string;
}> {
  const res = await apiFetch('/api/document/remove-block', {
    method: 'POST',
    body: JSON.stringify({
      block_id: blockId,
      day_number: dayNumber,
      expected_version: expectedVersion,
    }),
  });
  if (res.status === 409) {
    throw new Error('VERSION_CONFLICT');
  }
  if (!res.ok) throw new Error(`remove-block failed: ${res.status}`);
  return res.json();
}
