'use client';

import { useRouter } from 'next/navigation';
import { useEffect, useMemo, useState } from 'react';

import { useToast } from '@/components/ui/toast';
import { apiFetch, fetchSharedTrip } from '@/lib/api';
import { calculateMapCenter, extractPOIsFromDayCards, type MapPOI } from '@/lib/ghost-timeline-adapter';
import type { DayCard, StrategySection } from '@/types/plan-envelope';

import { ReadOnlyTimeline } from './ReadOnlyTimeline';
import {
  SharedTripErrorState,
  SharedTripHeader,
  SharedTripHeroImage,
  SharedTripLoadingState,
  SharedTripMapSection,
  SharedTripStrategySection,
} from './SharedTripSections';

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

  if (error) {
    return <SharedTripErrorState error={error} />;
  }

  if (!data) {
    return <SharedTripLoadingState />;
  }

  return (
    <div className="min-h-screen bg-zinc-950 text-white">
      <SharedTripHeader
        title={data.title}
        dayCount={data.day_count}
        isForking={isForking}
        onForkTrip={handleForkTrip}
      />
      <SharedTripHeroImage
        heroImageUrl={data.hero_image_url}
        destination={data.destination}
      />

      <main className="mx-auto max-w-5xl px-4 py-6 space-y-6">
        <SharedTripStrategySection strategySections={strategySections} />
        <SharedTripMapSection mapItems={mapItems} mapCenter={mapCenter} />
        <section>
          <ReadOnlyTimeline dayCards={dayCards} />
        </section>
      </main>
    </div>
  );
}
