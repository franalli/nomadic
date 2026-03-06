/**
 * Shared configuration constants.
 *
 * BACKEND_URL is used by both server-side (RSC) and client-side code.
 * Server components should prefer BACKEND_URL (internal network).
 * Client components use NEXT_PUBLIC_API_URL (browser-reachable).
 */
export const BACKEND_URL =
  process.env.BACKEND_URL ||
  process.env.NEXT_PUBLIC_API_URL ||
  'http://localhost:8000';
