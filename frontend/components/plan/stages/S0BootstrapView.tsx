/**
 * S0BootstrapView
 *
 * Bootstrap state view - shows scaffold checklist with state indicators.
 * Displays progress toward plan generation.
 *
 * Content rules:
 * - No destination: "Your plan" title, "Set destination and dates to begin"
 * - With destination: Destination name as title, scaffold with status indicators
 * - Status indicators: Set (check), Next (arrow), Locked (lock)
 */

'use client';

import { ArrowRight, Check, Lock } from 'lucide-react';

import { cn } from '@/lib/utils';
import type { DestinationCard } from '@/types/plan-envelope';

interface S0BootstrapViewProps {
  destinationCard?: DestinationCard;
  /** Whether user can generate a plan (has destination + dates) */
  canGeneratePlan?: boolean;
}

type ScaffoldStatus = 'Set' | 'Next' | 'Locked';

export function S0BootstrapView({ destinationCard, canGeneratePlan = false }: S0BootstrapViewProps) {
  const hasDestination = !!destinationCard;

  // No destination yet - show initial scaffold
  if (!hasDestination) {
    return (
      <EmptyScaffold
        title="Your plan"
        subtitle="Set destination and dates to begin."
        rows={[
          { label: 'Destination', state: 'Next' },
          { label: 'Strategy', state: 'Locked' },
          { label: 'Itinerary', state: 'Locked' },
        ]}
      />
    );
  }

  // Destination set, no plan yet - show progress scaffold
  return (
    <EmptyScaffold
      title={destinationCard.title}
      subtitle="As you set constraints, your trip plan will take shape here."
      rows={[
        { label: 'Destination', state: 'Set' },
        { label: 'Strategy', state: canGeneratePlan ? 'Next' : 'Locked' },
        { label: 'Itinerary', state: 'Locked' },
      ]}
    />
  );
}

interface ScaffoldRow {
  label: string;
  state: ScaffoldStatus;
}

interface EmptyScaffoldProps {
  title: string;
  subtitle: string;
  rows: ScaffoldRow[];
}

function EmptyScaffold({ title, subtitle, rows }: EmptyScaffoldProps) {
  return (
    <div className="flex flex-col h-full p-6 justify-center items-center">
      <div className="w-full max-w-xs mx-auto text-center">
        {/* Title */}
        <h2 className="text-lg font-medium text-[var(--theme-text)]">
          {title}
        </h2>
        {/* Subtitle */}
        <p className="text-sm text-[var(--theme-text-muted)] mt-1 mb-6">
          {subtitle}
        </p>

        {/* Progress checklist */}
        <div className="space-y-2">
          {rows.map((row) => (
            <ScaffoldRowComponent key={row.label} label={row.label} state={row.state} />
          ))}
        </div>
      </div>
    </div>
  );
}

function ScaffoldRowComponent({ label, state }: { label: string; state: ScaffoldStatus }) {
  const config: Record<ScaffoldStatus, { Icon: typeof Check; iconClass: string; textClass: string }> = {
    Set: { Icon: Check, iconClass: 'text-primary', textClass: 'text-primary' },
    Next: { Icon: ArrowRight, iconClass: 'text-amber-500', textClass: 'text-amber-500' },
    Locked: { Icon: Lock, iconClass: 'text-[var(--theme-text-muted)] opacity-50', textClass: 'text-[var(--theme-text-muted)] opacity-50' },
  };
  const { Icon, iconClass, textClass } = config[state];

  return (
    <div
      className="flex items-center gap-3 px-3 py-2.5 bg-[var(--theme-panel)] border border-[var(--theme-border)] rounded-md"
      style={{ boxShadow: 'var(--theme-shadow)' }}
    >
      <Icon className={cn('w-4 h-4', iconClass)} />
      <span className="flex-1 text-sm text-[var(--theme-text)] text-left">{label}</span>
      <span className={cn('text-xs font-medium', textClass)}>{state}</span>
    </div>
  );
}

export default S0BootstrapView;
