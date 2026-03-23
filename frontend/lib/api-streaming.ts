/**
 * SSE/streaming API functions and types.
 *
 * Split from api.ts — these handle Server-Sent Events streaming,
 * browse activities, specialist enrichment, shared trips, and deeplink tracking.
 */

import { API_BASE } from '@/lib/config';
import { fetchSharedTripClient } from '@/lib/sharedTripApi';
import type { DateFlexSuggestion, DocumentTripInputs, PlanDocumentData } from '@/types/document';
import type {
  DayCard,
  ItineraryAssumptions,
  ItineraryOverview,
  PlanViewState,
  StrategySection,
} from '@/types/plan-envelope';
import type { Tile } from '@/types/tile';

import { apiFetch, getCsrfToken } from './api';

// ─────────────────────────────────────────────────────────────────────────────
// Browse Activities helpers (module-private)
// ─────────────────────────────────────────────────────────────────────────────

export interface BrowseActivitiesParams {
  destination: string;
  dayNumber?: number;
  date?: string | null;
  hotelLocation?: { lat: number; lng: number } | null;
  categories?: string[];
}

interface BrowseActivitiesResponse {
  tiles: import('./api').BrowseTile[];
  total: number;
}

const BROWSE_DEFAULT_CATEGORIES = ['cultural'];
const BROWSE_CACHE_TTL_MS = 5 * 60 * 1000;
const BROWSE_CACHE_MAX_ENTRIES = 64;
const browseActivitiesCache = new Map<
  string,
  { expiresAt: number; payload: BrowseActivitiesResponse }
>();
const browseActivitiesInflight = new Map<string, Promise<BrowseActivitiesResponse>>();

function normalizeCategories(categories?: string[]): string[] {
  const source = categories ?? BROWSE_DEFAULT_CATEGORIES;
  return Array.from(new Set(source.map((c) => c.trim().toLowerCase()).filter(Boolean))).sort();
}

function browseActivitiesKey(params: BrowseActivitiesParams): string {
  return JSON.stringify({
    destination: params.destination.trim().toLowerCase(),
    dayNumber: params.dayNumber ?? null,
    date: params.date ?? null,
    categories: normalizeCategories(params.categories),
    hotelLocation: params.hotelLocation
      ? `${params.hotelLocation.lat},${params.hotelLocation.lng}`
      : null,
  });
}

function pruneBrowseActivitiesCache(now: number): void {
  for (const [key, entry] of browseActivitiesCache.entries()) {
    if (entry.expiresAt <= now) {
      browseActivitiesCache.delete(key);
    }
  }

  while (browseActivitiesCache.size > BROWSE_CACHE_MAX_ENTRIES) {
    const oldestKey = browseActivitiesCache.keys().next().value;
    if (!oldestKey) break;
    browseActivitiesCache.delete(oldestKey);
  }
}

// ─────────────────────────────────────────────────────────────────────────────

function extractApiErrorDetail(payload: unknown): string | null {
  if (typeof payload === 'string') {
    const trimmed = payload.trim();
    return trimmed.length > 0 ? trimmed : null;
  }

  if (!payload || typeof payload !== 'object') {
    return null;
  }

  const detail = (payload as { detail?: unknown }).detail;
  if (typeof detail === 'string') {
    return detail.trim() || null;
  }

  if (!Array.isArray(detail)) {
    return null;
  }

  const messages = detail
    .map((item) => {
      if (typeof item === 'string') return item.trim();
      if (!item || typeof item !== 'object') return null;
      const msg = 'msg' in item ? item.msg : null;
      return typeof msg === 'string' ? msg.trim() : null;
    })
    .filter((msg): msg is string => Boolean(msg));

  return messages.length > 0 ? messages.join('; ') : null;
}

// ─────────────────────────────────────────────────────────────────────────────
// SSE Types
// ─────────────────────────────────────────────────────────────────────────────

interface SSETokenEvent {
  type: 'token';
  data: string;
}

interface SSECompleteEvent {
  type: 'complete';
  data: {
    document: unknown;
    session_state: Record<string, unknown>;
    version: number;
    updated_by: string;
    updated_at: string;
    changes_made: boolean;
    request_id: string;
    observability?: unknown;
    response_degraded?: boolean;
    response_error_type?: string;
  };
}

interface SSEErrorEvent {
  type: 'error';
  message: string;
}

export interface SSENodeStatusEvent {
  type: 'node_status';
  data: {
    /**
     * Node or tool identifier.
     *
     * v1 graph nodes: router, specialist, local_expert, logistics, architect, guard, synthesizer
     * v2 tool names:  extract_trip_fields, get_specialist_advice, get_local_intel,
     *                 search_tiles, validate_plan, build_itinerary
     *
     * Both pipelines run in parallel (feature-flagged). Frontend must handle either set.
     */
    node: string;
    status: 'started' | 'completed';
    label: string; // Human-readable label for UI (e.g., "Finding flights")
    icon_key: string; // Icon identifier for frontend (e.g., "plane", "search", "calendar")
    estimated_duration_ms: number;
    // Strategy-specific fields (optional, only present for strategy_node / get_specialist_advice)
    stage?: number;
    tier?: 'outline' | 'section' | 'full';
    topic?: string;
    max_tokens?: number;
  };
}

export interface SSEPartialContext {
  plan_view_state?: PlanViewState;
  itinerary_overview?: ItineraryOverview | null;
  itinerary_assumptions?: ItineraryAssumptions | null;
  constraint_violations?: PlanDocumentData['constraint_violations'];
  warnings?: string[];
}

export interface SpecialistPreviewSection {
  id?: string | null;
  specialist_type?: string | null;
  title?: string | null;
  one_liner?: string | null;
  hero_image?: string | null;
  feasibility_status?: StrategySection['feasibility_status'];
  feasibility_reason?: string | null;
  alternative_suggestion?: string | null;
  content_count?: number;
  highlights?: string[];
}

export interface SpecialistPreviewActivity {
  title: string;
  day?: number | null;
  specialist_type: string;
  duration_hours?: number | null;
  description?: string | null;
  image_url?: string | null;
  coordinates?: [number, number] | null;
}

export interface SpecialistPreviewPayload {
  destination?: string | null;
  topics?: string[];
  activities?: SpecialistPreviewActivity[];
  sections?: SpecialistPreviewSection[];
  strategy_sections?: StrategySection[];
}

export interface DayCardsPartialPayload {
  day_cards: DayCard[];
  tiles?: Record<string, Tile>;
  strategy_sections?: StrategySection[];
  plan_view_state?: PlanViewState;
  itinerary_overview?: ItineraryOverview | null;
  itinerary_assumptions?: ItineraryAssumptions | null;
  constraint_violations?: PlanDocumentData['constraint_violations'];
  warnings?: string[];
}

export interface TileEnrichmentPayload extends DayCardsPartialPayload {
  day_cards_changed?: boolean;
  tiles_changed?: boolean;
  context?: SSEPartialContext;
}

export type SSEPartialData =
  | {
      kind: 'strategy_sections';
      payload: StrategySection[];
    }
  | {
      kind: 'tiles';
      payload: Record<string, Tile>;
      tiles_replaced?: boolean;
    }
  | {
      kind: 'trip_inputs';
      payload: Partial<DocumentTripInputs>;
    }
  | {
      kind: 'day_cards';
      payload: DayCardsPartialPayload;
    }
  | {
      kind: 'specialist_preview';
      payload: SpecialistPreviewPayload;
    }
  | {
      kind: 'tile_enrichment';
      payload: TileEnrichmentPayload;
      tiles_replaced?: boolean;
    }
  | {
      kind: 'date_flex_suggestion';
      payload: DateFlexSuggestion;
    };

export interface SSEPartialEvent {
  type: 'partial';
  data: SSEPartialData;
}

export interface SSEFeasibilityWarningEvent {
  type: 'feasibility_warning';
  data: {
    topic: string;
    status: 'infeasible' | 'caveat';
    reason: string | null;
    alternative: string | null;
  };
}

export interface SSEHeartbeatEvent {
  type: 'heartbeat';
}

type SSEEvent = SSETokenEvent | SSECompleteEvent | SSEErrorEvent | SSENodeStatusEvent | SSEPartialEvent | SSEFeasibilityWarningEvent | SSEHeartbeatEvent;

/**
 * Callbacks for streaming graph plan responses.
 */
interface StreamGraphPlanCallbacks {
  /** Called for each token received from the stream */
  onToken: (token: string) => void;
  /** Called when the stream completes with the full response */
  onComplete: (response: SSECompleteEvent['data']) => void;
  /** Called when an error occurs */
  onError: (error: Error) => void;
  /** Called when node status changes (e.g., strategy node starts) */
  onNodeStatus?: (status: SSENodeStatusEvent['data']) => void;
  /** Called when partial data is available before completion (progressive rendering) */
  onPartial?: (data: SSEPartialEvent['data']) => void;
  /** Called when a feasibility warning is received (e.g., activity impossible at destination) */
  onFeasibilityWarning?: (data: SSEFeasibilityWarningEvent['data']) => void;
  /** Called when a heartbeat event is received (connection keepalive) */
  onHeartbeat?: () => void;
}

// ─────────────────────────────────────────────────────────────────────────────
// Functions
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Stream a graph plan response using Server-Sent Events.
 *
 * This function connects to the SSE endpoint and streams tokens as they arrive,
 * providing real-time feedback to the user.
 *
 * @param body - The request body (same as GraphPlanRequest)
 * @param callbacks - Callbacks for handling stream events
 * @returns A function to abort the stream
 */
export function streamGraphPlan(
  body: {
    message: string;
    session_state?: Record<string, unknown>;
    trip_inputs?: Record<string, unknown>;
    reset?: boolean;
    thread_id?: string;
    ui_phase?: 'bootstrap' | 'expanded';
    suggestion_clicked?: string;
  },
  callbacks: StreamGraphPlanCallbacks
): () => void {
  const controller = new AbortController();
  const url = `${API_BASE}/api/graph_plan/stream`;

  // Build headers with CSRF token
  const headers: HeadersInit = {
    'Content-Type': 'application/json',
  };
  const csrfToken = getCsrfToken();
  if (csrfToken) {
    headers['X-CSRF-Token'] = csrfToken;
  }

  // Start the fetch request
  fetch(url, {
    method: 'POST',
    credentials: 'include',
    headers,
    body: JSON.stringify(body),
    signal: controller.signal,
  })
    .then(async (response) => {
      if (!response.ok) {
        let detail: string | null = null;
        const raw = await response.text();
        if (raw) {
          try {
            detail = extractApiErrorDetail(JSON.parse(raw));
          } catch {
            detail = raw.trim() || null;
          }
        }
        throw new Error(
          detail
            ? `Stream request failed: ${response.status}: ${detail}`
            : `Stream request failed: ${response.status}`
        );
      }

      if (!response.body) {
        throw new Error('No response body');
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      try {
        while (true) {
          const { done, value } = await reader.read();

          if (done) {
            break;
          }

          // Decode the chunk and add to buffer
          buffer += decoder.decode(value, { stream: true });

          // Process complete SSE events from the buffer
          const lines = buffer.split('\n');
          buffer = '';

          let currentEvent = '';
          let currentData = '';

          for (const line of lines) {
            if (line.startsWith('event: ')) {
              currentEvent = line.slice(7).trim();
            } else if (line.startsWith('data: ')) {
              currentData = line.slice(6);
            } else if (line === '' && currentData) {
              // Empty line signals end of event
              try {
                const parsed = JSON.parse(currentData) as SSEEvent;

                // Wrap callbacks in try-catch to prevent unhandled errors from leaving reader open
                try {
                  if (parsed.type === 'token') {
                    callbacks.onToken(parsed.data);
                  } else if (parsed.type === 'node_status') {
                    callbacks.onNodeStatus?.(parsed.data);
                  } else if (parsed.type === 'partial') {
                    callbacks.onPartial?.(parsed.data);
                  } else if (parsed.type === 'feasibility_warning') {
                    callbacks.onFeasibilityWarning?.(parsed.data);
                  } else if (parsed.type === 'heartbeat') {
                    callbacks.onHeartbeat?.();
                  } else if (parsed.type === 'complete') {
                    callbacks.onComplete(parsed.data);
                  } else if (parsed.type === 'error') {
                    callbacks.onError(new Error(parsed.message));
                  }
                } catch (callbackError) {
                  console.error('[SSE] Callback error:', callbackError);
                  // Don't rethrow - continue processing stream
                }
              } catch {
                // Ignore parse errors for incomplete data
              }
              currentEvent = '';
              currentData = '';
            } else if (line !== '') {
              // Incomplete line, add back to buffer
              buffer += line + '\n';
            }
          }

          // Keep any remaining incomplete data in the buffer
          if (currentData) {
            buffer = `event: ${currentEvent}\ndata: ${currentData}`;
          }
        }
      } finally {
        // Ensure reader is released even if callbacks throw
        reader.releaseLock();
      }
    })
    .catch((error) => {
      if (error.name !== 'AbortError') {
        callbacks.onError(error);
      }
    });

  // Return abort function
  return () => controller.abort();
}

/**
 * Browse activities for a destination via Google Places.
 * Used by the BrowseActivitiesSheet for free/buffer days.
 */
export async function browseActivities(
  params: BrowseActivitiesParams
): Promise<BrowseActivitiesResponse> {
  const categories = params.categories ?? BROWSE_DEFAULT_CATEGORIES;
  const now = Date.now();
  pruneBrowseActivitiesCache(now);

  const cacheKey = browseActivitiesKey({ ...params, categories });
  const cached = browseActivitiesCache.get(cacheKey);
  if (cached && cached.expiresAt > now) {
    return cached.payload;
  }

  const inflight = browseActivitiesInflight.get(cacheKey);
  if (inflight) {
    return inflight;
  }

  const request = (async () => {
    const res = await apiFetch('/api/activities/browse', {
      method: 'POST',
      body: JSON.stringify({
        destination: params.destination,
        day_number: params.dayNumber,
        date: params.date,
        hotel_location: params.hotelLocation,
        categories,
      }),
    });
    if (!res.ok) throw new Error(`browse-activities failed: ${res.status}`);
    const payload = (await res.json()) as BrowseActivitiesResponse;
    browseActivitiesCache.set(cacheKey, {
      expiresAt: Date.now() + BROWSE_CACHE_TTL_MS,
      payload,
    });
    pruneBrowseActivitiesCache(Date.now());
    return payload;
  })();

  browseActivitiesInflight.set(cacheKey, request);
  try {
    return await request;
  } finally {
    browseActivitiesInflight.delete(cacheKey);
  }
}

/**
 * Fetch enrichment data for a specialist section (local_expert only).
 * Returns null if section not found, pending if not yet ready.
 */
export async function getSpecialistEnrichment(sectionId: string): Promise<{
  status: 'ready' | 'pending' | 'failed';
  section_id: string;
  data?: Record<string, unknown>;
  error_code?: string;
  retry_after_ms?: number;
} | null> {
  // Bust intermediary/browser caches so repeated pending polls can progress to ready
  // without requiring a hard refresh.
  const nonce = Date.now();
  const res = await apiFetch(
    `/api/specialist/${encodeURIComponent(sectionId)}/enrichment?ts=${nonce}`,
    { cache: 'no-store' }
  );
  if (res.status === 404) return null;
  if (res.status === 202) {
    const pendingPayload = (await res.json().catch(() => ({}))) as {
      retry_after_ms?: unknown;
      section_id?: unknown;
    };
    return {
      status: 'pending',
      section_id: typeof pendingPayload.section_id === 'string' ? pendingPayload.section_id : sectionId,
      retry_after_ms:
        typeof pendingPayload.retry_after_ms === 'number' ? pendingPayload.retry_after_ms : 1500,
    };
  }
  if (!res.ok) return null;
  return res.json();
}

/**
 * Fetch a shared trip snapshot by slug.
 * Used by SharedTripView for client-side fallback loading.
 * Credentials are omitted — shared trips are public.
 */
export async function fetchSharedTrip(
  slug: string,
  signal?: AbortSignal,
): Promise<import('@/components/shared/SharedTripView').SharedTripData> {
  return fetchSharedTripClient(slug, signal);
}

/**
 * Fire-and-forget deeplink click tracking.
 * Reuses existing /api/tiles/click endpoint.
 */
export function trackDeeplinkClick(tileId: string, branchId?: string): void {
  apiFetch('/api/tiles/click', {
    method: 'POST',
    body: JSON.stringify({ tile_id: tileId, branch_id: branchId }),
  }).catch(() => {});
}
