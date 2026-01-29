/**
 * TransportStrategyCard
 *
 * "Getting Around" strategic advice card.
 * Shows transport options and tips - this is INTEL, not booking.
 * Part of the Plan tab's strategy-focused design.
 */

'use client';

import { Train } from 'lucide-react';

import { cn } from '@/lib/utils';

export interface TransportTip {
  mode: string;
  description: string;
  /** Optional tip/warning */
  tip?: string;
}

export interface TransportStrategyCardProps {
  /** Main airport/arrival point info */
  arrivalInfo?: string;
  /** Transport tips for getting around */
  tips: TransportTip[];
  className?: string;
}

export function TransportStrategyCard({ arrivalInfo, tips, className }: TransportStrategyCardProps) {
  if (!arrivalInfo && tips.length === 0) return null;

  return (
    <div
      className={cn(
        'p-4 rounded-xl border transition-colors',
        // Light mode
        'bg-zinc-50 border-zinc-200',
        // Dark mode
        'dark:bg-zinc-900 dark:border-white/10',
        className
      )}
    >
      {/* Header */}
      <div className="flex items-center gap-2 mb-3">
        <Train className="w-4 h-4 text-emerald-600 dark:text-emerald-400" />
        <h4 className="text-sm font-bold text-zinc-900 dark:text-white">Getting Around</h4>
      </div>

      {/* Arrival info */}
      {arrivalInfo && (
        <p className="text-xs text-zinc-600 dark:text-zinc-400 mb-3 leading-relaxed">
          {arrivalInfo}
        </p>
      )}

      {/* Transport tips */}
      {tips.length > 0 && (
        <div className="space-y-2">
          {tips.map((tip, idx) => (
            <div key={idx} className="flex items-start gap-2">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 mt-1.5 shrink-0" />
              <div>
                <span className="text-xs font-medium text-zinc-700 dark:text-zinc-300">
                  {tip.mode}:
                </span>{' '}
                <span className="text-xs text-zinc-500 dark:text-zinc-400">
                  {tip.description}
                </span>
                {tip.tip && (
                  <span className="text-xs text-zinc-500 dark:text-zinc-400 ml-1">
                    ({tip.tip})
                  </span>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
