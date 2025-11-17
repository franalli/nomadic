'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';

import { BranchPanel } from '@/components/branches/BranchPanel';
import { ChatPanel } from '@/components/chat/ChatPanel';
import { TilesGrid } from '@/components/tiles/TilesGrid';
import { getOrCreateSessionId } from '@/lib/session';
import type {
  SessionStateResponse,
  TilesSearchRequest,
  TilesSearchResponse,
} from '@/types/api';
import type { PlanBranch } from '@/types/plan';
import type { Tile } from '@/types/tile';

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';

export function AppShell() {
  const [branches, setBranches] = useState<PlanBranch[]>([]);
  const [selectedBranchId, setSelectedBranchId] = useState<string | null>(null);
  const [tiles, setTiles] = useState<Tile[]>([]);
  const [tilesRequestId, setTilesRequestId] = useState<string | null>(null);
  const [tripContextId, setTripContextId] = useState<number | null>(null);
  const [toastMessage, setToastMessage] = useState<string | null>(null);

  const [origin, setOrigin] = useState('');
  const [startDate, setStartDate] = useState('');
  const [endDate, setEndDate] = useState('');
  const [budgetBucket, setBudgetBucket] = useState('');
  const [groupSize, setGroupSize] = useState('2');
  const [vibes, setVibes] = useState<string[]>([]);

  const selectedBranch = useMemo(
    () => branches.find((branch) => branch.id === selectedBranchId) ?? null,
    [branches, selectedBranchId]
  );

  const numericGroupSize = useMemo(() => {
    const parsed = parseInt(groupSize, 10);
    return Number.isFinite(parsed) && parsed > 0 ? parsed : undefined;
  }, [groupSize]);

  const handleBranchSelect = useCallback(
    async (branchId: string) => {
      setSelectedBranchId(branchId);
      const branch = branches.find((b) => b.id === branchId);
      if (!branch) return;

      const sessionId = getOrCreateSessionId();
      const parsedBranchId = Number(branchId);
      const branchIdNumber = Number.isFinite(parsedBranchId) ? parsedBranchId : undefined;

      const body: TilesSearchRequest = {
        branch_id: branchIdNumber,
        session_id: sessionId || undefined,
        trip_context_id: tripContextId ?? undefined,
        origin: origin || undefined,
        destination: branch.destination,
        destination_hint: branch.destination,
        start_date: startDate || undefined,
        end_date: endDate || undefined,
        budget_bucket: budgetBucket || undefined,
        group_size: numericGroupSize,
        vibes: vibes.length ? vibes : undefined,
      };

      try {
        const res = await fetch(`${API_BASE}/v1/tiles/search`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        });

        if (!res.ok) {
          console.error('Failed to fetch tiles for branch', res.status);
          setToastMessage('Unable to refresh tiles for that branch. Please try again.');
          return;
        }

        const data: TilesSearchResponse = await res.json();
        setTiles(data.tiles);
        setTilesRequestId(data.tiles_request_id ?? data.request_id ?? null);
      } catch (error) {
        console.error('Failed to fetch tiles for branch', error);
        setToastMessage('Unable to refresh tiles for that branch. Please try again.');
      }
    },
    [
      branches,
      budgetBucket,
      endDate,
      numericGroupSize,
      origin,
      startDate,
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

    async function hydrateSessionState() {
      try {
        const sessionId = getOrCreateSessionId();
        if (!sessionId) return;

        const res = await fetch(`${API_BASE}/v1/sessions/${sessionId}/state`);
        if (!res.ok) return;

        const data: SessionStateResponse = await res.json();
        if (cancelled) return;

        if (data.trip_context) {
          setOrigin(data.trip_context.origin ?? '');
          setStartDate(data.trip_context.start_date ?? '');
          setEndDate(data.trip_context.end_date ?? '');
          setBudgetBucket(data.trip_context.budget_bucket ?? '');
          setGroupSize(
            data.trip_context.group_size != null
              ? String(data.trip_context.group_size)
              : '2'
          );
          setVibes(data.trip_context.vibes ?? []);
          setTripContextId(data.trip_context.id);
        }

        if (data.branches.length) {
          setBranches(data.branches);
          const fallbackBranchId = data.primary_branch_id ?? data.branches[0].id;
          setSelectedBranchId(fallbackBranchId);
          setTiles(data.tiles);
          setTilesRequestId(data.tiles_request_id ?? null);
        }
      } catch (error) {
        console.error('Failed to hydrate session state', error);
      }
    }

    hydrateSessionState();

    return () => {
      cancelled = true;
    };
  }, []);

  const handleClearContext = useCallback(() => {
    setOrigin('');
    setStartDate('');
    setEndDate('');
    setBudgetBucket('');
    setGroupSize('2');
    setVibes([]);
  }, []);

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
        <section className="rounded-lg border bg-white p-4 shadow-sm">
          <ChatPanel
            origin={origin}
            startDate={startDate}
            endDate={endDate}
            budgetBucket={budgetBucket}
            groupSize={groupSize}
            vibes={vibes}
            onOriginChange={setOrigin}
            onStartDateChange={setStartDate}
            onEndDateChange={setEndDate}
            onBudgetBucketChange={setBudgetBucket}
            onGroupSizeChange={setGroupSize}
            onVibesChange={setVibes}
            onClearContext={handleClearContext}
            onBranchesChange={(bs) => setBranches(bs)}
            onTilesChange={setTiles}
            onPrimaryBranchSelected={(id) => setSelectedBranchId(id)}
            onTilesRequestIdChange={setTilesRequestId}
            onTripContextChange={setTripContextId}
          />
        </section>

        <div className="flex flex-col gap-4">
          <section className="rounded-lg border bg-white p-4 shadow-sm">
            <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-600">
              Branches
            </h2>
            <BranchPanel
              branches={branches}
              selectedBranchId={selectedBranchId}
              onBranchSelect={handleBranchSelect}
            />
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
