/**
 * TileSectionHeader
 *
 * Contextual header for tile sections with specialist awareness.
 * Displays dynamic title/subtitle based on active specialists.
 */

'use client';

import { ChevronDown } from 'lucide-react';

import { generateTileHeader } from '@/lib/specialist-utils';
import { cn } from '@/lib/utils';

interface TileSectionHeaderProps {
  /** Category of tiles being displayed */
  category: 'stays' | 'flights' | 'activities';
  /** Active specialist types (e.g., ['diving', 'hiking']) */
  specialists: string[];
  /** Total count of tiles in this category */
  count: number;
  /** Current sort option */
  sortBy?: string;
  /** Callback when sort option changes */
  onSortChange?: (sort: string) => void;
  /** Additional className */
  className?: string;
}

export function TileSectionHeader({
  category,
  specialists,
  count,
  sortBy = 'recommended',
  onSortChange,
  className,
}: TileSectionHeaderProps) {
  const { title, subtitle } = generateTileHeader(category, specialists);

  return (
    <div className={cn('flex items-start justify-between mb-2', className)}>
      <div>
        <h3 className="text-lg font-semibold text-zinc-100">{title}</h3>
        <p className="text-sm text-zinc-400 mt-0.5">
          {subtitle}
          {count > 0 && (
            <span className="text-zinc-500 ml-1">({count})</span>
          )}
        </p>
      </div>

      {/* Sort dropdown placeholder */}
      {onSortChange && (
        <div className="relative">
          <select
            value={sortBy}
            onChange={(e) => onSortChange(e.target.value)}
            className={cn(
              'appearance-none text-xs bg-transparent text-zinc-400 pr-6 py-1',
              'border-none outline-none cursor-pointer',
              'hover:text-zinc-300 transition-colors'
            )}
          >
            <option value="recommended">Recommended</option>
            <option value="price_low">Price: Low to High</option>
            <option value="price_high">Price: High to Low</option>
            <option value="rating">Highest Rated</option>
          </select>
          <ChevronDown className="absolute right-0 top-1/2 -translate-y-1/2 w-4 h-4 text-zinc-500 pointer-events-none" />
        </div>
      )}
    </div>
  );
}

export default TileSectionHeader;
