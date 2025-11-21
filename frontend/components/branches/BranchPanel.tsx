'use client';

import { MapPin, Sparkles } from 'lucide-react';

import type { PlanBranch } from '@/types/plan';

type BranchPanelProps = {
  branches: PlanBranch[];
  selectedBranchId: string | null;
  onBranchSelect: (branchId: string) => void;
};

export function BranchPanel({
  branches,
  selectedBranchId,
  onBranchSelect,
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
        <div className="pointer-events-none absolute -right-20 -top-10 h-40 w-40 rounded-full bg-primary/20 blur-3xl" />
        <div className="pointer-events-none absolute bottom-0 left-0 h-32 w-32 rounded-full bg-accent/15 blur-2xl" />
        <div className="relative space-y-3 p-4 sm:p-5">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="space-y-1">
              <p className="text-xs font-semibold uppercase tracking-wide text-primary">
                Selected suggestion
              </p>
              <h4 className="text-foreground font-display text-xl font-bold">
                {selected.destination}
              </h4>
              {selected.description && (
                <p className="text-muted-foreground text-sm leading-relaxed">
                  {selected.description}
                </p>
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
          </div>
        </div>
      </div>
    </div>
  );
}
