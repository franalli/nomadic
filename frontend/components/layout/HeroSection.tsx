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
    <div className="py-4 text-white sm:py-6">
      <h1
        className="flex items-baseline font-display text-3xl font-bold leading-tight sm:text-4xl lg:text-5xl"
        aria-label={`Roam freely. ${HERO_TAGLINE}`}
      >
        <span className="flex w-1/2 items-baseline justify-end gap-2 whitespace-nowrap pr-2 sm:gap-3 sm:pr-4">
          <span className="flex items-center gap-2">
            <Compass className="h-6 w-6 sm:h-8 sm:w-8 lg:h-10 lg:w-10" />
            <span className="tracking-tight">Nomadic</span>
          </span>
          <span className="text-white/40">|</span>
          <span>Roam freely.</span>
        </span>
        <span className="w-1/2 pl-2 sm:pl-4">
          <span className="text-accent whitespace-nowrap">
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
      <div className="relative h-28 overflow-hidden">
        <HeroBackground />
        <HeroTitle typedTagline={typedTagline} variant="compact" />
      </div>
    );
  }

  return (
    <div className="relative min-h-screen overflow-hidden">
      <div className="absolute inset-x-0 top-0 h-[400px] sm:h-[500px]">
        <HeroBackground />
      </div>
      <div className="absolute inset-0 top-[400px] sm:top-[500px] bg-background" />
      <div className="relative z-10 flex min-h-screen flex-col">
        <div
          ref={chatPanelContainerRef}
          className="mx-auto flex max-w-6xl flex-1 flex-col items-center justify-start gap-4 px-0 sm:px-4 pb-4 pt-8 sm:pt-10"
        >
          <HeroTitle typedTagline={typedTagline} variant="full" />
          {children}
        </div>
      </div>
    </div>
  );
});

export { HERO_TAGLINE };
