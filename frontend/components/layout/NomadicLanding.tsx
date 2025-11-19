'use client';

import Image from 'next/image';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { BranchPanel } from '@/components/branches/BranchPanel';
import { ChatPanel } from '@/components/chat/ChatPanel';
import { TilesGrid } from '@/components/tiles/TilesGrid';
import { API_BASE } from '@/lib/api';
import { clearSessionId, getOrCreateSessionId } from '@/lib/session';
import type {
  SessionSnapshot,
  TilesSearchRequest,
  TilesSearchResponse,
} from '@/types/api';
import type { PlanBranch } from '@/types/plan';
import type { Tile } from '@/types/tile';

const VIBE_OPTIONS = [
  { value: 'adventure', label: 'Adventure' },
  { value: 'history', label: 'History' },
  { value: 'local_culture', label: 'Local Culture' },
  { value: 'art', label: 'Art' },
  { value: 'foodie', label: 'Foodie' },
  { value: 'nightlife', label: 'Nightlife' },
  { value: 'outdoors', label: 'Outdoors' },
  { value: 'relaxation', label: 'Relaxation' },
  { value: 'family', label: 'Family' },
];

type BranchSelectionOverrides = {
  branch?: PlanBranch;
  origin?: string;
  startDate?: string;
  endDate?: string;
  budgetBucket?: string;
  groupSize?: number;
  vibes?: string[];
  tripContextId?: number | null;
  errorMessageOverride?: string;
};

const POPULAR_ROUTES = [
  {
    title: 'Alpine Weekends',
    subtitle: 'Zurich → Alps → Milan',
  },
  {
    title: 'Desert to Coast',
    subtitle: 'Marrakesh → Atlas → Essaouira',
  },
  {
    title: 'Steppe & Skyline',
    subtitle: 'Ulaanbaatar → Seoul → Tokyo',
  },
];

type LandingHeaderProps = {
  onStartNewSession: () => void | Promise<void>;
  isResettingSession: boolean;
};

function LandingHeader({
  onStartNewSession,
  isResettingSession,
}: LandingHeaderProps) {
  return (
    <header className="border-border bg-surface/80 border-b backdrop-blur">
      <div className="max-w-content mx-auto flex items-center justify-between p-4 md:px-8">
        <div className="flex items-center gap-3">
          <Image
            src="/nomadic_logo.png"
            alt="Nomadic logo"
            width={60}
            height={60}
            priority
            className="size-20"
          />
          <span className="font-heading text-text text-xl md:text-2xl">Nomadic</span>
        </div>

        <nav className="text-text-soft hidden items-center gap-6 text-sm md:flex">
          <button className="hover:text-text transition-colors">Stays</button>
          <button className="hover:text-text transition-colors">Flights</button>
          <button className="hover:text-text transition-colors">Activities</button>
          <button className="hover:text-text transition-colors">Deals</button>
        </nav>

        <div className="flex items-center gap-3">
          <button className="text-text-soft hover:text-text hidden text-sm md:inline-flex">
            Sign in
          </button>
          <button
            type="button"
            onClick={onStartNewSession}
            disabled={isResettingSession}
            className="bg-charcoal text-surface shadow-soft focus-visible:ring-sky focus-visible:ring-offset-bg inline-flex items-center justify-center rounded-full px-4 py-2 text-xs font-medium tracking-wide transition-colors hover:bg-black focus:outline-none focus-visible:ring-2 focus-visible:ring-offset-2 disabled:opacity-60"
          >
            {isResettingSession ? 'Resetting…' : 'Start new trip'}
          </button>
        </div>
      </div>
    </header>
  );
}

function HeroIntro() {
  return (
    <div className="space-y-5 text-center md:text-left">
      <h1 className="font-heading text-display text-text">
        Plan trips with
        <span className="text-bronze block">nomad-level precision.</span>
      </h1>
      <p className="text-text-soft mx-auto max-w-3xl text-base md:mx-0">
        Nomadic weaves flights, stays, and experiences into a single, elegant
        itinerary—so your journeys feel as curated as they look.
      </p>
      <div className="text-text-muted flex flex-wrap items-center justify-center gap-4 text-xs md:justify-start">
        <span className="bg-surface shadow-soft inline-flex items-center gap-2 rounded-full px-3 py-1">
          <span className="bg-bronze size-2 rounded-full" />
          Trusted by frequent flyers
        </span>
        <span className="bg-surface shadow-soft inline-flex items-center gap-2 rounded-full px-3 py-1">
          <span className="bg-sky size-2 rounded-full" />
          Built for complex itineraries
        </span>
      </div>
    </div>
  );
}

function PopularRoutesSection() {
  return (
    <section className="border-border bg-bg border-t">
      <div className="max-w-content mx-auto px-4 py-12 md:px-8 md:py-16">
        <div className="flex items-end justify-between gap-4">
          <div>
            <h2 className="font-heading text-h2 text-text">Popular routes</h2>
            <p className="text-text-soft mt-2 text-sm">
              Curated itineraries where Nomadic truly shines.
            </p>
          </div>
          <button className="text-text-soft hover:text-text hidden text-sm font-medium underline-offset-4 hover:underline md:inline-flex">
            See all routes
          </button>
        </div>
        <div className="mt-8 grid gap-6 md:grid-cols-3">
          {POPULAR_ROUTES.map((item) => (
            <article
              key={item.title}
              className="border-border bg-surface shadow-card hover:shadow-soft group overflow-hidden rounded-lg border transition-all duration-200 hover:-translate-y-0.5"
            >
              <div className="from-charcoal/80 via-bronze/60 to-sky/70 h-32 bg-gradient-to-tr" />
              <div className="space-y-1.5 p-4">
                <h3 className="font-heading text-text text-lg">{item.title}</h3>
                <p className="text-text-soft text-xs">{item.subtitle}</p>
                <p className="text-text-muted pt-2 text-[11px]">
                  Layer flights, trains, and stays into one synced plan. Save as a
                  template or share with friends.
                </p>
              </div>
            </article>
          ))}
        </div>
      </div>
    </section>
  );
}

function LandingFooter() {
  return (
    <footer className="border-border bg-bg-strong text-text-onDark border-t">
      <div className="max-w-content mx-auto flex flex-col gap-6 px-4 py-8 text-sm md:flex-row md:items-center md:justify-between md:px-8">
        <p className="text-text-onDark/80 text-xs">
          © {new Date().getFullYear()} Nomadic. Crafted for modern nomads.
        </p>
        <div className="text-text-onDark/80 flex flex-wrap gap-4 text-xs">
          <button className="hover:text-sky transition-colors">Privacy</button>
          <button className="hover:text-sky transition-colors">Terms</button>
          <button className="hover:text-sky transition-colors">Support</button>
        </div>
      </div>
    </footer>
  );
}

export function NomadicLanding() {
  const [branches, setBranches] = useState<PlanBranch[]>([]);
  const [selectedBranchId, setSelectedBranchId] = useState<string | null>(null);
  const [tiles, setTiles] = useState<Tile[]>([]);
  const [tilesRequestId, setTilesRequestId] = useState<string | null>(null);
  const [tripContextId, setTripContextId] = useState<number | null>(null);
  const [toastMessage, setToastMessage] = useState<string | null>(null);
  const [isHydratingSnapshot, setIsHydratingSnapshot] = useState(false);
  const [isResettingSession, setIsResettingSession] = useState(false);
  const tilesFetchControllerRef = useRef<AbortController | null>(null);
  const [branchesExpanded, setBranchesExpanded] = useState(false);
  const [tilesExpanded, setTilesExpanded] = useState(false);
  const [chatKey, setChatKey] = useState(0);

  const abortTilesFetch = useCallback(() => {
    if (tilesFetchControllerRef.current) {
      tilesFetchControllerRef.current.abort();
      tilesFetchControllerRef.current = null;
    }
  }, []);

  const [origin, setOrigin] = useState('');
  const [startDate, setStartDate] = useState('');
  const [endDate, setEndDate] = useState('');
  const [budgetBucket, setBudgetBucket] = useState<string | undefined>(undefined);
  const [groupSize, setGroupSize] = useState<number | undefined>(2);
  const [vibes, setVibes] = useState<string[]>([]);

  const selectedBranch = useMemo(
    () => branches.find((branch) => branch.id === selectedBranchId) ?? null,
    [branches, selectedBranchId]
  );

  const handleBranchSelect = useCallback(
    async (branchId: string, overrides?: BranchSelectionOverrides) => {
      abortTilesFetch();
      const controller = new AbortController();
      tilesFetchControllerRef.current = controller;

      setSelectedBranchId(branchId);
      const branch = overrides?.branch ?? branches.find((b) => b.id === branchId);
      if (!branch) return;

      const sessionId = getOrCreateSessionId();
      const parsedBranchId = Number(branchId);
      const branchIdNumber = Number.isFinite(parsedBranchId) ? parsedBranchId : undefined;

      const requestOrigin = overrides?.origin ?? origin;
      const requestStartDate = overrides?.startDate ?? startDate;
      const requestEndDate = overrides?.endDate ?? endDate;
      const requestBudgetBucket = overrides?.budgetBucket ?? budgetBucket;
      const requestGroupSize = overrides?.groupSize ?? groupSize;
      const requestVibes = overrides?.vibes ?? vibes;
      const requestTripContextId = overrides?.tripContextId ?? tripContextId;
      const errorMessageOverride = overrides?.errorMessageOverride;

      const body: TilesSearchRequest = {
        branch_id: branchIdNumber,
        session_id: sessionId || undefined,
        trip_context_id: requestTripContextId ?? undefined,
        origin: requestOrigin || undefined,
        destination: branch.destination,
        destination_hint: branch.destination,
        start_date: requestStartDate || undefined,
        end_date: requestEndDate || undefined,
        budget_bucket: requestBudgetBucket || undefined,
        group_size: requestGroupSize,
        vibes: requestVibes.length ? requestVibes : undefined,
      };

      try {
        const res = await fetch(`${API_BASE}/v1/tiles/search`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
          signal: controller.signal,
        });

        if (!res.ok) {
          console.error('Failed to fetch tiles for branch', res.status);
          setToastMessage(
            errorMessageOverride ??
              'Unable to refresh tiles for that branch. Please try again.'
          );
          return;
        }

        const data: TilesSearchResponse = await res.json();
        if (controller.signal.aborted) return;
        setTiles(data.tiles);
        setTilesRequestId(data.tiles_request_id ?? data.request_id ?? null);
      } catch (error) {
        if ((error as DOMException).name === 'AbortError') return;
        console.error('Failed to fetch tiles for branch', error);
        setToastMessage(
          errorMessageOverride ??
            'Unable to refresh tiles for that branch. Please try again.'
        );
      } finally {
        if (tilesFetchControllerRef.current === controller) {
          tilesFetchControllerRef.current = null;
        }
      }
    },
    [
      abortTilesFetch,
      branches,
      budgetBucket,
      endDate,
      origin,
      startDate,
      groupSize,
      tripContextId,
      vibes,
    ]
  );

  useEffect(() => {
    if (!toastMessage) return undefined;
    const timer = window.setTimeout(() => setToastMessage(null), 4000);
    return () => window.clearTimeout(timer);
  }, [toastMessage]);

  useEffect(() => {
    let cancelled = false;

    async function hydrateSessionSnapshot() {
      try {
        setIsHydratingSnapshot(true);
        const sessionId = getOrCreateSessionId();
        if (!sessionId) return;

        const res = await fetch(
          `${API_BASE}/v1/session/snapshot?session_id=${sessionId}`
        );
        if (!res.ok) return;

        const data: SessionSnapshot = await res.json();
        if (cancelled) return;

        if (data.trip_context) {
          setOrigin(data.trip_context.origin ?? '');
          setStartDate(data.trip_context.start_date ?? '');
          setEndDate(data.trip_context.end_date ?? '');
          setBudgetBucket(data.trip_context.budget_bucket ?? undefined);
          setGroupSize(
            data.trip_context.group_size != null ? data.trip_context.group_size : 2
          );
          setVibes(data.trip_context.vibes ?? []);
          setTripContextId(data.trip_context.id);
        }

        if (!data.branches.length) return;

        const hydratedBranches: PlanBranch[] = data.branches.map((branch) => ({
          id: String(branch.id),
          label: branch.label,
          description: branch.description,
          destination: branch.destination,
        }));

        setBranches(hydratedBranches);

        if (hydratedBranches.length > 0) {
          setBranchesExpanded(true);
        }

        const fallbackBranchId =
          data.primary_branch_id != null
            ? String(data.primary_branch_id)
            : hydratedBranches[0].id;
        const fallbackBranch =
          hydratedBranches.find((branch) => branch.id === fallbackBranchId) ||
          hydratedBranches[0];

        setSelectedBranchId(fallbackBranchId);

        const snapshotTiles = data.tiles ?? [];
        setTiles(snapshotTiles);
        setTilesRequestId(null);

        if (snapshotTiles.length > 0) {
          setTilesExpanded(true);
        }

        const shouldFetchTiles = snapshotTiles.length === 0 && Boolean(fallbackBranch);
        if (shouldFetchTiles && fallbackBranch) {
          const overrides: BranchSelectionOverrides | undefined = data.trip_context
            ? {
                branch: fallbackBranch,
                origin: data.trip_context.origin ?? '',
                startDate: data.trip_context.start_date ?? '',
                endDate: data.trip_context.end_date ?? '',
                budgetBucket: data.trip_context.budget_bucket ?? undefined,
                groupSize: data.trip_context.group_size ?? undefined,
                vibes: data.trip_context.vibes ?? [],
                tripContextId: data.trip_context.id,
                errorMessageOverride:
                  'We restored your branches but could not refresh tiles automatically. Select a branch to try again.',
              }
            : {
                branch: fallbackBranch,
                tripContextId: null,
                errorMessageOverride:
                  'We restored your branches but could not refresh tiles automatically. Select a branch to try again.',
              };

          await handleBranchSelect(fallbackBranchId, overrides);
        }
      } catch (error) {
        console.error('Failed to hydrate session snapshot', error);
        setToastMessage(
          'Unable to reload your previous session. You can still plan a new trip.'
        );
      } finally {
        setIsHydratingSnapshot(false);
      }
    }

    hydrateSessionSnapshot();

    return () => {
      cancelled = true;
    };
    // We intentionally run this only once on mount to restore the last session snapshot.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleClearContext = useCallback(() => {
    abortTilesFetch();
    setOrigin('');
    setStartDate('');
    setEndDate('');
    setBudgetBucket(undefined);
    setGroupSize(2);
    setVibes([]);
    setTripContextId(null);
    setBranches([]);
    setSelectedBranchId(null);
    setTiles([]);
    setTilesRequestId(null);
    setBranchesExpanded(false);
    setTilesExpanded(false);
    setChatKey((prev) => prev + 1);
  }, [abortTilesFetch]);

  const handleStartNewSession = useCallback(async () => {
    const sessionId = getOrCreateSessionId();
    abortTilesFetch();
    setIsResettingSession(true);
    let didResetServerState = false;

    try {
      if (sessionId) {
        const res = await fetch(
          `${API_BASE}/v1/session?session_id=${encodeURIComponent(sessionId)}`,
          {
            method: 'DELETE',
          }
        );

        if (!res.ok) {
          throw new Error(`Failed to reset session: ${res.status}`);
        }

        didResetServerState = true;
      }
    } catch (error) {
      console.error('Failed to reset planning session', error);
    } finally {
      clearSessionId();
      handleClearContext();
      setIsResettingSession(false);
    }

    setToastMessage(
      didResetServerState
        ? 'Started a fresh planning session.'
        : 'Cleared your local planner, but the previous session may reappear if you refresh.'
    );
  }, [abortTilesFetch, handleClearContext]);

  useEffect(() => () => abortTilesFetch(), [abortTilesFetch]);

  const handleToggleVibe = useCallback((value: string) => {
    setVibes((prev) =>
      prev.includes(value) ? prev.filter((v) => v !== value) : [...prev, value]
    );
  }, []);

  const handlePlanResult = useCallback(
    (result: {
      tripContextId: number | null;
      branches: PlanBranch[];
      tiles: Tile[];
      primaryBranchId: string | null;
      tilesRequestId: string | null;
    }) => {
      setTripContextId(result.tripContextId);
      setBranches(result.branches);
      setTiles(result.tiles);
      setTilesRequestId(result.tilesRequestId);
      setSelectedBranchId(result.primaryBranchId);

      if (result.branches.length > 0) {
        setBranchesExpanded(true);
      }
      if (result.tiles.length > 0) {
        setTilesExpanded(true);
      }
    },
    []
  );

  return (
    <div className="bg-bg font-body text-text min-h-screen">
      {toastMessage && (
        <div className="fixed right-4 top-4 z-50 flex items-start gap-3 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800 shadow-lg">
          <span>{toastMessage}</span>
          <button
            type="button"
            className="text-xs font-semibold uppercase tracking-wide text-red-700"
            onClick={() => setToastMessage(null)}
          >
            Dismiss
          </button>
        </div>
      )}

      <LandingHeader
        onStartNewSession={handleStartNewSession}
        isResettingSession={isResettingSession}
      />

      <main>
        <section className="bg-bg-soft">
          <div className="max-w-content md:py-18 mx-auto flex flex-col gap-10 px-4 py-12 md:px-8">
            <HeroIntro />

            <div className="grid gap-6 md:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]">
              <div className="flex flex-col gap-4">
                <div className="border-border bg-surface shadow-card space-y-4 rounded-lg border p-5">
                  <div className="flex items-center justify-between gap-2">
                    <h2 className="font-heading text-h3 text-text">Trip details</h2>
                    <button
                      type="button"
                      onClick={handleStartNewSession}
                      disabled={isResettingSession}
                      className="border-border text-text-soft hover:border-bronze hover:text-bronze rounded-full border px-3 py-1 text-xs font-semibold transition-colors disabled:opacity-60"
                    >
                      {isResettingSession ? 'Starting…' : 'New session'}
                    </button>
                  </div>

                  <div className="space-y-4 text-sm">
                    <div className="space-y-1.5">
                      <label className="text-text-soft block text-xs font-medium">
                        Origin
                      </label>
                      <input
                        type="text"
                        value={origin}
                        onChange={(event) => setOrigin(event.target.value)}
                        placeholder="e.g. Amsterdam"
                        className="border-border bg-surface text-text placeholder:text-text-muted focus-visible:ring-sky focus-visible:ring-offset-surface w-full rounded-md border px-3 py-2 text-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-offset-2"
                      />
                    </div>

                    <div className="grid gap-3 md:grid-cols-2">
                      <div className="space-y-1.5">
                        <label className="text-text-soft block text-xs font-medium">
                          Check-in
                        </label>
                        <input
                          type="date"
                          value={startDate}
                          onChange={(event) => setStartDate(event.target.value)}
                          className="border-border bg-surface text-text focus-visible:ring-sky focus-visible:ring-offset-surface w-full rounded-md border px-3 py-2 text-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-offset-2"
                        />
                      </div>
                      <div className="space-y-1.5">
                        <label className="text-text-soft block text-xs font-medium">
                          Check-out
                        </label>
                        <input
                          type="date"
                          value={endDate}
                          onChange={(event) => setEndDate(event.target.value)}
                          className="border-border bg-surface text-text focus-visible:ring-sky focus-visible:ring-offset-surface w-full rounded-md border px-3 py-2 text-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-offset-2"
                        />
                      </div>
                    </div>

                    <div className="grid gap-3 md:grid-cols-2">
                      <div className="space-y-1.5">
                        <label className="text-text-soft block text-xs font-medium">
                          Budget
                        </label>
                        <select
                          value={budgetBucket ?? ''}
                          onChange={(event) =>
                            setBudgetBucket(event.target.value || undefined)
                          }
                          className="border-border bg-surface text-text focus-visible:ring-sky focus-visible:ring-offset-surface w-full rounded-md border px-3 py-2 text-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-offset-2"
                        >
                          <option value="">Flexible</option>
                          <option value="value">Value</option>
                          <option value="mid">Mid</option>
                          <option value="premium">Premium</option>
                          <option value="luxury">Luxury</option>
                        </select>
                      </div>
                      <div className="space-y-1.5">
                        <label className="text-text-soft block text-xs font-medium">
                          Travelers
                        </label>
                        <input
                          type="number"
                          min={1}
                          value={groupSize ?? ''}
                          onChange={(event) =>
                            setGroupSize(
                              event.target.value ? Number(event.target.value) : undefined
                            )
                          }
                          className="border-border bg-surface text-text focus-visible:ring-sky focus-visible:ring-offset-surface w-full rounded-md border px-3 py-2 text-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-offset-2"
                        />
                      </div>
                    </div>

                    <div className="space-y-1.5">
                      <label className="text-text-soft block text-xs font-medium">
                        Vibes
                      </label>
                      <div className="flex flex-wrap gap-2">
                        {VIBE_OPTIONS.map((option) => {
                          const active = vibes.includes(option.value);
                          return (
                            <button
                              key={option.value}
                              type="button"
                              onClick={() => handleToggleVibe(option.value)}
                              className={`rounded-full border px-3 py-1 text-[11px] font-medium transition-colors ${
                                active
                                  ? 'border-bronze bg-bronze/10 text-bronze'
                                  : 'border-border bg-surface text-text-soft hover:border-bronze/60'
                              }`}
                            >
                              {option.label}
                            </button>
                          );
                        })}
                      </div>
                    </div>
                  </div>
                </div>

                <div className="border-border bg-surface shadow-card rounded-lg border p-4">
                  <div className="mb-3 flex items-center justify-between">
                    <h3 className="text-text-soft text-sm font-semibold uppercase tracking-wide">
                      Planner chat
                    </h3>
                  </div>
                  <div className="h-64">
                    <ChatPanel
                      key={chatKey}
                      origin={origin}
                      startDate={startDate}
                      endDate={endDate}
                      budgetBucket={budgetBucket}
                      groupSize={groupSize}
                      vibes={vibes}
                      tripContextId={tripContextId}
                      selectedBranchId={selectedBranchId}
                      onPlanResult={handlePlanResult}
                    />
                  </div>
                </div>
              </div>

              <div className="flex flex-col gap-4">
                <div className="border-border bg-surface shadow-card rounded-lg border">
                  <button
                    type="button"
                    onClick={() => setBranchesExpanded((prev) => !prev)}
                    aria-expanded={branchesExpanded}
                    className="hover:bg-bg-soft flex w-full items-center justify-between p-4 text-left transition-colors"
                  >
                    <h3 className="text-text-soft text-sm font-semibold uppercase tracking-wide">
                      Your Trip Ideas {branches.length > 0 && `(${branches.length})`}
                    </h3>
                    <span className="text-text-muted">
                      {branchesExpanded ? '−' : '+'}
                    </span>
                  </button>
                  <div
                    className={`grid transition-[grid-template-rows] duration-300 ease-out ${
                      branchesExpanded ? 'grid-rows-[1fr]' : 'grid-rows-[0fr]'
                    }`}
                  >
                    <div className="border-border overflow-hidden border-t p-4">
                      {isHydratingSnapshot && branches.length === 0 ? (
                        <p className="text-text-soft text-sm">
                          Restoring your last session…
                        </p>
                      ) : branches.length === 0 ? (
                        <p className="text-text-muted text-sm">
                          Start chatting to generate trip branches.
                        </p>
                      ) : (
                        <BranchPanel
                          branches={branches}
                          selectedBranchId={selectedBranchId}
                          onBranchSelect={handleBranchSelect}
                        />
                      )}
                    </div>
                  </div>
                </div>

                <div className="border-border bg-surface shadow-card rounded-lg border">
                  <button
                    type="button"
                    onClick={() => setTilesExpanded((prev) => !prev)}
                    aria-expanded={tilesExpanded}
                    className="hover:bg-bg-soft flex w-full items-center justify-between p-4 text-left transition-colors"
                  >
                    <div>
                      <h3 className="text-text-soft text-sm font-semibold uppercase tracking-wide">
                        Booking Options {tiles.length > 0 && `(${tiles.length})`}
                      </h3>
                      <p className="text-text-muted text-xs">
                        {groupSize && groupSize > 0
                          ? `${groupSize} ${groupSize === 1 ? 'traveler' : 'travelers'}`
                          : 'Travelers not set'}
                      </p>
                    </div>
                    <span className="text-text-muted">{tilesExpanded ? '−' : '+'}</span>
                  </button>
                  <div
                    className={`grid transition-[grid-template-rows] duration-300 ease-out ${
                      tilesExpanded ? 'grid-rows-[1fr]' : 'grid-rows-[0fr]'
                    }`}
                  >
                    <div className="border-border overflow-hidden border-t p-4">
                      {tiles.length === 0 ? (
                        <p className="text-text-muted text-sm">
                          Select a branch to see destination tiles.
                        </p>
                      ) : (
                        <TilesGrid
                          tiles={tiles}
                          activeBranch={selectedBranch}
                          tilesRequestId={tilesRequestId}
                        />
                      )}
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </section>

        <PopularRoutesSection />
      </main>

      <LandingFooter />
    </div>
  );
}
