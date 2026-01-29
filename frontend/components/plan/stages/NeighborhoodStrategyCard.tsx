/**
 * NeighborhoodStrategyCard
 *
 * "Where to Stay" strategic advice card.
 * Shows neighborhood options with price tiers - this is INTEL, not booking.
 * Part of the Plan tab's strategy-focused design.
 */

'use client';

import { MapPin } from 'lucide-react';
import React from 'react';

import { cn } from '@/lib/utils';

export interface NeighborhoodOption {
  name: string;
  description: string;
  /** Price tier: $ to $$$$ */
  priceTier?: string;
  /** Whether this is the recommended option */
  isRecommended?: boolean;
  /** Tags like "First Time", "Nightlife", "Beach" */
  tags?: string[];
}

export interface NeighborhoodStrategyCardProps {
  neighborhoods: NeighborhoodOption[];
  className?: string;
}

export function NeighborhoodStrategyCard({ neighborhoods, className }: NeighborhoodStrategyCardProps) {
  if (neighborhoods.length === 0) return null;

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
      <div className="flex items-center gap-2 mb-4">
        <MapPin className="w-4 h-4 text-emerald-600 dark:text-emerald-400" />
        <h4 className="text-sm font-bold text-zinc-900 dark:text-white">Strategic Base (Where to Stay)</h4>
      </div>

      {/* Neighborhood options */}
      <div className="space-y-4">
        {neighborhoods.map((neighborhood, idx) => (
          <React.Fragment key={neighborhood.name}>
            {idx > 0 && <div className="h-px bg-zinc-200 dark:bg-white/5" />}
            <div className="flex justify-between items-start">
              <div className="flex-1 min-w-0 pr-3 space-y-1">
                <p className="text-sm font-semibold text-zinc-800 dark:text-zinc-200">
                  {neighborhood.name}
                </p>
                <p className="text-xs text-zinc-500 dark:text-zinc-400 leading-relaxed">
                  {neighborhood.description}
                </p>
                {/* Tags */}
                {neighborhood.tags && neighborhood.tags.length > 0 && (
                  <div className="flex gap-2 mt-1 flex-wrap">
                    {neighborhood.tags.map((tag) => (
                      <span
                        key={tag}
                        className="text-[10px] bg-zinc-100 dark:bg-zinc-800 px-1.5 py-0.5 rounded text-zinc-600 dark:text-zinc-400"
                      >
                        {tag}
                      </span>
                    ))}
                  </div>
                )}
              </div>
              {neighborhood.priceTier && (
                <span className="text-xs font-bold text-zinc-400 dark:text-zinc-500 shrink-0">
                  {neighborhood.priceTier}
                </span>
              )}
            </div>
          </React.Fragment>
        ))}
      </div>
    </div>
  );
}
