'use client';

import { Plane } from 'lucide-react';

import { cn } from '@/lib/utils';

// ─────────────────────────────────────────────────────────────────────────────
// Shared pill button style for origin quick-select buttons
// ─────────────────────────────────────────────────────────────────────────────

const originPillClass = cn(
  'inline-flex items-center gap-1.5 px-3.5 py-2.5 rounded-lg',
  // Light: White card with border
  'bg-white border-2 border-zinc-200',
  'text-xs font-semibold text-zinc-600',
  'hover:border-zinc-900 hover:bg-zinc-50 hover:text-zinc-900',
  // Dark: Glass Fill - substance, not just outline
  'dark:bg-white/5 dark:border-2 dark:border-white/15',
  'dark:text-zinc-400',
  'dark:hover:bg-white/10 dark:hover:text-white dark:hover:border-white/40',
  'transition-all duration-150'
);

// ─────────────────────────────────────────────────────────────────────────────
// OriginPillButton — reusable pill for both recent & popular origins
// ─────────────────────────────────────────────────────────────────────────────

interface OriginPillButtonProps {
  label: string;
  onClick: () => void;
}

export function OriginPillButton({ label, onClick }: OriginPillButtonProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={originPillClass}
    >
      <Plane className="h-3.5 w-3.5" />
      {label}
    </button>
  );
}
