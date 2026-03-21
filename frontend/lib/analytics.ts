import { apiFetch } from './api';

/**
 * Fire-and-forget event tracking for YC funnel metrics.
 * Uses apiFetch with keepalive for page-unload resilience (critical for deeplink clicks).
 */
export function trackEvent(
  eventType: string,
  destination?: string | null,
  metadata?: Record<string, unknown>,
): void {
  apiFetch('/api/analytics/event', {
    method: 'POST',
    body: JSON.stringify({
      event_type: eventType,
      destination: destination || undefined,
      metadata: metadata || undefined,
    }),
    keepalive: true,
  }).catch(() => {});
}
