import type { StrategySection } from '@/types/plan-envelope';

type RawConstraint = NonNullable<StrategySection['constraints_applied']>[number] & Record<string, unknown>;

export type IntelCategoryKey =
  | 'visa'
  | 'transport'
  | 'money'
  | 'safety'
  | 'booking'
  | 'culture'
  | 'connectivity'
  | 'language'
  | 'weather'
  | 'good_to_know';

export interface IntelCategory {
  key: IntelCategoryKey;
  label: string;
  shortLabel: string;
  icon: string;
  items: string[];
}

export interface TripAlert {
  id: string;
  type: string;
  severity: 'blocking' | 'strong';
  icon: string;
  title: string;
  description: string;
}

const TRIP_ALERT_TYPES = new Set([
  'visa',
  'health',
  'safety',
  'weather_blocking',
  'insurance',
  'legal',
]);

// TODO: replace with country_code from destination_card when available
// This hardcoded map violates CLAUDE.md rule #11 (no hard-coded world data).
// Once backend DestinationCard includes country_code, use countryCodeToFlag() instead.
const DESTINATION_FLAG_MAP: Record<string, string> = {
  italy: '\u{1F1EE}\u{1F1F9}',
  rome: '\u{1F1EE}\u{1F1F9}',
  milan: '\u{1F1EE}\u{1F1F9}',
  venice: '\u{1F1EE}\u{1F1F9}',
  france: '\u{1F1EB}\u{1F1F7}',
  paris: '\u{1F1EB}\u{1F1F7}',
  spain: '\u{1F1EA}\u{1F1F8}',
  madrid: '\u{1F1EA}\u{1F1F8}',
  barcelona: '\u{1F1EA}\u{1F1F8}',
  portugal: '\u{1F1F5}\u{1F1F9}',
  lisbon: '\u{1F1F5}\u{1F1F9}',
  greece: '\u{1F1EC}\u{1F1F7}',
  athens: '\u{1F1EC}\u{1F1F7}',
  turkey: '\u{1F1F9}\u{1F1F7}',
  istanbul: '\u{1F1F9}\u{1F1F7}',
  japan: '\u{1F1EF}\u{1F1F5}',
  tokyo: '\u{1F1EF}\u{1F1F5}',
  kyoto: '\u{1F1EF}\u{1F1F5}',
  thailand: '\u{1F1F9}\u{1F1ED}',
  bangkok: '\u{1F1F9}\u{1F1ED}',
  phuket: '\u{1F1F9}\u{1F1ED}',
  indonesia: '\u{1F1EE}\u{1F1E9}',
  bali: '\u{1F1EE}\u{1F1E9}',
  singapore: '\u{1F1F8}\u{1F1EC}',
  vietnam: '\u{1F1FB}\u{1F1F3}',
  hanoi: '\u{1F1FB}\u{1F1F3}',
  saigon: '\u{1F1FB}\u{1F1F3}',
  australia: '\u{1F1E6}\u{1F1FA}',
  sydney: '\u{1F1E6}\u{1F1FA}',
  melbourne: '\u{1F1E6}\u{1F1FA}',
  uk: '\u{1F1EC}\u{1F1E7}',
  'united kingdom': '\u{1F1EC}\u{1F1E7}',
  london: '\u{1F1EC}\u{1F1E7}',
  ireland: '\u{1F1EE}\u{1F1EA}',
  dublin: '\u{1F1EE}\u{1F1EA}',
  germany: '\u{1F1E9}\u{1F1EA}',
  berlin: '\u{1F1E9}\u{1F1EA}',
  munich: '\u{1F1E9}\u{1F1EA}',
  netherlands: '\u{1F1F3}\u{1F1F1}',
  amsterdam: '\u{1F1F3}\u{1F1F1}',
  switzerland: '\u{1F1E8}\u{1F1ED}',
  zurich: '\u{1F1E8}\u{1F1ED}',
  austria: '\u{1F1E6}\u{1F1F9}',
  vienna: '\u{1F1E6}\u{1F1F9}',
  usa: '\u{1F1FA}\u{1F1F8}',
  us: '\u{1F1FA}\u{1F1F8}',
  'united states': '\u{1F1FA}\u{1F1F8}',
  canada: '\u{1F1E8}\u{1F1E6}',
  mexico: '\u{1F1F2}\u{1F1FD}',
  brazil: '\u{1F1E7}\u{1F1F7}',
  argentina: '\u{1F1E6}\u{1F1F7}',
  peru: '\u{1F1F5}\u{1F1EA}',
  colombia: '\u{1F1E8}\u{1F1F4}',
  morocco: '\u{1F1F2}\u{1F1E6}',
  egypt: '\u{1F1EA}\u{1F1EC}',
  uae: '\u{1F1E6}\u{1F1EA}',
  dubai: '\u{1F1E6}\u{1F1EA}',
  india: '\u{1F1EE}\u{1F1F3}',
  delhi: '\u{1F1EE}\u{1F1F3}',
  mumbai: '\u{1F1EE}\u{1F1F3}',
  south_korea: '\u{1F1F0}\u{1F1F7}',
  seoul: '\u{1F1F0}\u{1F1F7}',
};

const INTEL_CATEGORIES: Array<Pick<IntelCategory, 'key' | 'label' | 'shortLabel' | 'icon'>> = [
  { key: 'visa', label: 'Visa', shortLabel: 'Visa', icon: '🛂' },
  { key: 'transport', label: 'Getting Around', shortLabel: 'Transport', icon: '🚇' },
  { key: 'money', label: 'Money & Tipping', shortLabel: 'Money', icon: '💶' },
  { key: 'safety', label: 'Safety', shortLabel: 'Safety', icon: '🔒' },
  { key: 'booking', label: 'Booking', shortLabel: 'Booking', icon: '🎟️' },
  { key: 'culture', label: 'Culture & Etiquette', shortLabel: 'Culture', icon: '🏛️' },
  { key: 'connectivity', label: 'Connectivity', shortLabel: 'Connectivity', icon: '📱' },
  { key: 'language', label: 'Language', shortLabel: 'Language', icon: '🗣️' },
  { key: 'weather', label: 'Weather', shortLabel: 'Weather', icon: '🌦️' },
  { key: 'good_to_know', label: 'Good to Know', shortLabel: 'Good to Know', icon: 'ℹ️' },
];

function normalizeToken(value: unknown): string {
  if (typeof value !== 'string') return '';
  return value.trim().toLowerCase().replace(/[\s-]+/g, '_');
}

function normalizeText(value: string): string {
  return value.trim().toLowerCase().replace(/\s+/g, ' ');
}

function normalizeForDedup(value: string): string {
  return normalizeText(value).replace(/[^\p{L}\p{N}\s]/gu, '');
}

function cleanText(value: unknown): string {
  if (typeof value !== 'string') return '';
  return value.replace(/\s+/g, ' ').trim();
}

function looksLikeVisaText(text: string): boolean {
  const normalized = normalizeText(text);
  if (!normalized) return false;

  if (
    /\b(visa|schengen|immigration|e-?visa|visa on arrival|voa|passport control|border control|eta|esta)\b/.test(
      normalized
    )
  ) {
    return true;
  }

  if (/\b(stay limit|max stay|overstay|entry requirement|entry permit)\b/.test(normalized)) {
    return true;
  }

  if (/\bpassport\b/.test(normalized)) {
    return /\b(entry|border|immigration|arrival|departure|control|stamp|stamped|validity)\b/.test(
      normalized
    );
  }

  if (/\bpermit\b/.test(normalized)) {
    return /\b(entry|immigration|stay|residence|travel)\b/.test(normalized);
  }

  return false;
}

function looksLikeSafetyText(text: string): boolean {
  const normalized = normalizeText(text);
  if (!normalized) return false;
  return /\b(pickpocket|pickpockets|crime|unsafe|safe|safety|scam|scams|danger|risk|risky|theft|fraud|assault|harassment|emergency|police)\b/.test(
    normalized
  );
}

function looksLikeMoneyText(text: string): boolean {
  const normalized = normalizeText(text);
  if (!normalized) return false;
  return /\b(tip|tipping|currency|money|cash|card|pay|coperto|euro|\$|vat|tax[-\s]?free|refund|duty[-\s]?free)\b/.test(
    normalized
  );
}

function looksLikeBusinessHoursText(text: string): boolean {
  const normalized = normalizeText(text);
  if (!normalized) return false;
  if (/\b(siesta|opening hours|business hours)\b/.test(normalized)) return true;
  return (
    /\b(shop|shops|store|stores|restaurant|restaurants|market|markets|museum|museums|attraction|attractions)\b/.test(
      normalized
    )
    && /\b(open|opening|close|closed|closing|hours|hour)\b/.test(normalized)
  );
}

function constraintText(constraint: RawConstraint): string {
  const reason = cleanText(constraint.reason);
  const rule = cleanText(constraint.rule);
  return reason || rule;
}

function constraintDetails(constraint: RawConstraint): string {
  const reason = cleanText(constraint.reason);
  const rule = cleanText(constraint.rule);
  if (!reason && !rule) return '';
  if (!reason) return rule;
  if (!rule || normalizeText(reason) === normalizeText(rule)) return reason;
  return `${reason}. ${rule}`;
}

function inferConstraintType(constraint: RawConstraint): string {
  const rawType = normalizeToken(constraint.type);
  if (rawType) {
    if (rawType === 'weather') return 'weather';
    if (rawType === 'transportation') return 'transport';
    if (rawType === 'money_costs') return 'money';
    if (rawType === 'cultural_norms') return 'culture';
    if (rawType === 'booking') return 'booking';
    return rawType;
  }

  const text = `${cleanText(constraint.reason)} ${cleanText(constraint.rule)}`.toLowerCase();
  if (/(book|booking|reserve|reservation|ticket|timed entry|sold out|availability|advance)/.test(text)) {
    return 'booking';
  }
  if (looksLikeVisaText(text)) return 'visa';
  if (/(health|vaccine|hospital|medical|disease)/.test(text)) return 'health';
  if (looksLikeSafetyText(text)) return 'safety';
  if (/(storm|hurricane|monsoon|weather|heatwave|flood|snow)/.test(text)) return 'weather';
  if (/(insurance|coverage)/.test(text)) return 'insurance';
  if (/(illegal|law|legal|prohibited|permit)/.test(text)) return 'legal';
  if (/(book|reservation|timed entry|sold out|availability|advance ticket)/.test(text)) {
    return 'booking_window';
  }
  if (/(metro|bus|taxi|train|transport|transit)/.test(text)) return 'transport';
  return 'unknown';
}

function inferConstraintSeverity(constraint: RawConstraint): string {
  const raw = normalizeToken(constraint.severity);
  if (raw) return raw;

  const text = `${cleanText(constraint.reason)} ${cleanText(constraint.rule)}`.toLowerCase();
  if (/(mandatory|required|must|prohibited|illegal|danger|critical|unsafe)/.test(text)) return 'strong';
  return 'soft';
}

export function isTripAlertConstraint(constraint: RawConstraint): boolean {
  const severity = inferConstraintSeverity(constraint);
  if (severity !== 'blocking' && severity !== 'strong') return false;
  const type = inferConstraintType(constraint);
  if (type === 'safety' && !looksLikeSafetyText(constraintDetails(constraint))) return false;
  return TRIP_ALERT_TYPES.has(type);
}

function constraintId(constraint: RawConstraint): string {
  const type = inferConstraintType(constraint);
  const core = constraintText(constraint) || cleanText(constraint.rule) || cleanText(constraint.reason);
  return `${type}:${normalizeText(core || 'unknown')}`;
}

export function extractTripAlerts(sections: StrategySection[] | undefined): TripAlert[] {
  if (!sections || sections.length === 0) return [];

  const alerts: TripAlert[] = [];
  const seen = new Set<string>();

  for (const section of sections) {
    for (const raw of section.constraints_applied ?? []) {
      const constraint = raw as RawConstraint;
      if (!isTripAlertConstraint(constraint)) continue;
      const id = constraintId(constraint);
      if (seen.has(id)) continue;
      seen.add(id);

      const severity = inferConstraintSeverity(constraint) as 'blocking' | 'strong';
      const type = inferConstraintType(constraint);
      const title = constraintText(constraint) || 'Trip advisory';
      const description = constraintDetails(constraint) || title;

      alerts.push({
        id,
        type,
        severity,
        icon: severity === 'blocking' ? '🔴' : '⚠️',
        title,
        description,
      });
    }
  }

  return alerts.sort((a, b) => {
    if (a.severity === b.severity) return a.title.localeCompare(b.title);
    return a.severity === 'blocking' ? -1 : 1;
  });
}

function classifyTextToCategory(text: string): IntelCategoryKey | null {
  const normalized = normalizeText(text);
  if (!normalized) return null;
  if (/(book|booking|reserve|reservation|ticket|sold out|availability|ahead|timed entry)/.test(normalized)) {
    return 'booking';
  }
  if (looksLikeVisaText(normalized)) return 'visa';
  if (/(metro|bus|taxi|train|transport|transit|drive|traffic)/.test(normalized)) return 'transport';
  if (looksLikeMoneyText(normalized)) return 'money';
  if (looksLikeBusinessHoursText(normalized)) return 'culture';
  if (looksLikeSafetyText(normalized)) return 'safety';
  if (/(culture|custom|dress|etiquette|respect|temple|church|religious)/.test(normalized)) return 'culture';
  if (/(sim|esim|wifi|internet|connectivity|cell|data|app)/.test(normalized)) return 'connectivity';
  if (/(language|speak|english|phrase|translation)/.test(normalized)) return 'language';
  if (/(weather|rain|season|summer|winter|temperature|monsoon|storm)/.test(normalized)) return 'weather';
  return null;
}

function classifyConstraintToIntelCategory(constraint: RawConstraint): IntelCategoryKey | null {
  const type = inferConstraintType(constraint);
  const severity = inferConstraintSeverity(constraint);
  const details = constraintDetails(constraint);

  if (type === 'visa') {
    if (looksLikeVisaText(details)) return 'visa';
    return classifyTextToCategory(details);
  }
  if (type === 'transport') return 'transport';
  if (type === 'money') return 'money';
  if (type === 'booking') return 'booking';
  if (type === 'safety' && severity !== 'blocking' && severity !== 'strong') {
    const fallback = classifyTextToCategory(details);
    if (fallback && fallback !== 'safety') return fallback;
    if (looksLikeSafetyText(details)) return 'safety';
    return fallback;
  }
  if (type === 'booking_window' || type === 'availability') return 'booking';
  if (type === 'weather' && (severity === 'soft' || severity === 'warning' || severity === 'info')) {
    return 'weather';
  }

  const fallback = classifyTextToCategory(details);
  return fallback;
}

function addUnique(
  target: Map<IntelCategoryKey, string[]>,
  key: IntelCategoryKey,
  value: string,
  globalSeen?: Set<string>
): void {
  const text = cleanText(value);
  if (!text) return;
  const needle = normalizeForDedup(text);

  if (globalSeen) {
    if (globalSeen.has(needle)) return;
    globalSeen.add(needle);
  }

  const existing = target.get(key) ?? [];
  if (!existing.some(item => normalizeForDedup(item) === needle)) {
    existing.push(text);
    target.set(key, existing);
  }
}

function gatherTipCount(sections: StrategySection[] | undefined): number {
  if (!sections || sections.length === 0) return 0;
  const unique = new Set<string>();

  for (const section of sections) {
    for (const principle of section.principles ?? []) {
      const text = cleanText(principle);
      if (text) unique.add(normalizeText(text));
    }
    for (const item of section.content_added ?? []) {
      const line = cleanText(item.description || item.title || '');
      if (line) unique.add(normalizeText(line));
    }
  }

  return unique.size;
}

export function buildDestinationIntel(
  sections: StrategySection[] | undefined
): { categories: IntelCategory[]; tipCount: number; summaryLabels: string[] } {
  if (!sections || sections.length === 0) {
    return { categories: [], tipCount: 0, summaryLabels: [] };
  }

  const bucket = new Map<IntelCategoryKey, string[]>();
  const globalSeen = new Set<string>();
  const seenConstraintRules = new Set<string>();

  for (const section of sections) {
    if ((section.specialist_type || '') === 'general') continue;

    for (const raw of section.constraints_applied ?? []) {
      const constraint = raw as RawConstraint;
      if (isTripAlertConstraint(constraint)) continue;
      const dedupeRule = normalizeForDedup(cleanText(constraint.rule || constraint.reason || ''));
      if (dedupeRule && seenConstraintRules.has(dedupeRule)) continue;
      if (dedupeRule) seenConstraintRules.add(dedupeRule);
      const key = classifyConstraintToIntelCategory(constraint) ?? 'good_to_know';
      addUnique(bucket, key, constraintText(constraint), globalSeen);
    }

    for (const principle of section.principles ?? []) {
      const key = classifyTextToCategory(principle) ?? 'good_to_know';
      addUnique(bucket, key, principle, globalSeen);
    }

    for (const content of section.content_added ?? []) {
      const summary = cleanText(content.description || content.title || '');
      if (!summary) continue;

      const byType = classifyTextToCategory(cleanText(content.type || ''));
      const byText = classifyTextToCategory(`${cleanText(content.title)} ${summary} ${cleanText(content.logic_hook)}`);
      const key = byType || byText || 'good_to_know';
      addUnique(bucket, key, summary, globalSeen);
    }
  }

  const populated = INTEL_CATEGORIES.map((meta) => ({
    ...meta,
    items: bucket.get(meta.key) ?? [],
  })).filter(category => category.items.length > 0);

  if (populated.length === 0) {
    return { categories: [], tipCount: 0, summaryLabels: [] };
  }

  const visibleCategories: IntelCategory[] = [];
  for (const category of populated) {
    if (visibleCategories.length >= 6) break;
    if (category.key === 'good_to_know') continue;
    visibleCategories.push(category);
  }
  if (visibleCategories.length < 6) {
    const catchAll = populated.find(category => category.key === 'good_to_know');
    if (catchAll) visibleCategories.push(catchAll);
  }

  const visibleTipCount = visibleCategories.reduce((acc, c) => acc + c.items.length, 0);
  const tipCount = visibleTipCount || globalSeen.size || gatherTipCount(sections);
  const summaryLabels = visibleCategories.slice(0, 4).map(c => c.shortLabel);

  return { categories: visibleCategories, tipCount, summaryLabels };
}

/**
 * Convert an ISO 3166-1 alpha-2 country code to its flag emoji.
 * Each letter is offset into the Regional Indicator Symbol range (U+1F1E6..U+1F1FF).
 *
 * Ready for use once backend DestinationCard includes `country_code`.
 */
export function countryCodeToFlag(cc: string): string {
  const upper = cc.toUpperCase();
  if (upper.length !== 2) return '\u{1F30D}';
  return String.fromCodePoint(
    ...[...upper].map(c => 0x1F1E6 + c.charCodeAt(0) - 65)
  );
}

/**
 * Resolve a flag emoji for a destination.
 *
 * Accepts an optional ISO country code (preferred path once backend provides it).
 * Falls back to the legacy DESTINATION_FLAG_MAP lookup by city/country name.
 */
export function destinationFlag(
  destination: string | null | undefined,
  countryCode?: string | null,
): string {
  // Preferred: use country_code when available
  if (countryCode) return countryCodeToFlag(countryCode);

  if (!destination) return '\u{1F30D}';

  const raw = destination.toLowerCase().trim();
  const commaParts = raw.split(',');
  const candidates = [
    raw,
    raw.replace(/\./g, ''),
    commaParts[0]?.trim() ?? '',
    commaParts[1]?.trim() ?? '',
    raw.replace(/\s+/g, '_'),
  ].filter(Boolean);

  for (const key of candidates) {
    if (DESTINATION_FLAG_MAP[key]) return DESTINATION_FLAG_MAP[key];
  }

  return '\u{1F30D}';
}
