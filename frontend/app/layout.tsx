import './globals.css';

import type { ReactNode } from 'react';

import { MapboxErrorSuppressor } from '@/components/map/MapboxErrorSuppressor';
import { ConsentManager } from '@/components/nomadic/consent-manager';
import { Providers } from '@/components/providers/Providers';

export const metadata = {
  title: 'Nomadic – Interactive Travel Planner',
  description: 'Constraint-based travel planning',
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-bg text-text">
        {/* Skip link for keyboard navigation */}
        <a
          href="#main-content"
          className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-[100] focus:rounded-lg focus:bg-primary focus:px-4 focus:py-2 focus:text-primary-foreground focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2"
        >
          Skip to main content
        </a>
        <Providers>
          {/* Suppress known Mapbox timing errors before they reach error overlay */}
          <MapboxErrorSuppressor>
            <main id="main-content" role="main">
              {children}
            </main>
          </MapboxErrorSuppressor>
        </Providers>
        <ConsentManager />
        {/* Toast portal target */}
        <div id="toast-portal" />
      </body>
    </html>
  );
}
