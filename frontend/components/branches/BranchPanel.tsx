'use client';

import { useState } from 'react';

import { Button } from '@/components/ui/button';

const mockBranches = [
  { id: 'lisbon', label: 'Lisbon · City & Coast' },
  { id: 'alps', label: 'Alps · Hiking' },
  { id: 'city', label: 'City Break' },
];

export function BranchPanel() {
  const [active, setActive] = useState<string>('lisbon');

  return (
    <div className="flex flex-1 flex-col gap-2">
      <div className="flex flex-wrap gap-1">
        {mockBranches.map((b) => (
          <Button
            key={b.id}
            variant={b.id === active ? 'primary' : 'outline'}
            className="px-2 py-1 text-xs"
            onClick={() => setActive(b.id)}
          >
            {b.label}
          </Button>
        ))}
      </div>
      <p className="text-muted mt-3 text-xs">
        Branch selection is static for now. Later this will reflect actual branching from
        the conversation and attach tiles per branch.
      </p>
    </div>
  );
}
