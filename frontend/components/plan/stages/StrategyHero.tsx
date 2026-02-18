// TODO: DS spacing audit — requires visual QA pass
/* eslint no-unused-vars: ["error", { "args": "none" }] */
/**
 * StrategyHero
 *
 * Magazine-style strategy card with two variants:
 * - `hero`: Full-width image with editorial typography (Bridge Mode)
 * - `compact`: Trip DNA Bar - single row summary (Full Mode)
 *
 * Compact mode is self-contained: clicking opens a BottomSheet with full details.
 *
 * @see docs/ux_unified_architecture.md Section XII
 */

'use client';

import {
  AlertCircle,
  Bike,
  Binoculars,
  Building,
  Calendar,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Clock,
  Info,
  MapPin,
  Mountain,
  Sailboat,
  Snowflake,
  Sparkles,
  Users,
  Waves,
} from 'lucide-react';
import Image from 'next/image';
import React, { useId, useMemo, useState } from 'react';

import { BottomSheet } from '@/components/ui/bottom-sheet';
import { DS } from '@/lib/design-system';
import { getSpecialistConfig } from '@/lib/specialists';
import { cn } from '@/lib/utils';
import type { StrategySection, TravelIntelligence } from '@/types/plan-envelope';

// Lucide icon mapping from registry string names to components
const ICON_MAP: Record<string, React.ComponentType<{ className?: string }>> = {
  Waves, Mountain, Snowflake, Bike, Sailboat, Binoculars, Building, Sparkles,
};

function getTopicIcon(specialistType: string): React.ComponentType<{ className?: string }> {
  const config = getSpecialistConfig(specialistType);
  if (config) return ICON_MAP[config.icon] || Sparkles;
  if (specialistType === 'local_expert') return Building;
  return Sparkles;
}

function renderTopicIcon(specialistType: string, className?: string) {
  const Icon = getTopicIcon(specialistType);
  return <Icon className={className} />;
}

function getTopicLabel(specialistType: string): string {
  const config = getSpecialistConfig(specialistType);
  if (config) return config.displayName;
  if (specialistType === 'local_expert') return 'Local Expert';
  if (specialistType === 'general') return 'General';
  return specialistType;
}

// Generic fallback image (specialist-specific hero images come from backend hero_image field)
const GENERIC_FALLBACK_IMAGE =
  'https://images.unsplash.com/photo-1469854523086-cc02fe5d8800?q=80&w=2021&auto=format&fit=crop';

// Accordion icon Tailwind classes keyed by specialist type (component-local UI)
const SPECIALIST_STYLE_CLASSES: Record<string, { light: string; icon: string }> = {
  diving: { light: 'bg-blue-50', icon: 'text-blue-600 dark:text-blue-400' },
  hiking: { light: 'bg-emerald-50', icon: 'text-emerald-600 dark:text-emerald-400' },
  skiing: { light: 'bg-blue-50', icon: 'text-blue-600 dark:text-blue-400' },
  sailing: { light: 'bg-cyan-50', icon: 'text-cyan-600 dark:text-cyan-400' },
  boating: { light: 'bg-cyan-50', icon: 'text-cyan-600 dark:text-cyan-400' },
  cycling: { light: 'bg-lime-50', icon: 'text-lime-600 dark:text-lime-400' },
  surfing: { light: 'bg-indigo-50', icon: 'text-indigo-600 dark:text-indigo-400' },
  climbing: { light: 'bg-orange-50', icon: 'text-orange-600 dark:text-orange-400' },
  wildlife_safari: { light: 'bg-amber-50', icon: 'text-amber-600 dark:text-amber-400' },
  local_expert: { light: 'bg-purple-50', icon: 'text-purple-600 dark:text-purple-400' },
  general: { light: 'bg-emerald-50', icon: 'text-emerald-600 dark:text-emerald-400' },
};
const DEFAULT_STYLE = { light: 'bg-zinc-50', icon: 'text-zinc-600 dark:text-zinc-400' };

/**
 * Get summary badge text showing content counts
 */
function getSummaryBadge(section: StrategySection): string {
  const tipCount = (section.principles?.length || 0) + (section.content_added?.length || 0);
  // Only count blocking/strong constraints (not soft/info)
  const constraintCount = (section.constraints_applied || []).filter(c => {
    const sev = (c as Record<string, string>).severity;
    return !sev || sev === 'blocking' || sev === 'strong';
  }).length;
  const parts: string[] = [];
  if (tipCount > 0) parts.push(`${tipCount} tip${tipCount > 1 ? 's' : ''}`);
  if (constraintCount > 0) parts.push(`${constraintCount} constraint${constraintCount > 1 ? 's' : ''}`);
  return parts.join(' • ') || 'View details';
}

/**
 * Get friendly section label for constraints based on specialist type
 * These are system-inferred rules, not user-set constraints
 */
function getConstraintSectionLabel(specialistType: string): string {
  const labels: Record<string, string> = {
    diving: 'Safety Requirements',
    hiking: 'Trail Safety',
    skiing: 'Mountain Safety',
    sailing: 'Maritime Safety',
    boating: 'Maritime Safety',
    cycling: 'Route Safety',
    surfing: 'Ocean Safety',
    climbing: 'Climbing Safety',
    wildlife_safari: 'Safari Safety',
    local_expert: 'Local Tips',
    general: 'Things to Know',
  };
  return labels[specialistType] || 'Safety & Constraints';
}

/**
 * Get concise badge text for constraint (3-4 words max)
 */
export function getShortConstraintLabel(rule: string): string {
  // Map common full rules to short labels
  const shortLabels: Record<string, string> = {
    'min_24h_buffer_after_dive': 'No-Fly 24h',
    'min_18h_surface_interval': 'Surface Interval',
    'advanced_cert_required_for_deep': 'Adv. Cert Needed',
    'altitude_acclimatization': 'Altitude Adjust',
    'proper_footwear_required': 'Proper Footwear',
    'check_snow_conditions': 'Snow Check',
    'guide_required_offpiste': 'Guide Required',
    'feasibility_caveat': 'Location Advisory',
    'cover_shoulders_and_knees_when_visiting_temples': 'Temple Dress Code',
    'rainy_season': 'Rainy Season',
    'strong_currents': 'Beach Safety',
  };

  // Check for direct match
  const lowerRule = rule.toLowerCase().replace(/ /g, '_');
  if (shortLabels[lowerRule]) {
    return shortLabels[lowerRule];
  }

  // Fallback: take first 3-4 words and capitalize
  const words = rule.replace(/_/g, ' ').split(' ').slice(0, 4);
  return words.map(w => w.charAt(0).toUpperCase() + w.slice(1).toLowerCase()).join(' ');
}

// =============================================================================
// Travel Intelligence Display Component (12-Category Local Expert)
// =============================================================================

interface TravelIntelligencePanelProps {
  intelligence: TravelIntelligence;
}

function TravelIntelligencePanel({ intelligence }: TravelIntelligencePanelProps) {
  const [expandedSection, setExpandedSection] = useState<string | null>(null);

  const toggleSection = (section: string) => {
    setExpandedSection(expandedSection === section ? null : section);
  };

  // Section configuration with icons
  const sections = useMemo(() => [
    { key: 'visa_entry', label: 'Visa & Entry', icon: '🛂', data: intelligence.visa_entry },
    { key: 'safety_health', label: 'Safety & Health', icon: '🏥', data: intelligence.safety_health },
    { key: 'money_costs', label: 'Money & Costs', icon: '💰', data: intelligence.money_costs },
    { key: 'transportation', label: 'Getting Around', icon: '🚕', data: intelligence.transportation },
    { key: 'cultural_norms', label: 'Cultural Norms', icon: '🙏', data: intelligence.cultural_norms },
    { key: 'connectivity', label: 'Connectivity', icon: '📱', data: intelligence.connectivity },
    { key: 'seasonality', label: 'Weather & Seasons', icon: '🌦️', data: intelligence.seasonality },
    { key: 'things_to_do', label: 'Things to Do', icon: '🎯', data: intelligence.things_to_do },
    { key: 'neighborhoods', label: 'Neighborhoods', icon: '🏘️', data: intelligence.neighborhoods },
    { key: 'accommodation', label: 'Where to Stay', icon: '🏨', data: intelligence.accommodation },
    { key: 'scams_traps', label: 'Scams & Traps', icon: '⚠️', data: intelligence.scams_traps },
    { key: 'packing', label: 'Packing Tips', icon: '🎒', data: intelligence.packing },
  ].filter(s => s.data && Object.keys(s.data).some(k => {
    const val = (s.data as Record<string, unknown>)[k];
    return val !== undefined && val !== null && val !== '' &&
           !(Array.isArray(val) && val.length === 0);
  })), [intelligence]);

  if (sections.length === 0) return null;

  return (
    <div className="space-y-2">
      <h4 className={DS.text.label}>Travel Intelligence</h4>
      <div className="space-y-1.5">
        {sections.map(({ key, label, icon, data }) => (
          <div
            key={key}
            className={cn(
              'rounded-lg border overflow-hidden transition-all',
              'bg-white dark:bg-zinc-900 border-zinc-200 dark:border-zinc-700'
            )}
          >
            <button
              type="button"
              onClick={() => toggleSection(key)}
              className={cn(
                'w-full flex items-center justify-between p-3 text-left',
                'hover:bg-zinc-50 dark:hover:bg-zinc-800/50 transition-colors'
              )}
            >
              <div className="flex items-center gap-2">
                <span className="text-base">{icon}</span>
                <span className="text-sm font-medium text-zinc-900 dark:text-white">{label}</span>
              </div>
              <ChevronDown
                className={cn(
                  'w-4 h-4 text-zinc-400 transition-transform duration-200',
                  expandedSection === key && 'rotate-180'
                )}
              />
            </button>

            {expandedSection === key && (
              <div className="px-3 pb-3 pt-0 text-sm text-zinc-600 dark:text-zinc-400 space-y-2 border-t border-zinc-100 dark:border-zinc-800">
                <TravelIntelligenceContent sectionKey={key} data={data} />
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

interface TravelIntelligenceContentProps {
  sectionKey: string;
  data: unknown;
}

function TravelIntelligenceContent({ sectionKey, data }: TravelIntelligenceContentProps) {
  if (!data) return null;

  // Type-safe access helpers
  const d = data as Record<string, unknown>;
  const str = (key: string): string => {
    const v = d[key];
    return typeof v === 'string' ? v : typeof v === 'number' ? String(v) : '';
  };
  const num = (key: string): number | undefined => {
    const v = d[key];
    return typeof v === 'number' ? v : undefined;
  };
  const bool = (key: string): boolean | undefined => {
    const v = d[key];
    return typeof v === 'boolean' ? v : undefined;
  };
  const arr = (key: string): unknown[] => {
    const v = d[key];
    return Array.isArray(v) ? v : [];
  };
  const obj = (key: string): Record<string, unknown> => {
    const v = d[key];
    return typeof v === 'object' && v !== null && !Array.isArray(v) ? v as Record<string, unknown> : {};
  };

  switch (sectionKey) {
    case 'visa_entry':
      return (
        <div className="pt-2 space-y-2">
          {bool('visa_on_arrival') !== undefined && (
            <p className="flex items-center gap-2">
              <span className={bool('visa_on_arrival') ? 'text-emerald-500' : 'text-red-500'}>
                {bool('visa_on_arrival') ? '✓' : '✗'}
              </span>
              Visa on arrival: {bool('visa_on_arrival') ? 'Yes' : 'No'}
            </p>
          )}
          {num('max_stay_days') !== undefined && <p>Max stay: {num('max_stay_days')} days</p>}
          {num('passport_validity_months') !== undefined && <p>Passport validity: {num('passport_validity_months')} months required</p>}
          {arr('key_requirements').length > 0 && (
            <div>
              <p className="font-medium text-zinc-800 dark:text-zinc-200 text-xs uppercase mt-2">Required:</p>
              <ul className="list-disc list-inside space-y-0.5 text-xs">
                {(arr('key_requirements') as string[]).map((r, i) => <li key={i}>{r}</li>)}
              </ul>
            </div>
          )}
          {str('immigration_tip') && (
            <p className="text-xs italic text-emerald-600 dark:text-emerald-400 mt-2">💡 {str('immigration_tip')}</p>
          )}
        </div>
      );

    case 'safety_health':
      return (
        <div className="pt-2 space-y-2">
          {str('overall_safety') && <p><strong>Safety:</strong> {str('overall_safety')}</p>}
          {bool('tap_water_safe') !== undefined && (
            <p className="flex items-center gap-2">
              <span className={bool('tap_water_safe') ? 'text-emerald-500' : 'text-red-500'}>
                {bool('tap_water_safe') ? '✓' : '✗'}
              </span>
              Tap water: {bool('tap_water_safe') ? 'Safe' : 'Not safe - drink bottled'}
            </p>
          )}
          {str('emergency_number') && <p><strong>Emergency:</strong> {str('emergency_number')}</p>}
          {str('nearest_hospital') && <p><strong>Hospital:</strong> {str('nearest_hospital')}</p>}
          {arr('common_concerns').length > 0 && (
            <div>
              <p className="font-medium text-red-600 dark:text-red-400 text-xs uppercase mt-2">⚠️ Watch out for:</p>
              <ul className="list-disc list-inside space-y-0.5 text-xs">
                {(arr('common_concerns') as string[]).map((c, i) => <li key={i}>{c}</li>)}
              </ul>
            </div>
          )}
        </div>
      );

    case 'money_costs': {
      const db = obj('daily_budget');
      const backpacker = typeof db.backpacker === 'string' ? db.backpacker : '';
      const midRange = typeof db.mid_range === 'string' ? db.mid_range : '';
      const luxury = typeof db.luxury === 'string' ? db.luxury : '';
      return (
        <div className="pt-2 space-y-2">
          {str('currency') && <p><strong>Currency:</strong> {str('currency')}</p>}
          {str('exchange_tip') && <p className="text-xs">{str('exchange_tip')}</p>}
          {(backpacker || midRange || luxury) && (
            <div className="grid grid-cols-3 gap-2 mt-2">
              {backpacker && (
                <div className="text-center p-2 rounded bg-zinc-50 dark:bg-zinc-800">
                  <p className={`${DS.textSize.micro} uppercase text-zinc-500`}>Budget</p>
                  <p className="font-medium">{backpacker}</p>
                </div>
              )}
              {midRange && (
                <div className="text-center p-2 rounded bg-zinc-50 dark:bg-zinc-800">
                  <p className={`${DS.textSize.micro} uppercase text-zinc-500`}>Mid</p>
                  <p className="font-medium">{midRange}</p>
                </div>
              )}
              {luxury && (
                <div className="text-center p-2 rounded bg-zinc-50 dark:bg-zinc-800">
                  <p className={`${DS.textSize.micro} uppercase text-zinc-500`}>Luxury</p>
                  <p className="font-medium">{luxury}</p>
                </div>
              )}
            </div>
          )}
          {str('haggling') && <p className="text-xs mt-2"><strong>Haggling:</strong> {str('haggling')}</p>}
        </div>
      );
    }

    case 'transportation': {
      const atc = arr('airport_to_city') as Array<{method: string; price?: string; time?: string; tip?: string}>;
      const rideApps = arr('ride_apps') as string[];
      return (
        <div className="pt-2 space-y-2">
          {atc.length > 0 && (
            <div>
              <p className="font-medium text-xs uppercase mb-1">Airport → City</p>
              <div className="space-y-1">
                {atc.map((t, i) => (
                  <div key={i} className="text-xs flex items-center gap-2">
                    <span className="font-medium">{t.method}:</span>
                    {t.price && <span>{t.price}</span>}
                    {t.time && <span className="text-zinc-500">({t.time})</span>}
                  </div>
                ))}
              </div>
            </div>
          )}
          {rideApps.length > 0 && (
            <p><strong>Ride apps:</strong> {rideApps.join(', ')}</p>
          )}
          {str('traffic_note') && <p className="text-xs italic">{str('traffic_note')}</p>}
        </div>
      );
    }

    case 'cultural_norms': {
      const dc = obj('dress_code');
      const taboos = arr('important_taboos') as string[];
      const temples = typeof dc.temples === 'string' ? dc.temples : '';
      const restaurants = typeof dc.restaurants === 'string' ? dc.restaurants : '';
      return (
        <div className="pt-2 space-y-2">
          {(temples || restaurants) && (
            <div>
              <p className="font-medium text-xs uppercase mb-1">Dress Code</p>
              {temples && (
                <p className="text-xs"><strong>Temples:</strong> {temples}</p>
              )}
              {restaurants && (
                <p className="text-xs"><strong>Restaurants:</strong> {restaurants}</p>
              )}
            </div>
          )}
          {str('greetings') && <p><strong>Greeting:</strong> {str('greetings')}</p>}
          {str('lgbtq_friendly') && <p><strong>LGBTQ+:</strong> {str('lgbtq_friendly')}</p>}
          {taboos.length > 0 && (
            <div>
              <p className="font-medium text-red-600 dark:text-red-400 text-xs uppercase mt-2">🚫 Never do:</p>
              <ul className="list-disc list-inside space-y-0.5 text-xs">
                {taboos.map((t, i) => <li key={i}>{t}</li>)}
              </ul>
            </div>
          )}
        </div>
      );
    }

    case 'connectivity': {
      const apps = arr('essential_apps') as string[];
      return (
        <div className="pt-2 space-y-2">
          {str('best_sim_provider') && <p><strong>Best SIM:</strong> {str('best_sim_provider')}</p>}
          {str('sim_cost') && <p><strong>Cost:</strong> {str('sim_cost')}</p>}
          {str('where_to_buy') && <p><strong>Buy at:</strong> {str('where_to_buy')}</p>}
          {bool('esim_works') !== undefined && (
            <p>eSIM: {bool('esim_works') ? '✓ Works' : '✗ Not supported'}</p>
          )}
          {apps.length > 0 && (
            <div>
              <p className="font-medium text-xs uppercase mt-2">Essential Apps:</p>
              <p className="text-xs">{apps.join(', ')}</p>
            </div>
          )}
        </div>
      );
    }

    case 'seasonality': {
      const bestMonths = arr('best_months') as string[];
      const festivals = arr('major_festivals') as Array<{name: string; when?: string; impact?: string}>;
      return (
        <div className="pt-2 space-y-2">
          {bestMonths.length > 0 && (
            <p><strong>Best time:</strong> {bestMonths.join(', ')}</p>
          )}
          {str('high_season') && <p><strong>High season:</strong> {str('high_season')}</p>}
          {str('rainy_season') && <p><strong>Rainy season:</strong> {str('rainy_season')}</p>}
          {festivals.length > 0 && (
            <div>
              <p className="font-medium text-xs uppercase mt-2">🎉 Festivals:</p>
              {festivals.map((f, i) => (
                <div key={i} className="text-xs mt-1">
                  <strong>{f.name}</strong> {f.when && `(${f.when})`}
                  {f.impact && <p className="text-zinc-500">{f.impact}</p>}
                </div>
              ))}
            </div>
          )}
          {str('current_season_tip') && (
            <p className="text-xs italic text-emerald-600 dark:text-emerald-400 mt-2">💡 {str('current_season_tip')}</p>
          )}
        </div>
      );
    }

    case 'things_to_do': {
      const mustDo = arr('must_do') as Array<{name: string; why?: string; booking?: string; cost?: string}>;
      const skipThese = arr('skip_these') as string[];
      return (
        <div className="pt-2 space-y-2">
          {mustDo.length > 0 && (
            <div>
              <p className="font-medium text-xs uppercase mb-1">🎯 Must Do</p>
              <div className="space-y-2">
                {mustDo.slice(0, 5).map((item, i) => (
                  <div key={i} className="text-xs p-2 rounded bg-zinc-50 dark:bg-zinc-800">
                    <p className="font-medium text-zinc-900 dark:text-white">{item.name}</p>
                    {item.why && <p className="text-zinc-500 mt-0.5">{item.why}</p>}
                    <div className={`flex gap-2 mt-1 ${DS.textSize.micro}`}>
                      {item.cost && <span className="text-emerald-600">{item.cost}</span>}
                      {item.booking && <span className="text-zinc-500 dark:text-zinc-400">{item.booking}</span>}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
          {skipThese.length > 0 && (
            <div>
              <p className="font-medium text-red-600 dark:text-red-400 text-xs uppercase mt-2">❌ Skip These</p>
              <ul className="list-disc list-inside space-y-0.5 text-xs">
                {skipThese.map((s, i) => <li key={i}>{s}</li>)}
              </ul>
            </div>
          )}
        </div>
      );
    }

    case 'neighborhoods': {
      const whereToStay = arr('where_to_stay') as Array<{name: string; vibe?: string; best_for?: string[]; price_range?: string}>;
      const avoidStaying = arr('avoid_staying_in') as string[];
      return (
        <div className="pt-2 space-y-2">
          {whereToStay.length > 0 && (
            <div className="space-y-2">
              {whereToStay.map((n, i) => (
                <div key={i} className="text-xs p-2 rounded bg-zinc-50 dark:bg-zinc-800">
                  <p className="font-medium text-zinc-900 dark:text-white">{n.name}</p>
                  {n.vibe && <p className="text-zinc-500 mt-0.5">{n.vibe}</p>}
                  <div className={`flex gap-2 mt-1 ${DS.textSize.micro}`}>
                    {n.price_range && <span className="px-1.5 py-0.5 rounded bg-zinc-200 dark:bg-zinc-700">{n.price_range}</span>}
                    {Array.isArray(n.best_for) && n.best_for.slice(0, 2).map((b, j) => (
                      <span key={j} className="px-1.5 py-0.5 rounded bg-emerald-100 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-400">{b}</span>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          )}
          {avoidStaying.length > 0 && (
            <div>
              <p className="font-medium text-red-600 dark:text-red-400 text-xs uppercase mt-2">⚠️ Avoid:</p>
              <ul className="list-disc list-inside space-y-0.5 text-xs">
                {avoidStaying.map((a, i) => <li key={i}>{a}</li>)}
              </ul>
            </div>
          )}
        </div>
      );
    }

    case 'accommodation': {
      const priceRanges = obj('price_ranges');
      const bookingPlatforms = arr('booking_platforms') as string[];
      const priceItems = Object.entries(priceRanges)
        .filter(([, v]) => typeof v === 'string' && v)
        .map(([k, v]) => ({ key: k, value: String(v) }));
      return (
        <div className="pt-2 space-y-2">
          {priceItems.length > 0 && (
            <div className="grid grid-cols-2 gap-2">
              {priceItems.map(({ key, value }) => (
                <div key={key} className="text-xs p-2 rounded bg-zinc-50 dark:bg-zinc-800">
                  <p className={`${DS.textSize.micro} uppercase text-zinc-500`}>{key.replace('_', ' ')}</p>
                  <p className="font-medium">{value}</p>
                </div>
              ))}
            </div>
          )}
          {bookingPlatforms.length > 0 && (
            <p className="text-xs"><strong>Book on:</strong> {bookingPlatforms.join(', ')}</p>
          )}
          {str('book_ahead') && <p className="text-xs italic text-zinc-600 dark:text-zinc-400">📅 {str('book_ahead')}</p>}
        </div>
      );
    }

    case 'scams_traps': {
      const commonScams = arr('common_scams') as Array<{name: string; how_it_works?: string; how_to_avoid?: string}>;
      return (
        <div className="pt-2 space-y-2">
          {commonScams.length > 0 && (
            <div className="space-y-2">
              {commonScams.map((scam, i) => (
                <div key={i} className="text-xs p-2 rounded bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800">
                  <p className="font-medium text-red-700 dark:text-red-400">⚠️ {scam.name}</p>
                  {scam.how_it_works && <p className="text-red-600/70 dark:text-red-400/70 mt-0.5">{scam.how_it_works}</p>}
                  {scam.how_to_avoid && <p className="text-emerald-600 dark:text-emerald-400 mt-1">✓ {scam.how_to_avoid}</p>}
                </div>
              ))}
            </div>
          )}
          {str('taxi_scam_tip') && (
            <p className="text-xs p-2 rounded bg-zinc-50 dark:bg-zinc-800/50">🚕 {str('taxi_scam_tip')}</p>
          )}
          {str('general_advice') && (
            <p className="text-xs italic text-zinc-500">{str('general_advice')}</p>
          )}
        </div>
      );
    }

    case 'packing': {
      const mustPack = arr('must_pack') as string[];
      const dontBring = arr('dont_bring') as string[];
      const electrical = obj('electrical');
      const plugType = typeof electrical.plug_type === 'string' ? electrical.plug_type : '';
      const voltage = typeof electrical.voltage === 'string' ? electrical.voltage : '';
      const adapterNeeded = typeof electrical.adapter_needed === 'boolean' ? electrical.adapter_needed : false;
      return (
        <div className="pt-2 space-y-2">
          {mustPack.length > 0 && (
            <div>
              <p className="font-medium text-emerald-600 dark:text-emerald-400 text-xs uppercase">✓ Must Pack</p>
              <ul className="list-disc list-inside space-y-0.5 text-xs">
                {mustPack.map((p, i) => <li key={i}>{p}</li>)}
              </ul>
            </div>
          )}
          {dontBring.length > 0 && (
            <div>
              <p className="font-medium text-red-600 dark:text-red-400 text-xs uppercase mt-2">✗ Don&apos;t Bring</p>
              <ul className="list-disc list-inside space-y-0.5 text-xs">
                {dontBring.map((p, i) => <li key={i}>{p}</li>)}
              </ul>
            </div>
          )}
          {plugType && (
            <p className="text-xs mt-2">
              <strong>Electrical:</strong> {plugType}{voltage && `, ${voltage}`}
              {adapterNeeded && ' (adapter needed)'}
            </p>
          )}
        </div>
      );
    }

    default:
      return null;
  }
}

// =============================================================================
// Main Component Props
// =============================================================================

interface StrategyHeroProps {
  section: StrategySection;
  variant: 'hero' | 'compact' | 'accordion';
  /** Default expanded state for accordion variant */
  defaultExpanded?: boolean;
  /** Controlled expanded state (for parent-managed expansion) */
  isExpanded?: boolean;
  /** Callback when accordion expansion changes */
  onExpandChange?: (expanded: boolean) => void;
  /** @deprecated Click handler - compact mode now self-manages expansion */
  onExpand?: () => void;
}

/**
 * Get the best available hero image from section data
 */
function getHeroImage(section: StrategySection): string {
  // Priority 1: Backend-provided hero_image (for niche specialists)
  if (section.hero_image) {
    return section.hero_image;
  }

  // Priority 2: vibe_trio (General specialist - destination-specific images)
  if (section.vibe_trio?.[0]?.image_url) {
    return section.vibe_trio[0].image_url;
  }

  // Priority 3: destination_gallery (Local Expert)
  if (section.destination_gallery?.[0]?.image_url) {
    return section.destination_gallery[0].image_url;
  }

  // Priority 4: First content_added with image
  const contentImage = section.content_added?.find((c) => c.image_url)?.image_url;
  if (contentImage) {
    return contentImage;
  }

  // Priority 5: Generic fallback (specialist images come from backend hero_image field)
  return GENERIC_FALLBACK_IMAGE;
}

/**
 * Get constraint icon based on type
 */
function getConstraintIcon(type: string) {
  if (type === 'safety' || type.includes('safety')) {
    return <AlertCircle className="w-3 h-3 text-amber-400" />;
  }
  if (type === 'temporal' || type.includes('time') || type.includes('buffer')) {
    return <Clock className="w-3 h-3 text-blue-400" />;
  }
  return <Info className="w-3 h-3 text-zinc-400" />;
}

/**
 * Format constraint rule to human-readable text
 */
function formatConstraintRule(rule: string): string {
  return rule
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (l) => l.toUpperCase())
    .replace('Min ', '')
    .replace('Max ', '');
}

export function StrategyHero({
  section,
  variant,
  defaultExpanded = false,
  isExpanded: controlledExpanded,
  onExpandChange,
  onExpand
}: StrategyHeroProps) {
  const topic = section.specialist_type || 'general';
  const topicLabel = getTopicLabel(topic);
  const heroImage = getHeroImage(section);
  // Deduplicate constraints — backend may emit the same rule twice
  // Exclude soft/info severity — only count blocking + strong constraints
  const constraints = React.useMemo(() => {
    const raw = section.constraints_applied;
    if (!raw || raw.length === 0) return [];
    const deduped = [...new Map(raw.map(c => [c.rule || c.reason, c])).values()];
    return deduped.filter(c => {
      const sev = (c as Record<string, string>).severity;
      return !sev || sev === 'blocking' || sev === 'strong';
    });
  }, [section.constraints_applied]);
  const constraintCount = constraints.length;

  // Generate unique IDs for accessibility
  const uniqueId = useId();
  const headerId = `${uniqueId}-header`;
  const contentId = `${uniqueId}-content`;

  // Internal state for sheet (compact mode is now self-contained)
  const [isSheetOpen, setIsSheetOpen] = useState(false);

  // Internal state for accordion expansion (used when not controlled)
  const [internalExpanded, setInternalExpanded] = useState(defaultExpanded);

  // Use controlled state if provided, otherwise use internal state
  const isAccordionExpanded = controlledExpanded !== undefined ? controlledExpanded : internalExpanded;

  // Get specialist colors
  const specialistColors = SPECIALIST_STYLE_CLASSES[topic] || DEFAULT_STYLE;

  // Infeasible state
  const isInfeasible = section.feasibility_status === 'infeasible';

  // Handler for opening the sheet (compact/hero modes)
  const handleExpand = () => {
    // Support legacy onExpand callback if provided
    if (onExpand) {
      onExpand();
    }
    // Always open the internal sheet
    setIsSheetOpen(true);
  };

  // Handler for toggling accordion expansion
  const handleAccordionToggle = () => {
    const newState = !isAccordionExpanded;
    if (controlledExpanded === undefined) {
      setInternalExpanded(newState);
    }
    onExpandChange?.(newState);
  };

  // Keyboard handler for accordion
  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      handleAccordionToggle();
    } else if (e.key === 'Escape' && isAccordionExpanded) {
      e.preventDefault();
      if (controlledExpanded === undefined) {
        setInternalExpanded(false);
      }
      onExpandChange?.(false);
    }
  };

  // --- RENDER: ACCORDION MODE (Collapsible inline cards) ---
  if (variant === 'accordion') {
    const summaryText = getSummaryBadge(section);

    return (
      <div
        role="region"
        aria-labelledby={headerId}
        data-state={isAccordionExpanded ? 'expanded' : 'collapsed'}
        data-specialist={topic}
        className={cn(
          // Base container
          'w-full rounded-xl mb-3 overflow-hidden',
          'transition-all duration-200',
          // Light: DS.materials.surface pattern
          'bg-zinc-50 border border-zinc-100',
          // Dark: Glass Fill Rule (bg-white/5, not transparent)
          'dark:bg-white/[0.03] dark:border-white/5',
          // Shadow
          isAccordionExpanded ? 'shadow-soft' : 'shadow-card',
          // Infeasible state
          isInfeasible && 'opacity-60'
        )}
      >
        {/* Accordion Header (clickable) */}
        <div
          id={headerId}
          role="button"
          tabIndex={0}
          aria-expanded={isAccordionExpanded}
          aria-controls={contentId}
          onClick={handleAccordionToggle}
          onKeyDown={handleKeyDown}
          className={cn(
            'flex items-center gap-3 p-3 cursor-pointer',
            'min-h-[60px]',
            'transition-all duration-150',
            // Hover: Tactile Rule - border snaps to visible
            'hover:bg-zinc-100/50 dark:hover:bg-white/[0.02]',
            // Focus visible
            'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500 focus-visible:ring-offset-2',
            // Expanded header styling
            isAccordionExpanded && [
              'border-b border-zinc-100 dark:border-white/5',
              'bg-zinc-100/50 dark:bg-white/[0.02]',
            ]
          )}
        >
          {/* Specialist Icon (circular badge) */}
          <div
            className={cn(
              'w-8 h-8 rounded-full flex items-center justify-center shrink-0',
              specialistColors.light,
              'dark:bg-white/10'
            )}
          >
            {renderTopicIcon(topic, cn('w-4 h-4', specialistColors.icon))}
          </div>

          {/* Title and Summary */}
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2">
              <span className="text-sm font-medium text-zinc-900 dark:text-white leading-tight">
                {topicLabel}
              </span>
              {/* Infeasible badge */}
              {isInfeasible && (
                <span className={`px-1.5 py-0.5 rounded ${DS.textSize.nano} font-bold bg-red-100 dark:bg-red-900/30 text-red-600 dark:text-red-400`}>
                  Unavailable
                </span>
              )}
              {/* Ready checkmark */}
              {!isInfeasible && (
                <CheckCircle2 className="w-3.5 h-3.5 text-emerald-500 shrink-0" />
              )}
            </div>
            <p className="text-xs text-zinc-500 dark:text-zinc-400 mt-0.5 line-clamp-2">
              {section.one_liner || section.editorial_one_liner || summaryText}
            </p>
          </div>

          {/* Summary Badge (hidden on small screens) */}
          <span className={`hidden sm:inline-flex ${DS.textSize.micro} font-medium uppercase tracking-wide px-2 py-0.5 rounded-md bg-zinc-100 text-zinc-500 dark:bg-white/5 dark:text-zinc-400`}>
            {summaryText}
          </span>

          {/* Toggle Button */}
          <div
            className={cn(
              'w-6 h-6 flex items-center justify-center',
              'text-zinc-400 dark:text-zinc-500',
              'transition-transform duration-200',
              isAccordionExpanded && 'rotate-180'
            )}
          >
            <ChevronDown className="w-4 h-4" />
          </div>
        </div>

        {/* Accordion Content */}
        <div
          id={contentId}
          aria-hidden={!isAccordionExpanded}
          className={cn(
            'overflow-hidden transition-all duration-300 ease-out accordion-scrollbar',
            // Collapsed: hidden
            !isAccordionExpanded && 'max-h-0 opacity-0',
            // Expanded: visible with max height
            isAccordionExpanded && 'max-h-[300px] opacity-100 overflow-y-auto'
          )}
        >
          <div
            className={cn(
              'p-4 space-y-4',
              // Stagger animation
              'transform transition-all duration-200 delay-100',
              !isAccordionExpanded && '-translate-y-2',
              isAccordionExpanded && 'translate-y-0'
            )}
          >
            {/* Strategy Logic / One-liner */}
            {(section.one_liner || section.editorial_one_liner) && (
              <div className="space-y-1">
                <h4 className={cn(DS.text.label, 'flex items-center gap-1.5')}>
                  <Sparkles className="w-3 h-3" />
                  Strategy Logic
                </h4>
                <p className="text-sm text-zinc-600 dark:text-zinc-400 leading-relaxed">
                  {section.one_liner || section.editorial_one_liner}
                </p>
              </div>
            )}

            {/* Constraints - Label changes based on specialist type */}
            {constraints.length > 0 && (
              <div className="space-y-2">
                <h4 className={cn(DS.text.label, 'flex items-center gap-1.5')}>
                  <AlertCircle className="w-3 h-3" />
                  {getConstraintSectionLabel(topic)}
                </h4>
                <div className="flex flex-wrap gap-1.5">
                  {constraints.map((c, i) => (
                    <span
                      key={i}
                      className={cn(
                        'inline-flex items-center gap-1 px-2 py-0.5 rounded-md',
                        `${DS.textSize.mini} font-medium`,
                        c.type === 'safety' || c.type?.includes('safety')
                          ? 'bg-amber-50 text-amber-700 border border-amber-200 dark:bg-amber-900/30 dark:text-amber-400 dark:border-amber-700/50'
                          : 'bg-blue-50 text-blue-700 border border-blue-200 dark:bg-blue-900/30 dark:text-blue-400 dark:border-blue-700/50'
                      )}
                      title={c.reason || formatConstraintRule(c.rule)} // Full text on hover
                    >
                      {getConstraintIcon(c.type)}
                      {getShortConstraintLabel(c.rule)}
                    </span>
                  ))}
                </div>
              </div>
            )}

            {/* Principles / Key Points - filter out duplicates from one_liner and constraints */}
            {(() => {
              const uniquePrinciples = section.principles?.filter(principle => {
                const isOneLiner = principle === section.one_liner || principle === section.editorial_one_liner;
                const isConstraintReason = constraints.some(c => c.reason === principle);
                return !isOneLiner && !isConstraintReason;
              }) || [];
              return uniquePrinciples.length > 0 && (
                <div className="space-y-2">
                  <h4 className={cn(DS.text.label, 'flex items-center gap-1.5')}>
                    <Info className="w-3 h-3" />
                    Key Principles
                  </h4>
                  <ul className="space-y-1.5">
                    {uniquePrinciples.slice(0, 4).map((principle, i) => (
                      <li key={i} className="flex items-start gap-2 text-sm text-zinc-600 dark:text-zinc-400 leading-relaxed">
                        <CheckCircle2 className="w-4 h-4 text-emerald-500 shrink-0 mt-0.5" />
                        {principle}
                      </li>
                    ))}
                  </ul>
                </div>
              );
            })()}

            {/* Content Added (Recommendations) - show first 3 */}
            {section.content_added && section.content_added.length > 0 && (
              <div className="space-y-2">
                <h4 className={cn(DS.text.label, 'flex items-center gap-1.5')}>
                  <Sparkles className="w-3 h-3" />
                  Recommendations
                </h4>
                <div className="space-y-2">
                  {section.content_added.slice(0, 3).map((item, i) => (
                    <div
                      key={i}
                      className="flex gap-2 items-start p-2 rounded-lg bg-zinc-100/50 dark:bg-white/[0.02] border border-zinc-100 dark:border-white/5"
                    >
                      {item.image_url && (
                        <div className="relative w-12 h-12 rounded-md overflow-hidden shrink-0 bg-zinc-200 dark:bg-zinc-800">
                          <Image src={item.image_url} alt={item.title} fill className="object-cover" sizes="48px" />
                        </div>
                      )}
                      <div className="flex-1 min-w-0">
                        <p className="text-sm font-medium text-zinc-900 dark:text-white">{item.title}</p>
                        {item.description && (
                          <p className="text-xs text-zinc-500 dark:text-zinc-400 line-clamp-1 mt-0.5">
                            {item.description}
                          </p>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Infeasibility reason */}
            {isInfeasible && section.feasibility_reason && (
              <div className="p-3 rounded-lg bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800/50">
                <p className="text-sm text-red-700 dark:text-red-400">{section.feasibility_reason}</p>
                {section.alternative_suggestion && (
                  <p className="text-xs text-red-600/70 dark:text-red-400/70 mt-1">
                    💡 {section.alternative_suggestion}
                  </p>
                )}
              </div>
            )}
          </div>
        </div>
      </div>
    );
  }

  // --- RENDER: COMPACT MODE (Trip DNA Bar) ---
  if (variant === 'compact') {
    return (
      <>
        <button
          type="button"
          onClick={handleExpand}
          className={cn(
            'w-full flex items-center gap-3 p-3 rounded-xl mb-3 text-left transition-all group',
            'bg-zinc-50 dark:bg-white/5 border border-zinc-200 dark:border-white/10',
            'cursor-pointer',
            'hover:border-zinc-300 dark:hover:border-white/20',
            'hover:bg-zinc-100 dark:hover:bg-white/10',
            'hover:shadow-card',
            'active:scale-[0.995]',
            isInfeasible && 'opacity-60'
          )}
        >
          {/* Tiny Thumbnail */}
          <div className="relative w-10 h-10 rounded-lg overflow-hidden shrink-0 bg-zinc-200 dark:bg-zinc-800">
            <Image src={heroImage} alt={section.title} fill className="object-cover" sizes="40px" />
          </div>

          {/* Text Summary */}
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2">
              {/* Topic Icon */}
              {renderTopicIcon(topic, "w-3.5 h-3.5 text-emerald-600 dark:text-emerald-400 shrink-0")}

              {/* Title */}
              <span className="text-xs font-bold text-zinc-900 dark:text-white truncate">
                {topicLabel}
              </span>

              {/* Ready checkmark */}
              {!isInfeasible && (
                <span className="text-emerald-600 dark:text-emerald-400 text-xs">✓</span>
              )}

              {/* Infeasible badge */}
              {isInfeasible && (
                <span className={`px-1.5 py-0.5 rounded ${DS.textSize.nano} font-bold bg-red-100 dark:bg-red-900/30 text-red-600 dark:text-red-400`}>
                  Unavailable
                </span>
              )}

              {/* Constraint Count Badge */}
              {constraintCount > 0 && !isInfeasible && (
                <span className={`px-1.5 py-0.5 rounded-full bg-amber-100 dark:bg-amber-900/30 ${DS.textSize.nano} font-bold text-amber-700 dark:text-amber-400`}>
                  {constraintCount} {constraintCount === 1 ? 'Rule' : 'Rules'}
                </span>
              )}
            </div>

            {/* One-liner - show meaningful subtitle for all specialist types */}
            <p className="text-xs text-zinc-500 dark:text-zinc-400 line-clamp-2 mt-0.5 group-hover:text-zinc-700 dark:group-hover:text-zinc-300">
              {section.one_liner ||
                section.editorial_one_liner ||
                (section.principles?.length > 0 ? section.principles[0] : null) ||
                (constraintCount > 0 ? `${constraintCount} constraint${constraintCount > 1 ? 's' : ''} active` : null) ||
                section.subtitle ||
                'Tap to view details'}
            </p>
          </div>

          {/* Expand indicator - always visible in compact mode */}
          <ChevronRight className="w-4 h-4 text-zinc-400 dark:text-zinc-500 shrink-0 group-hover:text-zinc-600 dark:group-hover:text-zinc-300 transition-colors" />
        </button>

        {/* Details Sheet - self-contained expansion */}
        <BottomSheet
          open={isSheetOpen}
          onOpenChange={setIsSheetOpen}
          title={`${topicLabel} Strategy`}
          hint="Tap outside to close"
        >
          {/* pb-24 ensures content can scroll past any floating buttons (Build Itinerary) */}
          <div className="space-y-6 pb-24">
            {/* ============================================= */}
            {/* GENERAL STRATEGY LAYOUT (Trip Overview)      */}
            {/* ============================================= */}
            {section.specialist_type === 'general' ? (
              <>
                {/* Trip Summary Stats - 3 Column Grid */}
                {section.trip_summary && (
                  <div className="grid grid-cols-3 gap-2">
                    <div className={cn(DS.infoBox.container, 'p-3 flex flex-col items-center text-center')}>
                      <MapPin className="w-4 h-4 text-emerald-500 mb-1" />
                      <span className={`${DS.textSize.micro} uppercase text-zinc-500 dark:text-zinc-400 font-bold`}>Dest</span>
                      <span className="text-sm font-medium text-zinc-900 dark:text-white">{section.trip_summary.destination}</span>
                    </div>
                    <div className={cn(DS.infoBox.container, 'p-3 flex flex-col items-center text-center')}>
                      <Calendar className="w-4 h-4 text-emerald-500 mb-1" />
                      <span className={`${DS.textSize.micro} uppercase text-zinc-500 dark:text-zinc-400 font-bold`}>Dates</span>
                      <span className="text-xs font-medium text-zinc-900 dark:text-white">{section.trip_summary.dates}</span>
                    </div>
                    <div className={cn(DS.infoBox.container, 'p-3 flex flex-col items-center text-center')}>
                      <Users className="w-4 h-4 text-emerald-500 mb-1" />
                      <span className={`${DS.textSize.micro} uppercase text-zinc-500 dark:text-zinc-400 font-bold`}>Travelers</span>
                      <span className="text-xs font-medium text-zinc-900 dark:text-white">{section.trip_summary.travelers}</span>
                    </div>
                  </div>
                )}

                {/* Vibe Trio - Primary image gallery from backend */}
                {section.vibe_trio && section.vibe_trio.filter(v => v.image_url).length > 0 && (
                  <div className="space-y-3">
                    <h4 className={DS.text.label}>Trip Vibe</h4>
                    <div className="grid grid-cols-2 gap-2 aspect-[16/9] rounded-2xl overflow-hidden">
                      {/* Primary Image (Left, Full Height) */}
                      {section.vibe_trio[0]?.image_url && (
                        <div className="relative h-full">
                          <Image
                            src={section.vibe_trio[0].image_url}
                            alt={section.vibe_trio[0].label || 'Trip vibe'}
                            fill
                            className="object-cover"
                            sizes="300px"
                          />
                          <div className="absolute inset-0 bg-gradient-to-t from-black/60 to-transparent flex items-end p-3">
                            <span className="text-white text-xs font-bold uppercase tracking-wider drop-shadow-md">
                              {section.vibe_trio[0].label}
                            </span>
                          </div>
                        </div>
                      )}

                      {/* Secondary Images (Right Column) */}
                      <div className="grid grid-rows-2 gap-2 h-full">
                        {section.vibe_trio
                          .slice(1, 3)
                          .filter((vibe) => vibe.image_url)
                          .map((vibe, i) => (
                            <div key={i} className="relative h-full">
                              <Image
                                src={vibe.image_url}
                                alt={vibe.label || 'Trip vibe'}
                                fill
                                className="object-cover"
                                sizes="200px"
                              />
                              <div className="absolute inset-0 bg-gradient-to-t from-black/60 to-transparent flex items-end p-3">
                                <span className={`text-white ${DS.textSize.micro} font-bold uppercase tracking-wider drop-shadow-md`}>
                                  {vibe.label}
                                </span>
                              </div>
                            </div>
                          ))}
                      </div>
                    </div>
                  </div>
                )}

                {/* Fallback: Vibe Grid from content_added (legacy support) */}
                {(!section.vibe_trio || section.vibe_trio.length === 0) &&
                  section.content_added && section.content_added.filter(c => c.image_url).length > 0 && (
                  <div className="space-y-3">
                    <h4 className={DS.text.label}>Destination Vibe</h4>
                    <div className="grid grid-cols-2 gap-2">
                      {section.content_added
                        .filter((item) => item.image_url)
                        .slice(0, 4)
                        .map((item, i) => (
                          <div key={i} className="relative aspect-square rounded-xl overflow-hidden bg-zinc-100 dark:bg-zinc-900">
                            <Image src={item.image_url!} alt={item.title} fill className="object-cover" sizes="200px" />
                            <div className="absolute inset-0 bg-gradient-to-t from-black/60 to-transparent" />
                            <span className="absolute bottom-2 left-2 text-xs font-bold text-white drop-shadow-md">
                              {item.title}
                            </span>
                          </div>
                        ))}
                    </div>
                  </div>
                )}

                {/* Editorial One-Liner as Quote */}
                {(section.editorial_one_liner || section.one_liner) && (
                  <div className="p-4 rounded-xl bg-zinc-50 dark:bg-zinc-900/50 border border-zinc-200 dark:border-white/5">
                    <p className="text-zinc-600 dark:text-zinc-300 italic text-sm leading-relaxed">
                      &ldquo;{section.editorial_one_liner || section.one_liner}&rdquo;
                    </p>
                  </div>
                )}

                {/* Principles as Highlights */}
                {section.principles && section.principles.length > 0 && (
                  <div className="space-y-3">
                    <h4 className={DS.text.label}>Trip Highlights</h4>
                    <ul className="space-y-2">
                      {section.principles.map((principle, i) => (
                        <li key={i} className="flex gap-2 items-start text-sm text-zinc-600 dark:text-zinc-300">
                          <CheckCircle2 className="w-4 h-4 text-emerald-500 shrink-0 mt-0.5" />
                          {principle}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </>
            ) : section.specialist_type === 'local_expert' && section.destination_gallery && section.destination_gallery.length > 0 ? (
              /* ============================================= */
              /* LOCAL EXPERT LAYOUT (Destination Gallery)    */
              /* ============================================= */
              <>
                {/* Destination Gallery - "Vibe Trio" Carousel */}
                <div className="space-y-2">
                  <h4 className={DS.text.label}>Destination Preview</h4>
                  <div className="flex gap-3 overflow-x-auto pb-2 snap-x no-scrollbar -mx-4 px-4">
                    {section.destination_gallery
                      .filter((img) => img.image_url)
                      .map((img, idx) => (
                        <div
                          key={idx}
                          className="shrink-0 snap-center relative w-56 h-36 rounded-xl overflow-hidden shadow-card dark:shadow-none border border-zinc-200 dark:border-zinc-700/50"
                        >
                          <Image
                            src={img.image_url}
                            alt={img.label || 'Destination image'}
                            fill
                            className="object-cover"
                            sizes="224px"
                          />
                        </div>
                      ))}
                  </div>
                </div>

                {/* Strategy Logic */}
                {section.one_liner && (
                  <div className="space-y-2">
                    <h4 className={DS.text.label}>Local Insight</h4>
                    <p className={DS.text.body}>{section.one_liner}</p>
                  </div>
                )}

                {/* Principles / Key Points */}
                {section.principles && section.principles.length > 0 && (
                  <div className="space-y-3">
                    <h4 className={DS.text.label}>Key Principles</h4>
                    <ul className="space-y-2">
                      {section.principles.map((principle, i) => (
                        <li key={i} className="flex gap-2 items-start text-sm text-zinc-600 dark:text-zinc-300">
                          <CheckCircle2 className="w-4 h-4 text-emerald-500 shrink-0 mt-0.5" />
                          {principle}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}

                {/* Local Recommendations */}
                {section.content_added && section.content_added.length > 0 && (
                  <div className="space-y-3">
                    <h4 className={DS.text.label}>Local Recommendations</h4>
                    <div className="space-y-3">
                      {section.content_added.map((item, i) => (
                        <div
                          key={i}
                          className={cn(
                            'rounded-xl border p-3 flex gap-3',
                            'bg-white border-zinc-200 dark:bg-zinc-900 dark:border-zinc-700'
                          )}
                        >
                          {item.image_url && (
                            <div className="relative w-16 h-16 rounded-lg overflow-hidden shrink-0 bg-zinc-100 dark:bg-zinc-800">
                              <Image src={item.image_url} alt={item.title} fill className="object-cover" sizes="64px" />
                            </div>
                          )}
                          <div className="flex-1 min-w-0">
                            <div className="flex items-start justify-between gap-2">
                              <p className="text-sm font-bold text-zinc-900 dark:text-white">{item.title}</p>
                              {item.type && (
                                <span className={`${DS.textSize.micro} font-bold bg-zinc-100 dark:bg-zinc-800 text-zinc-600 dark:text-zinc-300 px-2 py-0.5 rounded uppercase shrink-0`}>
                                  {item.type}
                                </span>
                              )}
                            </div>
                            {item.description && (
                              <p className="text-xs text-zinc-600 dark:text-zinc-400 leading-relaxed mt-1 line-clamp-2">
                                {item.description}
                              </p>
                            )}
                            {item.logic_hook && (
                              <div className={`${DS.textSize.mini} mt-2 inline-flex items-center gap-1.5 px-2 py-1 rounded-md bg-emerald-50 dark:bg-emerald-950 text-emerald-700 dark:text-emerald-300 border border-emerald-200 dark:border-emerald-700/60`}>
                                <Sparkles className="w-3 h-3 text-emerald-600 dark:text-emerald-400" />
                                <span className="font-medium">{item.logic_hook}</span>
                              </div>
                            )}
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* Comprehensive Travel Intelligence (12 Categories) */}
                {section.travel_intelligence && (
                  <TravelIntelligencePanel intelligence={section.travel_intelligence} />
                )}
              </>
            ) : (
              /* ============================================= */
              /* ACTIVITY SPECIALIST LAYOUT (Diving, etc.)    */
              /* Fixed-height banner to prevent giant images  */
              /* @see docs/ux_unified_architecture.md XII.C   */
              /* ============================================= */
              <>
                {/* Single Hero Image with Badge - FIXED HEIGHT (not aspect ratio) */}
                {/* Mobile: h-48 (192px), Desktop: h-64 (256px) - max ~30% viewport */}
                <div className="relative h-48 md:h-64 w-full rounded-xl overflow-hidden">
                  <Image
                    src={heroImage}
                    alt={section.title}
                    fill
                    className="object-cover"
                    sizes="(max-width: 768px) 100vw, 600px"
                  />
                  <div className="absolute inset-0 bg-gradient-to-t from-black/60 to-transparent" />
                  <div className="absolute bottom-3 left-3 right-3">
                    <span
                      className={cn(
                        `inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md ${DS.textSize.micro} font-bold uppercase tracking-widest`,
                        'bg-white/20 backdrop-blur-md text-white border border-white/20'
                      )}
                    >
                      {renderTopicIcon(topic, "w-3 h-3")}
                      {topicLabel}
                    </span>
                  </div>
                </div>

                {/* Strategy Logic */}
                {section.one_liner && (
                  <div className="space-y-2">
                    <h4 className={DS.text.label}>Strategy Logic</h4>
                    <p className={DS.text.body}>{section.one_liner}</p>
                  </div>
                )}

                {/* Constraints List */}
                {constraints.length > 0 && (
                  <div className="space-y-3">
                    <h4 className={DS.text.label}>Applied Constraints</h4>
                    <div className="grid gap-2">
                      {constraints.map((c, i) => (
                        <div key={i} className={DS.infoBox.container}>
                          <div className="flex gap-3">
                            {getConstraintIcon(c.type)}
                            <div className="flex-1 min-w-0">
                              <p className="font-medium text-sm text-zinc-900 dark:text-zinc-100">
                                {formatConstraintRule(c.rule)}
                              </p>
                              {c.reason && (
                                <p className="text-xs text-zinc-500 dark:text-zinc-400 mt-0.5">
                                  {c.reason}
                                </p>
                              )}
                            </div>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* Principles / Key Points */}
                {section.principles && section.principles.length > 0 && (
                  <div className="space-y-3">
                    <h4 className={DS.text.label}>Key Principles</h4>
                    <ul className="space-y-2">
                      {section.principles.map((principle, i) => (
                        <li key={i} className="flex gap-2 items-start text-sm text-zinc-600 dark:text-zinc-300">
                          <CheckCircle2 className="w-4 h-4 text-emerald-500 shrink-0 mt-0.5" />
                          {principle}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}

                {/* Content Added (Recommendations) */}
                {section.content_added && section.content_added.length > 0 && (
                  <div className="space-y-3">
                    <h4 className={DS.text.label}>Expert Recommendations</h4>
                    <div className="space-y-3">
                      {section.content_added.map((item, i) => (
                        <div
                          key={i}
                          className={cn(
                            'rounded-xl border p-3 flex gap-3',
                            'bg-white border-zinc-200 dark:bg-zinc-900 dark:border-zinc-700'
                          )}
                        >
                          {item.image_url && (
                            <div className="relative w-16 h-16 rounded-lg overflow-hidden shrink-0 bg-zinc-100 dark:bg-zinc-800">
                              <Image src={item.image_url} alt={item.title} fill className="object-cover" sizes="64px" />
                            </div>
                          )}
                          <div className="flex-1 min-w-0">
                            <div className="flex items-start justify-between gap-2">
                              <p className="text-sm font-bold text-zinc-900 dark:text-white">{item.title}</p>
                              {item.type && (
                                <span className={`${DS.textSize.micro} font-bold bg-zinc-100 dark:bg-zinc-800 text-zinc-600 dark:text-zinc-300 px-2 py-0.5 rounded uppercase shrink-0`}>
                                  {item.type}
                                </span>
                              )}
                            </div>
                            {item.description && (
                              <p className="text-xs text-zinc-600 dark:text-zinc-400 leading-relaxed mt-1 line-clamp-2">
                                {item.description}
                              </p>
                            )}
                            {item.logic_hook && (
                              <div className={`${DS.textSize.mini} mt-2 inline-flex items-center gap-1.5 px-2 py-1 rounded-md bg-emerald-50 dark:bg-emerald-950 text-emerald-700 dark:text-emerald-300 border border-emerald-200 dark:border-emerald-700/60`}>
                                <Sparkles className="w-3 h-3 text-emerald-600 dark:text-emerald-400" />
                                <span className="font-medium">{item.logic_hook}</span>
                              </div>
                            )}
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* Logistics Notes (if any) */}
                {section.logistics_notes && section.logistics_notes.length > 0 && (
                  <div className="space-y-3">
                    <h4 className={DS.text.label}>Logistics Notes</h4>
                    <ul className="space-y-1.5">
                      {section.logistics_notes.map((note, i) => (
                        <li key={i} className="text-xs text-zinc-600 dark:text-zinc-400 flex items-start gap-2">
                          <span className="text-zinc-400 mt-0.5">•</span>
                          {note}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </>
            )}
          </div>
        </BottomSheet>
      </>
    );
  }

  // --- RENDER: HERO MODE (Magazine Style) ---
  // CRITICAL: Hero mode must also be clickable to open BottomSheet
  // This was a regression - cards must always be expandable
  return (
    <>
    <button
      type="button"
      onClick={handleExpand}
      className={cn(
        'relative w-full rounded-2xl overflow-hidden shadow-card group mb-6 text-left',
        'cursor-pointer transition-all',
        'hover:shadow-soft hover:scale-[1.01]',
        'active:scale-[0.995]',
        'focus:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500 focus-visible:ring-offset-2',
        isInfeasible && 'opacity-70'
      )}
    >
      {/* 1. Background Image - FIXED HEIGHT to prevent giant images */}
      {/* Mobile: h-56 (224px), Desktop: h-72 (288px) - max ~30% viewport */}
      {/* @see docs/ux_unified_architecture.md - Fixed-Height Banner pattern */}
      <div className="relative h-56 md:h-72 w-full">
        <Image
          src={heroImage}
          alt={section.title}
          fill
          className="object-cover transition-transform duration-700 group-hover:scale-105"
          priority
          sizes="(max-width: 768px) 100vw, 800px"
        />
        {/* Gradient Overlay for Text Readability */}
        <div className="absolute inset-0 bg-gradient-to-t from-black/90 via-black/40 to-transparent" />
      </div>

      {/* 2. Content Overlay */}
      <div className="absolute inset-0 p-5 md:p-6 flex flex-col justify-end">
        {/* Specialist Badge */}
        <div className="mb-2">
          <span
            className={cn(
              `inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md ${DS.textSize.micro} font-bold uppercase tracking-widest`,
              'bg-white/20 backdrop-blur-md text-white border border-white/20'
            )}
          >
            {renderTopicIcon(topic, "w-3 h-3")}
            {topicLabel} Strategy
          </span>

          {/* Infeasible badge */}
          {isInfeasible && (
            <span className={`ml-2 px-2 py-1 rounded-md ${DS.textSize.micro} font-bold bg-red-500/80 text-white`}>
              Unavailable
            </span>
          )}
        </div>

        {/* Title */}
        <h1 className="text-xl md:text-2xl lg:text-3xl font-bold text-white mb-2 leading-tight">
          {section.title}
        </h1>

        {/* One-liner / Subtitle */}
        <p className="text-white/80 text-sm md:text-base line-clamp-2 max-w-xl mb-4">
          {section.one_liner || section.subtitle}
        </p>

        {/* Infeasibility reason */}
        {isInfeasible && section.feasibility_reason && (
          <p className="text-red-300 text-sm mb-3">{section.feasibility_reason}</p>
        )}

        {/* Alternative suggestion */}
        {isInfeasible && section.alternative_suggestion && (
          <p className="text-white/60 text-xs mb-4">
            💡 {section.alternative_suggestion}
          </p>
        )}

        {/* 3. Constraint Pills (Horizontal Scroll) - use short labels to prevent truncation */}
        {constraints.length > 0 && !isInfeasible && (
          <div className="flex items-center gap-2 overflow-x-auto no-scrollbar -mx-5 md:-mx-6 px-5 md:px-6 pb-1">
            {constraints.map((c, i) => (
              <div
                key={i}
                className={cn(
                  'flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg shrink-0',
                  'bg-black/40 backdrop-blur-md border border-white/10'
                )}
                title={c.reason || formatConstraintRule(c.rule)} // Full text on hover
              >
                {getConstraintIcon(c.type)}
                <span className="text-xs font-medium text-white/90">
                  {getShortConstraintLabel(c.rule)}
                </span>
              </div>
            ))}
          </div>
        )}

        {/* Principles (if no constraints) */}
        {constraints.length === 0 &&
          section.principles.length > 0 &&
          !isInfeasible && (
            <div className="flex flex-wrap gap-2">
              {section.principles.slice(0, 3).map((principle, i) => (
                <div
                  key={i}
                  className={cn(
                    'flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg',
                    'bg-black/40 backdrop-blur-md border border-white/10'
                  )}
                >
                  <Sparkles className="w-3 h-3 text-emerald-400" />
                  <span className="text-xs font-medium text-white/90 line-clamp-1">
                    {principle}
                  </span>
                </div>
              ))}
            </div>
          )}
      </div>
    </button>

    {/* Details Sheet - Hero mode expansion (same as compact mode) */}
    <BottomSheet
      open={isSheetOpen}
      onOpenChange={setIsSheetOpen}
      title={`${topicLabel} Strategy`}
      hint="Tap to expand"
    >
      <div className="space-y-6 pb-24">
        {/* ============================================= */}
        {/* GENERAL / LOCAL EXPERT LAYOUT               */}
        {/* ============================================= */}
        {(section.specialist_type === 'general' || section.specialist_type === 'local_expert') ? (
          <>
            {/* Trip Summary Stats */}
            {section.trip_summary && (
              <div className="grid grid-cols-3 gap-3">
                <div className="p-3 rounded-lg bg-zinc-100 dark:bg-zinc-800/50">
                  <span className={`${DS.textSize.micro} uppercase tracking-widest text-zinc-500 dark:text-zinc-400`}>Destination</span>
                  <p className="text-sm font-medium text-zinc-900 dark:text-white mt-0.5">{section.trip_summary.destination}</p>
                </div>
                <div className="p-3 rounded-lg bg-zinc-100 dark:bg-zinc-800/50">
                  <span className={`${DS.textSize.micro} uppercase tracking-widest text-zinc-500 dark:text-zinc-400`}>Dates</span>
                  <p className="text-sm font-medium text-zinc-900 dark:text-white mt-0.5">{section.trip_summary.dates}</p>
                </div>
                <div className="p-3 rounded-lg bg-zinc-100 dark:bg-zinc-800/50">
                  <span className={`${DS.textSize.micro} uppercase tracking-widest text-zinc-500 dark:text-zinc-400`}>Travelers</span>
                  <p className="text-sm font-medium text-zinc-900 dark:text-white mt-0.5">{section.trip_summary.travelers}</p>
                </div>
              </div>
            )}

            {/* Destination Gallery */}
            {section.destination_gallery && section.destination_gallery.length > 0 && (
              <div className="space-y-3">
                <h4 className={DS.text.label}>Destination Vibes</h4>
                <div className="flex gap-2 overflow-x-auto no-scrollbar -mx-4 px-4 pb-2">
                  {section.destination_gallery
                    .filter((img) => img.image_url)
                    .map((img, idx) => (
                      <div key={idx} className="relative w-32 h-24 rounded-lg overflow-hidden shrink-0">
                        <Image src={img.image_url} alt={img.label || 'Destination image'} fill className="object-cover" sizes="128px" />
                        <div className="absolute inset-0 bg-gradient-to-t from-black/60 to-transparent" />
                        <span className={`absolute bottom-2 left-2 ${DS.textSize.micro} font-medium text-white`}>{img.label}</span>
                      </div>
                    ))}
                </div>
              </div>
            )}

            {/* One-liner */}
            {section.one_liner && (
              <p className="text-sm italic text-muted-foreground">{section.one_liner}</p>
            )}

            {/* Principles */}
            {section.principles && section.principles.length > 0 && (
              <div className="space-y-3">
                <h4 className={DS.text.label}>Key Highlights</h4>
                <div className="space-y-2">
                  {section.principles.map((p, i) => (
                    <div key={i} className="flex items-start gap-2">
                      <Sparkles className="w-4 h-4 text-emerald-500 mt-0.5 shrink-0" />
                      <span className="text-sm text-zinc-700 dark:text-zinc-300">{p}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Recommendations */}
            {section.content_added && section.content_added.length > 0 && (
              <div className="space-y-3">
                <h4 className={DS.text.label}>Local Tips</h4>
                <div className="space-y-3">
                  {section.content_added.map((item, idx) => (
                    <div key={idx} className={DS.infoBox.container}>
                      <div className="flex gap-3">
                        {item.image_url && (
                          <div className="relative w-16 h-16 rounded-lg overflow-hidden shrink-0">
                            <Image src={item.image_url} alt={item.title} fill className="object-cover" sizes="64px" />
                          </div>
                        )}
                        <div className="flex-1 min-w-0">
                          <p className="font-medium text-sm text-zinc-900 dark:text-zinc-100">{item.title}</p>
                          <p className="text-xs text-muted-foreground mt-0.5 line-clamp-2">{item.description}</p>
                          {item.logic_hook && (
                            <p className={`${DS.textSize.micro} text-emerald-600 dark:text-emerald-400 mt-1 font-medium`}>
                              💡 {item.logic_hook}
                            </p>
                          )}
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Comprehensive Travel Intelligence (12 Categories) - Hero mode */}
            {section.specialist_type === 'local_expert' && section.travel_intelligence && (
              <TravelIntelligencePanel intelligence={section.travel_intelligence} />
            )}
          </>
        ) : (
          /* ============================================= */
          /* ACTIVITY SPECIALIST LAYOUT (Diving, etc.)    */
          /* ============================================= */
          <>
            {/* Hero Image in Sheet */}
            <div className="relative h-48 w-full rounded-xl overflow-hidden">
              <Image src={heroImage} alt={section.title} fill className="object-cover" sizes="100vw" />
              <div className="absolute inset-0 bg-gradient-to-t from-black/60 to-transparent" />
              <div className="absolute bottom-3 left-3">
                <span className={cn(
                  `inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md ${DS.textSize.micro} font-bold uppercase tracking-widest`,
                  'bg-white/20 backdrop-blur-md text-white border border-white/20'
                )}>
                  {renderTopicIcon(topic, "w-3 h-3")}
                  {topicLabel}
                </span>
              </div>
            </div>

            {/* Strategy Logic */}
            {section.one_liner && (
              <div className="space-y-2">
                <h4 className={DS.text.label}>Strategy Logic</h4>
                <p className={DS.text.body}>{section.one_liner}</p>
              </div>
            )}

            {/* Constraints */}
            {constraints.length > 0 && (
              <div className="space-y-3">
                <h4 className={DS.text.label}>Applied Constraints</h4>
                <div className="space-y-2">
                  {constraints.map((c, i) => (
                    <div key={i} className={DS.infoBox.container}>
                      <div className="flex gap-3">
                        {getConstraintIcon(c.type)}
                        <div className="flex-1 min-w-0">
                          <p className="font-medium text-sm text-zinc-900 dark:text-zinc-100">
                            {formatConstraintRule(c.rule)}
                          </p>
                          {c.reason && (
                            <p className="text-xs text-muted-foreground mt-0.5">{c.reason}</p>
                          )}
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Principles */}
            {section.principles && section.principles.length > 0 && (
              <div className="space-y-3">
                <h4 className={DS.text.label}>Key Principles</h4>
                <div className="space-y-2">
                  {section.principles.map((p, i) => (
                    <div key={i} className="flex items-start gap-2">
                      <Sparkles className="w-4 h-4 text-emerald-500 mt-0.5 shrink-0" />
                      <span className="text-sm text-zinc-700 dark:text-zinc-300">{p}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Recommendations */}
            {section.content_added && section.content_added.length > 0 && (
              <div className="space-y-3">
                <h4 className={DS.text.label}>Expert Recommendations</h4>
                <div className="space-y-3">
                  {section.content_added.map((item, idx) => (
                    <div key={idx} className={DS.infoBox.container}>
                      <div className="flex gap-3">
                        {item.image_url && (
                          <div className="relative w-16 h-16 rounded-lg overflow-hidden shrink-0">
                            <Image src={item.image_url} alt={item.title} fill className="object-cover" sizes="64px" />
                          </div>
                        )}
                        <div className="flex-1 min-w-0">
                          <p className="font-medium text-sm text-zinc-900 dark:text-zinc-100">{item.title}</p>
                          <p className="text-xs text-muted-foreground mt-0.5 line-clamp-2">{item.description}</p>
                          {item.logic_hook && (
                            <p className={`${DS.textSize.micro} text-emerald-600 dark:text-emerald-400 mt-1 font-medium`}>
                              💡 {item.logic_hook}
                            </p>
                          )}
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </>
        )}
      </div>
    </BottomSheet>
    </>
  );
}

export default StrategyHero;
