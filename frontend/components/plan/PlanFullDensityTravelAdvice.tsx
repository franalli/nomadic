'use client';

import type { IntelCategory } from '@/lib/travelIntel';

interface PlanFullDensityTravelAdviceProps {
  hasDestinationIntel: boolean;
  intelExpanded: boolean;
  intelCategories: IntelCategory[];
  isAnyRegenerating: boolean;
  isRegenUpdating: boolean;
}

export function PlanFullDensityTravelAdvice({
  hasDestinationIntel,
  intelExpanded,
  intelCategories,
  isAnyRegenerating,
  isRegenUpdating,
}: PlanFullDensityTravelAdviceProps) {
  if (!hasDestinationIntel) return null;

  return (
    <div className="px-4 pb-2 pt-1">
      {intelExpanded && (
        <div
          id="destination-intel-panel"
          aria-labelledby="destination-intel-trigger"
          className="mt-2 rounded-xl border border-zinc-200 bg-white dark:border-white/10 dark:bg-zinc-900/40"
        >
          <div className="max-h-[280px] space-y-4 overflow-y-auto px-4 py-4">
            {intelCategories.map((category) => (
              <div key={category.key} className="space-y-1">
                <p className="flex items-center gap-2 text-sm font-medium text-zinc-800 dark:text-zinc-200">
                  <span>{category.icon}</span>
                  <span>{category.label}</span>
                </p>
                <ul className="list-disc list-outside marker:text-emerald-400 space-y-1 pl-10">
                  {category.items.map((item) => (
                    <li
                      key={`${category.key}-${item}`}
                      className="text-sm leading-relaxed text-zinc-600 dark:text-zinc-400"
                    >
                      {item}
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        </div>
      )}

      {isAnyRegenerating && !isRegenUpdating && (
        <div className="mt-2 flex items-center gap-2 rounded-lg border border-zinc-200 bg-zinc-50 px-3 py-2 dark:border-white/10 dark:bg-zinc-900/60">
          <div className="h-4 w-4 animate-spin rounded-full border-2 border-emerald-500 border-t-transparent" />
          <p className="text-xs text-zinc-600 dark:text-zinc-400">Updating plan...</p>
        </div>
      )}
    </div>
  );
}
