'use client';

import React from 'react';

import { MobileModeHeader } from '@/components/layout/MobileModeHeader';
import { useIsDesktop } from '@/hooks/useIsDesktop';
import { cn } from '@/lib/utils';
import type { PlanState } from '@/types/plan-envelope';

import { DesktopSplitLayout, MobileSplitLayout } from './SplitLayoutSections';

// ─────────────────────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────────────────────

interface SplitLayoutViewProps {
  /** Content for the left panel (Planner: chat + controls) */
  plannerContent: React.ReactNode;
  /** Content for the right panel (Plan View: StrategyStageRenderer) */
  planViewContent: React.ReactNode;
  /** Current plan state for status display */
  planState?: PlanState;
  /** Optional compact header content (branding) */
  headerContent?: React.ReactNode;
  /** Callback to reset/clear the session */
  onReset?: () => void;
  /** Whether a reset request is currently in-flight */
  isResetting?: boolean;
  /** Whether Plan tab is unlocked (plan has been generated) */
  planTabEnabled?: boolean;
  /** Mobile-only: chat input rendered below swipe container (visible on both pages) */
  mobileInput?: React.ReactNode;
  /** Mobile-only: trip status bar rendered above swipe container (shared across pages) */
  mobileStatusBar?: React.ReactNode;
  /** Data density from StrategyStageRenderer — controls landing vs plan-active layout */
  dataDensity?: 'empty' | 'ghost' | 'bridge' | 'full';
}

// ─────────────────────────────────────────────────────────────────────────────
// Component
// ─────────────────────────────────────────────────────────────────────────────

export function SplitLayoutView({
  plannerContent,
  planViewContent,
  planState = 'INCOMPLETE',
  headerContent,
  onReset,
  isResetting = false,
  planTabEnabled = false,
  mobileInput,
  mobileStatusBar,
  dataDensity = 'empty',
}: SplitLayoutViewProps) {
  const isDesktop = useIsDesktop();

  const isLanding = dataDensity === 'empty' || dataDensity === 'bridge';

  return (
    <div className="flex flex-col h-[100dvh] lg:h-screen overflow-hidden">
      {headerContent && (
        <header className="hidden lg:flex items-center h-14 px-6 border-b border-[var(--theme-hairline)] bg-[var(--theme-panel)]">
          {headerContent}
        </header>
      )}

      <MobileModeHeader
        planState={planState}
        onReset={onReset}
        isResetting={isResetting}
      />

      <div
        className={cn(
          'flex flex-col',
          'flex-1 overflow-hidden min-h-0',
          'lg:flex lg:flex-row lg:relative'
        )}
      >
        {isDesktop ? (
          <DesktopSplitLayout
            isLanding={isLanding}
            plannerContent={plannerContent}
            planViewContent={planViewContent}
          />
        ) : (
          <MobileSplitLayout
            plannerContent={plannerContent}
            planViewContent={planViewContent}
            planTabEnabled={planTabEnabled}
            mobileInput={mobileInput}
            mobileStatusBar={mobileStatusBar}
          />
        )}
      </div>
    </div>
  );
}
