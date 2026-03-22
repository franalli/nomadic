'use client';

import { motion } from 'framer-motion';

import { getTopicLabel } from '@/components/plan/stages/StrategyHeroUtils';
import { SPRING_CONFIG } from '@/lib/animation-config';
import { DS } from '@/lib/design-system';
import { SPECIALIST_TEXT_COLOR } from '@/lib/specialist-colors';
import { cn } from '@/lib/utils';
import type { DayBlock } from '@/types/plan-envelope';

// Animation constants (hoisted to avoid new object refs per render)
const PREVIEW_INITIAL = { scale: 0.95, opacity: 0 };
const PREVIEW_ANIMATE = { scale: 1.03, opacity: 1 };
const PREVIEW_TRANSITION = { type: 'spring' as const, ...SPRING_CONFIG.BOUNCE };

interface DragPreviewCardProps {
  block: DayBlock;
}

export function DragPreviewCard({ block }: DragPreviewCardProps) {
  const specialistColor = block.specialist_type
    ? (SPECIALIST_TEXT_COLOR[block.specialist_type] ?? 'text-emerald-600 dark:text-emerald-400')
    : null;
  const price = block.booked_tile?.price_estimate;

  return (
    <motion.div
      initial={PREVIEW_INITIAL}
      animate={PREVIEW_ANIMATE}
      transition={PREVIEW_TRANSITION}
      className={cn(
        'w-64 rounded-xl px-3 py-2.5',
        'pointer-events-none',
        // Glass surface — manual composition to preserve rounded-xl + custom shadow
        'bg-white/95 dark:bg-zinc-900/95',
        'backdrop-blur-xl',
        'border border-zinc-200 dark:border-white/10',
        // Elevated shadow
        `${DS.shadow.dragPreview} dark:${DS.shadow.dragPreviewDark}`,
        // Emerald accent ring
        'ring-1 ring-emerald-500/30 dark:ring-emerald-500/20',
      )}
    >
      <div className="flex items-center gap-2.5">
        {block.image_url && (
          <img
            src={block.image_url}
            alt=""
            loading="eager"
            className="h-10 w-10 rounded-lg object-cover shrink-0"
          />
        )}
        <div className="min-w-0">
          <p className="truncate text-sm font-medium text-zinc-900 dark:text-white">
            {block.summary || block.activity_type}
          </p>
          <div className="flex items-center gap-1.5 mt-0.5">
            {specialistColor && (
              <span className={cn(DS.textSize.micro, 'uppercase font-semibold tracking-wide', specialistColor)}>
                {getTopicLabel(block.specialist_type!)}
              </span>
            )}
            {price != null && price > 0 && (
              <span className={cn(DS.textSize.micro, 'font-medium text-zinc-500 dark:text-zinc-400')}>
                ~${price.toLocaleString()}
              </span>
            )}
          </div>
        </div>
      </div>
    </motion.div>
  );
}
