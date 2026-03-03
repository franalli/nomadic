/**
 * Pure data extraction for trip PDF generation.
 * No React, no side effects — just transforms store data into a flat PDF-ready shape.
 */

import type { DocumentTripInputs } from '@/types/document';
import type { DayCard } from '@/types/plan-envelope';
import type { Tile } from '@/types/tile';

// ---------------------------------------------------------------------------
// Exported interfaces
// ---------------------------------------------------------------------------

export interface PdfHotelLink {
  title: string;
  url: string;
  pricePerNight: string | null; // "~$150" or null
}

export interface PdfActivityLink {
  name: string;
  url: string;
  meta: string | null; // "~$120 · 4h" or "2h" or null
}

export interface PdfBlockData {
  period: string;
  summary: string;
  duration: string | null;
  priceDisplay: string | null;
  isBuffer: boolean;
  bufferReason: string | null;
  bufferType: 'no_fly' | 'rest_day' | 'acclimatization' | 'arrival' | 'departure' | null;
  constraintNotes: string[]; // human-readable constraint descriptions
  specialistType: string | null; // display name, e.g. "Diving", "Hiking"
  hotelName: string | null; // for check-in/out blocks
  logisticsDetails: string | null; // terminal info, hotel address
  intensity: 'light' | 'moderate' | 'challenging' | null;
}

export interface PdfDaySection {
  dayNumber: number;
  date: string | null; // "Apr 2" formatted date
  label: string; // Descriptive only (no "Day N" prefix — that's added by the renderer)
  blocks: PdfBlockData[];
  intensity: 'light' | 'moderate' | 'challenging' | null; // derived from blocks — pick the highest
}

export interface TripPdfData {
  destination: string;
  dates: string; // "Apr 1 – 7, 2025" or "Dates TBD"
  travelers: string; // "2 adults, 1 child" or "1 adult"
  budget: string | null; // "$3,000" or null
  days: PdfDaySection[];
  hotelLinks: PdfHotelLink[];
  activityLinks: PdfActivityLink[];
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

type Intensity = 'light' | 'moderate' | 'challenging';
const INTENSITY_RANK: Record<Intensity, number> = { light: 1, moderate: 2, challenging: 3 };

function deriveDayIntensity(blocks: DayCard['blocks']): Intensity | null {
  let max = 0;
  let label: Intensity | null = null;
  for (const b of blocks) {
    if (b.intensity && INTENSITY_RANK[b.intensity] > max) {
      max = INTENSITY_RANK[b.intensity];
      label = b.intensity;
    }
  }
  return label;
}

/** Convert raw specialist_type ("wildlife_safari") to display name ("Wildlife Safari"). */
function formatSpecialistType(raw: string | undefined): string | null {
  if (!raw || raw === 'general') return null;
  return raw.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
}

const PRICE_LEVEL_MAP: Record<number, string> = {
  0: 'Free',
  1: '$',
  2: '$$',
  3: '$$$',
  4: '$$$$',
};

const SHORT_MONTHS = [
  'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
  'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec',
];

/** Format ISO date to short display: "Apr 2" */
function formatShortDate(isoDate: string | undefined): string | null {
  if (!isoDate) return null;
  const d = new Date(isoDate + 'T00:00:00');
  if (isNaN(d.getTime())) return null;
  return `${SHORT_MONTHS[d.getMonth()]} ${d.getDate()}`;
}

function formatDateRange(startIso: string | null | undefined, endIso: string | null | undefined): string {
  if (!startIso || !endIso) return 'Dates TBD';

  const start = new Date(startIso + 'T00:00:00');
  const end = new Date(endIso + 'T00:00:00');

  if (isNaN(start.getTime()) || isNaN(end.getTime())) return 'Dates TBD';

  const sMonth = SHORT_MONTHS[start.getMonth()];
  const eMonth = SHORT_MONTHS[end.getMonth()];
  const sDay = start.getDate();
  const eDay = end.getDate();
  const sYear = start.getFullYear();
  const eYear = end.getFullYear();

  if (sYear !== eYear) {
    return `${sMonth} ${sDay}, ${sYear} – ${eMonth} ${eDay}, ${eYear}`;
  }
  if (sMonth === eMonth) {
    return `${sMonth} ${sDay} – ${eDay}, ${sYear}`;
  }
  return `${sMonth} ${sDay} – ${eMonth} ${eDay}, ${sYear}`;
}

function pluralize(count: number, singular: string): string {
  return count === 1 ? `${count} ${singular}` : `${count} ${singular}s`;
}

function formatTravelers(adults: number | null | undefined, children: number | null | undefined): string {
  const a = typeof adults === 'number' ? adults : 0;
  const c = typeof children === 'number' ? children : 0;
  // Default to 1 adult when travelers not specified — matches UI default
  if (a === 0 && c === 0) return '1 adult';

  const parts: string[] = [];
  if (a > 0) parts.push(pluralize(a, 'adult'));
  if (c > 0) parts.push(c === 1 ? '1 child' : `${c} children`);
  return parts.join(', ');
}

function formatBudget(budget: number | null | undefined, currency: string | null | undefined): string | null {
  if (budget == null || budget <= 0) return null;
  const formatted = budget.toLocaleString('en-US');
  if (!currency || currency === 'USD') return `$${formatted}`;
  return `${formatted} ${currency}`;
}

function formatBlockPrice(block: { booked_tile?: { price_estimate?: number }; price_estimate?: number; price_level?: number }): string | null {
  // Priority: booked tile estimate → block estimate → price level symbol
  const estimate = block.booked_tile?.price_estimate ?? block.price_estimate;
  if (estimate != null && estimate > 0) return `~$${Math.round(estimate)}`;
  if (block.price_level != null && block.price_level in PRICE_LEVEL_MAP) return PRICE_LEVEL_MAP[block.price_level];
  return null;
}

/** Clean duration: "4.0h" → "4h" */
function cleanDuration(d: string | null): string | null {
  if (!d) return null;
  return d.replace(/\.0h$/, 'h');
}

/** Build a "~$120 / 4h" style meta string from price + duration. */
function buildMetaString(priceDisplay: string | null, duration: string | null): string | null {
  const parts = [priceDisplay, cleanDuration(duration)].filter(Boolean);
  return parts.length > 0 ? parts.join(' / ') : null;
}

/** Strip "Day N" prefix from a label to avoid "Day 2: Day 2" in the PDF. */
function extractDayDescription(label: string | undefined, dayNumber: number): string {
  if (!label) return '';
  const dayPrefix = new RegExp(`^Day\\s+${dayNumber}\\b\\s*[-–:]?\\s*`, 'i');
  return label.replace(dayPrefix, '').trim();
}

/** Extract human-readable constraint notes from a block. */
function extractConstraintNotes(block: DayCard['blocks'][number]): string[] {
  const notes: string[] = [];

  // buffer_reason is the richest constraint text (e.g., "PADI Standard - 24h surface interval")
  if (block.buffer_reason) {
    notes.push(block.buffer_reason);
  }

  // active_constraints carry structured safety intelligence
  if (Array.isArray(block.active_constraints)) {
    for (const c of block.active_constraints) {
      // Show "title: description" when both exist, otherwise just whichever is available
      const text = c.title && c.description
        ? `${c.title}: ${c.description}`
        : c.title || c.description;
      if (text && !notes.includes(text)) notes.push(text);
    }
  }

  return notes;
}

// ---------------------------------------------------------------------------
// Main extraction
// ---------------------------------------------------------------------------

export function extractTripPdfData(
  tripInputs: DocumentTripInputs | undefined,
  dayCards: DayCard[],
  tiles: Record<string, Tile>,
): TripPdfData {
  // Hotel links — same filter as BookingSummary
  const hotelLinks: PdfHotelLink[] = Object.values(tiles)
    .filter(
      (t) =>
        (t.type === 'hotel' || t.type === 'accommodation' || t.type === 'stay') &&
        t.deeplink_url &&
        t.deeplink_url !== '#' &&
        t.deeplink_url !== '',
    )
    .map((t) => ({
      title: t.title,
      url: t.deeplink_url,
      pricePerNight:
        t.price_estimate != null && t.price_estimate > 0
          ? `~$${Math.round(t.price_estimate)}/night`
          : null,
    }));

  // Activity links from day card blocks — with price/duration metadata, deduplicated by name
  const seen = new Set<string>();
  const activityLinks: PdfActivityLink[] = dayCards
    .flatMap((dc) => dc.blocks)
    .filter((b) => b.deeplink && b.deeplink !== '' && !b.is_buffer && !b.is_skeleton)
    .filter((b) => {
      const key = b.summary || b.activity_type || 'Activity';
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    })
    .map((b) => ({
      name: b.summary || b.activity_type || 'Activity',
      url: b.deeplink!,
      meta: buildMetaString(
        formatBlockPrice(b),
        b.duration ?? null,
      ),
    }));

  // Day sections
  const days: PdfDaySection[] = dayCards.map((dc) => ({
    dayNumber: dc.day_number,
    date: formatShortDate(dc.date),
    label: extractDayDescription(dc.label, dc.day_number),
    blocks: dc.blocks.map((b) => ({
      period: b.period,
      summary: b.summary,
      duration: cleanDuration(b.duration ?? null),
      priceDisplay: formatBlockPrice(b),
      isBuffer: b.is_buffer ?? false,
      bufferReason: b.buffer_reason ?? null,
      bufferType: b.buffer_type ?? null,
      constraintNotes: extractConstraintNotes(b),
      specialistType: formatSpecialistType(b.specialist_type),
      hotelName: b.hotel_name ?? null,
      logisticsDetails: b.logistics_details ?? null,
      intensity: b.intensity ?? null,
    })),
    intensity: deriveDayIntensity(dc.blocks),
  }));

  return {
    destination: tripInputs?.destination ?? 'Destination TBD',
    dates: formatDateRange(tripInputs?.start_date, tripInputs?.end_date),
    travelers: formatTravelers(tripInputs?.adults, tripInputs?.children),
    budget: formatBudget(tripInputs?.budget, tripInputs?.currency),
    days,
    hotelLinks,
    activityLinks,
  };
}
