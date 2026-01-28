'use client';

import { Check, Compass, Loader2, MoreVertical, RotateCcw } from 'lucide-react';
import Link from 'next/link';
import { memo, useState } from 'react';

import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { useMobileMode } from '@/contexts/MobileModeContext';
import { cn } from '@/lib/utils';
import type { PlanState } from '@/types/plan-envelope';

// ─────────────────────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────────────────────

interface MobileModeHeaderProps {
  /** Current plan state for status display in Plan Mode */
  planState?: PlanState;
  /** Callback to reset/clear the session */
  onReset?: () => void;
  className?: string;
}

// ─────────────────────────────────────────────────────────────────────────────
// Status Configuration
// ─────────────────────────────────────────────────────────────────────────────

const STATUS_CONFIG: Record<
  PlanState,
  { text: string; icon?: React.ReactNode; className: string }
> = {
  INCOMPLETE: {
    text: '',
    className: 'text-muted-foreground',
  },
  RESOLVING: {
    text: 'Planning...',
    icon: <Loader2 className="h-3 w-3 animate-spin" />,
    className: 'text-primary/80',
  },
  STABLE: {
    text: 'Up to date',
    icon: <Check className="h-3 w-3" />,
    className: 'text-green-600/80',
  },
  LOCKED: {
    text: 'Locked',
    className: 'text-foreground',
  },
};

// ─────────────────────────────────────────────────────────────────────────────
// Component
// ─────────────────────────────────────────────────────────────────────────────

/**
 * MobileModeHeader - Mobile-only header with consistent branding.
 *
 * DESIGN PRINCIPLE: Bottom tabs are the ONLY navigation method.
 * No "← Edit" back button - this creates a parallel workspace model
 * like Instagram, Airbnb, or Spotify where you tap tabs to switch views.
 *
 * Both Modes:
 * - Left: Nomadic logo + wordmark (brand anchor)
 * - Right: Menu (⋮) with Reset, Help & Legal
 *
 * Plan Mode additionally shows status indicator.
 */
function MobileModeHeaderInner({
  planState = 'INCOMPLETE',
  onReset,
  className,
}: MobileModeHeaderProps) {
  const { isDesktop } = useMobileMode();
  const [menuOpen, setMenuOpen] = useState(false);

  // Don't render on desktop - split view shows both panels
  if (isDesktop) {
    return null;
  }

  const status = STATUS_CONFIG[planState];

  return (
    <header
      className={cn(
        'fixed top-0 left-0 right-0 z-[1100]',
        'h-[calc(var(--mobile-header-height,48px)+env(safe-area-inset-top))]',
        'px-3 pt-[env(safe-area-inset-top)]',
        'flex items-center justify-between',
        'backdrop-blur',
        'border-b',
        'bg-background/80 border-border/50',
        'dark:bg-background/60 dark:border-border/30',
        'lg:hidden', // Only show on mobile
        className
      )}
    >
      {/* Left side: Nomadic branding (consistent across all modes) */}
      <div className="flex items-center gap-2">
        <Compass className="h-5 w-5 text-primary shrink-0" />
        <span className="font-semibold text-sm text-foreground">Nomadic</span>
      </div>

      {/* Right side: Status (if active) + Menu */}
      <div className="flex items-center gap-2">
        {/* Status indicator - only show when there's active status */}
        {status.text && (
          <div
            className={cn(
              'flex items-center gap-1.5 text-xs font-medium',
              status.className
            )}
          >
            {status.icon}
            <span>{status.text}</span>
          </div>
        )}

        {/* Menu button with Popover - Reset moved inside for safety */}
        <Popover open={menuOpen} onOpenChange={setMenuOpen}>
          <PopoverTrigger asChild>
            <button
              type="button"
              className="p-2 text-muted-foreground hover:text-foreground transition-colors -mr-2"
              aria-label="Menu"
            >
              <MoreVertical className="h-5 w-5" />
            </button>
          </PopoverTrigger>
          <PopoverContent align="end" className="w-[200px] p-2">
            <nav className="flex flex-col">
              {/* Reset - moved inside menu to prevent accidental taps */}
              {onReset && (
                <>
                  <button
                    type="button"
                    onClick={() => {
                      setMenuOpen(false);
                      onReset();
                    }}
                    className="flex items-center gap-2 px-2 py-2 text-sm rounded-md hover:bg-muted transition-colors text-left text-red-600 dark:text-red-400"
                  >
                    <RotateCcw className="h-4 w-4" />
                    <span>Reset Trip</span>
                  </button>
                  <div className="h-px bg-border my-1" />
                </>
              )}

              <span className="px-2 py-1.5 text-xs font-medium text-muted-foreground">Help & Legal</span>
              <Link
                href="/privacy"
                className="px-2 py-2 text-sm rounded-md hover:bg-muted transition-colors"
                onClick={() => setMenuOpen(false)}
              >
                Privacy Policy
              </Link>
              <Link
                href="/terms"
                className="px-2 py-2 text-sm rounded-md hover:bg-muted transition-colors"
                onClick={() => setMenuOpen(false)}
              >
                Terms of Service
              </Link>
              <Link
                href="/cookies"
                className="px-2 py-2 text-sm rounded-md hover:bg-muted transition-colors"
                onClick={() => setMenuOpen(false)}
              >
                Cookie Policy
              </Link>
              <Link
                href="/contact"
                className="px-2 py-2 text-sm rounded-md hover:bg-muted transition-colors"
                onClick={() => setMenuOpen(false)}
              >
                Contact Us
              </Link>
            </nav>
          </PopoverContent>
        </Popover>
      </div>
    </header>
  );
}

export const MobileModeHeader = memo(MobileModeHeaderInner);
