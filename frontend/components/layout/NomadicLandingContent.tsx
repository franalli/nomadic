'use client';

import { FloatingBuildButton } from '@/components/layout/FloatingBuildButton';
import { useNomadicLandingController } from '@/components/layout/hooks/useNomadicLandingController';
import { LandingSheets } from '@/components/layout/LandingSheets';
import { SplitLayoutView } from '@/components/layout/SplitLayoutView';
import { ErrorBoundary } from '@/components/ui/ErrorBoundary';

export function NomadicLanding() {
  const { splitLayoutProps, landingSheetsProps, floatingBuildButtonProps } =
    useNomadicLandingController();

  return (
    <>
      <div className="appTopo text-zinc-900 dark:text-white">
        <SplitLayoutView {...splitLayoutProps} />
        <FloatingBuildButton {...floatingBuildButtonProps} />
      </div>

      <LandingSheets {...landingSheetsProps} />
    </>
  );
}

export default function NomadicLandingWithProvider() {
  return (
    <ErrorBoundary label="App">
      <NomadicLanding />
    </ErrorBoundary>
  );
}
