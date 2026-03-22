/* eslint no-unused-vars: ["error", { "args": "none" }] */
import { API_BASE } from '@/lib/config';
import { debugLog } from '@/lib/debug';

export { API_BASE } from '@/lib/config';

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
  duration?: string | null;
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

// ─────────────────────────────────────────────────────────────────────────────
// Internal helpers
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Read the CSRF token from the csrf cookie.
 * This cookie is set by the backend and is readable by JS (not HttpOnly).
 */
export function getCsrfToken(): string | null {
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

// ─────────────────────────────────────────────────────────────────────────────
// apiFetch
// ─────────────────────────────────────────────────────────────────────────────

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
    console.error('[apiFetch] Fetch FAILED:', {
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
 * Reset the current session — destroys trip data but preserves auth.
 *
 * The backend deletes the old session's data, creates a fresh session
 * linked to the same user_id, and sets new session + CSRF cookies.
 */
export async function resetSession(): Promise<Response> {
  return apiFetch('/api/session', { method: 'DELETE' });
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
// Re-exports for backward compatibility
// ─────────────────────────────────────────────────────────────────────────────

export { applyArrangement, fillDay, refreshTiles, removeBlock,validateArrangement } from './api-document';
export type {
  DayCardsPartialPayload,
  SpecialistPreviewActivity,
  SpecialistPreviewPayload,
  SpecialistPreviewSection,
  SSEFeasibilityWarningEvent,
  SSENodeStatusEvent,
  SSEPartialContext,
  SSEPartialData,
  SSEPartialEvent,
  TileEnrichmentPayload,
} from './api-streaming';
export {
  browseActivities,
  fetchSharedTrip,
  getSpecialistEnrichment,
  streamGraphPlan,
  trackDeeplinkClick,
} from './api-streaming';
