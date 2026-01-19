'use client';

import { Compass } from 'lucide-react';
import React, { memo } from 'react';

const HERO_HEADLINE = 'Set trip constraints once.';
const HERO_TAGLINE = 'Everything updates together.';

interface HeroBackgroundProps {
  className?: string;
}

/**
 * Product-first hero background - base gradient only
 * Contours moved to full-hero wrapper for full coverage
 */
const HeroBackground = memo(function HeroBackground({
  className = '',
}: HeroBackgroundProps) {
  return (
    <div className={`absolute inset-0 ${className}`}>
      {/* Base gradient - softened dark teal/green tones */}
      <div
        className="absolute inset-0"
        style={{
          background: `
            radial-gradient(1200px 600px at 50% 0%, rgba(255,255,255,0.04), transparent 55%),
            linear-gradient(180deg, #080d15 0%, #051210 55%, #040f0a 100%)
          `,
        }}
      />
    </div>
  );
});

interface HeroTitleProps {
  variant: 'compact' | 'full';
}

/**
 * Hero title - static text, no typing animation
 * Two-line headline with orange accent on second line
 */
const HeroTitle = memo(function HeroTitle({ variant }: HeroTitleProps) {
  if (variant === 'compact') {
    return (
      <div className="relative z-10 px-4 py-6 sm:px-6 sm:py-8">
        <div className="text-white">
          <h1
            className="font-display text-xl font-bold leading-tight sm:text-2xl md:text-3xl"
            aria-label={`${HERO_HEADLINE} ${HERO_TAGLINE}`}
          >
            <span className="inline-flex items-center gap-2">
              <Compass className="h-5 w-5 sm:h-6 sm:w-6" />
              <span>Nomadic</span>
            </span>
            <span className="mx-3">{HERO_HEADLINE}</span>
            <span className="text-accent ml-2 tracking-tight">{HERO_TAGLINE}</span>
          </h1>
        </div>
      </div>
    );
  }

  return (
    <div className="hero-fade-in py-4 text-white sm:py-6">
      <h1
        className="font-display text-center font-bold leading-tight"
        aria-label={`${HERO_HEADLINE} ${HERO_TAGLINE}`}
      >
        {/* Logo and brand */}
        <div className="mb-3 flex items-center justify-center gap-2 sm:mb-4 sm:gap-3">
          <Compass className="h-6 w-6 sm:h-8 sm:w-8 lg:h-10 lg:w-10" />
          <span className="text-2xl tracking-tight sm:text-3xl lg:text-4xl">Nomadic</span>
        </div>
        {/* Stacked tagline - two lines with hierarchy */}
        <div className="text-xl sm:text-2xl md:text-3xl lg:text-4xl">
          <div className="font-medium text-white/90">{HERO_HEADLINE}</div>
          <div className="text-accent mt-1 font-normal tracking-tight">
            {HERO_TAGLINE}
          </div>
        </div>
      </h1>
    </div>
  );
});

export interface HeroSectionProps {
  variant: 'compact' | 'full';
  children?: React.ReactNode;
  chatPanelContainerRef?: React.RefObject<HTMLDivElement | null>;
}

/**
 * Hero section component that handles both compact (split layout) and full (centered) variants
 */
export const HeroSection = memo(function HeroSection({
  variant,
  children,
  chatPanelContainerRef,
}: HeroSectionProps) {
  if (variant === 'compact') {
    return (
      <div className="relative h-28 overflow-hidden">
        <HeroBackground />
        <HeroTitle variant="compact" />
      </div>
    );
  }

  return (
    <div className="relative min-h-screen">
      {/* Layer 1: Hero background gradient (spec values) */}
      <div className="fixed inset-0 z-0">
        <div
          className="absolute inset-0"
          style={{
            background: `
              radial-gradient(1200px 600px at 50% 0%, rgba(255,255,255,0.06), rgba(255,255,255,0) 55%),
              linear-gradient(180deg, #0b1220 0%, #06150f 55%, #06120d 100%)
            `,
          }}
        />
      </div>

      {/* Layer 2: Contours */}
      <div
        className="pointer-events-none fixed z-[1]"
        style={{
          top: '-15%',
          left: '-15%',
          right: '-15%',
          bottom: '-15%',
          backgroundImage: 'url("/assets/contours.svg")',
          backgroundRepeat: 'repeat',
          backgroundSize: '900px 900px',
          transform: 'rotate(-5deg)',
          opacity: 0.11,
          filter: 'blur(0.14px)',
        }}
      />

      {/* Hero title - positioned independently */}
      <div className="pointer-events-none relative z-10">
        <div className="mx-auto max-w-6xl px-4 pt-8 sm:pt-10">
          <HeroTitle variant="full" />
        </div>
      </div>

      {/* Chat panel container - sits within the dark hero area */}
      <div
        ref={chatPanelContainerRef}
        className="relative z-20 flex min-h-screen flex-col items-center justify-start px-0 pb-4 pt-24 sm:px-4 sm:pt-28"
      >
        {children}
      </div>
    </div>
  );
});

export { HERO_TAGLINE };
