'use client';

import type { LucideIcon } from 'lucide-react';
import {
  Bed,
  Camera,
  Mountain,
  PlaneLanding,
  PlaneTakeoff,
  ShieldAlert,
  Sparkles,
  Utensils,
  Waves,
} from 'lucide-react';

import type { DayBlock } from '@/types/plan-envelope';

export function getIconForBlock(block: DayBlock): LucideIcon {
  const type = block.activity_type?.toLowerCase() || '';
  const summary = block.summary?.toLowerCase() || '';

  if (block.buffer_type === 'arrival') return PlaneLanding;
  if (block.buffer_type === 'departure') return PlaneTakeoff;
  if (block.is_buffer || block.buffer_type) return ShieldAlert;
  if (type.includes('dive') || summary.includes('dive') || summary.includes('snorkel')) return Waves;
  if (type.includes('hike') || summary.includes('hike') || summary.includes('trek')) return Mountain;
  if (
    type.includes('meal') ||
    type.includes('dining') ||
    summary.includes('dinner') ||
    summary.includes('lunch')
  ) {
    return Utensils;
  }
  if (type.includes('hotel') || type.includes('stay') || summary.includes('check-in') || summary.includes('check in')) {
    return Bed;
  }
  if (type.includes('tour') || summary.includes('tour') || summary.includes('sightseeing')) {
    return Camera;
  }

  return Sparkles;
}

export function filterBlocks(blocks: DayBlock[]): DayBlock[] {
  const hasSpecialist = blocks.some(
    (block) => block.specialist_type && !['general', 'local_expert'].includes(block.specialist_type)
  );
  if (!hasSpecialist) return blocks;

  return blocks.filter((block) => {
    const summary = (block.summary || '').toLowerCase();
    const type = (block.activity_type || '').toLowerCase();

    if (block.specialist_type && !['general', 'local_expert'].includes(block.specialist_type)) {
      return true;
    }
    if (summary.includes('explore') || type.includes('general')) {
      return false;
    }
    return true;
  });
}
