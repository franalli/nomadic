'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { BranchPanel } from '@/components/branches/BranchPanel';
import { ChatPanel } from '@/components/chat/ChatPanel';
import { TilesGrid } from '@/components/tiles/TilesGrid';
import { TripContextForm } from '@/components/TripContextForm';
import { clearSessionId, getOrCreateSessionId } from '@/lib/session';
import type {
  SessionSnapshot,
  TilesSearchRequest,
  TilesSearchResponse,
} from '@/types/api';
import type { PlanBranch } from '@/types/plan';
import type { Tile } from '@/types/tile';

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';

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

export function AppShell() {
  const [branches, setBranches] = useState<PlanBranch[]>([]);
  const [selectedBranchId, setSelectedBranchId] = useState<string | null>(null);
  const [tiles, setTiles] = useState<Tile[]>([]);
  const [tilesRequestId, setTilesRequestId] = useState<string | null>(null);
  const [tripContextId, setTripContextId] = useState<number | null>(null);
  const [toastMessage, setToastMessage] = useState<string | null>(null);
  const [isHydratingSnapshot, setIsHydratingSnapshot] = useState(false);
  const [isResettingSession, setIsResettingSession] = useState(false);
  const tilesFetchControllerRef = useRef<AbortController | null>(null);

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
    },
    []
  );

  return (
    <main className="mx-auto flex min-h-screen max-w-6xl flex-col gap-6 p-4">
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
      <header className="text-center md:text-left">
        <h1 className="text-2xl font-semibold">Nomadic</h1>
        <p className="text-sm text-slate-500">Your AI-powered trip companion</p>
      </header>

      <div className="grid gap-4 md:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]">
        <div className="flex flex-col gap-4">
          <TripContextForm
            origin={origin}
            onOriginChange={setOrigin}
            startDate={startDate}
            onStartDateChange={setStartDate}
            endDate={endDate}
            onEndDateChange={setEndDate}
            budgetBucket={budgetBucket}
            onBudgetBucketChange={setBudgetBucket}
            groupSize={groupSize}
            onGroupSizeChange={setGroupSize}
            vibes={vibes}
            onToggleVibe={handleToggleVibe}
            onStartNewSession={handleStartNewSession}
            isStartingNewSession={isResettingSession}
          />

          <ChatPanel
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

        <div className="flex flex-col gap-4">
          <section className="rounded-lg border bg-white p-4 shadow-sm">
            <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-600">
              Branches
            </h2>
            {isHydratingSnapshot && branches.length === 0 ? (
              <p className="text-sm text-slate-500">Restoring your last session…</p>
            ) : (
              <BranchPanel
                branches={branches}
                selectedBranchId={selectedBranchId}
                onBranchSelect={handleBranchSelect}
              />
            )}
          </section>

          <section className="rounded-lg border bg-white p-4 shadow-sm">
            <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-600">
              Tiles
            </h2>
            <TilesGrid
              tiles={tiles}
              activeBranch={selectedBranch}
              tilesRequestId={tilesRequestId}
            />
          </section>
        </div>
      </div>
    </main>
  );
}
