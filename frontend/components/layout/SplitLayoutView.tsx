'use client';

import { motion } from 'framer-motion';
import { ChevronDown, ChevronUp, Compass } from 'lucide-react';
import React, { memo, useState } from 'react';

import { GeneratingLoader } from '@/components/layout/GeneratingLoader';
import { HeroSection } from '@/components/layout/HeroSection';
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
  /** Whether we're in generating state (show loader instead of branches) */
  isGenerating: boolean;
  /** Whether branches are ready to display */
  hasBranchesReady: boolean;
  /** Trip details form content to display below the hero */
  tripDetailsContent?: React.ReactNode;
}

/**
 * Split layout view with:
 * - Desktop (lg+): Fixed sidebar on left, scrollable main content on right
 * - Mobile (<lg): Stack layout with content on top, expandable chat bar at bottom
 */
export const SplitLayoutView = memo(function SplitLayoutView({
  sidebarContent,
  mainContent,
  isGenerating,
  hasBranchesReady,
  tripDetailsContent,
}: SplitLayoutViewProps) {
  // Mobile chat bar expanded state
  const [mobileChatExpanded, setMobileChatExpanded] = useState(false);

  return (
    <div className="flex flex-col lg:flex-row min-h-screen">
      {/* Desktop sidebar - Chat Panel */}
      {/* Only visible on lg+ screens */}
      <aside
        className="no-scrollbar fixed left-0 top-0 h-screen overflow-y-auto border-r border-white/10 bg-gradient-to-b from-black/90 via-black/80 to-black/90 shadow-2xl
          w-1/4 min-w-[320px]
          z-40
          hidden lg:block"
        aria-label="Trip planning chat"
      >
        <div className="flex h-full flex-col p-4 pb-2">
          <SidebarHeader />
          {/* Chat Panel */}
          <div className="flex-1 overflow-hidden">
            <Card className="bg-card/75 flex h-full flex-col border-white/20 shadow-xl backdrop-blur">
              <CardContent className="flex h-full min-h-0 flex-col p-4 pb-3">
                {sidebarContent}
              </CardContent>
            </Card>
          </div>
        </div>
      </aside>

      {/* Main content area */}
      {/* Desktop: offset by sidebar width, Mobile: full width with bottom padding for chat bar */}
      <section
        className="min-w-0 flex-1 w-full lg:ml-[max(25%,320px)] pb-[140px] lg:pb-0"
        aria-label="Your trip plan"
      >
        <div className="min-h-screen">
          {/* Hero section (condensed) */}
          <HeroSection variant="compact" />

          {/* Trip details form - editable trip inputs below hero */}
          {tripDetailsContent && (
            <div className="bg-muted/30 border-b border-border/30 px-4 py-4 lg:px-6 w-full">
              <div className="w-full">
                {tripDetailsContent}
              </div>
            </div>
          )}

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
                <GeneratingLoader compact className="lg:hidden" />
                <GeneratingLoader className="hidden lg:flex" />
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
        </div>
      </section>

      {/* Mobile chat bar - fixed at bottom */}
      {/* Only visible on screens < lg */}
      <aside
        className={`fixed bottom-0 left-0 right-0 z-50 lg:hidden
          bg-gradient-to-t from-black/95 via-black/90 to-black/85 backdrop-blur-lg
          border-t border-white/10 shadow-2xl
          transition-all duration-300 ease-out
          ${mobileChatExpanded ? 'h-[60vh]' : 'h-[140px]'}`}
        aria-label="Trip planning chat"
      >
        {/* Expand/collapse handle */}
        <button
          type="button"
          onClick={() => setMobileChatExpanded(!mobileChatExpanded)}
          className="absolute -top-3 left-1/2 -translate-x-1/2 z-10
            bg-primary hover:bg-primary/90 text-primary-foreground
            rounded-full px-4 py-1 shadow-lg
            flex items-center gap-1 text-xs font-medium
            transition-colors"
          aria-label={mobileChatExpanded ? 'Collapse chat' : 'Expand chat'}
        >
          {mobileChatExpanded ? (
            <>
              <ChevronDown className="h-4 w-4" />
              <span>Collapse</span>
            </>
          ) : (
            <>
              <ChevronUp className="h-4 w-4" />
              <span>Chat</span>
            </>
          )}
        </button>

        {/* Chat content */}
        <div className="h-full overflow-hidden p-3 pt-4">
          <Card className="bg-card/75 flex h-full flex-col border-white/20 shadow-xl backdrop-blur">
            <CardContent className="flex h-full min-h-0 flex-col p-3">
              {sidebarContent}
            </CardContent>
          </Card>
        </div>
      </aside>
    </div>
  );
});
