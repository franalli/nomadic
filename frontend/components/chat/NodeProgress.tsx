'use client';

import {
  AlertCircle,
  Bike,
  Building2,
  Car,
  ClipboardList,
  Globe,
  type LucideIcon,
  MapPin,
  Mountain,
  Plane,
  Sailboat,
  Snowflake,
  Sparkles,
  Waves,
} from 'lucide-react';
import { useEffect, useState } from 'react';

// Icon mapping by icon_key from backend
const ICON_MAP: Record<string, LucideIcon> = {
  // Strategy topics (for strategy_node)
  hiking: Mountain,
  skiing: Snowflake,
  diving: Waves,
  cycling: Bike,
  boating: Sailboat,
  // Specialist node icons
  plane: Plane,
  building: Building2,
  car: Car,
  'map-pin': MapPin,
  globe: Globe,
  clipboard: ClipboardList,
  'alert-circle': AlertCircle,
  sparkles: Sparkles,
};

interface NodeProgressProps {
  node: string;
  label: string;
  iconKey: string;
  estimatedDurationMs: number;
  startTime: number;
  // Strategy-specific (optional)
  stage?: number;
  topic?: string;
  // Action-specific copy (optional, overrides default label/stage)
  actionTitle?: string;
  actionSubtext?: string;
}

// Stage labels for strategy node
const STAGE_LABELS: Record<number, string> = {
  0: 'Getting inspiration',
  1: 'Creating outline',
  2: 'Expanding details',
};

export const NodeProgress = ({
  node,
  label,
  iconKey,
  estimatedDurationMs,
  startTime,
  stage,
  actionTitle,
  actionSubtext,
}: NodeProgressProps) => {
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    const interval = setInterval(() => {
      setElapsed(Date.now() - startTime);
    }, 100);
    return () => clearInterval(interval);
  }, [startTime]);

  // Calculate progress with ease-out curve for smooth deceleration towards 100%
  const rawProgress = Math.min(elapsed / estimatedDurationMs, 1);
  // Ease-out exponential: 1 - (1 - x)^3 - starts fast, slows as it nears 100%
  const timeProgress = 1 - Math.pow(1 - rawProgress, 3);
  const progress = timeProgress;

  const Icon = ICON_MAP[iconKey] || Globe;
  const isComplete = progress >= 0.98;

  // For strategy node, show stage label; otherwise just show the label
  const isStrategyNode = node === 'strategy_node';
  const stageLabel = isStrategyNode && stage !== undefined ? STAGE_LABELS[stage] : null;

  // Time remaining estimate
  const remainingMs = Math.max(0, estimatedDurationMs - elapsed);
  const remainingSec = Math.ceil(remainingMs / 1000);
  const timeLabel = isComplete
    ? 'Finishing up...'
    : remainingSec <= 1
      ? 'Almost done...'
      : `~${remainingSec}s remaining`;

  // Use action-specific copy if provided, otherwise fall back to default
  const displayLabel = actionTitle ?? label;
  const displaySubtext = actionSubtext ?? stageLabel ?? null;

  return (
    <div className="text-left message-enter">
      <div className="border border-border/40 bg-gradient-to-br from-muted via-muted to-muted/70 text-foreground inline-flex flex-col gap-2 rounded-2xl rounded-bl-md px-4 py-3 shadow-[0_2px_6px_rgba(0,0,0,0.06),0_4px_12px_rgba(0,0,0,0.04),inset_0_1px_0_rgba(255,255,255,0.6)] dark:shadow-[0_2px_6px_rgba(0,0,0,0.2),0_4px_12px_rgba(0,0,0,0.15),inset_0_1px_0_rgba(255,255,255,0.08)]">
        <div className="flex items-center gap-2 text-sm">
          <Icon
            className={`h-4 w-4 animate-pulse transition-colors duration-500 ${isComplete ? 'text-emerald-500' : 'text-primary'}`}
          />
          <span className="font-medium">{displayLabel}</span>
          {displaySubtext && (
            <>
              <span className="text-muted-foreground">-</span>
              <span className="text-muted-foreground">{displaySubtext}</span>
            </>
          )}
        </div>

        {/* Progress bar with time estimate */}
        <div className="flex items-center gap-2">
          <div className="w-40 h-1.5 bg-muted-foreground/20 rounded-full overflow-hidden">
            <div
              className={`h-full transition-all duration-500 ease-out rounded-full ${isComplete ? 'bg-emerald-500' : 'bg-primary'}`}
              style={{ width: `${Math.min(progress * 100, 100)}%` }}
            />
          </div>
          <span className="text-xs text-muted-foreground whitespace-nowrap">{timeLabel}</span>
        </div>
      </div>
    </div>
  );
};
