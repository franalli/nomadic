/* eslint no-unused-vars: ["error", { "args": "none" }] */
import { debugLog } from '@/lib/debug';
import { useDocumentStore } from '@/state/documentStore';

// ─────────────────────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────────────────────

export interface BrowseTile {
  id: string;
  type: string;
  title: string;
  subtitle?: string;
  description?: string;
  image_url?: string | null;
  photo_name?: string | null;
  rating?: number | null;
  review_count?: number | null;
  location_label?: string;
  geo?: { lat: number; lng: number } | null;
  price_estimate?: string | null;
  source: string;
  provider: string;
  category: string;
  tags?: string[];
  place_id?: string;
  maps_uri?: string | null;
}

interface BrowseActivitiesParams {
  destination: string;
  dayNumber?: number;
  date?: string | null;
  hotelLocation?: { lat: number; lng: number } | null;
  categories?: string[];
}

interface BrowseActivitiesResponse {
  tiles: BrowseTile[];
  total: number;
}

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
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

/**
 * Read the CSRF token from the csrf cookie.
 * This cookie is set by the backend and is readable by JS (not HttpOnly).
 */
function getCsrfToken(): string | null {
  if (typeof document === 'undefined') return null;

  const cookies = document.cookie.split(';');
  for (const cookie of cookies) {
    const [name, value] = cookie.trim().split('=');
    if (name === 'csrf') {
      return decodeURIComponent(value);
    }
  }
  return null;
}

function createClientRequestId(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID();
  }
  return `req_${Date.now()}_${Math.random().toString(36).slice(2, 10)}`;
}

/**
 * Check if a method requires CSRF protection.
 */
function isUnsafeMethod(method?: string): boolean {
  if (!method) return false;
  const unsafe = ['POST', 'PUT', 'PATCH', 'DELETE'];
  return unsafe.includes(method.toUpperCase());
}

/**
 * Fetch wrapper for API calls with automatic credential and CSRF handling.
 *
 * Features:
 * - Includes credentials (cookies) in all requests
 * - Automatically adds X-CSRF-Token header for unsafe methods
 * - Handles 401 Unauthorized responses (session expired)
 *
 * Returns the raw Response object so callers can decide how to handle it.
 */
export async function apiFetch(path: string, options?: RequestInit): Promise<Response> {
  const url = `${API_BASE}${path}`;
  const method = (options?.method || 'GET').toUpperCase();

  // Build headers
  const headers = new Headers(options?.headers || {});
  if (options?.body !== undefined && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }
  // Keep trace headers on unsafe methods to avoid forcing CORS preflights on simple GETs.
  if (isUnsafeMethod(method)) {
    if (!headers.has('X-Client-Request-Id')) {
      headers.set('X-Client-Request-Id', createClientRequestId());
    }
    if (!headers.has('X-Client-Attempt')) {
      headers.set('X-Client-Attempt', '1');
    }
  }
  const clientRequestId = headers.get('X-Client-Request-Id');
  const clientAttempt = headers.get('X-Client-Attempt');

  // Add CSRF token for unsafe methods
  let csrfToken: string | null = null;
  if (isUnsafeMethod(options?.method)) {
    csrfToken = getCsrfToken();
    if (csrfToken) {
      headers.set('X-CSRF-Token', csrfToken);
    }
  }

  // CRITICAL: Check signal state before fetch to fail fast
  if (options?.signal?.aborted) {
    debugLog('[apiFetch] ⛔ Signal already aborted before fetch');
    throw new DOMException('Signal already aborted', 'AbortError');
  }

  try {
    const res = await fetch(url, {
      ...options,
      credentials: 'include', // Always include cookies
      headers,
    });

    // Single-line success log (collapsed from 4 lines for cleaner console)
    debugLog(
      `[apiFetch] ✅ ${options?.method || 'GET'} ${url} → ${res.status} ` +
      `(rid=${clientRequestId ?? 'n/a'} attempt=${clientAttempt ?? 'n/a'})`
    );
    return res;
  } catch (error) {
    // DEBUG: Log detailed error info (Error objects don't serialize well)
    const err = error as Error;
    console.error('[apiFetch] ❌ Fetch FAILED:', {
      url,
      method: options?.method || 'GET',
      hasCsrf: !!csrfToken,
      hasSignal: !!options?.signal,
      signalAborted: options?.signal?.aborted,
      clientRequestId,
      clientAttempt,
      errorName: err?.name,
      errorMessage: err?.message,
      wasAborted: err?.name === 'AbortError',
    });
    throw error;
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// Retry Utilities
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Check if an error is a transient/retryable error.
 *
 * Transient errors include:
 * - Network errors (TypeError: Failed to fetch)
 * - Timeout errors
 * - 5xx server errors (503 Service Unavailable, etc.)
 *
 * @param error - The error to check
 * @returns true if the error is transient and should be retried
 */
function isTransientError(error: unknown): boolean {
  if (error instanceof Error) {
    const message = error.message.toLowerCase();
    return (
      message.includes('timeout') ||
      message.includes('network') ||
      message.includes('failed to fetch') ||
      message.includes('503') ||
      message.includes('502') ||
      message.includes('504')
    );
  }
  return false;
}

/**
 * Check if a Response status indicates a transient error.
 *
 * NOTE: 429 is intentionally excluded. Unlike 5xx errors (server hiccups),
 * 429 means "you are sending too many requests" — retrying makes it worse.
 * Callers should handle 429 via the Retry-After header, not blind retries.
 *
 * @param status - HTTP status code
 * @returns true if status indicates a retryable error
 */
function isTransientStatus(status: number): boolean {
  return status === 502 || status === 503 || status === 504;
}

/**
 * Sleep for a given number of milliseconds.
 *
 * @param ms - Milliseconds to sleep
 * @returns Promise that resolves after the delay
 */
function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/**
 * Parse the Retry-After header from a 429 response into seconds.
 * Returns null if the header is missing or unparseable.
 */
export function parseRetryAfter(response: Response): number | null {
  const header = response.headers.get('Retry-After');
  if (!header) return null;
  const seconds = parseInt(header, 10);
  return isNaN(seconds) || seconds <= 0 ? null : seconds;
}

/**
 * Options for fetchWithRetry.
 */
interface FetchWithRetryOptions {
  /** Maximum number of retry attempts (default: 3) */
  maxRetries?: number;
  /** Base delay in ms before first retry (default: 1000) */
  baseDelay?: number;
  /** Maximum delay in ms between retries (default: 10000) */
  maxDelay?: number;
  /** Callback when a retry is attempted */
  onRetry?: (attempt: number, error: unknown) => void;
}

/**
 * Wrapper around apiFetch that automatically retries on transient errors.
 *
 * Uses exponential backoff with jitter:
 * - Retry 1: baseDelay * 1 + random(0-500)ms
 * - Retry 2: baseDelay * 2 + random(0-500)ms
 * - Retry 3: baseDelay * 4 + random(0-500)ms
 *
 * @param path - API path to fetch
 * @param options - fetch options (same as apiFetch)
 * @param retryOptions - retry configuration
 * @returns Response from the successful fetch
 * @throws Last error if all retries fail
 *
 * @example
 * ```ts
 * const res = await fetchWithRetry('/api/document/tiles/abc', { method: 'POST' }, {
 *   maxRetries: 3,
 *   onRetry: (attempt) => debugLog(`Retrying (attempt ${attempt})...`)
 * });
 * ```
 */
export async function fetchWithRetry(
  path: string,
  options?: RequestInit,
  retryOptions: FetchWithRetryOptions = {}
): Promise<Response> {
  const { maxRetries = 3, baseDelay = 1000, maxDelay = 10000, onRetry } = retryOptions;

  let lastError: unknown;
  const requestId = createClientRequestId();

  for (let attempt = 0; attempt <= maxRetries; attempt++) {
    try {
      const headers = new Headers(options?.headers || {});
      headers.set('X-Client-Request-Id', requestId);
      headers.set('X-Client-Attempt', String(attempt + 1));

      const res = await apiFetch(path, {
        ...options,
        headers,
      });

      // D8: Handle 429 rate limit — honour Retry-After header before retrying
      if (res.status === 429 && attempt < maxRetries) {
        onRetry?.(attempt + 1, new Error('HTTP 429'));
        const retryAfterSeconds = parseRetryAfter(res);
        const delay = retryAfterSeconds
          ? retryAfterSeconds * 1000
          : Math.min(baseDelay * Math.pow(2, attempt), maxDelay);
        await sleep(delay);
        continue;
      }

      // Check for transient HTTP status codes
      if (isTransientStatus(res.status) && attempt < maxRetries) {
        onRetry?.(attempt + 1, new Error(`HTTP ${res.status}`));
        const delay = Math.min(baseDelay * Math.pow(2, attempt), maxDelay) + Math.random() * 500;
        await sleep(delay);
        continue;
      }

      return res;
    } catch (error) {
      lastError = error;

      // Don't retry abort errors - those are intentional
      if ((error as DOMException)?.name === 'AbortError') {
        throw error;
      }

      // Check if this is a transient error worth retrying
      if (isTransientError(error) && attempt < maxRetries) {
        onRetry?.(attempt + 1, error);
        const delay = Math.min(baseDelay * Math.pow(2, attempt), maxDelay) + Math.random() * 500;
        await sleep(delay);
        continue;
      }

      // Non-transient error or max retries reached
      throw error;
    }
  }

  // This should only be reached if all retries failed
  throw lastError;
}

/**
 * Reset the current session by calling DELETE /api/session.
 * The backend will clear the session cookies.
 */
export async function resetSession(): Promise<Response> {
  const url = `${API_BASE}/api/session`;

  const headers: HeadersInit = {};
  const csrfToken = getCsrfToken();
  if (csrfToken) {
    headers['X-CSRF-Token'] = csrfToken;
  }

  return fetch(url, {
    method: 'DELETE',
    credentials: 'include',
    headers,
  });
}

/**
 * LocalStorage keys used by the application.
 * Keep in sync when adding new localStorage usage.
 */
const LOCAL_STORAGE_KEYS = {
  /** Trip summary cached for the summary page */
  TRIP_SUMMARY: 'nomadic_trip_summary',
  /** User consent preferences (GDPR) - should NOT be cleared on fresh start */
  CONSENT: 'nomadic_consent',
} as const;

/**
 * Clear all session-related localStorage data.
 *
 * This clears trip summary and other session data, but intentionally
 * preserves the user's consent preferences to maintain GDPR compliance
 * and avoid re-prompting users.
 *
 * Call this during "Fresh Start" or session reset operations.
 */
export function clearSessionLocalStorage(): void {
  if (typeof window === 'undefined') return;

  try {
    // Clear session-related data
    window.localStorage.removeItem(LOCAL_STORAGE_KEYS.TRIP_SUMMARY);

    // NOTE: We intentionally do NOT clear CONSENT preferences
    // to maintain GDPR compliance and avoid re-prompting users

    // Add any future session-related localStorage keys here
  } catch (error) {
    console.error('Failed to clear session localStorage', error);
  }
}

/**
 * Validate a trip input (origin or destination) using LLM-based validation.
 *
 * @param fieldType - Type of input: 'origin' or 'destination'
 * @param value - The raw input value to validate
 * @returns Validation result with corrected values and validity flag
 */
interface ValidationResponse {
  corrected_values: string[];
  is_valid: boolean;
  reason?: string;
}

export async function validateTripInput(
  fieldType: 'origin' | 'destination',
  value: string
): Promise<ValidationResponse> {
  const res = await apiFetch('/api/validate-trip-input', {
    method: 'POST',
    body: JSON.stringify({ field_type: fieldType, value }),
  });

  if (!res.ok) {
    throw new Error(`Validation failed: ${res.status}`);
  }

  return res.json();
}

/**
 * Fetch the destination image URL from Unsplash.
 * Called when user selects a destination to show the correct banner image.
 */
interface DestinationImageResponse {
  image_url: string;
  destination: string;
}

export async function fetchDestinationImage(
  destination: string,
  options?: { signal?: AbortSignal }
): Promise<DestinationImageResponse> {
  const res = await apiFetch('/api/destination-image', {
    method: 'POST',
    body: JSON.stringify({ destination }),
    signal: options?.signal,
  });

  if (!res.ok) {
    throw new Error(`Failed to fetch destination image: ${res.status}`);
  }

  return res.json();
}

// ─────────────────────────────────────────────────────────────────────────────
// Tile Refresh API
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
  day_card?: import('@/types/plan-envelope').DayCard;
  tiles?: Record<string, import('@/types/tile').Tile>;
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
  day_card: import('@/types/plan-envelope').DayCard;
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

/**
 * SSE Event types for streaming graph plan responses.
 */
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
  };
}

interface SSEErrorEvent {
  type: 'error';
  message: string;
}

export interface SSENodeStatusEvent {
  type: 'node_status';
  data: {
    node: string;
    status: 'started' | 'completed';
    label: string; // Human-readable label for UI (e.g., "Finding flights")
    icon_key: string; // Icon identifier for frontend (e.g., "plane", "hiking")
    estimated_duration_ms: number;
    // Strategy-specific fields (optional, only present for strategy_node)
    stage?: number;
    tier?: 'outline' | 'section' | 'full';
    topic?: string;
    max_tokens?: number;
  };
}

export interface SSEPartialEvent {
  type: 'partial';
  data: {
    kind: 'strategy_sections' | 'tiles' | 'trip_inputs';
    payload: unknown;
  };
}

type SSEEvent = SSETokenEvent | SSECompleteEvent | SSEErrorEvent | SSENodeStatusEvent | SSEPartialEvent;

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
}

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
        throw new Error(`Stream request failed: ${response.status}`);
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
