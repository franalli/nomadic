/**
 * InfoCard
 *
 * Simple card for logistics grid (Visa, Plugs, Weather, Currency).
 * Part of the "Local Intel" display - strategy, not booking.
 */

'use client';

import type { LucideIcon } from 'lucide-react';

import { cn } from '@/lib/utils';

export interface InfoCardProps {
  icon: LucideIcon;
  title: string;
  text: string;
  className?: string;
}

export function InfoCard({ icon: Icon, title, text, className }: InfoCardProps) {
  return (
    <div
      className={cn(
        'p-3 rounded-xl border transition-colors',
        // Light mode - matches DS.materials.surface
        'bg-zinc-50 border-zinc-100',
        // Dark mode - Glass Fill Rule: bg-white/[0.03] for secondary surfaces
        'dark:bg-white/[0.03] dark:border-white/5',
        className
      )}
    >
      <div className="flex items-center gap-2 mb-1.5">
        <Icon className="w-3.5 h-3.5 text-emerald-600 dark:text-emerald-400" />
        <span className="text-xs font-semibold text-zinc-700 dark:text-zinc-300">{title}</span>
      </div>
      <p className="text-xs text-zinc-500 dark:text-zinc-400 leading-relaxed">{text}</p>
    </div>
  );
}
