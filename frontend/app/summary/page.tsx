'use client';

import { ArrowLeft, Plane, Sparkles } from 'lucide-react';
import Link from 'next/link';
import { useEffect, useMemo, useState } from 'react';

import { TileCard } from '@/components/tiles/TileCard';
import { loadTripSummary } from '@/lib/summary';
import type { TripSummaryPayload } from '@/types/summary';
import type { Tile } from '@/types/tile';

export default function SummaryPage() {
  const [summary, setSummary] = useState<TripSummaryPayload | null>(null);

  useEffect(() => {
    const payload = loadTripSummary();
    if (payload) {
      setSummary({
        ...payload,
        selection: {
          ...payload.selection,
          activities: payload.selection.activities ?? [],
        },
      });
    }
  }, []);

  const selectedTiles = useMemo(() => {
    if (!summary) return [];
    const picks: Tile[] = [];
    if (summary.selection.stay) picks.push(summary.selection.stay);
    if (summary.selection.flight) {
      const exists = picks.some((tile) => tile.id === summary.selection.flight?.id);
      if (!exists) picks.push(summary.selection.flight);
    }
    summary.selection.activities.forEach((activity) => {
      if (!picks.some((tile) => tile.id === activity.id)) {
        picks.push(activity);
      }
    });
    return picks;
  }, [summary]);

  if (!summary) {
    return (
      <div className="bg-background text-foreground min-h-screen">
        <div className="mx-auto flex max-w-3xl flex-col items-center gap-6 px-4 py-16 text-center">
          <div className="space-y-2">
            <p className="text-muted-foreground text-sm uppercase tracking-wide">
              Trip summary
            </p>
            <h1 className="font-display text-4xl font-bold">No trip summary yet</h1>
            <p className="text-muted-foreground text-base">
              Pick a suggestion in the planner and tap “Book Your Trip” to generate a
              summary.
            </p>
          </div>
          <Link
            href="/"
            className="bg-primary hover:bg-primary/90 text-primary-foreground rounded-full px-5 py-2 text-sm font-semibold transition"
          >
            Return to planner
          </Link>
        </div>
      </div>
    );
  }

  const { branch, selection } = summary;
  const mapSrc = (() => {
    const { origin, destinations } = branch;
    const destination = destinations?.[0] ?? null;
    if (origin && destination) {
      return `https://maps.google.com/maps?output=embed&f=d&source=embed&saddr=${encodeURIComponent(
        origin
      )}&daddr=${encodeURIComponent(destination)}&z=2`;
    }
    const query = destination || origin || 'World map';
    return `https://maps.google.com/maps?q=${encodeURIComponent(query)}&t=&ie=UTF8&iwloc=&output=embed`;
  })();

  // selectedTiles already contains only the selected items

  return (
    <div className="bg-background text-foreground min-h-screen">
      <div className="mx-auto flex w-full max-w-5xl flex-col gap-6 px-4 py-10">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div className="space-y-1">
            <Link
              href="/"
              className="text-muted-foreground hover:text-foreground inline-flex items-center gap-2 text-sm font-semibold uppercase tracking-wide"
            >
              <ArrowLeft className="h-4 w-4" />
              Back to planner
            </Link>
            <h1 className="font-display text-3xl font-bold">Trip summary</h1>
          </div>
          <div className="bg-primary/10 text-primary inline-flex items-center gap-2 rounded-full px-4 py-2 text-sm font-semibold">
            <Sparkles className="h-4 w-4" />
            {branch.destinations.join(', ') || 'TBD'}
          </div>
        </div>

        <div className="grid gap-4 md:grid-cols-[1fr_0.9fr]">
          <div className="bg-card/90 rounded-2xl border border-white/10 p-5 shadow-lg">
            <div className="flex items-center gap-2">
              <Sparkles className="text-primary h-4 w-4" />
              <p className="text-primary text-xs font-semibold uppercase tracking-wide">
                Saved picks
              </p>
            </div>
            <div className="mt-3 space-y-3 text-sm">
              {['Stay', 'Flight'].map((label) => {
                const tile = label === 'Stay' ? selection.stay : selection.flight;
                return (
                  <div
                    key={label}
                    className="border-border/50 bg-background/60 rounded-lg border p-3 shadow-inner"
                  >
                    <p className="text-muted-foreground text-xs font-semibold uppercase tracking-wide">
                      {label}
                    </p>
                    {tile ? (
                      <>
                        <p className="text-foreground mt-1 font-semibold">{tile.title}</p>
                        {tile.subtitle && (
                          <p className="text-muted-foreground text-xs">{tile.subtitle}</p>
                        )}
                      </>
                    ) : (
                      <p className="text-muted-foreground mt-1">
                        No {label.toLowerCase()} selected yet.
                      </p>
                    )}
                  </div>
                );
              })}
              <div className="border-border/50 bg-background/60 rounded-lg border p-3 shadow-inner">
                <p className="text-muted-foreground text-xs font-semibold uppercase tracking-wide">
                  Activities
                </p>
                {selection.activities.length === 0 ? (
                  <p className="text-muted-foreground mt-1">
                    No activities selected yet.
                  </p>
                ) : (
                  <ul className="mt-2 space-y-1">
                    {selection.activities.map((activity) => (
                      <li
                        key={activity.id}
                        className="text-foreground text-sm font-semibold"
                      >
                        {activity.title}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </div>
          </div>

          <div className="bg-card/90 rounded-2xl border border-white/10 p-5 shadow-lg">
            <div className="flex items-center gap-2">
              <Plane className="text-primary h-4 w-4" />
              <p className="text-primary text-xs font-semibold uppercase tracking-wide">
                Itinerary route
              </p>
            </div>
            <p className="text-muted-foreground mt-2 text-sm">
              {branch.origin ? branch.origin : 'Origin TBD'} →{' '}
              {branch.destinations.length > 0 ? branch.destinations.join(', ') : 'Destination TBD'}
            </p>
            <div className="mt-4 flex w-full justify-center">
              <div className="overflow-hidden rounded-xl border border-white/10 shadow-md">
                <iframe
                  title="Trip route map"
                  src={mapSrc}
                  className="h-[300px] w-[300px] border-none"
                  style={{
                    maxWidth: '300px',
                    maxHeight: '300px',
                    minWidth: '300px',
                    minHeight: '300px',
                  }}
                  loading="lazy"
                  referrerPolicy="no-referrer-when-downgrade"
                />
              </div>
            </div>
          </div>
        </div>

        <div className="bg-card/90 rounded-2xl border border-white/10 p-5 shadow-lg">
          <div className="flex items-center gap-2">
            <Sparkles className="text-primary h-4 w-4" />
            <p className="text-primary text-xs font-semibold uppercase tracking-wide">
              Selected booking links
            </p>
          </div>
          <div className="mt-4 grid grid-cols-1 gap-4 md:grid-cols-2">
            {selectedTiles.length === 0 ? (
              <div className="border-border/60 bg-background/50 text-muted-foreground rounded-xl border border-dashed p-4 text-sm md:col-span-2">
                Save at least one stay, flight, or activity in the planner to see it here.
              </div>
            ) : (
              selectedTiles.map((tile) => (
                <TileCard
                  key={tile.id}
                  tile={tile}
                  branchId={branch.id}
                  isSelected={true}
                />
              ))
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
