'use client';

import { motion } from 'framer-motion';
import { Briefcase, Map, MessageSquare } from 'lucide-react';
import { memo } from 'react';

import { type MobileTab,useMobileMode } from '@/contexts/MobileModeContext';
import { cn } from '@/lib/utils';

// ─────────────────────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────────────────────

interface TabConfig {
  id: MobileTab;
  label: string;
  icon: typeof MessageSquare;
}

interface MobileTabBarProps {
  className?: string;
  /** Whether the Book tab has content and should be enabled */
  bookTabEnabled?: boolean;
}

// ─────────────────────────────────────────────────────────────────────────────
// Tab Configuration
// ─────────────────────────────────────────────────────────────────────────────

const TABS: TabConfig[] = [
  { id: 'chat', label: 'Chat', icon: MessageSquare },
  { id: 'plan', label: 'Plan', icon: Map },
  { id: 'book', label: 'Book', icon: Briefcase },
];

// ─────────────────────────────────────────────────────────────────────────────
// Component
// ─────────────────────────────────────────────────────────────────────────────

/**
 * MobileTabBar - iOS-style 3-segment tab control for mobile navigation.
 *
 * Shows [ Chat | Plan | Book ] tabs with:
 * - Sliding background indicator
 * - Red dot badge on Plan tab for unread updates
 * - Fixed at bottom of screen
 */
function MobileTabBarInner({ className, bookTabEnabled = true }: MobileTabBarProps) {
  const { activeTab, setActiveTab, planTabHasUpdate, isDesktop } = useMobileMode();

  // Don't render on desktop
  if (isDesktop) {
    return null;
  }

  const activeIndex = TABS.findIndex((tab) => tab.id === activeTab);

  return (
    <nav
      className={cn(
        'fixed bottom-0 left-0 right-0 z-[1000]',
        'px-4 pt-2',
        'pb-[calc(8px+env(safe-area-inset-bottom))]', // pt-2 (8px) + safe area
        'bg-background/80 backdrop-blur-lg',
        'border-t border-border/50',
        'lg:hidden',
        className
      )}
      aria-label="Main navigation"
    >
      <div
        className={cn(
          'relative flex items-center',
          'bg-muted/50 rounded-xl p-1',
          'border border-border/30'
        )}
      >
        {/* Sliding Background Indicator */}
        <motion.div
          className={cn(
            'absolute top-1 bottom-1 rounded-lg',
            'bg-background shadow-sm',
            'border border-border/50'
          )}
          initial={false}
          animate={{
            left: `calc(${activeIndex * (100 / TABS.length)}% + 4px)`,
            width: `calc(${100 / TABS.length}% - 8px)`,
          }}
          transition={{
            type: 'spring',
            stiffness: 500,
            damping: 35,
          }}
        />

        {/* Tab Buttons */}
        {TABS.map((tab) => {
          const Icon = tab.icon;
          const isActive = activeTab === tab.id;
          const showBadge = tab.id === 'plan' && planTabHasUpdate && !isActive;
          const isBookDisabled = tab.id === 'book' && !bookTabEnabled;

          return (
            <button
              key={tab.id}
              type="button"
              onClick={() => !isBookDisabled && setActiveTab(tab.id)}
              disabled={isBookDisabled}
              className={cn(
                'relative flex-1 flex items-center justify-center gap-1.5',
                'py-2.5 rounded-lg',
                'text-sm font-medium',
                'transition-colors duration-150',
                isActive
                  ? 'text-foreground'
                  : 'text-muted-foreground hover:text-foreground/80',
                isBookDisabled && 'opacity-40 cursor-not-allowed'
              )}
              aria-selected={isActive}
              aria-disabled={isBookDisabled}
              role="tab"
            >
              <Icon className="h-4 w-4" />
              <span>{tab.label}</span>

              {/* Notification Badge */}
              {showBadge && (
                <motion.span
                  className={cn(
                    'absolute top-1.5 right-[calc(50%-24px)]',
                    'w-2 h-2 rounded-full',
                    'bg-red-500'
                  )}
                  initial={{ scale: 0 }}
                  animate={{ scale: 1 }}
                  exit={{ scale: 0 }}
                  transition={{ type: 'spring', stiffness: 500, damping: 25 }}
                />
              )}
            </button>
          );
        })}
      </div>
    </nav>
  );
}

export const MobileTabBar = memo(MobileTabBarInner);
