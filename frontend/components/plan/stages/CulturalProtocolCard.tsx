/**
 * CulturalProtocolCard
 *
 * "Cultural & Social Protocol" strategic advice card.
 * Shows dress code, tipping, alcohol rules, and social norms.
 * Part of the Plan tab's strategy-focused "friction reducer" design.
 */

'use client';

import type { LucideIcon } from 'lucide-react';

import { cn } from '@/lib/utils';

export interface ProtocolItem {
  icon: LucideIcon;
  title: string;
  /** HTML-safe content with <strong> and <br/> allowed */
  content: string;
}

export interface CulturalProtocolCardProps {
  items: ProtocolItem[];
  className?: string;
}

export function CulturalProtocolCard({ items, className }: CulturalProtocolCardProps) {
  if (items.length === 0) return null;

  return (
    <div className={cn('grid grid-cols-1 md:grid-cols-2 gap-3', className)}>
      {items.map((item) => {
        const Icon = item.icon;
        return (
          <div
            key={item.title}
            className={cn(
              'p-3 rounded-lg border transition-colors',
              // Light mode
              'border-zinc-200 bg-white',
              // Dark mode
              'dark:border-white/10 dark:bg-black/20'
            )}
          >
            <div className="flex items-center gap-2 mb-2">
              <Icon className="w-4 h-4 text-zinc-400 dark:text-zinc-500" />
              <span className="text-sm font-semibold text-zinc-900 dark:text-white">
                {item.title}
              </span>
            </div>
            <p
              className="text-xs text-zinc-500 dark:text-zinc-400 leading-relaxed"
              dangerouslySetInnerHTML={{ __html: item.content }}
            />
          </div>
        );
      })}
    </div>
  );
}
