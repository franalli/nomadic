import './globals.css';

import type { ReactNode } from 'react';

import { ConsentManager } from '@/components/nomadic/consent-manager';

export const metadata = {
  title: 'Nomadic – Interactive Travel Planner',
  description: 'Explore trips visually and book seamlessly with Nomadic',
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
        <main id="main-content" role="main">
          {children}
        </main>
        <ConsentManager />
      </body>
    </html>
  );
}
