'use client';

import { ArrowRightLeft, CheckCircle2, MapPin } from 'lucide-react';
import { memo, useEffect, useMemo, useState } from 'react';

import {
  resolveTabForTile,
  TAB_CONFIG,
  TileCardSkeleton,
  TilesGrid,
  type TileTabKey,
} from '@/components/tiles/TilesGrid';
import { Skeleton } from '@/components/ui/skeleton';
import { DETAIL_PRESETS } from '@/lib/mocks';
import { cn , formatBudgetDisplay } from '@/lib/utils';
import type { DocumentBranch, DocumentTripInputs, PlanStatus } from '@/types/document';
import type { Tile, TileSelection } from '@/types/tile';

import { BranchComparisonView } from './BranchComparisonView';
import { ComparisonToggle } from './ComparisonToggle';
import { useComparisonMode } from './hooks/useComparisonMode';

// Skeleton component for branch cards
const BranchCardSkeleton = memo(function BranchCardSkeleton() {
  return (
    <div className="rounded-2xl border border-border/40 bg-card overflow-hidden shadow-lg">
      {/* Hero image skeleton */}
      <Skeleton className="h-40 w-full rounded-none" />
      {/* Content skeleton */}
      <div className="p-4 space-y-3">
        <div className="flex justify-between items-start">
          <Skeleton className="h-5 w-16 rounded-full" />
          <Skeleton className="h-5 w-24 rounded-full" />
        </div>
        <Skeleton className="h-6 w-3/4" />
        <Skeleton className="h-4 w-full" />
        <div className="flex justify-between items-center pt-2">
          <Skeleton className="h-4 w-16" />
          <Skeleton className="h-4 w-20" />
        </div>
      </div>
    </div>
  );
});

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
) => ({
  amount: branch?.budget ?? inputs?.budget ?? null,
  currency: branch?.currency ?? inputs?.currency ?? 'USD',
});

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
  /** Show skeleton loaders while branches are loading */
  isLoading?: boolean;
  /** Callback to show toast notification when tile is selected (Tier 10.19) */
  onSelectionToast?: (message: string) => void;
  /** Plan regeneration status for reactive updates */
  planStatus?: PlanStatus;
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
  isLoading = false,
  onSelectionToast,
  planStatus = 'ready',
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

  // Comparison mode
  const {
    isComparisonMode,
    isComparisonReady,
    isBranchInComparison,
    toggleBranchForComparison,
    canCompare,
  } = useComparisonMode();
  const detailPreset = DETAIL_PRESETS[selectedIndex % DETAIL_PRESETS.length];
  // Use backend data first, fallback to mock presets
  const selectedHeroImages = selected?.hero_images?.length
    ? selected.hero_images
    : detailPreset.heroImages;
  const selectedVibe = selected?.vibe ?? detailPreset.vibe;
  const selectedFocus = selected?.focus ?? detailPreset.focus;
  const selectedHighlights = selected?.highlights?.length
    ? selected.highlights
    : detailPreset.highlights;
  const selectedFlow = selected?.flow?.length
    ? selected.flow
    : detailPreset.flow;
  const selectedNotes = selected?.notes?.length
    ? selected.notes
    : detailPreset.notes;
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
        const extraText = extras > 0 ? ` +${extras}` : '';
        return `${label}: ${first.title}${extraText}`;
      }

      if (optionCount > 0) {
        const highlight = options[0]?.title;
        return `${label}: ${optionCount} option${optionCount === 1 ? '' : 's'}${highlight ? ` (top: ${highlight})` : ''}`;
      }

      return `${label}: searching...`;
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

    return [stayLine, flightLine, activityLine].join(' · ');
  }, [
    countsForSelected,
    selectedTiles,
    tilesByTab,
  ]);

  // Show skeleton loaders while loading
  if (isLoading) {
    return (
      <div className="space-y-4">
        <div className="space-y-2">
          <Skeleton className="h-4 w-24" />
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            <BranchCardSkeleton />
            <BranchCardSkeleton />
            <BranchCardSkeleton />
          </div>
        </div>
      </div>
    );
  }

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
        <div className="flex items-center justify-between">
          <p className="text-muted-foreground text-xs font-semibold uppercase tracking-wide">
            Trip plan
          </p>
          <ComparisonToggle />
        </div>
        {isComparisonMode && !isComparisonReady && (
          <p className="text-muted-foreground text-xs">
            Select {isComparisonMode ? '1 more trip' : '2 trips'} to compare side-by-side
          </p>
        )}
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {branches.map((b, idx) => {
            const isActive = selected !== null && b.id === selected.id;
            const isInComparison = isBranchInComparison(b.id);
            const preset = DETAIL_PRESETS[idx % DETAIL_PRESETS.length];
            // Use backend images if available, fallback to mock presets
            const cardImage = b.image_url ?? b.hero_images?.[0] ?? preset.heroImages[0];
            const selection = branchSelections?.[b.id] ?? { activities: [] };
            const statusReady =
              Boolean(selection.stay) ||
              Boolean(selection.flight) ||
              (selection.activities?.length ?? 0) > 0;
            const badgeLabel = statusReady ? 'Ready' : 'Customizing';
            const badgeColor = statusReady ? 'bg-green-500' : 'bg-orange-500';
            const badgeTextColor = 'text-white';
            const branchBudget = resolveBudgetForBranch(b, tripInputs);
            const budgetLabel =
              formatBudgetDisplay(branchBudget.amount, branchBudget.currency) ?? preset.budget;
            const duration =
              resolveDurationForBranch(b, tripInputs)?.summary ?? preset.duration;

            const handleCardClick = () => {
              if (isComparisonMode) {
                toggleBranchForComparison(b.id);
              } else {
                onBranchSelect(b.id);
              }
            };

            // Quick compare: allow single-click comparison when another branch is selected
            const handleQuickCompare = (e: React.MouseEvent) => {
              e.stopPropagation(); // Don't trigger card click
              // This will: 1) enter comparison mode with selected branch, 2) add this branch
              if (selected) {
                toggleBranchForComparison(selected.id); // First branch (enters comparison mode)
                toggleBranchForComparison(b.id); // Second branch
              }
            };

            // Show quick compare button on cards that aren't selected
            const showQuickCompare = !isComparisonMode && selected && !isActive && canCompare;

            return (
              <button
                key={b.id}
                type="button"
                onClick={handleCardClick}
                aria-selected={isComparisonMode ? isInComparison : isActive}
                // Tier 11.10: Descriptive ARIA label for screen readers
                aria-label={`${b.destinations[0] || 'Trip option'} - ${
                  isComparisonMode
                    ? isInComparison
                      ? 'Selected for comparison'
                      : 'Click to add to comparison'
                    : isActive
                      ? 'Currently selected'
                      : 'Click to view'
                }`}
                className={cn(
                  'focus-visible:outline-primary group relative overflow-hidden rounded-2xl border text-left shadow-lg transition hover:translate-y-[-2px] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2',
                  isComparisonMode && isInComparison
                    ? 'ring-indigo-500 border-indigo-500 ring-2'
                    : isActive && !isComparisonMode
                      ? 'ring-accent border-accent shadow-accent/20 ring-2'
                      : 'border-border/40'
                )}
              >
                {/* Quick compare button - visible on mobile, hover on desktop (Tier 9) */}
                {showQuickCompare && (
                  <button
                    type="button"
                    onClick={handleQuickCompare}
                    className="absolute top-2 right-2 z-10 touch-manipulation opacity-100 sm:opacity-0 sm:group-hover:opacity-100 transition-opacity duration-200"
                    aria-label={`Compare with ${b.destinations[0] || 'this option'}`}
                  >
                    <span className="inline-flex items-center gap-1 bg-indigo-600 hover:bg-indigo-700 active:bg-indigo-800 text-white text-xs font-semibold px-3 py-2 rounded-full shadow-lg cursor-pointer transition-colors min-h-[44px] min-w-[44px]">
                      <ArrowRightLeft className="h-4 w-4" />
                      <span className="hidden sm:inline">Compare</span>
                    </span>
                  </button>
                )}
                <div
                  className="h-full w-full"
                  style={{
                    backgroundImage: `linear-gradient(180deg, rgba(0,0,0,0.05) 0%, rgba(0,0,0,0.55) 100%), url(${cardImage})`,
                    backgroundSize: 'cover',
                    backgroundPosition: 'center',
                  }}
                >
                  <div className="flex h-full flex-col justify-between gap-3 p-4">
                    <div className="flex flex-wrap items-start justify-between gap-2">
                      <div className="flex items-center gap-2">
                        {isComparisonMode && isInComparison && (
                          <span className="inline-flex items-center justify-center rounded-full bg-indigo-600 p-1 shadow-md">
                            <CheckCircle2 className="h-4 w-4 text-white" />
                          </span>
                        )}
                        {/* Plan status badge - shown when plan is stale or updating */}
                        {planStatus === 'updating' && (
                          <span className="inline-flex shrink-0 items-center gap-1 rounded-full bg-amber-500 px-3 py-1 text-[11px] font-semibold uppercase tracking-wide text-white shadow-md animate-pulse">
                            Updating
                          </span>
                        )}
                        {planStatus === 'stale' && (
                          <span className="inline-flex shrink-0 items-center gap-1 rounded-full bg-gray-500 px-3 py-1 text-[11px] font-semibold uppercase tracking-wide text-white shadow-md">
                            Out of date
                          </span>
                        )}
                        {planStatus === 'ready' && (
                          <span
                            className={`${badgeColor} ${badgeTextColor} inline-flex shrink-0 items-center gap-2 rounded-full px-3 py-1 text-[11px] font-semibold uppercase tracking-wide shadow-md`}
                          >
                            {badgeLabel}
                          </span>
                        )}
                      </div>
                      {/* Removed "Suggestion X" numbering per coherence guidelines */}
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

      {/* Show comparison view when 2 branches are selected, otherwise show detail panel */}
      {isComparisonReady ? (
        <BranchComparisonView tripInputs={tripInputs} />
      ) : (
        <div className="via-card/80 to-background relative overflow-hidden rounded-2xl border border-white/10 bg-gradient-to-br from-white/5 shadow-lg backdrop-blur">
          <div className="bg-primary/20 pointer-events-none absolute -right-24 -top-12 h-48 w-48 rounded-full blur-3xl" />
          <div className="bg-accent/15 pointer-events-none absolute bottom-0 left-0 h-36 w-36 rounded-full blur-2xl" />
          <div className="relative space-y-6 p-4 sm:p-5">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="space-y-1">
                <p className="text-muted-foreground text-[10px] font-medium uppercase tracking-wide">
                  Current plan
                </p>
                <div className="flex items-center gap-2">
                  <MapPin className="text-primary h-6 w-6" aria-hidden="true" />
                  <h4 className="text-foreground font-display text-3xl font-bold tracking-tight">
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

            {/* Constraint satisfaction header */}
            <div className="flex items-center gap-2 rounded-lg border border-green-500/20 bg-green-500/5 px-3 py-2">
              <CheckCircle2 className="h-4 w-4 text-green-500 flex-shrink-0" />
              <p className="text-sm font-medium text-green-600 dark:text-green-400">
                This plan satisfies constraints.
              </p>
            </div>

          <div className="flex flex-wrap items-center gap-3 pb-1">
            {(Object.keys(TAB_CONFIG) as TileTabKey[]).map((tabKey) => {
              const isOpen = openTab === tabKey;
              const count = tilesByTab[tabKey]?.length ?? 0;
              const Icon = TAB_CONFIG[tabKey].icon;
              return (
                <button
                  key={tabKey}
                  type="button"
                  onClick={() => setOpenTab((prev) => (prev === tabKey ? null : tabKey))}
                  className={`focus-visible:outline-primary group relative flex items-center gap-1.5 border-b pb-1.5 text-xs font-medium transition touch-manipulation min-h-[36px] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 active:scale-95 ${
                    isOpen
                      ? 'border-primary/50 text-primary'
                      : 'text-muted-foreground/70 hover:text-muted-foreground border-transparent'
                  }`}
                  aria-pressed={isOpen}
                >
                  <span
                    className={`flex h-6 w-6 items-center justify-center rounded-full transition ${
                      isOpen
                        ? 'bg-primary/10 text-primary'
                        : 'text-muted-foreground/60'
                    }`}
                  >
                    <Icon className="h-3.5 w-3.5" aria-hidden="true" />
                  </span>
                  <span>{TAB_CONFIG[tabKey].label}</span>
                  <span
                    className={`rounded-full px-1.5 py-0.5 text-[10px] font-medium ${
                      isOpen
                        ? 'bg-primary/10 text-primary'
                        : 'bg-muted/50 text-muted-foreground/60'
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
              // Tier 10.6: Show animated skeleton loaders during branch switch instead of static message
              <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-4">
                <TileCardSkeleton />
                <TileCardSkeleton />
                <TileCardSkeleton />
              </div>
            ) : tilesByTab[openTab]?.length ? (
              <TilesGrid
                tiles={branchTiles}
                activeBranch={selected}
                selectedTiles={selectedTiles}
                onTileToggle={(tile) => onTileToggle?.(tile, openTab)}
                forcedTab={openTab}
                hideTabSwitcher
                onSelectionToast={onSelectionToast}
              />
            ) : (
              <div className="border-border/60 text-muted-foreground rounded-xl border border-dashed bg-black/10 p-4 text-sm shadow-inner">
                No {TAB_CONFIG[openTab].label.toLowerCase()} yet for this plan.
                Check back after options refresh.
              </div>
            )}
          </div>

          <div className="space-y-5">
            <div className="rounded-lg border border-white/10 bg-white/5 p-3 shadow-sm">
              <p className="text-muted-foreground text-[10px] font-medium uppercase tracking-wide">
                Booking status
              </p>
              <p className="text-foreground mt-1 text-xs">{bookingSummary}</p>
            </div>

            <div className="grid grid-cols-3 gap-2">
              <div className="overflow-hidden rounded-lg border border-white/10 bg-black/20 shadow-inner">
                <div className="relative aspect-[3/2]">
                  <img
                    src={selectedHeroImages[0]}
                    alt={`${selected?.destinations[0] ?? 'Destination'} overview`}
                    loading="lazy"
                    className="h-full w-full object-cover opacity-90"
                  />
                  <div className="absolute inset-0 bg-gradient-to-t from-black/40 to-transparent" />
                </div>
              </div>
              <div className="overflow-hidden rounded-lg border border-white/10 bg-black/20 shadow-inner">
                <div className="relative aspect-[3/2]">
                  <img
                    src={selectedHeroImages[1]}
                    alt={`${selected?.destinations[0] ?? 'Destination'} detail`}
                    loading="lazy"
                    className="h-full w-full object-cover opacity-90"
                  />
                  <div className="absolute inset-0 bg-gradient-to-t from-black/40 to-transparent" />
                </div>
              </div>
              <div className="overflow-hidden rounded-lg border border-white/10 bg-black/20 shadow-inner">
                <div className="relative aspect-[3/2]">
                  <img
                    src={selectedHeroImages[2]}
                    alt={`${selected?.destinations[0] ?? 'Destination'} night detail`}
                    loading="lazy"
                    className="h-full w-full object-cover opacity-90"
                  />
                  <div className="absolute inset-0 bg-gradient-to-t from-black/40 to-transparent" />
                </div>
              </div>
            </div>

            {/* Core constraints - horizontal row */}
            <div className="grid grid-cols-3 gap-2">
              <div className="rounded-lg border border-white/10 bg-white/5 p-3 shadow-sm">
                <p className="text-muted-foreground text-[10px] font-medium uppercase tracking-wide">
                  Duration
                </p>
                <p className="text-foreground text-base font-bold">
                  {selectedDuration?.rangeLabel ?? detailPreset.duration}
                </p>
              </div>
              <div className="rounded-lg border border-white/10 bg-white/5 p-3 shadow-sm">
                <p className="text-muted-foreground text-[10px] font-medium uppercase tracking-wide">
                  Budget
                </p>
                <p className="text-foreground text-base font-bold">
                  {formatBudgetDisplay(selectedBudget.amount, selectedBudget.currency) ?? detailPreset.budget}
                </p>
              </div>
              <div className="rounded-lg border border-white/10 bg-white/5 p-3 shadow-sm">
                <p className="text-muted-foreground text-[10px] font-medium uppercase tracking-wide">
                  Tempo
                </p>
                <p className="text-foreground text-base font-bold">{selectedVibe}</p>
              </div>
            </div>

            {/* Focus - plan thesis */}
            <div className="rounded-lg border border-primary/20 bg-primary/5 p-3 shadow-sm">
              <p className="text-primary text-[10px] font-medium uppercase tracking-wide">
                Focus
              </p>
              <p className="text-foreground text-sm font-semibold mt-1">{selectedFocus}</p>
            </div>

            <div className="mt-4 space-y-3">
              <div className="rounded-lg border border-white/5 bg-white/[0.02] p-3">
                <p className="text-muted-foreground/70 text-[10px] font-medium uppercase tracking-wide">
                  Highlights
                </p>
                <ul className="text-muted-foreground mt-2 space-y-1.5 text-xs">
                  {selectedHighlights.map((item) => (
                    <li key={item} className="flex gap-2">
                      <span className="bg-muted-foreground/30 mt-1.5 h-1 w-1 rounded-full flex-shrink-0" />
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
                  {selectedFlow.map((item, idx) => (
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
                {selectedNotes.map((note) => (
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
      )}

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
          title={
            !selected
              ? 'Select a trip option above to continue'
              : !canBookTrip
                ? 'Complete your trip details to enable booking'
                : undefined
          }
          aria-label={
            !selected
              ? 'Book Trip - Select a trip option first'
              : !canBookTrip
                ? 'Book Trip - Complete trip details first'
                : 'Book Trip'
          }
          className={`focus-visible:outline-primary rounded-full px-5 py-2 text-sm font-semibold transition focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 ${
            !canBookTrip || !selected
              ? 'bg-muted text-muted-foreground cursor-not-allowed shadow-inner'
              : hasLockedSelection
                ? 'bg-orange-500 text-white shadow-lg shadow-orange-400/50 hover:bg-orange-600'
                : 'bg-primary text-primary-foreground shadow-primary/40 hover:bg-primary/90 shadow-lg'
          }`}
        >
          Book Trip
        </button>
      </div>
    </div>
  );
});
