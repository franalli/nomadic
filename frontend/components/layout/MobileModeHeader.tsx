'use client';

import { Check, Compass, Loader2, MoreVertical, RotateCcw } from 'lucide-react';
import Link from 'next/link';
import { memo, useEffect, useState } from 'react';

import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { useIsDesktop } from '@/hooks/useIsDesktop';
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
  /** Whether reset is currently in-flight (guards against spamming) */
  isResetting?: boolean;
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
    text: '',
    icon: <Check className="h-3 w-3" />,
    className: 'text-emerald-600/80 dark:text-emerald-400/80',
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
  isResetting = false,
  className,
}: MobileModeHeaderProps) {
  const isDesktop = useIsDesktop();
  const [menuOpen, setMenuOpen] = useState(false);
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);

  // Don't render on desktop - split view shows both panels
  if (isDesktop) {
    return null;
  }

  const status = STATUS_CONFIG[planState];

  return (
    <>
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

      {/* Right side: Menu only (status moved to floating pill below) */}
      <div className="flex items-center gap-2">
        {/* Menu button with Popover - deferred until mount to avoid Radix ID hydration mismatch */}
        {mounted ? (
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
                      disabled={isResetting}
                      onClick={() => {
                        if (isResetting) return;
                        setMenuOpen(false);
                        onReset();
                      }}
                      className="flex items-center gap-2 px-2 py-2.5 rounded-md hover:bg-zinc-100 dark:hover:bg-white/10 transition-colors text-left text-[10px] font-bold uppercase tracking-widest text-zinc-900 dark:text-white disabled:pointer-events-none disabled:opacity-60"
                    >
                      {isResetting ? (
                        <Loader2 className="h-3.5 w-3.5 animate-spin" />
                      ) : (
                        <RotateCcw className="h-3.5 w-3.5" />
                      )}
                      <span>{isResetting ? 'Resetting...' : 'Reset Trip'}</span>
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
        ) : (
          <button
            type="button"
            className="p-2 text-muted-foreground hover:text-foreground transition-colors -mr-2"
            aria-label="Menu"
          >
            <MoreVertical className="h-5 w-5" />
          </button>
        )}
      </div>
    </header>

    {/* Floating status pill — centered below header, glass morphism */}
    {status.text && (
      <div
        className={cn(
          'fixed z-[1099] left-1/2 -translate-x-1/2',
          'top-[calc(var(--mobile-header-height,48px)+env(safe-area-inset-top)+8px)]',
          'flex items-center gap-1.5',
          'px-3 py-1 rounded-full',
          'text-xs font-medium',
          'bg-background/80 backdrop-blur-md',
          'border border-border/40',
          'shadow-sm',
          'lg:hidden',
          status.className
        )}
      >
        {status.icon}
        <span>{status.text}</span>
      </div>
    )}
    </>
  );
}

export const MobileModeHeader = memo(MobileModeHeaderInner);
