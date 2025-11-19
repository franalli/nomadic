'use client';

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
      <div className="rounded-xl border p-3 text-sm text-gray-500">
        Trip ideas will appear here after you plan a trip.
      </div>
    );
  }

  const selected = branches.find((b) => b.id === selectedBranchId) ?? branches[0];

  return (
    <div className="flex flex-col gap-3 rounded-xl border p-3">
      <div className="flex flex-wrap gap-2">
        {branches.map((b) => {
          const isActive = b.id === selected.id;
          return (
            <button
              key={b.id}
              type="button"
              onClick={() => onBranchSelect(b.id)}
              className={
                'rounded-full border px-3 py-1 text-xs transition ' +
                (isActive
                  ? 'border-black bg-black text-white'
                  : 'border-gray-300 bg-white text-gray-700 hover:bg-gray-50')
              }
            >
              {b.label}
            </button>
          );
        })}
      </div>

      <div className="space-y-1 rounded-lg border border-gray-200 bg-gray-50 p-3 text-sm">
        <div className="font-semibold">{selected.destination}</div>
        {selected.description && <p className="text-gray-700">{selected.description}</p>}
      </div>
    </div>
  );
}
