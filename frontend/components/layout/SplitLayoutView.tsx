'use client';

import { motion } from 'framer-motion';
import { Compass, MessageCircle, X } from 'lucide-react';
import React, { memo, useState } from 'react';

import { GeneratingLoader } from '@/components/layout/GeneratingLoader';
import { HeroSection } from '@/components/layout/HeroSection';
import { Footer } from '@/components/nomadic/footer';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';

interface SidebarHeaderProps {
  className?: string;
}

/**
 * Compact header for the sidebar with logo
 */
const SidebarHeader = memo(function SidebarHeader({ className = '' }: SidebarHeaderProps) {
  return (
    <header className={`mb-4 flex items-center text-white ${className}`}>
      <div className="flex items-center gap-2">
        <Compass className="h-5 w-5" />
        <span className="font-display text-lg font-bold tracking-tight">
          Nomadic
        </span>
      </div>
    </header>
  );
});

export interface SplitLayoutViewProps {
  /** Content for the sidebar (typically chat panel) */
  sidebarContent: React.ReactNode;
  /** Content for the main area (typically branch panel) */
  mainContent: React.ReactNode;
  /** Current typed tagline for hero animation */
  typedTagline: string;
  /** Whether we're in generating state (show loader instead of branches) */
  isGenerating: boolean;
  /** Whether branches are ready to display */
  hasBranchesReady: boolean;
}

/**
 * Split layout view with fixed sidebar on left and scrollable main content on right.
 * Used when generating or when branches are ready.
 * On mobile, sidebar becomes a drawer that can be toggled.
 */
export const SplitLayoutView = memo(function SplitLayoutView({
  sidebarContent,
  mainContent,
  typedTagline,
  isGenerating,
  hasBranchesReady,
}: SplitLayoutViewProps) {
  const [mobileDrawerOpen, setMobileDrawerOpen] = useState(false);

  return (
    <div className="flex min-h-screen">
      {/* Mobile chat toggle button - fixed at bottom right on mobile */}
      <Button
        variant="primary"
        size="icon"
        type="button"
        onClick={() => setMobileDrawerOpen(true)}
        className="fixed bottom-6 right-6 z-50 h-14 w-14 rounded-full shadow-lg lg:hidden"
        aria-label="Open chat"
      >
        <MessageCircle className="h-6 w-6" />
      </Button>

      {/* Mobile drawer overlay */}
      {mobileDrawerOpen && (
        <div
          className="fixed inset-0 z-50 bg-black/50 lg:hidden"
          onClick={() => setMobileDrawerOpen(false)}
          aria-hidden="true"
        />
      )}

      {/* Left sidebar - Chat Panel */}
      {/* Desktop: fixed 25% width, Mobile: slide-in drawer */}
      <aside
        className={`no-scrollbar fixed left-0 top-0 h-screen overflow-y-auto border-r border-white/10 bg-gradient-to-b from-black/90 via-black/80 to-black/90 shadow-2xl transition-transform duration-300 ease-out
          w-[85vw] max-w-[400px] lg:w-1/4 lg:min-w-[320px]
          z-50 lg:z-40
          ${mobileDrawerOpen ? 'translate-x-0' : '-translate-x-full lg:translate-x-0'}`}
        aria-label="Trip planning chat"
      >
        <div className="flex h-full flex-col p-4">
          {/* Header with mobile close button */}
          <div className="flex items-center justify-between mb-4">
            <SidebarHeader className="!mb-0" />
            <Button
              variant="ghost"
              size="icon"
              type="button"
              onClick={() => setMobileDrawerOpen(false)}
              className="h-8 w-8 text-white hover:bg-white/10 lg:hidden"
              aria-label="Close chat"
            >
              <X className="h-5 w-5" />
            </Button>
          </div>
          {/* Chat Panel */}
          <div className="flex-1 overflow-hidden">
            <Card className="bg-card/95 flex h-full flex-col border-white/20 shadow-xl backdrop-blur">
              <CardContent className="flex h-full min-h-0 flex-col p-3">
                {sidebarContent}
              </CardContent>
            </Card>
          </div>
        </div>
      </aside>

      {/* Right content - Loader or Branches */}
      {/* Desktop: offset by sidebar width, Mobile: full width */}
      <section
        className="min-w-0 flex-1 w-full lg:ml-[max(25%,320px)]"
        aria-label="Trip options and results"
      >
        <div className="min-h-screen">
          {/* Hero section (condensed) */}
          <HeroSection typedTagline={typedTagline} variant="compact" />

          {/* Show loader when generating, branches when ready */}
          <section className="bg-background px-4 pb-14 pt-6 lg:px-6">
            {isGenerating && !hasBranchesReady ? (
              <motion.div
                key="generating-loader"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                transition={{ duration: 0.5 }}
              >
                <GeneratingLoader />
              </motion.div>
            ) : (
              <motion.div
                key="branch-panel"
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.5, ease: 'easeOut' }}
              >
                {mainContent}
              </motion.div>
            )}
          </section>

          <Footer />
        </div>
      </section>
    </div>
  );
});
