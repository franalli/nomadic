'use client';

import { Trash2 } from 'lucide-react';
import { memo, useEffect, useRef, useState } from 'react';

const HOLD_DURATION_MS = 1000;
const CIRCLE_RADIUS = 10;
const CIRCLE_CIRCUMFERENCE = 2 * Math.PI * CIRCLE_RADIUS;

interface HoldToDeleteButtonProps {
  onDelete: () => void;
  disabled?: boolean;
  className?: string;
}

/**
 * A delete button that requires press-and-hold to activate.
 * Shows a circular progress indicator while holding.
 * Releases early to cancel.
 */
export const HoldToDeleteButton = memo(function HoldToDeleteButton({
  onDelete,
  disabled = false,
  className = '',
}: HoldToDeleteButtonProps) {
  const [isHolding, setIsHolding] = useState(false);
  const [progress, setProgress] = useState(0);
  const startTimeRef = useRef<number>(0);
  const rafRef = useRef<number>(0);

  // Animation loop
  useEffect(() => {
    if (!isHolding) return;

    const animate = () => {
      const elapsed = performance.now() - startTimeRef.current;
      const newProgress = Math.min(elapsed / HOLD_DURATION_MS, 1);
      setProgress(newProgress);

      if (newProgress >= 1) {
        // Hold complete - trigger delete
        setIsHolding(false);
        setProgress(0);

        // Haptic feedback on mobile
        if (navigator.vibrate) {
          navigator.vibrate(50);
        }

        onDelete();
      } else {
        rafRef.current = requestAnimationFrame(animate);
      }
    };

    rafRef.current = requestAnimationFrame(animate);

    return () => {
      if (rafRef.current) {
        cancelAnimationFrame(rafRef.current);
      }
    };
  }, [isHolding, onDelete]);

  const handlePointerDown = (e: React.PointerEvent) => {
    if (disabled) return;
    e.preventDefault();
    e.currentTarget.setPointerCapture(e.pointerId);
    startTimeRef.current = performance.now();
    setIsHolding(true);
    setProgress(0);
  };

  const handlePointerUp = (e: React.PointerEvent) => {
    e.currentTarget.releasePointerCapture(e.pointerId);
    setIsHolding(false);
    setProgress(0);
  };

  const handlePointerCancel = () => {
    setIsHolding(false);
    setProgress(0);
  };

  // Calculate stroke-dashoffset for circular progress
  const strokeDashoffset = CIRCLE_CIRCUMFERENCE * (1 - progress);

  return (
    <button
      type="button"
      disabled={disabled}
      onPointerDown={handlePointerDown}
      onPointerUp={handlePointerUp}
      onPointerCancel={handlePointerCancel}
      onPointerLeave={handlePointerCancel}
      onContextMenu={(e) => e.preventDefault()}
      className={`relative flex items-center justify-center w-6 h-6 rounded-full
        bg-black/50 hover:bg-black/70 touch-none select-none
        ${disabled ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer'}
        ${className}`}
      style={{
        transform: isHolding ? 'scale(1.2)' : 'scale(1)',
        transition: 'transform 100ms ease-out, background-color 100ms ease-out'
      }}
      title="Hold to delete"
      aria-label="Hold to delete this message"
    >
      {/* Circular progress SVG */}
      <svg
        className="absolute inset-0 w-full h-full pointer-events-none"
        viewBox="0 0 24 24"
        fill="none"
        style={{ transform: 'rotate(-90deg)' }}
      >
        {/* Background circle */}
        <circle
          cx="12"
          cy="12"
          r={CIRCLE_RADIUS}
          stroke="rgba(34, 197, 94, 0.3)"
          strokeWidth="2.5"
          fill="none"
          opacity={isHolding ? 1 : 0}
        />
        {/* Progress circle - green */}
        <circle
          cx="12"
          cy="12"
          r={CIRCLE_RADIUS}
          stroke="#22c55e"
          strokeWidth="2.5"
          fill="none"
          strokeLinecap="round"
          strokeDasharray={CIRCLE_CIRCUMFERENCE}
          strokeDashoffset={strokeDashoffset}
          opacity={isHolding ? 1 : 0}
          style={{
            filter: progress >= 1 ? 'drop-shadow(0 0 6px #22c55e)' : 'none'
          }}
        />
      </svg>

      {/* Trash icon */}
      <Trash2
        className="h-3 w-3 relative z-10 pointer-events-none"
        style={{
          color: isHolding ? '#22c55e' : 'rgba(255, 255, 255, 0.9)',
          transition: 'color 100ms ease-out'
        }}
      />
    </button>
  );
});
