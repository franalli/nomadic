import { Copy } from 'lucide-react';
import Link from 'next/link';

import { InteractiveMap } from '@/components/map/InteractiveMap';
import { MapErrorBoundary } from '@/components/map/MapErrorBoundary';
import type { MapPOI } from '@/lib/ghost-timeline-adapter';
import type { StrategySection } from '@/types/plan-envelope';

function getStrategySummary(section: StrategySection): string | null {
  const candidates = [
    section.one_liner,
    section.tradeoffs_summary,
    section.editorial_one_liner,
    section.subtitle,
    section.must_dos?.[0],
    section.principles?.[0],
    section.logistics_notes?.[0],
    section.bullets?.[0],
  ];

  for (const candidate of candidates) {
    if (typeof candidate === 'string' && candidate.trim()) {
      return candidate.trim();
    }
  }
  return null;
}

export function SharedTripErrorState({ error }: { error: string }) {
  return (
    <div className="flex min-h-screen items-center justify-center bg-zinc-950 px-6 text-white">
      <div className="space-y-4 text-center">
        <h1 className="text-xl font-semibold">{error}</h1>
        <Link href="/" className="text-emerald-400 hover:text-emerald-300">
          Plan your own trip →
        </Link>
      </div>
    </div>
  );
}

export function SharedTripLoadingState() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-zinc-950 text-zinc-400">
      Loading trip...
    </div>
  );
}

interface SharedTripHeaderProps {
  title: string;
  dayCount: number | null;
  isForking: boolean;
  onForkTrip: () => void;
}

export function SharedTripHeader({
  title,
  dayCount,
  isForking,
  onForkTrip,
}: SharedTripHeaderProps) {
  return (
    <header className="sticky top-0 z-20 border-b border-white/10 bg-zinc-950/90 px-4 py-3 backdrop-blur">
      <div className="mx-auto flex max-w-5xl items-center justify-between gap-4">
        <div className="min-w-0">
          <h1 className="truncate text-sm font-semibold md:text-base">{title || 'Shared Trip'}</h1>
          <p className="text-[11px] uppercase tracking-widest text-zinc-400">
            Shared Trip{dayCount ? ` · ${dayCount} days` : ''}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={onForkTrip}
            disabled={isForking}
            className="inline-flex items-center gap-1.5 whitespace-nowrap rounded-full border border-white/15 px-3 py-2 text-xs font-semibold text-zinc-200 transition-colors hover:bg-white/10 disabled:cursor-not-allowed disabled:pointer-events-none disabled:opacity-50"
          >
            <Copy className="h-3.5 w-3.5" />
            {isForking ? 'Copying...' : 'Copy This Trip'}
          </button>
          <Link
            href="/"
            className="whitespace-nowrap rounded-full bg-emerald-500 px-4 py-2 text-xs font-bold text-white transition-colors hover:bg-emerald-400"
          >
            Plan Your Own Trip
          </Link>
        </div>
      </div>
    </header>
  );
}

export function SharedTripHeroImage({
  heroImageUrl,
  destination,
}: {
  heroImageUrl: string | null;
  destination: string | null;
}) {
  if (!heroImageUrl) {
    return null;
  }

  return (
    <div className="h-44 overflow-hidden md:h-64">
      <img
        src={heroImageUrl}
        alt={destination || 'Trip destination'}
        className="h-full w-full object-cover"
      />
    </div>
  );
}

export function SharedTripStrategySection({
  strategySections,
}: {
  strategySections: StrategySection[];
}) {
  if (strategySections.length === 0) {
    return null;
  }

  return (
    <section className="rounded-2xl border border-white/10 bg-white/[0.03] p-4">
      <h2 className="mb-2 text-sm font-semibold text-zinc-100">Trip Strategy</h2>
      <div className="space-y-2">
        {strategySections.slice(0, 4).map((section) => (
          <article key={section.id} className="rounded-lg border border-white/10 bg-black/20 p-3">
            <h3 className="text-sm font-medium text-white">
              {section.title || section.specialist_type || 'Strategy'}
            </h3>
            <p className="mt-1 text-sm text-zinc-400">
              {getStrategySummary(section) || 'Details available in the copied plan.'}
            </p>
          </article>
        ))}
      </div>
    </section>
  );
}

const WORLD_MAP_CENTER = { lat: 20, lng: 0, zoom: 2 };

export function SharedTripMapSection({
  mapItems,
  mapCenter,
}: {
  mapItems: MapPOI[];
  mapCenter: { lat: number; lng: number; zoom: number } | null;
}) {
  if (mapItems.length === 0) {
    return null;
  }

  return (
    <section className="rounded-2xl border border-white/10 bg-white/[0.03] p-4">
      <h2 className="mb-4 text-sm font-semibold text-zinc-100">Trip Map</h2>
      <div className="h-[300px] overflow-hidden rounded-xl border border-white/10">
        <MapErrorBoundary className="h-full w-full">
          <InteractiveMap
            items={mapItems}
            activeItemId={null}
            defaultCenter={mapCenter ?? WORLD_MAP_CENTER}
            className="h-full w-full"
            interactive={false}
            showAttribution={false}
          />
        </MapErrorBoundary>
      </div>
    </section>
  );
}
