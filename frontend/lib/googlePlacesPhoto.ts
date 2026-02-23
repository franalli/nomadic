import { apiFetch } from './api';

const GOOGLE_PLACES_PHOTO_NAME_RE = /^places\/[A-Za-z0-9_-]+\/photos\/[A-Za-z0-9_-]+$/;
const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

interface GooglePlacesPhotoOptions {
  maxWidth?: number;
  maxHeight?: number;
}

type SignedGooglePlacesPhotoResponse = {
  url?: unknown;
};

const signedPhotoUrlCache = new Map<string, string>();
const signedPhotoUrlInflight = new Map<string, Promise<string | undefined>>();

function clampDimension(value: number | undefined, fallback: number): number {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return fallback;
  return Math.max(64, Math.min(Math.round(numeric), 1600));
}

export function normalizeGooglePlacesPhotoName(value: unknown): string | undefined {
  if (typeof value !== 'string') return undefined;
  const trimmed = value.trim();
  if (!trimmed || !GOOGLE_PLACES_PHOTO_NAME_RE.test(trimmed)) return undefined;
  return trimmed;
}

export function buildGooglePlacesPhotoProxyUrl(
  photoName: unknown,
  options?: GooglePlacesPhotoOptions
): string | undefined {
  const normalized = normalizeGooglePlacesPhotoName(photoName);
  if (!normalized) return undefined;

  const params = new URLSearchParams({
    name: normalized,
    max_width: String(clampDimension(options?.maxWidth, 320)),
    max_height: String(clampDimension(options?.maxHeight, 240)),
  });
  return `${API_BASE}/api/media/google-places-photo?${params.toString()}`;
}

function signedPhotoCacheKey(photoName: string, width: number, height: number): string {
  return `${photoName}|${width}|${height}`;
}

export async function getSignedGooglePlacesPhotoProxyUrl(
  photoName: unknown,
  options?: GooglePlacesPhotoOptions
): Promise<string | undefined> {
  const normalized = normalizeGooglePlacesPhotoName(photoName);
  if (!normalized) return undefined;

  const width = clampDimension(options?.maxWidth, 320);
  const height = clampDimension(options?.maxHeight, 240);
  const cacheKey = signedPhotoCacheKey(normalized, width, height);
  const cached = signedPhotoUrlCache.get(cacheKey);
  if (cached) return cached;

  const inflight = signedPhotoUrlInflight.get(cacheKey);
  if (inflight) return inflight;

  const pending = (async () => {
    const params = new URLSearchParams({
      name: normalized,
      max_width: String(width),
      max_height: String(height),
      ttl_seconds: '300',
    });
    const res = await apiFetch(`/api/media/google-places-photo-url?${params.toString()}`);
    if (!res.ok) return undefined;

    const payload = await res.json() as SignedGooglePlacesPhotoResponse;
    const rawUrl = typeof payload.url === 'string' ? payload.url.trim() : '';
    if (!rawUrl) return undefined;
    const resolvedUrl = rawUrl.startsWith('http')
      ? rawUrl
      : `${API_BASE}${rawUrl.startsWith('/') ? rawUrl : `/${rawUrl}`}`;
    signedPhotoUrlCache.set(cacheKey, resolvedUrl);
    return resolvedUrl;
  })()
    .catch(() => undefined)
    .finally(() => {
      signedPhotoUrlInflight.delete(cacheKey);
    });

  signedPhotoUrlInflight.set(cacheKey, pending);
  return pending;
}

export function isGooglePlacesPhotoProxyUrl(url: unknown): boolean {
  if (typeof url !== 'string') return false;
  const trimmed = url.trim();
  if (!trimmed) return false;
  if (trimmed.startsWith('/api/media/google-places-photo')) return true;

  try {
    const parsed = new URL(trimmed);
    return parsed.pathname === '/api/media/google-places-photo';
  } catch {
    return false;
  }
}
