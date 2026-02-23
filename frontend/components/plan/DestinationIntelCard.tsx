'use client';

import { ChevronDown } from 'lucide-react';
import { useMemo, useState } from 'react';

import { DS } from '@/lib/design-system';
import { buildDestinationIntel, destinationFlag } from '@/lib/travelIntel';
import { cn } from '@/lib/utils';
import type { StrategySection } from '@/types/plan-envelope';

interface DestinationIntelCardProps {
  destination?: string | null;
  sections?: StrategySection[];
  className?: string;
}

export function DestinationIntelCard({
  destination,
  sections,
  className,
}: DestinationIntelCardProps) {
  const [expanded, setExpanded] = useState(false);
  const { categories, summaryLabels } = useMemo(
    () => buildDestinationIntel(sections),
    [sections]
  );

  if (categories.length === 0) return null;

  const place = destination || 'Destination';
  const flag = destinationFlag(destination);
  const categoryLabel = summaryLabels.join(' · ');
  const collapsedLabel = `${flag} ${place} Travel Intel`;

  return (
    <section className={cn('px-4', className)}>
      <div className="space-y-2">
        <button
          type="button"
          onClick={() => setExpanded(v => !v)}
          aria-expanded={expanded}
          className={cn(
            'w-full h-7 px-2.5 text-left',
            'inline-flex items-center justify-between gap-2 rounded-lg border',
            'border-zinc-600/50 bg-zinc-900/40',
            'text-zinc-400 hover:bg-zinc-800/50 transition-colors'
          )}
        >
          <p className="truncate text-sm text-zinc-400">
            {collapsedLabel}
          </p>
          <ChevronDown
            className={cn(
              'h-4 w-4 shrink-0 text-zinc-400 transition-transform',
              expanded && 'rotate-180'
            )}
          />
        </button>

        {expanded && (
          <div className="rounded-xl border border-zinc-700/30 bg-zinc-800/40">
            <div className="border-b border-zinc-700/30 px-3 py-2">
              <h3 className="truncate text-sm font-medium text-zinc-200">
                {flag} {place} Travel Intel
              </h3>
              {categoryLabel && (
                <p className={cn(DS.textSize.micro, 'mt-0.5 truncate text-zinc-400')}>
                  {categoryLabel}
                </p>
              )}
            </div>

            <div className="max-h-[280px] space-y-2 overflow-y-auto px-3 py-3">
              {categories.map((category) => (
                <div key={category.key} className="space-y-1">
                  <p className="flex items-center gap-2 text-sm font-medium text-zinc-200">
                    <span>{category.icon}</span>
                    <span>{category.label}</span>
                  </p>
                  <ul className="list-disc list-outside marker:text-emerald-400 space-y-1 pl-10">
                    {category.items.map((item) => (
                      <li key={item} className="text-sm leading-relaxed text-zinc-400">
                        {item}
                      </li>
                    ))}
                  </ul>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </section>
  );
}

export default DestinationIntelCard;
