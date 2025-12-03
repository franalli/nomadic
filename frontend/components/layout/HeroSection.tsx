'use client';

import { Compass } from 'lucide-react';
import React, { memo } from 'react';

const HERO_IMAGE =
  'https://images.unsplash.com/photo-1500530855697-b586d89ba3ee?auto=format&fit=crop&w=2000&q=80';
const HERO_VIDEO = '/hiking_video.mp4';
const HERO_TAGLINE = 'We Plan the Rest.';

interface HeroBackgroundProps {
  className?: string;
}

/**
 * Shared hero background with split image/video and gradient overlay
 */
const HeroBackground = memo(function HeroBackground({ className = '' }: HeroBackgroundProps) {
  return (
    <div className={`absolute inset-0 ${className}`}>
      <div className="flex h-full w-full">
        <div className="h-full w-1/2">
          <img
            src={HERO_IMAGE}
            alt="Nomadic hero"
            className="h-full w-full object-cover"
          />
        </div>
        <div className="h-full w-1/2">
          <video
            className="h-full w-full object-cover"
            src={HERO_VIDEO}
            poster={HERO_IMAGE}
            autoPlay
            loop
            muted
            playsInline
            aria-hidden="true"
          />
        </div>
      </div>
      <div className="to-background absolute inset-0 bg-gradient-to-b from-black/65 via-black/35" />
    </div>
  );
});

interface HeroHeaderProps {
  variant: 'compact' | 'full';
}

/**
 * Header with logo
 */
const HeroHeader = memo(function HeroHeader({ variant }: HeroHeaderProps) {
  if (variant === 'compact') {
    return null; // Compact variant doesn't have header in hero section
  }

  return (
    <header className="mx-auto flex max-w-6xl items-center justify-between px-4 py-6 text-white">
      <div className="flex items-center gap-2">
        <Compass className="h-6 w-6" />
        <span className="font-display text-xl font-bold tracking-tight">
          Nomadic
        </span>
      </div>
    </header>
  );
});

interface HeroTitleProps {
  typedTagline: string;
  variant: 'compact' | 'full';
}

/**
 * Hero title with typing animation
 */
const HeroTitle = memo(function HeroTitle({ typedTagline, variant }: HeroTitleProps) {
  if (variant === 'compact') {
    return (
      <div className="relative z-10 px-6 py-8">
        <div className="space-y-2 text-white">
          <h1
            className="font-display text-3xl font-bold leading-tight"
            aria-label={`Roam freely. ${HERO_TAGLINE}`}
          >
            Roam freely. <span className="text-accent">{typedTagline}</span>
          </h1>
        </div>
      </div>
    );
  }

  return (
    <div className="-mt-8 space-y-6 text-center text-white">
      <h1
        className="font-display text-4xl font-bold leading-tight sm:text-5xl lg:text-6xl"
        aria-label={`Roam freely. ${HERO_TAGLINE}`}
      >
        Roam freely.{' '}
        <span className="text-accent relative inline-block">
          <span className="invisible">{HERO_TAGLINE}</span>
          <span
            className="absolute left-0 top-0 whitespace-nowrap"
            aria-live="polite"
          >
            {typedTagline}
          </span>
        </span>
      </h1>
    </div>
  );
});

export interface HeroSectionProps {
  typedTagline: string;
  variant: 'compact' | 'full';
  children?: React.ReactNode;
  chatPanelContainerRef?: React.RefObject<HTMLDivElement | null>;
}

/**
 * Hero section component that handles both compact (split layout) and full (centered) variants
 */
export const HeroSection = memo(function HeroSection({
  typedTagline,
  variant,
  children,
  chatPanelContainerRef,
}: HeroSectionProps) {
  if (variant === 'compact') {
    return (
      <div className="relative overflow-hidden">
        <HeroBackground />
        <HeroTitle typedTagline={typedTagline} variant="compact" />
      </div>
    );
  }

  return (
    <div className="relative overflow-hidden">
      <HeroBackground />
      <div className="relative z-10">
        <HeroHeader variant="full" />
        <div
          ref={chatPanelContainerRef}
          className="mx-auto flex max-w-6xl flex-col items-center gap-6 px-0 sm:px-4 pb-12 pt-6"
        >
          <HeroTitle typedTagline={typedTagline} variant="full" />
          {children}
        </div>
      </div>
    </div>
  );
});

export { HERO_TAGLINE };
