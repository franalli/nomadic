import { Compass, MoreVertical, SlidersHorizontal } from 'lucide-react';
import type { ReactNode } from 'react';

import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { DS } from '@/lib/design-system';
import { cn } from '@/lib/utils';

export interface MobileModeHeaderStatus {
  text: string;
  icon?: ReactNode;
  className: string;
}

interface MobileModeHeaderShellProps {
  mounted: boolean;
  menuOpen: boolean;
  onMenuOpenChange: (open: boolean) => void;
  menuContent: ReactNode;
  className?: string;
}

export function formatMobileHeaderDateRange(startDate?: string | null, endDate?: string | null) {
  if (!startDate) return '';
  const start = new Date(startDate);
  const startFormatted = start.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
  if (!endDate) {
    return startFormatted;
  }
  const end = new Date(endDate);
  const endFormatted = end.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
  return `${startFormatted} - ${endFormatted}`;
}

export function MobileModeHeaderShell({
  mounted,
  menuOpen,
  onMenuOpenChange,
  menuContent,
  className,
}: MobileModeHeaderShellProps) {
  return (
    <header
      className={cn(
        'fixed left-0 right-0 top-0 z-[1100]',
        'h-[calc(var(--mobile-header-height,48px)+env(safe-area-inset-top))]',
        'flex items-center justify-between',
        'border-b bg-white/80 dark:bg-zinc-950/60 px-3 pt-[env(safe-area-inset-top)] backdrop-blur',
        'border-zinc-200/50 dark:border-white/5',
        'lg:hidden',
        className
      )}
    >
      <div className="flex items-center gap-2">
        <Compass className="h-5 w-5 shrink-0 text-emerald-600 dark:text-emerald-500" />
        <span className="text-sm font-semibold text-zinc-900 dark:text-white">Nomadic</span>
      </div>

      <div className="flex items-center gap-2">
        {mounted ? (
          <Popover open={menuOpen} onOpenChange={onMenuOpenChange}>
            <PopoverTrigger asChild>
              <button
                type="button"
                className="flex h-11 w-11 items-center justify-center text-zinc-500 dark:text-zinc-400 transition-colors hover:text-zinc-900 dark:hover:text-white"
                aria-label="Menu"
              >
                <MoreVertical className="h-5 w-5" />
              </button>
            </PopoverTrigger>
            <PopoverContent align="end" className={cn('w-[200px] p-2', DS.materials.glass)}>
              {menuContent}
            </PopoverContent>
          </Popover>
        ) : (
          <button
            type="button"
            className="flex h-11 w-11 items-center justify-center text-zinc-500 dark:text-zinc-400 transition-colors hover:text-zinc-900 dark:hover:text-white"
            aria-label="Menu"
          >
            <MoreVertical className="h-5 w-5" />
          </button>
        )}
      </div>
    </header>
  );
}

export function MobileModeCondensedBar({
  summary,
  onScrollToTop,
}: {
  summary: string;
  onScrollToTop: () => void;
}) {
  return (
    <div
      className={cn(
        'fixed left-0 right-0 z-[1098]',
        'top-[calc(var(--mobile-header-height,48px)+env(safe-area-inset-top))]',
        'flex h-14 items-center justify-between gap-3 border-b px-4 backdrop-blur-xl',
        'bg-white/90 border-zinc-200 dark:border-white/5 dark:bg-zinc-950/80',
        'lg:hidden'
      )}
    >
      <span className="min-w-0 truncate text-sm font-semibold text-zinc-900 dark:text-white">
        {summary}
      </span>
      <button
        type="button"
        onClick={onScrollToTop}
        className={cn(
          'flex h-11 w-11 items-center justify-center rounded-full transition-colors',
          'text-zinc-500 hover:bg-zinc-100 hover:text-zinc-900',
          'dark:text-zinc-400 dark:hover:bg-white/10 dark:hover:text-white'
        )}
        aria-label="Scroll plan to top"
      >
        <SlidersHorizontal className="h-5 w-5" />
      </button>
    </div>
  );
}

export function MobileModeStatusPill({ status }: { status: MobileModeHeaderStatus }) {
  if (!status.text) {
    return null;
  }

  return (
    <div
      className={cn(
        'fixed left-1/2 z-[1099] flex -translate-x-1/2 items-center gap-1.5 rounded-full',
        'top-[calc(var(--mobile-header-height,48px)+env(safe-area-inset-top)+8px)]',
        'border border-zinc-200/40 dark:border-white/10 bg-white/80 dark:bg-zinc-950/80 px-3 py-1 text-xs font-medium shadow-card backdrop-blur-md',
        'lg:hidden',
        status.className
      )}
    >
      {status.icon}
      <span>{status.text}</span>
    </div>
  );
}
