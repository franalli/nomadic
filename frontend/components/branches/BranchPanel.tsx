'use client';

import { MapPin } from 'lucide-react';
import { memo, useEffect, useMemo, useState } from 'react';

import {
  resolveTabForTile,
  TAB_CONFIG,
  TilesGrid,
  type TileTabKey,
} from '@/components/tiles/TilesGrid';
import { DETAIL_PRESETS } from '@/lib/mocks';
import { formatBudgetDisplay, normalizeBudgetInput } from '@/lib/utils';
import type { DocumentBranch, DocumentTripInputs } from '@/types/document';
import type { Tile, TileSelection } from '@/types/tile';

type TileCounts = Record<'stays' | 'flights' | 'activities', number>;

const DAY_IN_MS = 1000 * 60 * 60 * 24;
const DATE_RANGE_FORMATTER = new Intl.DateTimeFormat('en-US', {
  weekday: 'short',
  month: 'short',
  day: 'numeric',
});

const formatDuration = (start?: string | null, end?: string | null) => {
  if (!start || !end) return null;
  const startDate = new Date(start);
  const endDate = new Date(end);
  if (Number.isNaN(startDate.getTime()) || Number.isNaN(endDate.getTime())) return null;
  const diffMs = endDate.getTime() - startDate.getTime();
  if (diffMs < 0) return null;
  const days = Math.max(1, Math.round(diffMs / DAY_IN_MS));
  const startLabel = DATE_RANGE_FORMATTER.format(startDate);
  const endLabel = DATE_RANGE_FORMATTER.format(endDate);
  const rangeLabel = startLabel === endLabel ? startLabel : `${startLabel} - ${endLabel}`;
  const summary = `${days} day${days === 1 ? '' : 's'}`;
  return { summary, rangeLabel };
};

const resolveDurationForBranch = (
  branch?: DocumentBranch | null,
  inputs?: DocumentTripInputs | null
) => {
  if (!branch) return null;
  return formatDuration(
    branch.start_date ?? inputs?.start_date ?? null,
    branch.end_date ?? inputs?.end_date ?? null
  );
};

const resolveBudgetForBranch = (
  branch?: DocumentBranch | null,
  inputs?: DocumentTripInputs | null
) =>
  normalizeBudgetInput(branch?.budget) ?? normalizeBudgetInput(inputs?.budget);

type BranchPanelProps = {
  branches: DocumentBranch[];
  selectedBranchId: string | null;
  onBranchSelect: (branchId: string) => void;
  branchTileCounts?: Record<string, TileCounts>;
  tiles?: Tile[];
  tilesBranchId?: string | null;
  selectedTiles?: TileSelection;
  onTileToggle?: (tile: Tile, tab: TileTabKey) => void;
  branchSelections?: Record<string, TileSelection>;
  onBookTrip?: (branchId: string) => void;
  canBookTrip?: boolean;
  tripInputs?: DocumentTripInputs | null;
};

export const BranchPanel = memo(function BranchPanel({
  branches,
  selectedBranchId,
  onBranchSelect,
  branchTileCounts,
  tiles,
  tilesBranchId,
  selectedTiles,
  onTileToggle,
  branchSelections,
  onBookTrip,
  canBookTrip = true,
  tripInputs,
}: BranchPanelProps) {
  const hasBranches = branches.length > 0;
  const selected = hasBranches
    ? (branches.find((b) => b.id === selectedBranchId) ?? branches[0])
    : null;
  const selectedIndex = hasBranches
    ? Math.max(
        0,
        branches.findIndex((branch) => branch.id === selected?.id)
      )
    : 0;
  const detailPreset = DETAIL_PRESETS[selectedIndex % DETAIL_PRESETS.length];
  const selectedDuration = resolveDurationForBranch(selected, tripInputs);
  const selectedBudget = resolveBudgetForBranch(selected, tripInputs);
  const countsForSelected = selected ? branchTileCounts?.[selected.id] : undefined;
  const branchTiles = useMemo(() => {
    if (!selected) return [];
    if (tilesBranchId == null || tilesBranchId === selected.id) {
      return tiles ?? [];
    }
    return [];
  }, [selected, tiles, tilesBranchId]);
  const isStaleTiles =
    selected != null && tilesBranchId != null && tilesBranchId !== selected.id;
  const hasTilesForSelected = branchTiles.length > 0;
  const [openTab, setOpenTab] = useState<TileTabKey | null>('stays');
  const selectedBranchSelection = selected
    ? (branchSelections?.[selected.id] ?? { activities: [] })
    : { activities: [] };
  const hasLockedSelection =
    Boolean(selectedBranchSelection.stay) ||
    Boolean(selectedBranchSelection.flight) ||
    (selectedBranchSelection.activities?.length ?? 0) > 0;

  // Calculate estimated total for selected tiles
  const selectedTotal = useMemo(() => {
    const selection = selectedTiles ?? { activities: [] };
    const prices: number[] = [];
    let currency = '';

    if (selection.stay?.price_estimate != null) {
      prices.push(selection.stay.price_estimate);
      currency = currency || selection.stay.currency;
    }
    if (selection.flight?.price_estimate != null) {
      prices.push(selection.flight.price_estimate);
      currency = currency || selection.flight.currency;
    }
    for (const activity of selection.activities ?? []) {
      if (activity.price_estimate != null) {
        prices.push(activity.price_estimate);
        currency = currency || activity.currency;
      }
    }

    if (prices.length === 0) return null;
    const total = prices.reduce((sum, p) => sum + p, 0);
    return { total, currency, count: prices.length };
  }, [selectedTiles]);

  useEffect(() => {
    if (selected?.id) {
      setOpenTab('stays');
    }
  }, [selected?.id]);

  const tilesByTab = useMemo(() => {
    return branchTiles.reduce(
      (acc, tile) => {
        const tab = resolveTabForTile(tile);
        acc[tab].push(tile);
        return acc;
      },
      { stays: [], flights: [], activities: [] } as Record<TileTabKey, Tile[]>
    );
  }, [branchTiles]);

  const bookingSummary = useMemo(() => {
    const destination = selected?.destinations[0] ?? tripInputs?.destinations[0] ?? 'your trip';
    const origin = selected?.origin ?? tripInputs?.origin ?? null;
    const adults = selected?.adults ?? tripInputs?.adults ?? null;
    const children = selected?.children ?? tripInputs?.children ?? null;
    const travelerParts: string[] = [];
    if (adults != null && adults > 0) travelerParts.push(`${adults} adult${adults === 1 ? '' : 's'}`);
    if (children != null && children > 0) travelerParts.push(`${children} child${children === 1 ? '' : 'ren'}`);
    const travelerLabel = travelerParts.length > 0 ? travelerParts.join(', ') : null;
    const dateLabel = selectedDuration?.rangeLabel ?? null;
    const budgetLabel = formatBudgetDisplay(selectedBudget);

    const framingParts = [
      origin && destination ? `${origin} → ${destination}` : destination,
      dateLabel,
      travelerLabel,
      budgetLabel ? `budget ${budgetLabel}` : null,
    ].filter(Boolean);
    const intro = framingParts.length
      ? `Based on your latest notes (${framingParts.join(' · ')}), here's where bookings sit.`
      : "Here's where the booking picks sit.";

    const labelForTab = (tab: TileTabKey) => {
      if (tab === 'stays') return 'Hotels';
      if (tab === 'flights') return 'Flights';
      return 'Activities';
    };

    const describeCategory = (tab: TileTabKey, selections: Tile[]): string => {
      const label = labelForTab(tab);
      const options = tilesByTab[tab];
      const optionCount = options.length || countsForSelected?.[tab] || 0;

      if (selections.length > 0) {
        const [first] = selections;
        const extras = selections.length - 1;
        const extraText = extras > 0 ? ` +${extras} more` : '';
        return `${label}: locked ${first.title}${extraText} to match what you asked for.`;
      }

      if (optionCount > 0) {
        const highlight = options[0]?.title;
        const routeHint =
          tab === 'flights' && (origin || destination)
            ? ` for ${origin ? `${origin} → ` : ''}${destination}`
            : '';
        const highlightText = highlight ? `; leading pick ${highlight}` : '';
        return `${label}: ${optionCount} option${optionCount === 1 ? '' : 's'} ready${routeHint}${highlightText}.`;
      }

      return `${label}: still searching—no matches yet, but I'll refresh this branch as results land.`;
    };

    const stayLine = describeCategory(
      'stays',
      selectedTiles?.stay ? [selectedTiles.stay] : []
    );
    const flightLine = describeCategory(
      'flights',
      selectedTiles?.flight ? [selectedTiles.flight] : []
    );
    const activityLine = describeCategory('activities', selectedTiles?.activities ?? []);

    return [intro, stayLine, flightLine, activityLine].join(' ');
  }, [
    countsForSelected,
    selected,
    selectedBudget,
    selectedDuration,
    selectedTiles,
    tilesByTab,
    tripInputs,
  ]);

  if (!hasBranches) {
    return (
      <div className="border-primary/30 bg-primary/5 text-muted-foreground rounded-2xl border border-dashed p-4 text-sm shadow-inner">
        Trip ideas will appear here after you plan a trip.
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="space-y-2">
        <p className="text-muted-foreground text-xs font-semibold uppercase tracking-wide">
          Trip options
        </p>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {branches.map((b, idx) => {
            const isActive = selected !== null && b.id === selected.id;
            const preset = DETAIL_PRESETS[idx % DETAIL_PRESETS.length];
            const selection = branchSelections?.[b.id] ?? { activities: [] };
            const statusReady =
              Boolean(selection.stay) ||
              Boolean(selection.flight) ||
              (selection.activities?.length ?? 0) > 0;
            const badgeLabel = statusReady ? 'Ready' : 'Customizing';
            const badgeColor = statusReady ? 'bg-green-500' : 'bg-orange-500';
            const badgeTextColor = 'text-white';
            const budget = resolveBudgetForBranch(b, tripInputs) ?? preset.budget;
            const budgetLabel = formatBudgetDisplay(budget) ?? preset.budget;
            const duration =
              resolveDurationForBranch(b, tripInputs)?.summary ?? preset.duration;
            return (
              <button
                key={b.id}
                type="button"
                onClick={() => onBranchSelect(b.id)}
                className={`focus-visible:outline-primary relative overflow-hidden rounded-2xl border text-left shadow-lg transition hover:translate-y-[-2px] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 ${
                  isActive
                    ? 'ring-accent border-accent shadow-accent/20 ring-2'
                    : 'border-border/40'
                }`}
              >
                <div
                  className="h-full w-full"
                  style={{
                    backgroundImage: `linear-gradient(180deg, rgba(0,0,0,0.05) 0%, rgba(0,0,0,0.55) 100%), url(${preset.heroImages[0]})`,
                    backgroundSize: 'cover',
                    backgroundPosition: 'center',
                  }}
                >
                  <div className="flex h-full flex-col justify-between gap-3 p-4">
                    <div className="flex flex-wrap items-start justify-between gap-2">
                      <span
                        className={`${badgeColor} ${badgeTextColor} inline-flex shrink-0 items-center gap-2 rounded-full px-3 py-1 text-[11px] font-semibold uppercase tracking-wide shadow-md`}
                      >
                        {badgeLabel}
                      </span>
                      <span className="shrink-0 rounded-full bg-black/30 px-2 py-1 text-[11px] font-semibold text-white">
                        Suggestion {idx + 1}
                      </span>
                    </div>
                    <div className="space-y-2 text-white">
                      <p className="text-lg font-bold leading-tight">{b.destinations.join(', ') || 'TBD'}</p>
                      <p className="line-clamp-2 text-sm opacity-90">
                        {b.description ||
                          preset.highlights[0].replace('{destination}', b.destinations[0] || 'your destination')}
                      </p>
                      <div className="mt-2 flex flex-wrap items-center justify-between gap-2 text-sm font-semibold">
                        <span>{duration}</span>
                        <span>{budgetLabel}</span>
                      </div>
                    </div>
                  </div>
                </div>
              </button>
            );
          })}
        </div>
      </div>

      <div className="via-card/80 to-background relative overflow-hidden rounded-2xl border border-white/10 bg-gradient-to-br from-white/5 shadow-lg backdrop-blur">
        <div className="bg-primary/20 pointer-events-none absolute -right-24 -top-12 h-48 w-48 rounded-full blur-3xl" />
        <div className="bg-accent/15 pointer-events-none absolute bottom-0 left-0 h-36 w-36 rounded-full blur-2xl" />
        <div className="relative space-y-5 p-4 sm:p-5">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="space-y-1">
              <p className="text-primary text-xs font-semibold uppercase tracking-wide">
                Selected suggestion
              </p>
              <div className="flex items-center gap-2">
                <MapPin className="text-primary h-5 w-5" aria-hidden="true" />
                <h4 className="text-foreground font-display text-2xl font-bold">
                  {selected?.destinations.join(', ') || 'Unknown Destination'}
                </h4>
              </div>
              {selected?.description && (
                <p className="text-muted-foreground text-sm leading-relaxed">
                  {selected.description}
                </p>
              )}
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-4 pb-1">
            {(Object.keys(TAB_CONFIG) as TileTabKey[]).map((tabKey) => {
              const isOpen = openTab === tabKey;
              const count = countsForSelected?.[tabKey] ?? 0;
              const Icon = TAB_CONFIG[tabKey].icon;
              return (
                <button
                  key={tabKey}
                  type="button"
                  onClick={() => setOpenTab((prev) => (prev === tabKey ? null : tabKey))}
                  className={`focus-visible:outline-primary group relative flex items-center gap-2 border-b-2 pb-2 text-sm font-semibold transition focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 ${
                    isOpen
                      ? 'border-primary text-primary'
                      : 'text-muted-foreground hover:text-foreground border-transparent'
                  }`}
                  aria-pressed={isOpen}
                >
                  <span
                    className={`flex h-8 w-8 items-center justify-center rounded-full border transition ${
                      isOpen
                        ? 'border-primary/30 bg-primary/10 text-primary'
                        : 'border-border/70 text-muted-foreground bg-white'
                    }`}
                  >
                    <Icon className="h-4 w-4" aria-hidden="true" />
                  </span>
                  <span>{TAB_CONFIG[tabKey].label}</span>
                  <span
                    className={`rounded-full px-2 py-0.5 text-[11px] font-semibold ${
                      isOpen
                        ? 'bg-emerald-100 text-emerald-700'
                        : 'bg-muted text-muted-foreground'
                    }`}
                  >
                    {count}
                  </span>
                </button>
              );
            })}
          </div>

          <div
            className={`rounded-2xl ${
              openTab === null
                ? 'border-none bg-transparent p-0 shadow-none'
                : 'to-background border border-white/10 bg-gradient-to-br from-black/30 via-white/5 p-4 shadow-inner'
            }`}
          >
            {openTab === null ? null : isStaleTiles && !hasTilesForSelected ? (
              <div className="border-primary/30 bg-primary/5 text-muted-foreground rounded-xl border border-dashed p-4 text-sm shadow-inner">
                Switch to this suggestion to refresh matching options.
              </div>
            ) : tilesByTab[openTab]?.length ? (
              <TilesGrid
                tiles={branchTiles}
                activeBranch={selected}
                selectedTiles={selectedTiles}
                onTileToggle={(tile) => onTileToggle?.(tile, openTab)}
                forcedTab={openTab}
                hideTabSwitcher
              />
            ) : (
              <div className="border-border/60 text-muted-foreground rounded-xl border border-dashed bg-black/10 p-4 text-sm shadow-inner">
                No {TAB_CONFIG[openTab].label.toLowerCase()} yet for this suggestion.
                Check back after options refresh.
              </div>
            )}
          </div>

          <div className="space-y-5">
            <div className="rounded-xl border border-white/10 bg-white/5 p-3 shadow-sm">
              <p className="text-muted-foreground text-xs font-semibold uppercase tracking-wide">
                Booking summary
              </p>
              <p className="text-foreground mt-2 text-sm">{bookingSummary}</p>
            </div>

            <div className="grid grid-cols-3 gap-3">
              <div className="overflow-hidden rounded-xl border border-white/10 bg-black/20 shadow-inner">
                <div className="relative aspect-video">
                  <img
                    src={detailPreset.heroImages[0]}
                    alt={`${selected?.destinations[0] ?? 'Destination'} overview`}
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
                    alt={`${selected?.destinations[0] ?? 'Destination'} detail`}
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
                    alt={`${selected?.destinations[0] ?? 'Destination'} night detail`}
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
                <p className="text-foreground font-semibold">
                  {selectedDuration
                    ? `${selectedDuration.summary} · ${selectedDuration.rangeLabel}`
                    : detailPreset.duration}
                </p>
                <p className="text-muted-foreground text-xs">
                  Enough time to see the best corners without rushing.
                </p>
              </div>
              <div className="rounded-xl border border-white/10 bg-white/5 p-3 text-sm shadow-sm">
                <p className="text-muted-foreground text-xs font-semibold uppercase tracking-wide">
                  Budget feel
                </p>
                <p className="text-foreground font-semibold">
                  {formatBudgetDisplay(selectedBudget) ?? detailPreset.budget}
                </p>
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
                <ul className="text-foreground mt-2 space-y-2 text-sm">
                  {detailPreset.highlights.map((item) => (
                    <li key={item} className="flex gap-2">
                      <span className="bg-accent mt-1 h-1.5 w-1.5 rounded-full" />
                      <span>
                        {item.replace(
                          '{destination}',
                          selected?.destinations[0] ?? 'your destination'
                        )}
                      </span>
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
                <ul className="text-foreground mt-2 space-y-2 text-sm">
                  {detailPreset.flow.map((item, idx) => (
                    <li
                      key={item}
                      className="rounded-lg border border-white/10 bg-black/10 px-3 py-2"
                    >
                      <span className="text-primary text-xs font-semibold uppercase tracking-wide">
                        Day {idx + 1}
                      </span>
                      <p className="text-foreground text-sm">{item}</p>
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
                <span className="text-foreground/80 rounded-full bg-black/10 px-2 py-1 text-[10px] font-semibold uppercase tracking-wide">
                  Arrival tips
                </span>
              </div>
              <div className="text-foreground mt-2 space-y-2 text-sm">
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

      <div className="flex items-center justify-between gap-4">
        {selectedTotal && (
          <div className="text-sm">
            <span className="text-muted-foreground">Estimated total: </span>
            <span className="font-semibold text-foreground">
              {Math.round(selectedTotal.total).toLocaleString()} {selectedTotal.currency}
            </span>
            <span className="text-muted-foreground text-xs ml-1">
              ({selectedTotal.count} item{selectedTotal.count === 1 ? '' : 's'})
            </span>
          </div>
        )}
        <button
          type="button"
          onClick={() => {
            if (selected && onBookTrip) {
              onBookTrip(selected.id);
            }
          }}
          disabled={!canBookTrip || !selected}
          className={`focus-visible:outline-primary rounded-full px-5 py-2 text-sm font-semibold transition focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 ${
            !canBookTrip || !selected
              ? 'bg-muted text-muted-foreground cursor-not-allowed shadow-inner'
              : hasLockedSelection
                ? 'bg-orange-500 text-white shadow-lg shadow-orange-400/50 hover:bg-orange-600'
                : 'bg-primary text-primary-foreground shadow-primary/40 hover:bg-primary/90 shadow-lg'
          }`}
        >
          Book Your Trip
        </button>
      </div>
    </div>
  );
});
