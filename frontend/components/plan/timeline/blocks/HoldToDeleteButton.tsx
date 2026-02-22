'use client';

import { Trash2 } from 'lucide-react';
import { useCallback, useEffect, useRef, useState } from 'react';

import { cn } from '@/lib/utils';

interface HoldToDeleteButtonProps {
  onDelete: () => void;
  holdDuration?: number; // ms, default 1000
  className?: string;
  disabled?: boolean;
}

export function HoldToDeleteButton({
  onDelete,
  holdDuration = 1000,
  className,
  disabled,
}: HoldToDeleteButtonProps) {
  const [progress, setProgress] = useState(0);
  const [holding, setHolding] = useState(false);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const startTimeRef = useRef<number>(0);

  const clearHold = useCallback(() => {
    if (timerRef.current) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }
    setHolding(false);
    setProgress(0);
  }, []);

  const startHold = useCallback(() => {
    if (disabled) return;
    setHolding(true);
    startTimeRef.current = Date.now();
    timerRef.current = setInterval(() => {
      const elapsed = Date.now() - startTimeRef.current;
      const pct = Math.min(elapsed / holdDuration, 1);
      setProgress(pct);
      if (pct >= 1) {
        clearHold();
        onDelete();
      }
    }, 16); // ~60fps
  }, [disabled, holdDuration, onDelete, clearHold]);

  // Cleanup interval on unmount to prevent memory leaks
  useEffect(() => {
    return () => {
      if (timerRef.current) {
        clearInterval(timerRef.current);
        timerRef.current = null;
      }
    };
  }, []);

  // SVG circle parameters for radial progress
  const r = 12;
  const circ = 2 * Math.PI * r;

  return (
    <button
      type="button"
      aria-label="Hold to delete"
      disabled={disabled}
      className={cn(
        'relative flex items-center justify-center w-8 h-8 rounded-full transition-colors',
        'hover:bg-red-50 dark:hover:bg-red-950/30',
        holding && 'bg-red-50 dark:bg-red-950/30',
        disabled && 'opacity-50 cursor-not-allowed pointer-events-none',
        className,
      )}
      onPointerDown={startHold}
      onPointerUp={clearHold}
      onPointerLeave={clearHold}
      onPointerCancel={clearHold}
    >
      {holding && (
        <svg
          className="absolute inset-0 w-full h-full -rotate-90"
          viewBox="0 0 32 32"
        >
          <circle
            cx="16"
            cy="16"
            r={r}
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeDasharray={circ}
            strokeDashoffset={circ * (1 - progress)}
            className="text-red-500"
          />
        </svg>
      )}
      <Trash2
        className={cn(
          'w-3.5 h-3.5 transition-colors',
          holding ? 'text-red-500' : 'text-zinc-400 dark:text-zinc-500',
        )}
      />
    </button>
  );
}
