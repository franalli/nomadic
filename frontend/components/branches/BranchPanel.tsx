'use client';

import { ArrowRightLeft, CheckCircle2 } from 'lucide-react';
import { memo, useEffect, useMemo, useState } from 'react';

import { PlanDocument } from '@/components/plan';
import { TabBookingStatus } from '@/components/tiles/TabBookingStatus';
import {
  resolveTabForTile,
  TAB_CONFIG,
  TileCardSkeleton,
  TilesGrid,
  type TileTabKey,
} from '@/components/tiles/TilesGrid';
import { Loader } from '@/components/ui/loader';
import { Skeleton } from '@/components/ui/skeleton';
import { placeholderImagesForBranch } from '@/lib/placeholders';
import { cn , formatBudgetDisplay } from '@/lib/utils';
import type { DocumentBranch, DocumentTripInputs, PlanStatus } from '@/types/document';
import type { BookingStatus } from '@/types/plan-envelope';
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
  /** Per-tab booking status from backend */
  bookingStatus?: BookingStatus | null;
};

export const BranchPanel = memo(function BranchPanel({
  branches,
  selectedBranchId,
  onBranchSelect,
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
  bookingStatus,
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
  // Use backend data - placeholder images only as fallback
  const selectedHeroImages = selected?.hero_images?.length
    ? selected.hero_images
    : placeholderImagesForBranch({ id: selected?.id, destinations: selected?.destinations, index: selectedIndex });
  // Strategy content from backend (no mock fallback - show loading state instead)
  const selectedVibe = selected?.vibe ?? null;
  const selectedFocus = selected?.focus ?? null;
  const selectedHighlights = selected?.highlights?.length ? selected.highlights : [];
  const selectedNotes = selected?.notes?.length ? selected.notes : [];
  // Check if any booking types are enabled (don't show "searching..." if none enabled)
  const hasAnyBookingEnabled = tripInputs?.booking_types && (
    tripInputs.booking_types.hotels ||
    tripInputs.booking_types.flights ||
    tripInputs.booking_types.activities
  );
  const selectedDuration = resolveDurationForBranch(selected, tripInputs);
  const selectedBudget = resolveBudgetForBranch(selected, tripInputs);
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

  // Derive loading state for strategy content and plan regeneration
  // isRegenerating is true when:
  // 1. Plan is being regenerated (planStatus === 'updating'), OR
  // 2. Tiles are expected but haven't loaded yet (initial generation scenario)
  const isStrategyLoading = planStatus === 'updating';
  const isRegenerating = planStatus === 'updating' || (
    hasAnyBookingEnabled &&
    !hasTilesForSelected &&
    selected != null &&
    planStatus !== 'stale'  // Don't show during debounce period
  );
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
        <div className="flex items-center justify-end">
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
            // Use backend images if available, fallback to deterministic placeholders
            const placeholderImages = placeholderImagesForBranch({ id: b.id, destinations: b.destinations, index: idx });
            const cardImage = b.image_url ?? b.hero_images?.[0] ?? placeholderImages[0];
            const branchBudget = resolveBudgetForBranch(b, tripInputs);
            const budgetLabel = formatBudgetDisplay(branchBudget.amount, branchBudget.currency);
            const duration = resolveDurationForBranch(b, tripInputs)?.summary;

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
                        {/* Plan status badge moved to detail panel only */}
                      </div>
                      {/* Removed "Suggestion X" numbering per coherence guidelines */}
                    </div>
                    <div className="space-y-2 text-white">
                      <p className="text-lg font-bold leading-tight">{b.destinations.join(', ') || 'TBD'}</p>
                      {b.description && (
                        <p className="line-clamp-2 text-sm opacity-90">{b.description}</p>
                      )}
                      {(duration || budgetLabel) && (
                        <div className="mt-2 flex flex-wrap items-center justify-between gap-2 text-sm font-semibold">
                          {duration && <span>{duration}</span>}
                          {budgetLabel && <span>{budgetLabel}</span>}
                        </div>
                      )}
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
                  {count > 0 && (
                    <span
                      className={`rounded-full px-1.5 py-0.5 text-[10px] font-medium ${
                        isOpen
                          ? 'bg-primary/10 text-primary'
                          : 'bg-muted/50 text-muted-foreground/60'
                      }`}
                    >
                      {count}
                    </span>
                  )}
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
            {openTab === null ? null : (
              <>
                {/* Per-tab booking status from backend */}
                {bookingStatus?.[openTab] && (
                  <TabBookingStatus
                    status={bookingStatus[openTab]}
                    className="mb-3"
                  />
                )}
                {isStaleTiles && !hasTilesForSelected ? (
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
                    No {TAB_CONFIG[openTab].label.toLowerCase()} available.
                  </div>
                )}
              </>
            )}
          </div>

          <div className="space-y-5">
            {/* Updating indicator - minimal when plan is being regenerated */}
            {isRegenerating && (
              <div className="flex items-center gap-2 text-xs text-muted-foreground">
                <Loader size="sm" />
                <span>Updating...</span>
              </div>
            )}

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

            {/* Summary row - only render fields that have values */}
            <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-muted-foreground">
              {selectedDuration?.rangeLabel && <span>{selectedDuration.rangeLabel}</span>}
              {formatBudgetDisplay(selectedBudget.amount, selectedBudget.currency) && (
                <span>{formatBudgetDisplay(selectedBudget.amount, selectedBudget.currency)}</span>
              )}
              {selectedVibe && <span>{selectedVibe}</span>}
              {selectedFocus && <span className="text-foreground/80">{selectedFocus}</span>}
            </div>

            {/* Loading indicator for strategy content */}
            {isStrategyLoading && (
              <div className="flex items-center gap-2 text-xs text-muted-foreground">
                <Loader size="sm" />
              </div>
            )}

            <div className="mt-4 space-y-3">
              {/* Highlights - only render when populated */}
              {selectedHighlights.length > 0 && (
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
              )}
              {/* Plan document - day-by-day itinerary */}
              {selected && tripInputs && (
                <PlanDocument
                  branch={selected}
                  tiles={branchTiles}
                  tripInputs={tripInputs}
                  planStatus={planStatus}
                />
              )}
            </div>

            {/* Practical notes - only render when populated */}
            {selectedNotes.length > 0 && (
              <div className="rounded-xl border border-white/10 bg-white/5 p-3 shadow-sm">
                <p className="text-muted-foreground text-xs font-semibold uppercase tracking-wide">
                  Practical notes
                </p>
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
            )}
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
              ? 'Book - Select a trip option first'
              : !canBookTrip
                ? 'Book - Complete trip details first'
                : 'Book'
          }
          className={`focus-visible:outline-primary rounded-full px-5 py-2 text-sm font-semibold transition focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 ${
            !canBookTrip || !selected
              ? 'bg-muted text-muted-foreground cursor-not-allowed shadow-inner'
              : hasLockedSelection
                ? 'bg-orange-500 text-white shadow-lg shadow-orange-400/50 hover:bg-orange-600'
                : 'bg-primary text-primary-foreground shadow-primary/40 hover:bg-primary/90 shadow-lg'
          }`}
        >
          Book
        </button>
      </div>
    </div>
  );
});
