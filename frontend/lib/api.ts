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

/**
 * Reset the current session by calling DELETE /v1/session.
 * The backend will clear the session cookies.
 */
export async function resetSession(): Promise<Response> {
  const url = `${API_BASE}/v1/session`;

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
  const res = await apiFetch('/v1/validate-trip-input', {
    method: 'POST',
    body: JSON.stringify({ field_type: fieldType, value }),
  });

  if (!res.ok) {
    throw new Error(`Validation failed: ${res.status}`);
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
  apiFetch('/v1/suggestions/click', {
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

export type SSEEvent = SSETokenEvent | SSECompleteEvent | SSEErrorEvent;

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
  },
  callbacks: StreamGraphPlanCallbacks
): () => void {
  const controller = new AbortController();
  const url = `${API_BASE}/v1/graph_plan/stream`;

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
