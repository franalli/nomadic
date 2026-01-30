const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

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

  // Build headers
  const headers: HeadersInit = {
    'Content-Type': 'application/json',
    ...(options?.headers || {}),
  };

  // Add CSRF token for unsafe methods
  if (isUnsafeMethod(options?.method)) {
    const csrfToken = getCsrfToken();
    if (csrfToken) {
      (headers as Record<string, string>)['X-CSRF-Token'] = csrfToken;
    }
  }

  const res = await fetch(url, {
    ...options,
    credentials: 'include', // Always include cookies
    headers,
  });

  return res;
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
export function isTransientError(error: unknown): boolean {
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
 * @param status - HTTP status code
 * @returns true if status indicates a retryable error
 */
export function isTransientStatus(status: number): boolean {
  return status === 502 || status === 503 || status === 504 || status === 429;
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
 * Options for fetchWithRetry.
 */
export interface FetchWithRetryOptions {
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
 *   onRetry: (attempt) => console.log(`Retrying (attempt ${attempt})...`)
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

  for (let attempt = 0; attempt <= maxRetries; attempt++) {
    try {
      const res = await apiFetch(path, options);

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
export interface ValidationResponse {
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
export interface DestinationImageResponse {
  image_url: string;
  destination: string;
}

export async function fetchDestinationImage(
  destination: string
): Promise<DestinationImageResponse> {
  const res = await apiFetch('/api/destination-image', {
    method: 'POST',
    body: JSON.stringify({ destination }),
  });

  if (!res.ok) {
    throw new Error(`Failed to fetch destination image: ${res.status}`);
  }

  return res.json();
}

/**
 * Track a suggestion pill click for analytics.
 * Fire-and-forget - we don't wait for confirmation.
 */
export function trackSuggestionClick(
  suggestionText: string,
  suggestionIndex: number,
  requestId?: string
): void {
  apiFetch('/api/suggestions/click', {
    method: 'POST',
    body: JSON.stringify({
      suggestion_text: suggestionText,
      suggestion_index: suggestionIndex,
      request_id: requestId,
    }),
  }).catch(() => {
    // Silently ignore tracking failures
  });
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
export interface TileRefreshResponse {
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
 * SSE Event types for streaming graph plan responses.
 */
export interface SSETokenEvent {
  type: 'token';
  data: string;
}

export interface SSECompleteEvent {
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

export interface SSEErrorEvent {
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
    topic?: 'hiking' | 'skiing' | 'diving' | 'cycling' | 'boating';
    max_tokens?: number;
  };
}

export type SSEEvent = SSETokenEvent | SSECompleteEvent | SSEErrorEvent | SSENodeStatusEvent;

/**
 * Callbacks for streaming graph plan responses.
 */
export interface StreamGraphPlanCallbacks {
  /** Called for each token received from the stream */
  onToken: (token: string) => void;
  /** Called when the stream completes with the full response */
  onComplete: (response: SSECompleteEvent['data']) => void;
  /** Called when an error occurs */
  onError: (error: Error) => void;
  /** Called when node status changes (e.g., strategy node starts) */
  onNodeStatus?: (status: SSENodeStatusEvent['data']) => void;
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

              if (parsed.type === 'token') {
                callbacks.onToken(parsed.data);
              } else if (parsed.type === 'node_status') {
                callbacks.onNodeStatus?.(parsed.data);
              } else if (parsed.type === 'complete') {
                callbacks.onComplete(parsed.data);
              } else if (parsed.type === 'error') {
                callbacks.onError(new Error(parsed.message));
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
    })
    .catch((error) => {
      if (error.name !== 'AbortError') {
        callbacks.onError(error);
      }
    });

  // Return abort function
  return () => controller.abort();
}
