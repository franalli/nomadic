'use client';

import { Copy } from 'lucide-react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useEffect, useMemo, useState } from 'react';

import { InteractiveMap } from '@/components/map/InteractiveMap';
import { MapErrorBoundary } from '@/components/map/MapErrorBoundary';
import { useToast } from '@/components/ui/toast';
import { apiFetch, fetchSharedTrip } from '@/lib/api';
import { calculateMapCenter, extractPOIsFromDayCards, type MapPOI } from '@/lib/ghost-timeline-adapter';
import type { DayCard, StrategySection } from '@/types/plan-envelope';

import { ReadOnlyTimeline } from './ReadOnlyTimeline';

interface SharedTripSnapshot {
  strategy_sections?: StrategySection[];
  day_cards?: DayCard[];
}

export interface SharedTripData {
  slug: string;
  title: string;
  destination: string | null;
  hero_image_url: string | null;
  day_count: number | null;
  snapshot: SharedTripSnapshot;
  created_at: string;
}

interface SharedTripViewProps {
  slug: string;
  initialData?: SharedTripData | null;
  initialError?: string | null;
}

export function SharedTripView({
  slug,
  initialData = null,
  initialError = null,
}: SharedTripViewProps) {
  const router = useRouter();
  const { toast } = useToast();
  const [data, setData] = useState<SharedTripData | null>(initialData);
  const [error, setError] = useState<string | null>(initialError);
  const [isForking, setIsForking] = useState(false);

  useEffect(() => {
    if (initialData || initialError) return;
    const controller = new AbortController();
    fetchSharedTrip(slug, controller.signal)
      .then((payload) => setData(payload))
      .catch((err) => {
        if (!controller.signal.aborted) {
          setError(err instanceof Error ? err.message : 'Failed to load trip');
        }
      });
    return () => controller.abort();
  }, [initialData, initialError, slug]);

  const strategySections = useMemo(
    () => data?.snapshot?.strategy_sections ?? [],
    [data?.snapshot?.strategy_sections]
  );
  const dayCards = useMemo(
    () => data?.snapshot?.day_cards ?? [],
    [data?.snapshot?.day_cards]
  );
  const mapItems = useMemo<MapPOI[]>(
    () => extractPOIsFromDayCards(dayCards, strategySections, data?.destination ?? undefined),
    [data?.destination, dayCards, strategySections]
  );
  const mapCenter = useMemo(() => calculateMapCenter(mapItems), [mapItems]);

  const handleForkTrip = async () => {
    if (isForking) return;
    setIsForking(true);
    try {
      const primeSession = await apiFetch('/api/chat');
      if (!primeSession.ok) {
        throw new Error('Could not initialize session');
      }

      const forkResponse = await apiFetch(`/api/share/fork/${slug}`, {
        method: 'POST',
      });
      if (!forkResponse.ok) {
        throw new Error('Could not copy trip');
      }

      toast('Trip copied to your workspace', { type: 'success' });
      router.push('/');
    } catch {
      toast('Could not copy trip', { type: 'error' });
      setIsForking(false);
    }
  };

  const getStrategySummary = (section: StrategySection): string | null => {
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
      if (typeof candidate === 'string' && candidate.trim()) return candidate.trim();
    }
    return null;
  };

  if (error) {
    return (
      <div className="min-h-screen bg-zinc-950 text-white flex items-center justify-center px-6">
        <div className="text-center space-y-3">
          <h1 className="text-xl font-semibold">{error}</h1>
          <Link href="/" className="text-emerald-400 hover:text-emerald-300">
            Plan your own trip →
          </Link>
        </div>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="min-h-screen bg-zinc-950 text-zinc-400 flex items-center justify-center">
        Loading trip...
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-zinc-950 text-white">
      <header className="sticky top-0 z-20 border-b border-white/10 bg-zinc-950/90 backdrop-blur px-4 py-3">
        <div className="mx-auto max-w-5xl flex items-center justify-between gap-3">
          <div className="min-w-0">
            <h1 className="text-sm md:text-base font-semibold truncate">{data.title || 'Shared Trip'}</h1>
            <p className="text-[11px] uppercase tracking-widest text-zinc-400">
              Shared Trip{data.day_count ? ` · ${data.day_count} days` : ''}
            </p>
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={handleForkTrip}
              disabled={isForking}
              className="rounded-full border border-white/15 px-3 py-2 text-xs font-semibold text-zinc-200 hover:bg-white/10 transition-colors disabled:pointer-events-none disabled:opacity-50 disabled:cursor-not-allowed whitespace-nowrap inline-flex items-center gap-1.5"
            >
              <Copy className="h-3.5 w-3.5" />
              {isForking ? 'Copying...' : 'Copy This Trip'}
            </button>
            <Link
              href="/"
              className="rounded-full bg-emerald-500 px-4 py-2 text-xs font-bold text-white hover:bg-emerald-400 transition-colors whitespace-nowrap"
            >
              Plan Your Own Trip
            </Link>
          </div>
        </div>
      </header>

      {data.hero_image_url ? (
        <div className="h-44 md:h-64 overflow-hidden">
          <img
            src={data.hero_image_url}
            alt={data.destination || 'Trip destination'}
            className="h-full w-full object-cover"
          />
        </div>
      ) : null}

      <main className="mx-auto max-w-5xl px-4 py-6 space-y-6">
        {strategySections.length > 0 && (
          <section className="rounded-2xl border border-white/10 bg-white/[0.03] p-4">
            <h2 className="text-sm font-semibold text-zinc-100 mb-2">Trip Strategy</h2>
            <div className="space-y-2">
              {strategySections.slice(0, 4).map((section) => (
                <article key={section.id} className="rounded-lg border border-white/10 bg-black/20 p-3">
                  <h3 className="text-sm font-medium text-white">
                    {section.title || section.specialist_type || 'Strategy'}
                  </h3>
                  <p className="text-sm text-zinc-300 mt-1">
                    {getStrategySummary(section) || 'Details available in the copied plan.'}
                  </p>
                </article>
              ))}
            </div>
          </section>
        )}

        {mapItems.length > 0 && (
          <section className="rounded-2xl border border-white/10 bg-white/[0.03] p-4">
            <h2 className="text-sm font-semibold text-zinc-100 mb-3">Trip Map</h2>
            <div className="h-[300px] overflow-hidden rounded-xl border border-white/10">
              <MapErrorBoundary className="h-full w-full">
                <InteractiveMap
                  items={mapItems}
                  activeItemId={null}
                  defaultCenter={mapCenter}
                  className="h-full w-full"
                  interactive={false}
                  showAttribution={false}
                />
              </MapErrorBoundary>
            </div>
          </section>
        )}

        <section>
          <ReadOnlyTimeline dayCards={dayCards} />
        </section>
      </main>
    </div>
  );
}
