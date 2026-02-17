'use client';

import Link from 'next/link';

import { DS } from '@/lib/design-system';
import { cn } from '@/lib/utils';

export default function SummaryError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  console.error('[SummaryError]', error);

  return (
    <div className="flex min-h-screen items-center justify-center bg-white dark:bg-zinc-950 text-zinc-900 dark:text-white">
      <div className="text-center space-y-4 max-w-md px-6">
        <h2 className="text-xl font-semibold">Something went wrong</h2>
        <p className={cn(DS.text.muted)}>{error.message || 'An unexpected error occurred'}</p>
        <div className="flex items-center justify-center gap-3">
          <button
            onClick={reset}
            className={cn(DS.actions.primary, 'rounded-full text-sm')}
          >
            Try again
          </button>
          <Link
            href="/"
            className={cn(DS.actions.secondary, 'rounded-full text-sm')}
          >
            Return to planning
          </Link>
        </div>
      </div>
    </div>
  );
}
