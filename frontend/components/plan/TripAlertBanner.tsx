'use client';

import { X } from 'lucide-react';
import { useMemo, useState } from 'react';

import { extractTripAlerts } from '@/lib/travelIntel';
import { cn } from '@/lib/utils';
import type { StrategySection } from '@/types/plan-envelope';

interface TripAlertBannerProps {
  sections?: StrategySection[];
  className?: string;
}

const MAX_VISIBLE = 3;

export function TripAlertBanner({ sections, className }: TripAlertBannerProps) {
  const [dismissedIds, setDismissedIds] = useState<Set<string>>(new Set());
  const [showAll, setShowAll] = useState(false);
  const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set());

  const activeAlerts = useMemo(() => {
    const alerts = extractTripAlerts(sections);
    return alerts.filter(alert => !dismissedIds.has(alert.id));
  }, [dismissedIds, sections]);

  if (activeAlerts.length === 0) return null;

  const visible = showAll ? activeAlerts : activeAlerts.slice(0, MAX_VISIBLE);
  const hiddenCount = Math.max(activeAlerts.length - visible.length, 0);

  return (
    <section className={cn('px-4', className)}>
      <div className="space-y-1">
        {visible.map((alert) => {
          const expanded = expandedIds.has(alert.id);
          const isBlocking = alert.severity === 'blocking';
          return (
            <div
              key={alert.id}
              className={cn(
                'rounded-lg border px-3 py-2',
                isBlocking
                  ? 'border-red-600/30 bg-red-950/30'
                  : 'border-amber-600/30 bg-amber-950/30',
              )}
              style={{ borderLeftWidth: 4 }}
            >
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <p className="text-sm font-semibold text-zinc-100">
                    {alert.icon} {alert.title}
                  </p>
                  {expanded && (
                    <p className="mt-1 text-sm text-zinc-300">
                      {alert.description}
                    </p>
                  )}
                </div>
                <div className="flex items-center gap-1">
                  <button
                    type="button"
                    onClick={() => {
                      setExpandedIds((prev) => {
                        const next = new Set(prev);
                        if (next.has(alert.id)) next.delete(alert.id);
                        else next.add(alert.id);
                        return next;
                      });
                    }}
                    className="rounded px-1.5 py-0.5 text-xs font-medium text-zinc-200 hover:bg-white/10"
                  >
                    {expanded ? 'Less' : 'More →'}
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      setDismissedIds((prev) => {
                        const next = new Set(prev);
                        next.add(alert.id);
                        return next;
                      });
                    }}
                    aria-label="Dismiss alert"
                    className="rounded p-1 text-zinc-300 hover:bg-white/10"
                  >
                    <X className="h-3.5 w-3.5" />
                  </button>
                </div>
              </div>
            </div>
          );
        })}

        {hiddenCount > 0 && !showAll && (
          <button
            type="button"
            onClick={() => setShowAll(true)}
            className="text-xs font-medium text-zinc-400 hover:text-zinc-200"
          >
            + {hiddenCount} more alert{hiddenCount === 1 ? '' : 's'}
          </button>
        )}
      </div>
    </section>
  );
}

export default TripAlertBanner;
