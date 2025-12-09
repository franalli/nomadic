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
