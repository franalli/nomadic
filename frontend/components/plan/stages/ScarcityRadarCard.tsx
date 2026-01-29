/**
 * ScarcityRadarCard
 *
 * "Booking Horizon" / Scarcity Radar card.
 * Shows what needs to be booked in advance vs walk-in.
 * This is INTEL (urgency awareness), not direct booking CTAs.
 */

'use client';

import { Clock } from 'lucide-react';

import { cn } from '@/lib/utils';

export interface ScarcityItem {
  title: string;
  /** e.g., "3 weeks ahead", "Walk-in OK" */
  leadTime: string;
  /** Urgency level: critical (sells out), standard (book ahead), walkin (no booking needed) */
  urgency?: 'critical' | 'standard' | 'walkin';
}

export interface ScarcityRadarCardProps {
  items: ScarcityItem[];
  className?: string;
}

export function ScarcityRadarCard({ items, className }: ScarcityRadarCardProps) {
  if (items.length === 0) return null;

  // Separate by urgency for better display
  const criticalItems = items.filter((i) => i.urgency === 'critical' || !i.urgency);
  const standardItems = items.filter((i) => i.urgency === 'standard');
  const walkinItems = items.filter((i) => i.urgency === 'walkin');

  // Only show critical/standard items (walk-in items don't need a warning)
  const displayItems = [...criticalItems, ...standardItems];

  if (displayItems.length === 0) return null;

  return (
    <div
      className={cn(
        'p-3 rounded-lg border',
        // Amber warning style
        'bg-amber-50 border-amber-200',
        'dark:bg-amber-900/10 dark:border-amber-800/30',
        className
      )}
    >
      {/* Header */}
      <div className="flex items-center gap-2 mb-2">
        <Clock className="w-4 h-4 text-amber-600 dark:text-amber-500" />
        <span className="text-xs font-bold text-amber-800 dark:text-amber-200 uppercase tracking-wide">
          Advance Booking Required
        </span>
      </div>

      {/* Items list */}
      <ul className="list-disc list-inside text-xs text-zinc-700 dark:text-zinc-300 space-y-1 ml-1">
        {displayItems.map((item) => (
          <li key={item.title}>
            <strong className="text-zinc-800 dark:text-zinc-200">{item.title}:</strong>{' '}
            <span className="text-zinc-600 dark:text-zinc-400">{item.leadTime}</span>
          </li>
        ))}
      </ul>

      {/* Walk-in hint if any exist */}
      {walkinItems.length > 0 && (
        <p className="text-[10px] text-zinc-500 dark:text-zinc-400 mt-2 pt-2 border-t border-amber-200/50 dark:border-amber-800/30">
          Walk-in OK: {walkinItems.map((i) => i.title).join(', ')}
        </p>
      )}
    </div>
  );
}
