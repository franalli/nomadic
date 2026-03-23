'use client';

import { type ReactNode, useEffect } from 'react';

import { ToastProvider } from '@/components/ui/toast';
import { destroyTabGuard, initTabGuard } from '@/lib/tabGuard';
import { hydratePreferences } from '@/state/documentStore';

interface ProvidersProps {
  children: ReactNode;
}

/**
 * Client-side providers wrapper.
 * Wraps the app with all necessary client providers.
 */
export function Providers({ children }: ProvidersProps) {
  // Hydrate heart preferences from sessionStorage on mount
  useEffect(() => {
    hydratePreferences();
  }, []);

  // Advisory multi-tab guard — provides UX feedback before hitting server SSE limits
  useEffect(() => {
    initTabGuard();
    return () => destroyTabGuard();
  }, []);

  return (
    <ToastProvider>
      {children}
    </ToastProvider>
  );
}
