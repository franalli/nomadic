/**
 * Typewriter
 *
 * Character-by-character text reveal animation with blinking cursor.
 * Used in the startup sequence for the "INITIALIZING..." text.
 *
 * Features:
 * - Respects prefers-reduced-motion (shows full text instantly)
 * - Bifurcated aesthetic: Black caret (Light) / Emerald caret (Dark)
 * - Configurable typing speed
 */

'use client';

import { memo, useEffect, useState } from 'react';

import { cn } from '@/lib/utils';

interface TypewriterProps {
  text: string;
  speed?: number;
  onComplete?: () => void;
  className?: string;
}

export const Typewriter = memo(function Typewriter({
  text,
  speed = 40,
  onComplete,
  className,
}: TypewriterProps) {
  const [displayText, setDisplayText] = useState('');
  const [showCursor, setShowCursor] = useState(true);
  const [prefersReducedMotion, setPrefersReducedMotion] = useState(false);

  // Check reduced motion preference on mount
  useEffect(() => {
    if (typeof window !== 'undefined') {
      setPrefersReducedMotion(
        window.matchMedia('(prefers-reduced-motion: reduce)').matches
      );
    }
  }, []);

  // Typing effect
  useEffect(() => {
    if (prefersReducedMotion) {
      setDisplayText(text);
      onComplete?.();
      return;
    }

    let index = 0;
    const interval = setInterval(() => {
      if (index < text.length) {
        setDisplayText(text.slice(0, index + 1));
        index++;
      } else {
        clearInterval(interval);
        onComplete?.();
      }
    }, speed);

    return () => clearInterval(interval);
  }, [text, speed, onComplete, prefersReducedMotion]);

  // Cursor blink effect
  useEffect(() => {
    const blink = setInterval(() => setShowCursor((c) => !c), 530);
    return () => clearInterval(blink);
  }, []);

  return (
    <span className={className}>
      {displayText}
      <span
        className={cn(
          'inline-block w-[2px] h-[1em] ml-0.5 align-middle rounded-sm',
          // Light Mode: Solid Black Ink (per Section 17)
          'bg-zinc-950',
          // Dark Mode: Emerald with glow (per Section 17)
          'dark:bg-emerald-500 dark:shadow-[0_0_6px_rgba(16,185,129,0.6)]',
          showCursor ? 'opacity-100' : 'opacity-0',
          'transition-opacity duration-100'
        )}
      />
    </span>
  );
});

export default Typewriter;
