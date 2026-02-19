'use client';

import { motion } from 'framer-motion';

import { SPRING_CONFIG } from '@/lib/animation-config';
import { cn } from '@/lib/utils';
import type { DayBlock } from '@/types/plan-envelope';

interface DragPreviewCardProps {
  block: DayBlock;
}

export function DragPreviewCard({ block }: DragPreviewCardProps) {
  return (
    <motion.div
      initial={{ scale: 0.95, opacity: 0 }}
      animate={{ scale: 1.03, opacity: 1 }}
      transition={{ type: 'spring', ...SPRING_CONFIG.BOUNCE }}
      className={cn(
        'w-64 rounded-xl px-3 py-2.5',
        'pointer-events-none',
        // Glass Fill material
        'bg-white/95 dark:bg-zinc-900/95',
        'backdrop-blur-xl',
        'border border-zinc-200/50 dark:border-white/10',
        // Elevated shadow
        'shadow-[0_25px_50px_rgba(0,0,0,0.15)] dark:shadow-[0_25px_50px_rgba(0,0,0,0.4)]',
        // Emerald accent ring
        'ring-1 ring-emerald-500/30 dark:ring-emerald-500/20',
      )}
    >
      <div className="flex items-center gap-2.5">
        {block.image_url && (
          <img
            src={block.image_url}
            alt=""
            className="h-10 w-10 rounded-lg object-cover shrink-0"
          />
        )}
        <div className="min-w-0">
          <p className="truncate text-sm font-medium text-zinc-900 dark:text-white">
            {block.summary || block.activity_type}
          </p>
          {block.specialist_type && (
            <span className="text-[10px] uppercase font-semibold tracking-wide text-emerald-600 dark:text-emerald-400">
              {block.specialist_type}
            </span>
          )}
        </div>
      </div>
    </motion.div>
  );
}
