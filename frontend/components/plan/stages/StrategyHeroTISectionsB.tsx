'use client';
/**
 * StrategyHeroTISectionsB
 *
 * Travel Intelligence section renderers — second group:
 * seasonality, things_to_do, neighborhoods, accommodation, scams_traps, packing
 *
 * Called by TravelIntelligenceContent in StrategyHeroTravelIntelligence.tsx.
 */

import { DS } from '@/lib/design-system';

import type { SectionDataHelpers } from './StrategyHeroTISectionsA';

export function renderSeasonality(h: SectionDataHelpers) {
  const bestMonths = h.arr('best_months') as string[];
  const festivals = h.arr('major_festivals') as Array<{name: string; when?: string; impact?: string}>;
  return (
    <div className="pt-2 space-y-2">
      {bestMonths.length > 0 && <p><strong>Best time:</strong> {bestMonths.join(', ')}</p>}
      {h.str('high_season') && <p><strong>High season:</strong> {h.str('high_season')}</p>}
      {h.str('rainy_season') && <p><strong>Rainy season:</strong> {h.str('rainy_season')}</p>}
      {festivals.length > 0 && (
        <div>
          <p className="font-medium text-xs uppercase mt-2">🎉 Festivals:</p>
          {festivals.map((f) => (
            <div key={f.name} className="text-xs mt-1">
              <strong>{f.name}</strong> {f.when && `(${f.when})`}
              {f.impact && <p className="text-zinc-500">{f.impact}</p>}
            </div>
          ))}
        </div>
      )}
      {h.str('current_season_tip') && (
        <p className="text-xs italic text-emerald-600 dark:text-emerald-400 mt-2">💡 {h.str('current_season_tip')}</p>
      )}
    </div>
  );
}

export function renderThingsToDo(h: SectionDataHelpers) {
  const mustDo = h.arr('must_do') as Array<{name: string; why?: string; booking?: string; cost?: string}>;
  const skipThese = h.arr('skip_these') as string[];
  return (
    <div className="pt-2 space-y-2">
      {mustDo.length > 0 && (
        <div>
          <p className="font-medium text-xs uppercase mb-1">🎯 Must Do</p>
          <div className="space-y-2">
            {mustDo.slice(0, 5).map((item) => (
              <div key={item.name} className="text-xs p-2 rounded bg-zinc-50 dark:bg-zinc-800">
                <p className="font-medium text-zinc-900 dark:text-white">{item.name}</p>
                {item.why && <p className="text-zinc-500 dark:text-zinc-400 mt-0.5">{item.why}</p>}
                <div className={`flex gap-2 mt-1 ${DS.textSize.micro}`}>
                  {item.cost && <span className="text-emerald-600 dark:text-emerald-400">{item.cost}</span>}
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
            {skipThese.map((s, i) => <li key={`${s}-${i}`}>{s}</li>)}
          </ul>
        </div>
      )}
    </div>
  );
}

export function renderNeighborhoods(h: SectionDataHelpers) {
  const whereToStay = h.arr('where_to_stay') as Array<{name: string; vibe?: string; best_for?: string[]; price_range?: string}>;
  const avoidStaying = h.arr('avoid_staying_in') as string[];
  return (
    <div className="pt-2 space-y-2">
      {whereToStay.length > 0 && (
        <div className="space-y-2">
          {whereToStay.map((n) => (
            <div key={n.name} className="text-xs p-2 rounded bg-zinc-50 dark:bg-zinc-800">
              <p className="font-medium text-zinc-900 dark:text-white">{n.name}</p>
              {n.vibe && <p className="text-zinc-500 dark:text-zinc-400 mt-0.5">{n.vibe}</p>}
              <div className={`flex gap-2 mt-1 ${DS.textSize.micro}`}>
                {n.price_range && <span className="px-1.5 py-0.5 rounded bg-zinc-200 dark:bg-zinc-700 text-zinc-800 dark:text-zinc-200">{n.price_range}</span>}
                {Array.isArray(n.best_for) && n.best_for.slice(0, 2).map((b, j) => (
                  <span key={`${b}-${j}`} className="px-1.5 py-0.5 rounded bg-emerald-100 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-400">{b}</span>
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
            {avoidStaying.map((a, i) => <li key={`${a}-${i}`}>{a}</li>)}
          </ul>
        </div>
      )}
    </div>
  );
}

export function renderAccommodation(h: SectionDataHelpers) {
  const priceRanges = h.obj('price_ranges');
  const bookingPlatforms = h.arr('booking_platforms') as string[];
  const priceItems = Object.entries(priceRanges)
    .filter(([, v]) => typeof v === 'string' && v)
    .map(([k, v]) => ({ key: k, value: String(v) }));
  return (
    <div className="pt-2 space-y-2">
      {priceItems.length > 0 && (
        <div className="grid grid-cols-2 gap-2">
          {priceItems.map(({ key, value }) => (
            <div key={key} className="text-xs p-2 rounded bg-zinc-50 dark:bg-zinc-800">
              <p className={`${DS.textSize.micro} uppercase text-zinc-500 dark:text-zinc-400`}>{key.replace('_', ' ')}</p>
              <p className="font-medium text-zinc-900 dark:text-zinc-100">{value}</p>
            </div>
          ))}
        </div>
      )}
      {bookingPlatforms.length > 0 && (
        <p className="text-xs"><strong>Book on:</strong> {bookingPlatforms.join(', ')}</p>
      )}
      {h.str('book_ahead') && <p className="text-xs italic text-zinc-600 dark:text-zinc-400">📅 {h.str('book_ahead')}</p>}
    </div>
  );
}

export function renderScamsTraps(h: SectionDataHelpers) {
  const commonScams = h.arr('common_scams') as Array<{name: string; how_it_works?: string; how_to_avoid?: string}>;
  return (
    <div className="pt-2 space-y-2">
      {commonScams.length > 0 && (
        <div className="space-y-2">
          {commonScams.map((scam) => (
            <div key={scam.name} className="text-xs p-2 rounded bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800">
              <p className="font-medium text-red-700 dark:text-red-400">⚠️ {scam.name}</p>
              {scam.how_it_works && <p className="text-red-600/70 dark:text-red-400/70 mt-0.5">{scam.how_it_works}</p>}
              {scam.how_to_avoid && <p className="text-emerald-600 dark:text-emerald-400 mt-1">✓ {scam.how_to_avoid}</p>}
            </div>
          ))}
        </div>
      )}
      {h.str('taxi_scam_tip') && (
        <p className="text-xs p-2 rounded bg-zinc-50 dark:bg-zinc-800/50">🚕 {h.str('taxi_scam_tip')}</p>
      )}
      {h.str('general_advice') && (
        <p className="text-xs italic text-zinc-500">{h.str('general_advice')}</p>
      )}
    </div>
  );
}

export function renderPacking(h: SectionDataHelpers) {
  const mustPack = h.arr('must_pack') as string[];
  const dontBring = h.arr('dont_bring') as string[];
  const electrical = h.obj('electrical');
  const plugType = typeof electrical.plug_type === 'string' ? electrical.plug_type : '';
  const voltage = typeof electrical.voltage === 'string' ? electrical.voltage : '';
  const adapterNeeded = typeof electrical.adapter_needed === 'boolean' ? electrical.adapter_needed : false;
  return (
    <div className="pt-2 space-y-2">
      {mustPack.length > 0 && (
        <div>
          <p className="font-medium text-emerald-600 dark:text-emerald-400 text-xs uppercase">✓ Must Pack</p>
          <ul className="list-disc list-inside space-y-0.5 text-xs">
            {mustPack.map((p, i) => <li key={`${p}-${i}`}>{p}</li>)}
          </ul>
        </div>
      )}
      {dontBring.length > 0 && (
        <div>
          <p className="font-medium text-red-600 dark:text-red-400 text-xs uppercase mt-2">✗ Don&apos;t Bring</p>
          <ul className="list-disc list-inside space-y-0.5 text-xs">
            {dontBring.map((p, i) => <li key={`${p}-${i}`}>{p}</li>)}
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
