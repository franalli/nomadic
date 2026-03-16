'use client';

import { isBootstrap } from '@/components/plan/planStateHelpers';
import type { PlanViewState } from '@/types/plan-envelope';

interface ChatPanelLayoutStateArgs {
  isDesktop: boolean;
  planViewState: PlanViewState | undefined | null;
  isFraming?: boolean;
  isGenerating?: boolean;
  isSetupHeaderCollapsed?: boolean;
}

export function shouldUseLandingChatLayout({
  isDesktop,
  planViewState,
  isFraming = false,
  isGenerating = false,
}: ChatPanelLayoutStateArgs): boolean {
  if (!isDesktop) return false;
  if (isFraming || isGenerating) return false;
  return isBootstrap(planViewState);
}

export function shouldShowBootstrapHero({
  isDesktop,
  planViewState,
  isFraming = false,
  isGenerating = false,
  isSetupHeaderCollapsed = false,
}: ChatPanelLayoutStateArgs): boolean {
  if (isSetupHeaderCollapsed) return false;
  return shouldUseLandingChatLayout({
    isDesktop,
    planViewState,
    isFraming,
    isGenerating,
  });
}
