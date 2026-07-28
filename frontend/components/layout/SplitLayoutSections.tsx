import Link from 'next/link';
import type { ReactNode } from 'react';

import { MobileSwipeLayout } from '@/components/layout/MobileSwipeLayout';
import { DS } from '@/lib/design-system';
import { cn } from '@/lib/utils';

const FOOTER_LINKS = [
  { href: '/privacy', label: 'Privacy' },
  { href: '/terms', label: 'Terms' },
  { href: '/cookies', label: 'Cookies' },
  { href: '/contact', label: 'Contact' },
] as const;

interface DesktopSplitLayoutProps {
  isLanding: boolean;
  plannerContent: ReactNode;
  planViewContent: ReactNode;
}

interface MobileSplitLayoutProps {
  plannerContent: ReactNode;
  planViewContent: ReactNode;
  planTabEnabled: boolean;
  mobileInput?: ReactNode;
  mobileStatusBar?: ReactNode;
}

function LayoutFooterLinks({
  bordered = false,
  className,
}: {
  bordered?: boolean;
  className?: string;
}) {
  return (
    <footer
      className={cn(
        'shrink-0 flex items-center justify-center gap-2 px-4 text-[var(--theme-link-muted)]',
        DS.textSize.mini,
        bordered ? 'border-t border-[var(--theme-hairline)] py-2' : 'py-3',
        className
      )}
    >
      {FOOTER_LINKS.map((link, index) => (
        <span key={link.href} className="contents">
          {index > 0 ? (
            <span aria-hidden="true" className="opacity-30">
              ·
            </span>
          ) : null}
          <Link href={link.href} className="transition-colors hover:text-[var(--theme-link-muted-hover)]">
            {link.label}
          </Link>
        </span>
      ))}
    </footer>
  );
}

export function DesktopSplitLayout({
  isLanding,
  plannerContent,
  planViewContent,
}: DesktopSplitLayoutProps) {
  return (
    <>
      <div
        className={cn(
          'absolute inset-0 pointer-events-none z-0 bg-white transition-opacity duration-700 ease-out dark:bg-zinc-950',
          isLanding ? 'opacity-100' : 'opacity-0'
        )}
      >
        <div className="absolute inset-0 animate-topo-drift topo-contour-mask-350 opacity-[0.15] dark:opacity-[0.10]">
          <div className="absolute inset-0 bg-black dark:bg-white" />
        </div>
      </div>

      <aside
        className={cn(
          'relative z-10 flex h-[calc(100vh-56px)] flex-col transition-all duration-500 ease-[cubic-bezier(0.25,0.1,0.25,1)]',
          isLanding
            ? 'mx-auto w-[640px]'
            : [
                // Responsive width: holds 480px on laptops (≤~1500px), scales with
                // the viewport on large displays (e.g. 27"), capped so it never
                // crowds out the plan/map canvas. Trades against the map's flex-1.
                'mx-0 w-[clamp(480px,32vw,760px)] shrink-0 border-r',
                `border-zinc-200 bg-white ${DS.shadow.panelEdge}`,
                `dark:border-white/5 dark:bg-black/40 dark:backdrop-blur-xl dark:${DS.shadow.panelEdgeDark}`,
              ]
        )}
        aria-label="Trip planner"
      >
        {isLanding ? (
          <>
            <div className="flex flex-1 flex-col overflow-y-auto px-4 no-scrollbar">{plannerContent}</div>
            <LayoutFooterLinks />
          </>
        ) : (
          <>
            {/*
             * Split view: this wrapper must NOT scroll. It constrains height so
             * the pressure reaches ChatMessageList's own `min-h-0 flex-1
             * overflow-y-auto` scroller — keeping the status header, suggestion
             * chips and input pinned while only the message log scrolls.
             */}
            <div className="flex min-h-0 flex-1 flex-col overflow-hidden p-4">{plannerContent}</div>
            <LayoutFooterLinks bordered />
          </>
        )}
      </aside>

      <main
        className={cn(
          'rightCanvas flex h-[calc(100vh-56px)] flex-col transition-all delay-100 duration-500 ease-[cubic-bezier(0.16,1,0.3,1)]',
          isLanding
            ? 'w-0 min-w-0 overflow-hidden opacity-0 pointer-events-none'
            : 'flex-1 min-w-0 opacity-100'
        )}
        aria-label="Your trip plan"
        data-testid="plan-view"
      >
        <div id="plan-panel" className="flex-1 overflow-y-auto px-6 pb-6 pt-0 no-scrollbar">
          {planViewContent}
        </div>
      </main>
    </>
  );
}

export function MobileSplitLayout({
  plannerContent,
  planViewContent,
  planTabEnabled,
  mobileInput,
  mobileStatusBar,
}: MobileSplitLayoutProps) {
  return (
    <main
      className={cn(
        'flex min-h-0 flex-1 flex-col overflow-hidden lg:hidden',
        'pt-[calc(var(--mobile-header-height,48px)+env(safe-area-inset-top))]'
      )}
    >
      {mobileStatusBar}
      <MobileSwipeLayout
        chatContent={plannerContent}
        planContent={planViewContent}
        planTabEnabled={planTabEnabled}
      />
      {mobileInput}
    </main>
  );
}
