'use client';

import { type ReactNode, useEffect } from 'react';

import { ToastProvider } from '@/components/ui/toast';
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

  return (
    <ToastProvider>
      {children}
    </ToastProvider>
  );
}
