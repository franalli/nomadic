'use client';

import { useEffect, useState } from 'react';

import { Button } from '@/components/ui/button';
import type { PlanBranch } from '@/types/plan';

type BranchPanelProps = {
  branches: PlanBranch[];
};

export function BranchPanel({ branches }: BranchPanelProps) {
  const [active, setActive] = useState<string | null>(null);

  useEffect(() => {
    if (!branches.length) {
      setActive(null);
      return;
    }

    setActive((prev) => {
      if (prev && branches.some((branch) => branch.id === prev)) {
        return prev;
      }
      return branches[0].id;
    });
  }, [branches]);

  const activeBranch = branches.find((branch) => branch.id === active);

  if (!branches.length) {
    return (
      <p className="text-xs text-slate-500">
        Ask for a plan to see branches populate here.
      </p>
    );
  }

  return (
    <div className="flex flex-1 flex-col gap-3">
      <div className="flex flex-wrap gap-1">
        {branches.map((branch) => (
          <Button
            key={branch.id}
            variant={branch.id === active ? 'primary' : 'outline'}
            className="px-2 py-1 text-xs"
            onClick={() => setActive(branch.id)}
          >
            {branch.label}
          </Button>
        ))}
      </div>

      {activeBranch && (
        <div className="rounded-md border border-dashed border-slate-200 bg-slate-50 p-3 text-xs text-slate-600">
          <p className="text-sm font-semibold text-slate-800">{activeBranch.label}</p>
          <p className="mt-1">{activeBranch.description || activeBranch.destination}</p>
          <p className="mt-2 text-slate-500">Destination: {activeBranch.destination}</p>
        </div>
      )}
    </div>
  );
}
