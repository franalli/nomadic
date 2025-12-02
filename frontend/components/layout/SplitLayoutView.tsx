'use client';

import { motion } from 'framer-motion';
import { Compass, Menu, User } from 'lucide-react';
import React, { memo } from 'react';

import { GeneratingLoader } from '@/components/layout/GeneratingLoader';
import { HeroSection } from '@/components/layout/HeroSection';
import { Footer } from '@/components/nomadic/footer';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';

interface SidebarHeaderProps {
  className?: string;
}

/**
 * Compact header for the sidebar with logo and nav buttons
 */
const SidebarHeader = memo(function SidebarHeader({ className = '' }: SidebarHeaderProps) {
  return (
    <header className={`mb-4 flex items-center justify-between text-white ${className}`}>
      <div className="flex items-center gap-2">
        <Compass className="h-5 w-5" />
        <span className="font-display text-lg font-bold tracking-tight">
          Nomadic
        </span>
      </div>
      <div className="flex items-center gap-2">
        <Button
          variant="ghost"
          size="icon"
          type="button"
          className="h-8 w-8 text-white hover:bg-white/10"
        >
          <User className="h-4 w-4" />
        </Button>
        <Button
          variant="ghost"
          size="icon"
          type="button"
          className="h-8 w-8 text-white hover:bg-white/10"
        >
          <Menu className="h-4 w-4" />
        </Button>
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
 */
export const SplitLayoutView = memo(function SplitLayoutView({
  sidebarContent,
  mainContent,
  typedTagline,
  isGenerating,
  hasBranchesReady,
}: SplitLayoutViewProps) {
  return (
    <div className="flex min-h-screen">
      {/* Left sidebar - Chat Panel (25% width, sticky) */}
      <motion.div
        initial={{ x: '-100%', opacity: 0 }}
        animate={{ x: 0, opacity: 1 }}
        transition={{ duration: 0.5, ease: 'easeOut' }}
        className="no-scrollbar fixed left-0 top-0 z-40 h-screen w-1/4 min-w-[320px] overflow-y-auto border-r border-white/10 bg-gradient-to-b from-black/90 via-black/80 to-black/90 shadow-2xl"
      >
        <div className="flex h-full flex-col p-4">
          <SidebarHeader />
          {/* Chat Panel */}
          <div className="flex-1 overflow-hidden">
            <Card className="bg-card/95 flex h-full flex-col border-white/20 shadow-xl backdrop-blur">
              <CardContent className="flex h-full min-h-0 flex-col p-3">
                {sidebarContent}
              </CardContent>
            </Card>
          </div>
        </div>
      </motion.div>

      {/* Right content - Loader or Branches (75% width, with left margin for fixed sidebar) */}
      <motion.div
        initial={{ x: '100%', opacity: 0 }}
        animate={{ x: 0, opacity: 1 }}
        transition={{ duration: 0.5, ease: 'easeOut', delay: 0.1 }}
        className="ml-[25%] min-w-0 flex-1"
        style={{ marginLeft: 'max(25%, 320px)' }}
      >
        <div className="min-h-screen">
          {/* Hero section (condensed) */}
          <HeroSection typedTagline={typedTagline} variant="compact" />

          {/* Show loader when generating, branches when ready */}
          <section className="bg-background px-6 pb-14 pt-6">
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
      </motion.div>
    </div>
  );
});
