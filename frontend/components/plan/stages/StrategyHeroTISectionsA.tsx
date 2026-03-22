'use client';
/**
 * StrategyHeroTISectionsA
 *
 * Travel Intelligence section renderers — first group:
 * visa_entry, safety_health, money_costs, transportation, cultural_norms, connectivity
 *
 * Called by TravelIntelligenceContent in StrategyHeroTravelIntelligence.tsx.
 */

import { DS } from '@/lib/design-system';

export interface SectionDataHelpers {
  str: (key: string) => string;
  num: (key: string) => number | undefined;
  bool: (key: string) => boolean | undefined;
  arr: (key: string) => unknown[];
  obj: (key: string) => Record<string, unknown>;
}

export function renderVisaEntry(h: SectionDataHelpers) {
  return (
    <div className="pt-2 space-y-2">
      {h.bool('visa_on_arrival') !== undefined && (
        <p className="flex items-center gap-2">
          <span className={h.bool('visa_on_arrival') ? 'text-emerald-500' : 'text-red-500'}>
            {h.bool('visa_on_arrival') ? '✓' : '✗'}
          </span>
          Visa on arrival: {h.bool('visa_on_arrival') ? 'Yes' : 'No'}
        </p>
      )}
      {h.num('max_stay_days') !== undefined && <p>Max stay: {h.num('max_stay_days')} days</p>}
      {h.num('passport_validity_months') !== undefined && <p>Passport validity: {h.num('passport_validity_months')} months required</p>}
      {h.arr('key_requirements').length > 0 && (
        <div>
          <p className="font-medium text-zinc-800 dark:text-zinc-200 text-xs uppercase mt-2">Required:</p>
          <ul className="list-disc list-inside space-y-0.5 text-xs">
            {(h.arr('key_requirements') as string[]).map((r, i) => <li key={`${r}-${i}`}>{r}</li>)}
          </ul>
        </div>
      )}
      {h.str('immigration_tip') && (
        <p className="text-xs italic text-emerald-600 dark:text-emerald-400 mt-2">💡 {h.str('immigration_tip')}</p>
      )}
    </div>
  );
}

export function renderSafetyHealth(h: SectionDataHelpers) {
  return (
    <div className="pt-2 space-y-2">
      {h.str('overall_safety') && <p><strong>Safety:</strong> {h.str('overall_safety')}</p>}
      {h.bool('tap_water_safe') !== undefined && (
        <p className="flex items-center gap-2">
          <span className={h.bool('tap_water_safe') ? 'text-emerald-500' : 'text-red-500'}>
            {h.bool('tap_water_safe') ? '✓' : '✗'}
          </span>
          Tap water: {h.bool('tap_water_safe') ? 'Safe' : 'Not safe - drink bottled'}
        </p>
      )}
      {h.str('emergency_number') && <p><strong>Emergency:</strong> {h.str('emergency_number')}</p>}
      {h.str('nearest_hospital') && <p><strong>Hospital:</strong> {h.str('nearest_hospital')}</p>}
      {h.arr('common_concerns').length > 0 && (
        <div>
          <p className="font-medium text-red-600 dark:text-red-400 text-xs uppercase mt-2">⚠️ Watch out for:</p>
          <ul className="list-disc list-inside space-y-0.5 text-xs">
            {(h.arr('common_concerns') as string[]).map((c, i) => <li key={`${c}-${i}`}>{c}</li>)}
          </ul>
        </div>
      )}
    </div>
  );
}

export function renderMoneyCosts(h: SectionDataHelpers) {
  const db = h.obj('daily_budget');
  const backpacker = typeof db.backpacker === 'string' ? db.backpacker : '';
  const midRange = typeof db.mid_range === 'string' ? db.mid_range : '';
  const luxury = typeof db.luxury === 'string' ? db.luxury : '';
  return (
    <div className="pt-2 space-y-2">
      {h.str('currency') && <p><strong>Currency:</strong> {h.str('currency')}</p>}
      {h.str('exchange_tip') && <p className="text-xs">{h.str('exchange_tip')}</p>}
      {(backpacker || midRange || luxury) && (
        <div className="grid grid-cols-3 gap-2 mt-2">
          {backpacker && (
            <div className="text-center p-2 rounded bg-zinc-50 dark:bg-zinc-800">
              <p className={`${DS.textSize.micro} uppercase text-zinc-500 dark:text-zinc-400`}>Budget</p>
              <p className="font-medium text-zinc-900 dark:text-zinc-100">{backpacker}</p>
            </div>
          )}
          {midRange && (
            <div className="text-center p-2 rounded bg-zinc-50 dark:bg-zinc-800">
              <p className={`${DS.textSize.micro} uppercase text-zinc-500 dark:text-zinc-400`}>Mid</p>
              <p className="font-medium text-zinc-900 dark:text-zinc-100">{midRange}</p>
            </div>
          )}
          {luxury && (
            <div className="text-center p-2 rounded bg-zinc-50 dark:bg-zinc-800">
              <p className={`${DS.textSize.micro} uppercase text-zinc-500 dark:text-zinc-400`}>Luxury</p>
              <p className="font-medium text-zinc-900 dark:text-zinc-100">{luxury}</p>
            </div>
          )}
        </div>
      )}
      {h.str('haggling') && <p className="text-xs mt-2"><strong>Haggling:</strong> {h.str('haggling')}</p>}
    </div>
  );
}

export function renderTransportation(h: SectionDataHelpers) {
  const atc = h.arr('airport_to_city') as Array<{method: string; price?: string; time?: string}>;
  const rideApps = h.arr('ride_apps') as string[];
  return (
    <div className="pt-2 space-y-2">
      {atc.length > 0 && (
        <div>
          <p className="font-medium text-xs uppercase mb-1">Airport → City</p>
          <div className="space-y-1">
            {atc.map((t) => (
              <div key={t.method} className="text-xs flex items-center gap-2">
                <span className="font-medium">{t.method}:</span>
                {t.price && <span>{t.price}</span>}
                {t.time && <span className="text-zinc-500">({t.time})</span>}
              </div>
            ))}
          </div>
        </div>
      )}
      {rideApps.length > 0 && <p><strong>Ride apps:</strong> {rideApps.join(', ')}</p>}
      {h.str('traffic_note') && <p className="text-xs italic">{h.str('traffic_note')}</p>}
    </div>
  );
}

export function renderCulturalNorms(h: SectionDataHelpers) {
  const dc = h.obj('dress_code');
  const taboos = h.arr('important_taboos') as string[];
  const temples = typeof dc.temples === 'string' ? dc.temples : '';
  const restaurants = typeof dc.restaurants === 'string' ? dc.restaurants : '';
  return (
    <div className="pt-2 space-y-2">
      {(temples || restaurants) && (
        <div>
          <p className="font-medium text-xs uppercase mb-1">Dress Code</p>
          {temples && <p className="text-xs"><strong>Temples:</strong> {temples}</p>}
          {restaurants && <p className="text-xs"><strong>Restaurants:</strong> {restaurants}</p>}
        </div>
      )}
      {h.str('greetings') && <p><strong>Greeting:</strong> {h.str('greetings')}</p>}
      {h.str('lgbtq_friendly') && <p><strong>LGBTQ+:</strong> {h.str('lgbtq_friendly')}</p>}
      {taboos.length > 0 && (
        <div>
          <p className="font-medium text-red-600 dark:text-red-400 text-xs uppercase mt-2">🚫 Never do:</p>
          <ul className="list-disc list-inside space-y-0.5 text-xs">
            {taboos.map((t, i) => <li key={`${t}-${i}`}>{t}</li>)}
          </ul>
        </div>
      )}
    </div>
  );
}

export function renderConnectivity(h: SectionDataHelpers) {
  const apps = h.arr('essential_apps') as string[];
  return (
    <div className="pt-2 space-y-2">
      {h.str('best_sim_provider') && <p><strong>Best SIM:</strong> {h.str('best_sim_provider')}</p>}
      {h.str('sim_cost') && <p><strong>Cost:</strong> {h.str('sim_cost')}</p>}
      {h.str('where_to_buy') && <p><strong>Buy at:</strong> {h.str('where_to_buy')}</p>}
      {h.bool('esim_works') !== undefined && (
        <p>eSIM: {h.bool('esim_works') ? '✓ Works' : '✗ Not supported'}</p>
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
