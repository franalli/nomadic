'use client';

import { useState } from 'react';

import { BranchPanel } from '@/components/branches/BranchPanel';
import { ChatPanel } from '@/components/chat/ChatPanel';
import { TilesGrid } from '@/components/tiles/TilesGrid';
import type { PlanBranch, PlanMeta } from '@/types/plan';
import type { Tile } from '@/types/tile';

export function AppShell() {
  const [branches, setBranches] = useState<PlanBranch[]>([]);
  const [tiles, setTiles] = useState<Tile[]>([]);
  const [planMeta, setPlanMeta] = useState<PlanMeta>({
    primaryBranchId: null,
    tilesRequestId: null,
  });

  const primaryBranch =
    branches.find((branch) => branch.id === planMeta.primaryBranchId) ??
    branches[0] ??
    null;

  return (
    <main className="mx-auto flex min-h-screen max-w-6xl flex-col gap-6 p-4">
      <header className="text-center md:text-left">
        <h1 className="text-2xl font-semibold">Nomadic</h1>
        <p className="text-sm text-slate-500">Your AI-powered trip companion</p>
      </header>

      <div className="grid gap-4 md:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]">
        <section className="rounded-lg border bg-white p-4 shadow-sm">
          <ChatPanel
            onBranchesChange={setBranches}
            onTilesChange={setTiles}
            onPlanMetaChange={(meta) => setPlanMeta(meta)}
          />
        </section>

        <div className="flex flex-col gap-4">
          <section className="rounded-lg border bg-white p-4 shadow-sm">
            <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-600">
              Branches
            </h2>
            <BranchPanel branches={branches} />
          </section>

          <section className="rounded-lg border bg-white p-4 shadow-sm">
            <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-600">
              Tiles
            </h2>
            <TilesGrid
              tiles={tiles}
              primaryBranch={primaryBranch}
              tilesRequestId={planMeta.tilesRequestId}
            />
          </section>
        </div>
      </div>
    </main>
  );
}
