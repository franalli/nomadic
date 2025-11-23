'use client';

import { MapPin, Sparkles } from 'lucide-react';

import type { PlanBranch } from '@/types/plan';

type TileCounts = Record<'stays' | 'flights' | 'activities', number>;

const TILE_BADGE_LABELS: Record<keyof TileCounts, string> = {
  stays: 'Stays',
  flights: 'Flights',
  activities: 'Activities',
};

type BranchDetails = {
  vibe: string;
  duration: string;
  budget: string;
  focus: string;
  heroImages: string[];
  highlights: string[];
  flow: string[];
  notes: string[];
};

const DETAIL_PRESETS: BranchDetails[] = [
  {
    vibe: 'Coastal hikes + harbor nights',
    duration: '5-7 days',
    budget: '$$ to $$$',
    focus: 'Sea cliffs, seafood, slower mornings',
    heroImages: [
      'https://images.unsplash.com/photo-1507525428034-b723cf961d3e?auto=format&fit=crop&w=1600&q=80',
      'https://images.unsplash.com/photo-1505761671935-60b3a7427bad?auto=format&fit=crop&w=900&q=80',
      'https://images.unsplash.com/photo-1476610182048-b716b8518aae?auto=format&fit=crop&w=900&q=80',
    ],
    highlights: [
      'Cliff walk sunrise above {destination}',
      'Seafood tastings and harbor-side cafes',
      'Hidden coves for late-afternoon swims',
    ],
    flow: [
      'Day 1-2: Settle in, coastal trail, market dinner with ocean views',
      'Day 3-4: Island-hop by boat, snorkel bays, sunset sail back',
      'Day 5+: Bike shoreline villages, picnic on quieter beaches',
    ],
    notes: [
      'Pack layers — breezy nights near the water',
      'Book small boats 24h ahead in peak season',
      'Carry small cash for seaside cafes and bakeries',
    ],
  },
  {
    vibe: 'Alpine lakes + ridgeline views',
    duration: '6-9 days',
    budget: '$$',
    focus: 'Hikes, hut-to-hut stays, glacier viewpoints',
    heroImages: [
      'https://images.unsplash.com/photo-1501785888041-af3ef285b470?auto=format&fit=crop&w=1600&q=80',
      'https://images.unsplash.com/photo-1500530855697-b586d89ba3ee?auto=format&fit=crop&w=900&q=80',
      'https://images.unsplash.com/photo-1489515217757-5fd1be406fef?auto=format&fit=crop&w=900&q=80',
    ],
    highlights: [
      'Ridgeline hike above {destination} with alpine lakes',
      'Cable car to glacier terrace at golden hour',
      'Hut dinner with local cheese and mountain herbs',
    ],
    flow: [
      'Day 1-2: Warm-up lake loops, cable car summit, spa evening',
      'Day 3-5: Two-night hut circuit with panoramic ridges',
      'Day 6+: Slow day in valley villages, farm-to-table tasting',
    ],
    notes: [
      'Reserve huts 2-3 weeks out for best dorms',
      'Weather flips fast — light shell + microspikes recommended',
      'Transit pass covers lifts and valley buses',
    ],
  },
  {
    vibe: 'Design-forward city break',
    duration: '4-6 days',
    budget: '$$ to $$$',
    focus: 'Boutique stays, galleries, night markets',
    heroImages: [
      'https://images.unsplash.com/photo-1467269204594-9661b134dd2b?auto=format&fit=crop&w=1600&q=80',
      'https://images.unsplash.com/photo-1441986300917-64674bd600d8?auto=format&fit=crop&w=900&q=80',
      'https://images.unsplash.com/photo-1440404653325-ab127d49abb4?auto=format&fit=crop&w=900&q=80',
    ],
    highlights: [
      'Neighborhood coffee crawl across {destination}',
      'Evening street food and design market stop',
      'Modern art wing + rooftop aperitivo',
    ],
    flow: [
      'Day 1: Settle into boutique stay, sunset walk through old town',
      'Day 2-3: Gallery hop, chef-led dinner, night market shopping',
      'Day 4+: Day trip to nearby coast/vineyards, late train back',
    ],
    notes: [
      'Prebook timed gallery entries on weekends',
      'Most cafes cashless; markets prefer small notes',
      'Ride share + metro combo is fastest across districts',
    ],
  },
  {
    vibe: 'Desert canyons + stargazing',
    duration: '5-8 days',
    budget: '$ to $$',
    focus: 'Red rock vistas, slot canyons, campfire nights',
    heroImages: [
      'https://images.unsplash.com/photo-1500530855697-b586d89ba3ee?auto=format&fit=crop&w=1600&q=80',
      'https://images.unsplash.com/photo-1500534314209-a25ddb2bd429?auto=format&fit=crop&w=900&q=80',
      'https://images.unsplash.com/photo-1501004318641-b39e6451bec6?auto=format&fit=crop&w=900&q=80',
    ],
    highlights: [
      'Slot canyon walk at sunrise outside {destination}',
      '4x4 trail to overlook for sunset charcuterie',
      'Stargazing pad with hot chocolate under clear skies',
    ],
    flow: [
      'Day 1-2: Canyon rim hikes, settle into casita or camp',
      'Day 3-4: Guided slot canyon + night sky session',
      'Day 5+: Scenic byway drive, desert hot springs wind-down',
    ],
    notes: [
      'Hydrate constantly — dry air sneaks up fast',
      'Permits required for some canyon slots — secure early',
      'Cool nights — pack a light puffer even in summer',
    ],
  },
];

type BranchPanelProps = {
  branches: PlanBranch[];
  selectedBranchId: string | null;
  onBranchSelect: (branchId: string) => void;
  branchTileCounts?: Record<string, TileCounts>;
  onBookTrip?: (branchId: string) => void;
  canBookTrip?: boolean;
};

export function BranchPanel({
  branches,
  selectedBranchId,
  onBranchSelect,
  branchTileCounts,
  onBookTrip,
  canBookTrip = true,
}: BranchPanelProps) {
  if (!branches.length) {
    return (
      <div className="rounded-2xl border border-dashed border-primary/30 bg-primary/5 p-4 text-sm text-muted-foreground shadow-inner">
        Trip ideas will appear here after you plan a trip.
      </div>
    );
  }

  const selected = branches.find((b) => b.id === selectedBranchId) ?? branches[0];
  const selectedIndex = Math.max(
    0,
    branches.findIndex((branch) => branch.id === selected.id)
  );
  const detailPreset = DETAIL_PRESETS[selectedIndex % DETAIL_PRESETS.length];
  const countsForSelected = branchTileCounts?.[selected.id];
  const hasTileCounts =
    countsForSelected && Object.values(countsForSelected).some((value) => value > 0);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-2">
        {branches.map((b, idx) => {
          const isActive = b.id === selected.id;
          return (
            <button
              key={b.id}
              type="button"
              onClick={() => onBranchSelect(b.id)}
              className={
                'rounded-full border px-3 py-2 text-xs font-semibold transition focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary ' +
                (isActive
                  ? 'border-primary/70 bg-primary text-primary-foreground shadow-lg shadow-primary/25'
                  : 'border-border/40 bg-white/5 text-muted-foreground hover:border-primary/40 hover:text-foreground')
              }
            >
              <span className="mr-1 opacity-70">Suggestion {idx + 1} ·</span> {b.label}
            </button>
          );
        })}
      </div>

      <div className="relative overflow-hidden rounded-2xl border border-white/10 bg-gradient-to-br from-white/5 via-card/80 to-background shadow-lg backdrop-blur">
        <div className="pointer-events-none absolute -right-24 -top-12 h-48 w-48 rounded-full bg-primary/20 blur-3xl" />
        <div className="pointer-events-none absolute bottom-0 left-0 h-36 w-36 rounded-full bg-accent/15 blur-2xl" />
        <div className="relative space-y-5 p-4 sm:p-5">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="space-y-1">
              <p className="text-xs font-semibold uppercase tracking-wide text-primary">
                Selected suggestion
              </p>
              <h4 className="text-foreground font-display text-2xl font-bold">
                {selected.destination}
              </h4>
              {selected.description && (
                <p className="text-muted-foreground text-sm leading-relaxed">
                  {selected.description}
                </p>
              )}
              {hasTileCounts && countsForSelected && (
                <div className="flex flex-wrap gap-2 pt-1 text-[11px] font-semibold uppercase tracking-wide text-foreground">
                  {(Object.keys(TILE_BADGE_LABELS) as Array<keyof TileCounts>).map((key) => (
                    <span
                      key={key}
                      className="inline-flex items-center gap-1 rounded-full bg-black/15 px-3 py-1 text-white shadow-sm backdrop-blur"
                    >
                      <span className="h-1.5 w-1.5 rounded-full bg-accent" />
                      {TILE_BADGE_LABELS[key]}
                      <span className="rounded bg-white/10 px-2 py-0.5 text-[10px]">
                        {countsForSelected[key] ?? 0}
                      </span>
                    </span>
                  ))}
                </div>
              )}
            </div>
            <div className="inline-flex items-center gap-2 rounded-full bg-black/20 px-3 py-1 text-xs font-semibold text-white shadow-sm backdrop-blur">
              <Sparkles className="h-4 w-4 text-accent" />
              {selected.label}
            </div>
          </div>

          <div className="flex flex-wrap gap-2 text-xs text-muted-foreground">
            <span className="inline-flex items-center gap-1 rounded-full bg-black/10 px-3 py-1 font-medium text-foreground/80">
              <MapPin className="h-3 w-3" />
              {selected.destination}
            </span>
            <span className="rounded-full bg-white/5 px-3 py-1 font-medium text-foreground/80">
              Suggestion {selectedIndex + 1} of {branches.length}
            </span>
            <span className="rounded-full bg-white/5 px-3 py-1 font-medium text-foreground/80">
              {detailPreset.vibe}
            </span>
          </div>

          <div className="space-y-5">
            <div className="space-y-3">
              <div className="overflow-hidden rounded-xl border border-white/10 bg-black/20 shadow-inner">
                <div className="relative aspect-video">
                  <img
                    src={detailPreset.heroImages[0]}
                    alt={`${selected.destination} overview`}
                    className="h-full w-full object-cover"
                  />
                  <div className="absolute inset-0 bg-gradient-to-tr from-black/30 via-transparent to-black/10" />
                  <div className="absolute left-3 top-3 rounded-full bg-white/15 px-3 py-1 text-xs font-semibold text-white backdrop-blur">
                    Signature view
                  </div>
                </div>
              </div>
              <div className="overflow-hidden rounded-xl border border-white/10 bg-black/20 shadow-inner">
                <div className="relative aspect-[16/9]">
                  <img
                    src={detailPreset.heroImages[1]}
                    alt={`${selected.destination} detail`}
                    className="h-full w-full object-cover"
                  />
                  <div className="absolute bottom-2 left-2 rounded-full bg-black/40 px-2 py-1 text-[10px] font-semibold uppercase tracking-wide text-white">
                    Daylight wander
                  </div>
                </div>
              </div>
              <div className="overflow-hidden rounded-xl border border-white/10 bg-black/20 shadow-inner">
                <div className="relative aspect-[16/9]">
                  <img
                    src={detailPreset.heroImages[2]}
                    alt={`${selected.destination} night detail`}
                    className="h-full w-full object-cover"
                  />
                  <div className="absolute bottom-2 right-2 rounded-full bg-black/40 px-2 py-1 text-[10px] font-semibold uppercase tracking-wide text-white">
                    Evening vibe
                  </div>
                </div>
              </div>
            </div>

            <div className="grid gap-3 sm:grid-cols-2">
              <div className="rounded-xl border border-white/10 bg-white/5 p-3 text-sm shadow-sm">
                <p className="text-muted-foreground text-xs font-semibold uppercase tracking-wide">
                  Ideal duration
                </p>
                <p className="text-foreground font-semibold">{detailPreset.duration}</p>
                <p className="text-muted-foreground text-xs">
                  Enough time to see the best corners without rushing.
                </p>
              </div>
              <div className="rounded-xl border border-white/10 bg-white/5 p-3 text-sm shadow-sm">
                <p className="text-muted-foreground text-xs font-semibold uppercase tracking-wide">
                  Budget feel
                </p>
                <p className="text-foreground font-semibold">{detailPreset.budget}</p>
                <p className="text-muted-foreground text-xs">
                  Mix of local eats and a couple splurge moments.
                </p>
              </div>
              <div className="rounded-xl border border-white/10 bg-white/5 p-3 text-sm shadow-sm">
                <p className="text-muted-foreground text-xs font-semibold uppercase tracking-wide">
                  Focus
                </p>
                <p className="text-foreground font-semibold">{detailPreset.focus}</p>
                <p className="text-muted-foreground text-xs">
                  What this itinerary leans into most.
                </p>
              </div>
              <div className="rounded-xl border border-white/10 bg-white/5 p-3 text-sm shadow-sm">
                <p className="text-muted-foreground text-xs font-semibold uppercase tracking-wide">
                  Trip tempo
                </p>
                <p className="text-foreground font-semibold">{detailPreset.vibe}</p>
                <p className="text-muted-foreground text-xs">
                  Balance of adventure and recovery time.
                </p>
              </div>
            </div>

            <div className="space-y-3">
              <div className="rounded-xl border border-white/10 bg-white/5 p-3 shadow-sm">
                <div className="flex items-center justify-between">
                  <p className="text-muted-foreground text-xs font-semibold uppercase tracking-wide">
                    Highlights
                  </p>
                  <span className="text-muted-foreground text-[11px] font-semibold uppercase tracking-wide">
                    Curated
                  </span>
                </div>
                <ul className="mt-2 space-y-2 text-sm text-foreground">
                  {detailPreset.highlights.map((item) => (
                    <li key={item} className="flex gap-2">
                      <span className="mt-1 h-1.5 w-1.5 rounded-full bg-accent" />
                      <span>{item.replace('{destination}', selected.destination)}</span>
                    </li>
                  ))}
                </ul>
              </div>
              <div className="rounded-xl border border-white/10 bg-white/5 p-3 shadow-sm">
                <div className="flex items-center justify-between">
                  <p className="text-muted-foreground text-xs font-semibold uppercase tracking-wide">
                    Suggested flow
                  </p>
                  <span className="text-muted-foreground text-[11px] font-semibold uppercase tracking-wide">
                    Day-by-day
                  </span>
                </div>
                <ul className="mt-2 space-y-2 text-sm text-foreground">
                  {detailPreset.flow.map((item, idx) => (
                    <li
                      key={item}
                      className="rounded-lg border border-white/10 bg-black/10 px-3 py-2"
                    >
                      <span className="text-xs font-semibold uppercase tracking-wide text-primary">
                        Day {idx + 1}
                      </span>
                      <p className="text-sm text-foreground">{item}</p>
                    </li>
                  ))}
                </ul>
              </div>
            </div>

            <div className="rounded-xl border border-white/10 bg-white/5 p-3 shadow-sm">
              <div className="flex items-center justify-between gap-3">
                <p className="text-muted-foreground text-xs font-semibold uppercase tracking-wide">
                  On-the-ground notes
                </p>
                <span className="rounded-full bg-black/10 px-2 py-1 text-[10px] font-semibold uppercase tracking-wide text-foreground/80">
                  Arrival tips
                </span>
              </div>
              <div className="mt-2 space-y-2 text-sm text-foreground">
                {detailPreset.notes.map((note) => (
                  <div
                    key={note}
                    className="rounded-lg border border-white/10 bg-black/10 px-3 py-2"
                  >
                    {note}
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      </div>

      <div className="flex justify-end">
        <button
          type="button"
          onClick={() => canBookTrip && onBookTrip?.(selected.id)}
          disabled={!canBookTrip}
          className={`rounded-full px-5 py-2 text-sm font-semibold transition focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary ${
            canBookTrip
              ? 'bg-primary text-primary-foreground shadow-lg shadow-primary/40 hover:bg-primary/90'
              : 'cursor-not-allowed bg-muted text-muted-foreground shadow-inner'
          }`}
        >
          Book Your Trip
        </button>
      </div>
    </div>
  );
}
