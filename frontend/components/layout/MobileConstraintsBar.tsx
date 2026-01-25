'use client';

import { Calendar, ChevronDown, MapPin, Plane,Wallet } from 'lucide-react';
import { memo, useMemo, useState } from 'react';

import { formatBudget, formatDateRange } from '@/lib/plan-transform';
import { cn } from '@/lib/utils';
import { useDocumentStore } from '@/state/documentStore';

// ─────────────────────────────────────────────────────────────────────────────
// MobileConstraintsBar Component
// ─────────────────────────────────────────────────────────────────────────────

interface MobileConstraintsBarProps {
  className?: string;
}

function MobileConstraintsBarInner({ className }: MobileConstraintsBarProps) {
  const [expanded, setExpanded] = useState(false);
  const tripInputs = useDocumentStore((state) => state.document?.trip_inputs);

  // Derive resolved constraints
  const constraints = useMemo(() => {
    if (!tripInputs) return { resolved: [], unset: [] };

    const resolved: { icon: typeof MapPin; label: string }[] = [];
    const unset: { icon: typeof MapPin; label: string }[] = [];

    // Destination
    if (tripInputs.destination) {
      resolved.push({
        icon: MapPin,
        label: tripInputs.destination,
      });
    } else {
      unset.push({ icon: MapPin, label: 'Destination' });
    }

    // Origin
    if (tripInputs.origin) {
      resolved.push({
        icon: Plane,
        label: tripInputs.origin,
      });
    } else {
      unset.push({ icon: Plane, label: 'Origin' });
    }

    // Dates
    const dateRange = formatDateRange(tripInputs.start_date, tripInputs.end_date);
    if (dateRange) {
      resolved.push({
        icon: Calendar,
        label: dateRange,
      });
    } else {
      unset.push({ icon: Calendar, label: 'Dates' });
    }

    // Budget
    const budget = formatBudget(tripInputs.budget, tripInputs.currency ?? 'EUR');
    if (budget) {
      resolved.push({
        icon: Wallet,
        label: budget,
      });
    } else {
      unset.push({ icon: Wallet, label: 'Budget' });
    }

    return { resolved, unset };
  }, [tripInputs]);

  // Collapsed summary: show resolved constraints
  const collapsedSummary = constraints.resolved.map((c) => c.label).join(' · ');

  return (
    <div
      className={cn(
        'sticky top-0 z-40 bg-background/95 backdrop-blur border-b border-border/50',
        'lg:hidden', // Only show on mobile
        className
      )}
    >
      {/* Collapsed bar */}
      <button
        type="button"
        onClick={() => setExpanded(!expanded)}
        className="w-full p-3 flex items-center justify-between"
        aria-expanded={expanded}
        aria-label="Toggle constraints panel"
      >
        <div className="flex items-center gap-2 min-w-0 flex-1">
          {collapsedSummary ? (
            <span className="text-sm font-medium text-foreground truncate">
              {collapsedSummary}
            </span>
          ) : (
            <span className="text-sm text-muted-foreground">
              Set trip constraints
            </span>
          )}
          {constraints.unset.length > 0 && (
            <span className="text-xs text-muted-foreground/70 shrink-0">
              + {constraints.unset.length} more
            </span>
          )}
        </div>
        <ChevronDown
          className={cn(
            'h-4 w-4 text-muted-foreground transition-transform shrink-0',
            expanded && 'rotate-180'
          )}
        />
      </button>

      {/* Expanded content */}
      {expanded && (
        <div className="px-3 pb-3 space-y-3">
          {/* Resolved constraints */}
          {constraints.resolved.length > 0 && (
            <div className="flex flex-wrap gap-2">
              {constraints.resolved.map(({ icon: Icon, label }) => (
                <div
                  key={label}
                  className="inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg bg-card border border-border/50 text-sm"
                >
                  <Icon className="h-3.5 w-3.5 text-muted-foreground" />
                  <span className="text-foreground">{label}</span>
                </div>
              ))}
            </div>
          )}

          {/* Unset constraints */}
          {constraints.unset.length > 0 && (
            <div className="flex flex-wrap gap-2">
              {constraints.unset.map(({ icon: Icon, label }) => (
                <div
                  key={label}
                  className="inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg border border-dashed border-muted-foreground/30 text-sm"
                >
                  <Icon className="h-3.5 w-3.5 text-muted-foreground/50" />
                  <span className="text-muted-foreground/70">+ {label}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export const MobileConstraintsBar = memo(MobileConstraintsBarInner);
