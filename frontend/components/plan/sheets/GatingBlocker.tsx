'use client';
/**
 * GatingBlocker
 *
 * Shared prerequisite-gating component for module sheets (Flights, Stays, Activities).
 * Renders a notice with buttons to resolve unmet prerequisites.
 * Returns null when all gates are met.
 */

'use client';

import { AlertCircle } from 'lucide-react';
import { useEffect, useRef } from 'react';

import { DS } from '@/lib/design-system';
import { cn } from '@/lib/utils';

// ─────────────────────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────────────────────

interface Gate {
  /** Human-readable label, e.g. "Destination" */
  label: string;
  /** Whether this prerequisite is satisfied */
  met: boolean;
  /** Callback to open the sheet that resolves this gate */
  onOpen?: () => void;
}

interface GatingBlockerProps {
  /** Feature name shown in the message, e.g. "flights", "stays", "activities" */
  featureLabel: string;
  /** Ordered list of prerequisite gates */
  gates: Gate[];
  /** Close the current sheet (called before opening a gate's sheet) */
  onClose: () => void;
}

// ─────────────────────────────────────────────────────────────────────────────
// Component
// ─────────────────────────────────────────────────────────────────────────────

export function GatingBlocker({ featureLabel, gates, onClose }: GatingBlockerProps) {
  const gateTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    return () => {
      if (gateTimeoutRef.current) clearTimeout(gateTimeoutRef.current);
    };
  }, []);

  const unmet = gates.filter((g) => !g.met);

  if (unmet.length === 0) return null;

  const missing = unmet.map((g) => g.label);

  return (
    <div className={cn(
      // Clean, cool technical surface
      'mb-4 p-5 rounded-xl flex gap-4 items-start',
      'bg-zinc-50 dark:bg-white/[0.02]',
      'border border-zinc-100 dark:border-white/5'
    )}>
      <AlertCircle className="h-5 w-5 text-zinc-400 dark:text-zinc-500 flex-shrink-0 mt-0.5" />
      <div className="flex-1 min-w-0">
        <p className="text-sm text-zinc-600 dark:text-zinc-400">
          To include {featureLabel}, set {missing.join(' + ')}.
        </p>
        <div className="flex flex-wrap gap-2 mt-4">
          {unmet.map((gate) =>
            gate.onOpen ? (
              <button
                key={gate.label}
                type="button"
                onClick={() => {
                  onClose();
                  gateTimeoutRef.current = setTimeout(gate.onOpen!, 150);
                }}
                className={cn(
                  `${DS.textSize.micro} font-bold uppercase tracking-wide`,
                  'bg-zinc-800 dark:bg-zinc-700 text-white',
                  'px-3 py-1.5 rounded-lg',
                  'hover:bg-emerald-600 dark:hover:bg-emerald-500',
                  'transition-colors'
                )}
              >
                Set {gate.label.toLowerCase()}
              </button>
            ) : null
          )}
        </div>
        <p className="text-xs text-zinc-500 dark:text-zinc-500 mt-2">
          You can keep defaults for everything else.
        </p>
      </div>
    </div>
  );
}
