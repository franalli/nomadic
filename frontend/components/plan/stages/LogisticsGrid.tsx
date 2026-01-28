/**
 * LogisticsGrid
 *
 * 3-column responsive grid showing transport, visa, and weather info.
 * Used by LocalExpert specialist to display logistics notes.
 */

'use client';

import {
  Car,
  CloudSun,
  CreditCard,
  FileCheck,
  Info,
  type LucideIcon,
  Shirt,
} from 'lucide-react';
import { memo } from 'react';

import { cn } from '@/lib/utils';

interface LogisticsItem {
  type: 'transport' | 'visa' | 'weather' | 'packing' | 'payment' | 'general';
  title: string;
  content: string;
  tip?: string;
}

interface LogisticsGridProps {
  items: LogisticsItem[];
}

const typeConfig: Record<
  LogisticsItem['type'],
  { icon: LucideIcon; color: string }
> = {
  transport: { icon: Car, color: 'text-blue-500 bg-blue-500/10' },
  visa: { icon: FileCheck, color: 'text-emerald-500 bg-emerald-500/10' },
  weather: { icon: CloudSun, color: 'text-amber-500 bg-amber-500/10' },
  packing: { icon: Shirt, color: 'text-violet-500 bg-violet-500/10' },
  payment: { icon: CreditCard, color: 'text-pink-500 bg-pink-500/10' },
  general: { icon: Info, color: 'text-zinc-500 bg-zinc-500/10' },
};

export const LogisticsGrid = memo(function LogisticsGrid({
  items,
}: LogisticsGridProps) {
  if (!items || items.length === 0) return null;

  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
      {items.map((item, idx) => {
        const config = typeConfig[item.type] || typeConfig.general;
        const Icon = config.icon;

        return (
          <div
            key={idx}
            className={cn(
              'rounded-lg border p-3',
              'bg-white dark:bg-zinc-900',
              'border-zinc-200 dark:border-zinc-800'
            )}
          >
            {/* Header */}
            <div className="flex items-center gap-2 mb-2">
              <div
                className={cn(
                  'flex items-center justify-center w-7 h-7 rounded-md',
                  config.color
                )}
              >
                <Icon className="w-4 h-4" />
              </div>
              <h4 className="text-sm font-medium text-zinc-900 dark:text-white">
                {item.title}
              </h4>
            </div>

            {/* Content */}
            <p className="text-xs text-zinc-600 dark:text-zinc-400 leading-relaxed">
              {item.content}
            </p>

            {/* Tip (optional) */}
            {item.tip && (
              <div className="mt-2 pt-2 border-t border-zinc-100 dark:border-zinc-800">
                <p className="text-[10px] text-emerald-600 dark:text-emerald-400 font-medium">
                  💡 {item.tip}
                </p>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
});

export default LogisticsGrid;
