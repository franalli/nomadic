import './globals.css';

import type { ReactNode } from 'react';

export const metadata = {
  title: 'Nomadic – Interactive Travel Planner',
  description: 'Explore trips visually and book seamlessly with Nomadic',
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-slate-50 text-slate-800">{children}</body>
    </html>
  );
}
