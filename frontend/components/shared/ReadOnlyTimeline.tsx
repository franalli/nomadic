'use client';

import { CalendarDays, Clock3, Star } from 'lucide-react';

import { DS } from '@/lib/design-system';
import { cn } from '@/lib/utils';
import type { DayBlock, DayCard } from '@/types/plan-envelope';

interface ReadOnlyTimelineProps {
  dayCards: DayCard[];
}

function formatDateLabel(date?: string): string | null {
  if (!date) return null;
  const parsed = new Date(`${date}T00:00:00`);
  if (Number.isNaN(parsed.getTime())) return null;
  return parsed.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
}

function renderBlockMeta(block: DayBlock): string[] {
  const items: string[] = [];
  if (block.duration) items.push(block.duration);
  if (typeof block.rating === 'number') items.push(`${block.rating.toFixed(1)}★`);
  if (typeof block.price_level === 'number' && block.price_level > 0) {
    items.push('$'.repeat(block.price_level));
  }
  return items;
}

export function ReadOnlyTimeline({ dayCards }: ReadOnlyTimelineProps) {
  if (!dayCards.length) {
    return (
      <div className="rounded-xl border border-zinc-200 dark:border-white/10 p-4 text-zinc-500 dark:text-zinc-400">
        No itinerary items in this shared trip.
      </div>
    );
  }

  return (
    <div className="space-y-5">
      {dayCards.map((day) => {
        const dateLabel = formatDateLabel(day.date);
        return (
          <section
            key={day.day_number}
            className="rounded-2xl border border-zinc-200 dark:border-white/10 bg-white/80 dark:bg-zinc-900/60"
          >
            <header className="flex items-center justify-between px-4 py-3 border-b border-zinc-100 dark:border-white/5">
              <div className="flex items-center gap-2 text-zinc-900 dark:text-white">
                <CalendarDays className="h-4 w-4 text-emerald-500" />
                <h3 className="font-semibold">Day {day.day_number}</h3>
                {dateLabel && (
                  <span className="text-sm text-zinc-500 dark:text-zinc-400">· {dateLabel}</span>
                )}
              </div>
              {day.label && (
                <span className={cn(DS.textSize.micro, 'uppercase tracking-widest text-zinc-500 dark:text-zinc-400')}>
                  {day.label}
                </span>
              )}
            </header>

            <div className="p-4 space-y-3">
              {day.blocks.map((block, idx) => {
                const meta = renderBlockMeta(block);
                return (
                  <article
                    key={block.id || `${day.day_number}-${idx}-${block.summary}`}
                    className="rounded-xl border border-zinc-200/80 dark:border-white/10 bg-zinc-50/70 dark:bg-white/[0.03] p-3"
                  >
                    <div className="flex gap-3">
                      {block.image_url ? (
                        <img
                          src={block.image_url}
                          alt={block.summary}
                          className="h-16 w-24 rounded-lg object-cover flex-shrink-0"
                        />
                      ) : null}
                      <div className="min-w-0 flex-1">
                        <div className="flex items-start justify-between gap-2">
                          <h4 className="font-medium text-zinc-900 dark:text-white">
                            {block.summary}
                          </h4>
                          <span className={cn(DS.textSize.micro, 'uppercase tracking-widest text-zinc-500 dark:text-zinc-400')}>
                            {block.period}
                          </span>
                        </div>
                        {block.activity_type && block.activity_type !== block.summary && (
                          <p className="text-sm text-zinc-600 dark:text-zinc-300">{block.activity_type}</p>
                        )}
                        {meta.length > 0 && (
                          <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-zinc-500 dark:text-zinc-400">
                            {meta.map((item) => (
                              <span key={`${block.id || idx}-${item}`} className="inline-flex items-center gap-1">
                                {item.includes('★') ? <Star className="h-3 w-3" /> : <Clock3 className="h-3 w-3" />}
                                {item}
                              </span>
                            ))}
                          </div>
                        )}
                      </div>
                    </div>
                  </article>
                );
              })}
            </div>
          </section>
        );
      })}
    </div>
  );
}
