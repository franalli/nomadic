/**
 * ReadyToPlanBanner
 *
 * Prominent banner shown after 3+ exploration questions to prompt user
 * to start planning their trip with dates.
 *
 * @see docs/ux_unified_architecture.md Section I.A
 */

'use client';

import { Calendar, Sparkles, X } from 'lucide-react';
import { useState } from 'react';

import { cn } from '@/lib/utils';

interface ReadyToPlanBannerProps {
  destination: string;
  questionsAsked: number;
  onStartPlanning: () => void;
  className?: string;
}

export function ReadyToPlanBanner({
  destination,
  questionsAsked,
  onStartPlanning,
  className,
}: ReadyToPlanBannerProps) {
  const [isDismissed, setIsDismissed] = useState(false);

  if (isDismissed) return null;

  return (
    <div
      className={cn(
        'relative overflow-hidden',
        'bg-gradient-to-r from-emerald-500 to-blue-500',
        'rounded-xl p-6 text-white shadow-lg',
        className
      )}
    >
      {/* Dismiss button */}
      <button
        onClick={() => setIsDismissed(true)}
        className="absolute top-3 right-3 p-1 rounded-full hover:bg-white/20 transition-colors"
        aria-label="Dismiss banner"
      >
        <X className="w-4 h-4" />
      </button>

      <div className="flex items-start justify-between gap-4">
        <div className="flex-1">
          <div className="flex items-center gap-2 mb-2">
            <Sparkles className="w-5 h-5" />
            <h3 className="text-lg font-semibold">Ready to plan your trip?</h3>
          </div>

          <p className="text-emerald-50 text-sm mb-4 max-w-md">
            Based on our {questionsAsked} conversation{questionsAsked === 1 ? '' : 's'} about{' '}
            {destination}, I can create a personalized itinerary. Just let me know your dates!
          </p>

          <button
            onClick={onStartPlanning}
            className={cn(
              'flex items-center gap-2',
              'bg-white text-emerald-600',
              'px-5 py-2.5 rounded-lg',
              'hover:bg-emerald-50 transition-colors',
              'font-medium shadow-sm'
            )}
          >
            <Calendar className="w-4 h-4" />
            Start planning
          </button>
        </div>
      </div>

      {/* Decorative background elements */}
      <div className="absolute -right-8 -bottom-8 w-32 h-32 bg-white/10 rounded-full" />
      <div className="absolute -right-4 -bottom-4 w-20 h-20 bg-white/10 rounded-full" />
    </div>
  );
}
