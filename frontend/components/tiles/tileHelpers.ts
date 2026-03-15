import { placeholderImageForTile } from '@/lib/placeholders';
import { isFlightType, isHotelType } from '@/lib/utils';
import type { DocumentTripInputs } from '@/types/document';
import type { Tile } from '@/types/tile';

export type AmenityIconLabel = {
  icon: string;
  label: string;
};

export type TileActivityMeta = {
  category?: string;
  durationHours?: number;
  timeOfDay?: string;
  description?: string;
};

export type TileCheckTimes = {
  checkIn?: string;
  checkOut?: string;
};

type DeeplinkProvider = 'viator' | 'gyg' | 'aviasales' | 'google_flights' | 'booking' | 'other';

type TileWithDeeplink = Pick<Tile, 'deeplink_url'>;
type TileWithTypeAndDeeplink = Pick<Tile, 'deeplink_url' | 'type'>;
type HotelDeeplinkTile = Pick<
  Tile,
  'deeplink_url' | 'meta' | 'title' | 'type'
>;
type TripInputDeeplinkContext = Pick<
  DocumentTripInputs,
  'adults' | 'children' | 'end_date' | 'start_date'
>;

const AMENITY_ICONS: Record<string, string> = {
  pool: '\u{1F3CA}',
  'swimming pool': '\u{1F3CA}',
  breakfast: '\u{1F373}',
  'breakfast included': '\u{1F373}',
  wifi: '\u{1F4F6}',
  'free wifi': '\u{1F4F6}',
  parking: '\u{1F17F}\uFE0F',
  'free parking': '\u{1F17F}\uFE0F',
  spa: '\u{1F486}',
  gym: '\u{1F3CB}\uFE0F',
  fitness: '\u{1F3CB}\uFE0F',
  'fitness center': '\u{1F3CB}\uFE0F',
  restaurant: '\u{1F37D}\uFE0F',
  bar: '\u{1F378}',
  'air conditioning': '\u{2744}\uFE0F',
  'pet friendly': '\u{1F415}',
  beach: '\u{1F3D6}\uFE0F',
  yoga: '\u{1F9D8}',
  dive_center: '\u{1F93F}',
  dive_center_nearby: '\u{1F93F}',
  ski_room: '\u{1F3BF}',
  rooftop_bar: '\u{1F378}',
  garden: '\u{1F33F}',
  valley_view: '\u{1F3DE}\uFE0F',
  lake_view: '\u{1F3DE}\uFE0F',
  horseback: '\u{1F434}',
  guided_hikes: '\u{1F97E}',
};

function getDeeplinkProvider(deeplinkUrl: string): DeeplinkProvider {
  if (deeplinkUrl.includes('booking.com')) {
    return 'booking';
  }
  if (deeplinkUrl.includes('viator.com')) return 'viator';
  if (deeplinkUrl.includes('getyourguide.com')) return 'gyg';
  if (deeplinkUrl.includes('aviasales.com')) return 'aviasales';
  if (deeplinkUrl.includes('google.com/travel/flights')) return 'google_flights';
  return 'other';
}

export function isPartnerDeeplinkUrl(deeplinkUrl: string): boolean {
  return getDeeplinkProvider(deeplinkUrl) !== 'other';
}

function isBookingComHostname(hostname: string): boolean {
  return hostname === 'booking.com' || hostname.endsWith('.booking.com');
}

function isGoogleHostname(hostname: string): boolean {
  return hostname === 'google.com' || hostname.endsWith('.google.com');
}

function parseUrl(url: string): URL | null {
  try {
    return new URL(url);
  } catch {
    return null;
  }
}

function normalizeSearchPart(value: string | undefined | null): string | null {
  if (typeof value !== 'string') return null;
  const normalized = value.trim().replace(/\s+/g, ' ');
  return normalized.length > 0 ? normalized : null;
}

function appendUniqueSearchPart(parts: string[], candidate: string | undefined | null): void {
  const normalizedCandidate = normalizeSearchPart(candidate);

  if (!normalizedCandidate) return;

  const normalizedCandidateLower = normalizedCandidate.toLowerCase();
  const alreadyCovered = parts.some((part) => {
    const normalizedPartLower = part.toLowerCase();
    return (
      normalizedPartLower.includes(normalizedCandidateLower)
      || normalizedCandidateLower.includes(normalizedPartLower)
    );
  });

  if (!alreadyCovered) {
    parts.push(normalizedCandidate);
  }
}

function getBookingSearchString(
  tile: HotelDeeplinkTile,
  originalUrl: URL
): string {
  const meta = tile.meta as Record<string, unknown> | undefined;
  const searchParts: string[] = [];

  appendUniqueSearchPart(searchParts, tile.title);
  appendUniqueSearchPart(
    searchParts,
    typeof meta?.destination === 'string' ? meta.destination : undefined
  );
  appendUniqueSearchPart(
    searchParts,
    typeof meta?.location === 'string' ? meta.location : undefined
  );

  if (searchParts.length > 0) {
    return searchParts.join(', ');
  }

  return normalizeSearchPart(originalUrl.searchParams.get('ss')) ?? '';
}

function isValidIsoDate(value: string | undefined | null): value is string {
  return typeof value === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(value);
}

function normalizeTravelerCount(value: number | null | undefined): number | null {
  if (typeof value !== 'number' || !Number.isFinite(value)) return null;
  const normalized = Math.trunc(value);
  return normalized >= 0 ? normalized : null;
}

function getSearchParamTravelerCount(
  url: URL,
  paramName: string
): number | null {
  const rawValue = url.searchParams.get(paramName);
  if (!rawValue) return null;
  const parsedValue = Number.parseInt(rawValue, 10);
  return Number.isFinite(parsedValue) && parsedValue >= 0 ? parsedValue : null;
}

export function isDirectBookingHotelSearchUrl(tile: TileWithTypeAndDeeplink): boolean {
  if (!isHotelType(tile.type || '')) return false;

  const parsedUrl = parseUrl(tile.deeplink_url);
  if (!parsedUrl || !isBookingComHostname(parsedUrl.hostname.toLowerCase())) return false;

  return parsedUrl.pathname.toLowerCase().startsWith('/searchresults');
}

function isGoogleTravelHotelUrl(tile: TileWithTypeAndDeeplink): boolean {
  if (!isHotelType(tile.type || '')) return false;

  const parsedUrl = parseUrl(tile.deeplink_url);
  if (!parsedUrl || !isGoogleHostname(parsedUrl.hostname.toLowerCase())) return false;

  return parsedUrl.pathname.toLowerCase().includes('/travel/hotels');
}

function isGoogleMapsUrl(tile: TileWithTypeAndDeeplink): boolean {
  if (!isHotelType(tile.type || '')) return false;

  const parsedUrl = parseUrl(tile.deeplink_url);
  if (!parsedUrl) return false;

  const hostname = parsedUrl.hostname.toLowerCase();
  if (hostname === 'maps.google.com') return true;
  return isGoogleHostname(hostname) && parsedUrl.pathname.toLowerCase().startsWith('/maps');
}

export function getEffectiveHotelBookingDeeplink(
  tile: HotelDeeplinkTile,
  tripInputs?: TripInputDeeplinkContext | null
): string {
  if (!isDirectBookingHotelSearchUrl(tile)) {
    return tile.deeplink_url;
  }

  const parsedOriginalUrl = parseUrl(tile.deeplink_url);
  if (!parsedOriginalUrl) return tile.deeplink_url;

  const startDate = tripInputs?.start_date;
  const endDate = tripInputs?.end_date;
  const adults =
    normalizeTravelerCount(tripInputs?.adults)
    ?? getSearchParamTravelerCount(parsedOriginalUrl, 'group_adults')
    ?? 1;
  const children =
    normalizeTravelerCount(tripInputs?.children)
    ?? getSearchParamTravelerCount(parsedOriginalUrl, 'group_children')
    ?? 0;
  const searchString = getBookingSearchString(tile, parsedOriginalUrl);

  if (
    !isValidIsoDate(startDate)
    || !isValidIsoDate(endDate)
    || adults < 1
    || !searchString
  ) {
    return tile.deeplink_url;
  }

  const effectiveUrl = new URL(parsedOriginalUrl.origin + parsedOriginalUrl.pathname);
  const affiliateId = parsedOriginalUrl.searchParams.get('aid');
  const roomCount = parsedOriginalUrl.searchParams.get('no_rooms');

  if (affiliateId) {
    effectiveUrl.searchParams.set('aid', affiliateId);
  }

  effectiveUrl.searchParams.set('ss', searchString);
  effectiveUrl.searchParams.set('checkin', startDate);
  effectiveUrl.searchParams.set('checkout', endDate);
  effectiveUrl.searchParams.set('group_adults', String(adults));
  effectiveUrl.searchParams.set('group_children', String(children));
  effectiveUrl.searchParams.set('no_rooms', roomCount || '1');
  effectiveUrl.hash = parsedOriginalUrl.hash;

  return effectiveUrl.toString();
}

export function getEffectiveGoogleHotelDeeplink(
  tile: HotelDeeplinkTile,
  tripInputs?: TripInputDeeplinkContext | null
): string {
  if (!isGoogleTravelHotelUrl(tile) && !isGoogleMapsUrl(tile)) {
    return tile.deeplink_url;
  }

  const parsedOriginalUrl = parseUrl(tile.deeplink_url);
  if (!parsedOriginalUrl) return tile.deeplink_url;

  const startDate = tripInputs?.start_date;
  const endDate = tripInputs?.end_date;
  const adults = normalizeTravelerCount(tripInputs?.adults);
  const children = normalizeTravelerCount(tripInputs?.children) ?? 0;
  const searchString =
    getBookingSearchString(tile, parsedOriginalUrl)
    || normalizeSearchPart(parsedOriginalUrl.searchParams.get('q'));

  if (
    !isValidIsoDate(startDate)
    || !isValidIsoDate(endDate)
    || !searchString
  ) {
    return tile.deeplink_url;
  }

  const totalOccupancy =
    (adults !== null && adults >= 1)
      ? adults + children
      : getSearchParamTravelerCount(parsedOriginalUrl, 'brd_occupancy') ?? 1;
  const effectiveUrl = new URL('https://www.google.com/travel/hotels');
  const originalGl = normalizeSearchPart(parsedOriginalUrl.searchParams.get('gl'));
  const originalHl = normalizeSearchPart(parsedOriginalUrl.searchParams.get('hl'));

  effectiveUrl.searchParams.set('q', searchString);
  effectiveUrl.searchParams.set('brd_dates', `${startDate},${endDate}`);
  effectiveUrl.searchParams.set('brd_occupancy', String(totalOccupancy));

  if (originalGl) {
    effectiveUrl.searchParams.set('gl', originalGl);
  }
  if (originalHl) {
    effectiveUrl.searchParams.set('hl', originalHl);
  }

  return effectiveUrl.toString();
}

export function getEffectiveTileDeeplinkUrl(
  tile: HotelDeeplinkTile,
  tripInputs?: TripInputDeeplinkContext | null
): string {
  const bookingDeeplink = getEffectiveHotelBookingDeeplink(tile, tripInputs);
  if (bookingDeeplink !== tile.deeplink_url) {
    return bookingDeeplink;
  }

  return getEffectiveGoogleHotelDeeplink(tile, tripInputs);
}

export function getTileDeeplinkPillLabel(
  tile: TileWithDeeplink,
  deeplinkUrl: string = tile.deeplink_url
): string {
  const provider = getDeeplinkProvider(deeplinkUrl);

  if (provider === 'booking') return 'Book on Booking.com';
  if (provider === 'aviasales') return 'Book on Aviasales';
  if (provider === 'google_flights') return 'Book on Google Flights';
  if (provider === 'viator' || provider === 'gyg') return 'Book';
  return 'Map';
}

export function getTileDeeplinkActionLabel(
  tile: Pick<Tile, 'deeplink_url' | 'type'>,
  deeplinkUrl: string = tile.deeplink_url
): string {
  const provider = getDeeplinkProvider(deeplinkUrl);

  if (provider === 'booking') return 'Book on Booking.com';
  if (provider === 'aviasales') return 'Book on Aviasales';
  if (provider === 'google_flights') return 'Book on Google Flights';
  if (provider === 'viator') return 'Book on Viator';
  if (provider === 'gyg') return 'Book on GYG';
  return isHotelType(tile.type || '') ? 'View on Google Travel' : 'View on Google Maps';
}

export function getAmenityIconsWithLabels(tile: Tile): AmenityIconLabel[] {
  const meta = tile.meta as Record<string, unknown> | undefined;
  const amenities = (meta?.amenities as string[]) || [];
  const result: AmenityIconLabel[] = [];
  const seenIcons = new Set<string>();

  for (const amenity of amenities) {
    const key = amenity.toLowerCase();
    const icon = AMENITY_ICONS[key];
    if (icon && !seenIcons.has(icon)) {
      seenIcons.add(icon);
      result.push({
        icon,
        label: amenity.replace(/_/g, ' ').replace(/^\w/, c => c.toUpperCase()),
      });
      if (result.length >= 3) break;
    }
  }

  return result;
}

export function getTileFeatures(tile: Tile): string[] {
  const meta = tile.meta as Record<string, unknown> | undefined;

  if (meta?.features && Array.isArray(meta.features)) {
    return meta.features as string[];
  }

  if (isFlightType(tile.type || '')) {
    const features: string[] = [];
    if (typeof meta?.stops === 'string') features.push(meta.stops);
    if (typeof meta?.fare_class === 'string') features.push(meta.fare_class);
    if (typeof meta?.duration === 'string') features.push(meta.duration);
    return features;
  }

  return [];
}

export function getTileRelevanceBadges(tile: Tile): string[] {
  const badges: string[] = [];
  const meta = tile.meta as Record<string, unknown> | undefined;

  if (tile.is_refundable === true) {
    badges.push('Free cancellation');
  }
  if (meta?.breakfast_included === true) {
    badges.push('Breakfast included');
  }
  if (meta?.has_pool === true) {
    badges.push('Pool');
  }
  if (meta?.specialist_badges && Array.isArray(meta.specialist_badges)) {
    badges.push(...(meta.specialist_badges as string[]));
  }

  return badges.slice(0, 2);
}

export function getTileAmenities(tile: Tile): string[] {
  const meta = tile.meta as Record<string, unknown> | undefined;
  if (meta?.amenities && Array.isArray(meta.amenities)) {
    return meta.amenities as string[];
  }
  if (meta?.features && Array.isArray(meta.features)) {
    return meta.features as string[];
  }
  return [];
}

export function getTileCancellationText(tile: Tile): string | null {
  if (tile.is_refundable === true) {
    const meta = tile.meta as Record<string, unknown> | undefined;
    if (typeof meta?.cancellation_deadline === 'string') {
      return `Free cancellation until ${meta.cancellation_deadline}`;
    }
    return 'Free cancellation available';
  }
  if (tile.is_refundable === false) {
    return 'Non-refundable';
  }
  return null;
}

export function getTileCheckTimes(tile: Tile): TileCheckTimes {
  const meta = tile.meta as Record<string, unknown> | undefined;
  return {
    checkIn: typeof meta?.check_in === 'string' ? meta.check_in : undefined,
    checkOut: typeof meta?.check_out === 'string' ? meta.check_out : undefined,
  };
}

export function getTileReviewCount(tile: Tile): number | null {
  if (typeof tile.review_count === 'number') return tile.review_count;
  const meta = tile.meta as Record<string, unknown> | undefined;
  if (typeof meta?.review_count === 'number') return meta.review_count;
  if (typeof meta?.reviews === 'number') return meta.reviews;
  return null;
}

export function getTileAIReasoning(tile: Tile): string | null {
  const meta = tile.meta as Record<string, unknown> | undefined;
  if (typeof meta?.reasoning === 'string') return meta.reasoning;
  if (typeof meta?.ai_reasoning === 'string') return meta.ai_reasoning;
  return null;
}

export function isTileAIPick(tile: Tile): boolean {
  const meta = tile.meta as Record<string, unknown> | undefined;
  return meta?.is_ai_pick === true || meta?.ai_recommended === true;
}

export function getTileActivityMeta(tile: Tile): TileActivityMeta | null {
  if (tile.type !== 'activity') return null;
  const meta = tile.meta as Record<string, unknown> | undefined;
  if (!meta) return null;
  return {
    category: typeof meta.category === 'string' ? meta.category : undefined,
    durationHours: typeof meta.duration_hours === 'number' ? meta.duration_hours : undefined,
    timeOfDay: typeof meta.time_of_day === 'string' ? meta.time_of_day : undefined,
    description: typeof meta.description === 'string' && meta.description ? meta.description : undefined,
  };
}

export function getTileImages(tile: Tile): string[] {
  const meta = tile.meta as Record<string, unknown> | undefined;
  if (meta?.images && Array.isArray(meta.images)) {
    return meta.images as string[];
  }
  if (tile.image_url) {
    return [tile.image_url];
  }
  return [placeholderImageForTile(tile)];
}
