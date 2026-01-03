'use client';

import { Bike, Mountain, Sailboat, Snowflake, Waves } from 'lucide-react';
import { useEffect, useState } from 'react';

interface StrategyProgressProps {
  stage: number;
  tier: 'outline' | 'section' | 'full';
  topic: 'hiking' | 'skiing' | 'diving' | 'cycling' | 'boating';
  estimatedDurationMs: number;
  startTime: number;
}

const TOPIC_ICONS = {
  hiking: Mountain,
  skiing: Snowflake,
  diving: Waves,
  cycling: Bike,
  boating: Sailboat,
};

const TOPIC_LABELS = {
  hiking: 'Hiking',
  skiing: 'Skiing',
  diving: 'Diving',
  cycling: 'Cycling',
  boating: 'Boating',
};

const STAGE_LABELS: Record<number, string> = {
  0: 'Getting inspiration',
  1: 'Creating outline',
  2: 'Expanding details',
};

export const StrategyProgress = ({
  stage,
  topic,
  estimatedDurationMs,
  startTime,
}: StrategyProgressProps) => {
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    const interval = setInterval(() => {
      setElapsed(Date.now() - startTime);
    }, 100);
    return () => clearInterval(interval);
  }, [startTime]);

  // Calculate progress with ease-out curve for smooth deceleration towards 100%
  // Uses exponential ease-out: starts fast, slows down as it approaches completion
  const rawProgress = Math.min(elapsed / estimatedDurationMs, 1);
  // Ease-out exponential: 1 - (1 - x)^3 - starts fast, slows as it nears 100%
  const timeProgress = 1 - Math.pow(1 - rawProgress, 3);
  const progress = timeProgress;

  const Icon = TOPIC_ICONS[topic] || Mountain;
  const stageLabel = STAGE_LABELS[stage] || 'Processing';
  const topicLabel = TOPIC_LABELS[topic] || topic;
  const isComplete = progress >= 0.98;

  // Tier 10.7: Calculate remaining time estimate
  const remainingMs = Math.max(0, estimatedDurationMs - elapsed);
  const remainingSec = Math.ceil(remainingMs / 1000);
  const timeLabel = isComplete
    ? 'Finishing up...'
    : remainingSec <= 1
      ? 'Almost done...'
      : `~${remainingSec}s remaining`;

  return (
    <div className="text-left message-enter">
      <div className="border border-border/40 bg-gradient-to-br from-muted via-muted to-muted/70 text-foreground inline-flex flex-col gap-2 rounded-2xl rounded-bl-md px-4 py-3 shadow-[0_2px_6px_rgba(0,0,0,0.06),0_4px_12px_rgba(0,0,0,0.04),inset_0_1px_0_rgba(255,255,255,0.6)] dark:shadow-[0_2px_6px_rgba(0,0,0,0.2),0_4px_12px_rgba(0,0,0,0.15),inset_0_1px_0_rgba(255,255,255,0.08)]">
        <div className="flex items-center gap-2 text-sm">
          <Icon className={`h-4 w-4 animate-pulse transition-colors duration-500 ${isComplete ? 'text-amber-500' : 'text-primary'}`} />
          <span className="font-medium">{topicLabel}</span>
          <span className="text-muted-foreground">-</span>
          <span className="text-muted-foreground">{stageLabel}</span>
        </div>

        {/* Progress bar with time estimate */}
        <div className="flex items-center gap-2">
          <div className="w-40 h-1.5 bg-muted-foreground/20 rounded-full overflow-hidden">
            <div
              className={`h-full transition-all duration-500 ease-out rounded-full ${isComplete ? 'bg-amber-500' : 'bg-primary'}`}
              style={{ width: `${Math.min(progress * 100, 100)}%` }}
            />
          </div>
          <span className="text-xs text-muted-foreground whitespace-nowrap">{timeLabel}</span>
        </div>
      </div>
    </div>
  );
};
