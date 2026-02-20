/**
 * GhostSlot
 *
 * Placeholder for unbooked items that opens the booking drawer.
 * Shows dashed border with "Select X" label.
 *
 * @see docs/ux_unified_architecture.md Section 10.C
 */

'use client';

import { Building, type LucideIcon,Plane, Plus, Sparkles } from 'lucide-react';

import { cn } from '@/lib/utils';

interface GhostSlotProps {
  category: 'hotel' | 'flight' | 'activity';
  context?: string; // "3 Nights" for hotel, etc.
  onSelect: () => void;
}

const CONFIG: Record<string, { icon: LucideIcon; label: string }> = {
  hotel: { icon: Building, label: 'Select Hotel' },
  flight: { icon: Plane, label: 'Select Flight' },
  activity: { icon: Sparkles, label: 'Browse Activities' },
};

export function GhostSlot({ category, context, onSelect }: GhostSlotProps) {
  const config = CONFIG[category];
  const Icon = config.icon;

  return (
    <button
      onClick={onSelect}
      className={cn(
        'w-full p-4 rounded-xl transition-all',
        'border-2 border-dashed border-zinc-300 dark:border-white/10',
        'hover:border-emerald-500 hover:bg-emerald-50/50 dark:hover:bg-emerald-950/20',
        'group'
      )}
    >
      <div className="flex items-center justify-center gap-3 text-zinc-500 dark:text-zinc-400 group-hover:text-emerald-600 dark:group-hover:text-emerald-400">
        <Plus className="w-5 h-5" />
        <Icon className="w-5 h-5" />
        <span className="font-medium">{config.label}</span>
        {context && <span className="text-sm">({context})</span>}
      </div>
    </button>
  );
}
