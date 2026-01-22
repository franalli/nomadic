'use client';

import type { ReactNode } from 'react';

import { ToastProvider } from '@/components/ui/toast';

interface ProvidersProps {
  children: ReactNode;
}

/**
 * Client-side providers wrapper.
 * Wraps the app with all necessary client providers.
 */
export function Providers({ children }: ProvidersProps) {
  return (
    <ToastProvider>
      {children}
    </ToastProvider>
  );
}
