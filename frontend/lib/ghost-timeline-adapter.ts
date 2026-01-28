/**
 * Ghost Timeline Adapter
 *
 * Transforms specialist content into "skeleton blocks" for the ghost timeline.
 * Used in S0_BOOTSTRAP state to show a preview of the trip before full generation.
 *
 * "Assume & Refine" philosophy: Show specialist activities immediately,
 * fill gaps with pulsing skeleton placeholders.
 */

import type { DayBlock, DayCard, StrategySection } from '@/types/plan-envelope';

/**
 * Topic colors for specialist badges in ghost timeline.
 */
export const TOPIC_COLORS: Record<string, string> = {
  hiking: 'bg-emerald-500/20 text-emerald-500',
  diving: 'bg-cyan-500/20 text-cyan-500',
  skiing: 'bg-blue-500/20 text-blue-500',
  boating: 'bg-indigo-500/20 text-indigo-500',
  cycling: 'bg-lime-500/20 text-lime-500',
  local_expert: 'bg-amber-500/20 text-amber-500',
};

/**
 * Generate ghost day cards from specialist strategy sections.
 *
 * 1. Extract content_added from each specialist section (real blocks with coordinates)
 * 2. Map to proper DayCard/DayBlock format
 * 3. Fill empty days with skeleton blocks (is_skeleton: true)
 * 4. Return mixed list ready for TimelineThread
 *
 * @param strategySections - Strategy sections from documentStore (speculative content)
 * @param duration - Trip duration in days (defaults to 5 if not set)
 * @returns DayCard[] ready for TimelineThread
 */
export function generateGhostDayCards(
  strategySections: StrategySection[] | undefined,
  duration: number = 5
): DayCard[] {
  // Track which days have real content
  const dayContentMap = new Map<number, DayBlock[]>();

  // Extract activities from specialist sections
  if (strategySections) {
    strategySections.forEach((section) => {
      // Skip general agent - it doesn't have specific activities
      if (section.specialist_type === 'general') return;
      // Skip infeasible specialists
      if (section.feasibility_status === 'infeasible') return;

      section.content_added?.forEach((content) => {
        // Assign to specified day, or distribute across middle days
        let dayNum = content.day;
        if (!dayNum || dayNum < 1 || dayNum > duration) {
          // Default: place specialist activities on day 2 (after arrival)
          dayNum = Math.min(2, duration);
        }

        const block: DayBlock = {
          id: `ghost-${section.specialist_type}-${content.title}`,
          period: 'morning', // Default to morning for specialist activities
          activity_type: content.type || section.specialist_type || 'activity',
          summary: content.title,
          coordinates: undefined, // Specialist content may have coordinates
          is_skeleton: false,
          specialist_type: section.specialist_type,
        };

        // Add to day's blocks
        const existing = dayContentMap.get(dayNum) || [];
        existing.push(block);
        dayContentMap.set(dayNum, existing);
      });
    });
  }

  // Build day cards for all days in duration
  const dayCards: DayCard[] = [];

  for (let day = 1; day <= duration; day++) {
    const realBlocks = dayContentMap.get(day) || [];

    // Determine label based on day position and content
    let label: string;
    if (day === 1) {
      label = 'Arrival day';
    } else if (day === duration) {
      label = 'Departure day';
    } else if (realBlocks.length > 0) {
      // Use first activity type for label
      const firstActivity = realBlocks[0];
      label = firstActivity.activity_type
        ? `${capitalize(firstActivity.activity_type)} day`
        : `Day ${day}`;
    } else {
      label = `Day ${day}`;
    }

    // If day has no content, add a skeleton block
    const blocks: DayBlock[] =
      realBlocks.length > 0
        ? realBlocks
        : [
            {
              id: `skeleton-day-${day}`,
              period: 'morning',
              activity_type: '',
              summary: '',
              is_skeleton: true,
            },
          ];

    dayCards.push({
      day_number: day,
      label,
      blocks,
    });
  }

  return dayCards;
}

/**
 * Check if we have meaningful specialist content for ghost timeline.
 * Returns true if there's at least one content_added from a specialist.
 */
export function hasSpecialistContent(
  strategySections: StrategySection[] | undefined
): boolean {
  if (!strategySections) return false;

  return strategySections.some(
    (section) =>
      section.specialist_type &&
      section.specialist_type !== 'general' &&
      section.feasibility_status !== 'infeasible' &&
      section.content_added &&
      section.content_added.length > 0
  );
}

/**
 * Capitalize first letter of a string.
 */
function capitalize(str: string): string {
  if (!str) return str;
  return str.charAt(0).toUpperCase() + str.slice(1);
}
