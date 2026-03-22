'use client';

/* eslint no-unused-vars: ["error", { "args": "none" }] */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

interface UseDelayedLoaderOptions {
  /** Delay before showing loader (ms). Default: 400ms */
  showDelay?: number;
  /** ETA threshold - only show if estimated duration > this (ms). Default: 600ms */
  etaThreshold?: number;
}

interface DelayedLoaderState {
  /** Whether the loader should be visible */
  isVisible: boolean;
  /** Call when a loading operation starts. Pass estimated duration to check threshold. */
  startLoading: (estimatedDurationMs?: number) => void;
  /** Call when tangible output is received (first token, skeleton, stage change) */
  onTangibleOutput: () => void;
  /** Force reset the loader state */
  reset: () => void;
}

/**
 * Hook for managing a delayed loader that only shows for slow operations.
 *
 * - Shows loader after `showDelay` ms (default 400ms) to avoid flicker
 * - Skips showing if `estimatedDurationMs < etaThreshold` (default 600ms)
 * - Auto-hides on `onTangibleOutput()` or `reset()`
 *
 * @example
 * const loader = useDelayedLoader({ showDelay: 400, etaThreshold: 600 });
 *
 * // When backend job starts
 * loader.startLoading(estimatedMs);
 *
 * // When first token arrives or skeleton renders
 * loader.onTangibleOutput();
 *
 * // In JSX
 * {loader.isVisible && <NodeProgress ... />}
 */
export function useDelayedLoader(options: UseDelayedLoaderOptions = {}): DelayedLoaderState {
  const { showDelay = 400, etaThreshold = 600 } = options;

  const [isVisible, setIsVisible] = useState(false);
  const showTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const isPendingRef = useRef(false);

  // Cleanup timer on unmount
  useEffect(() => {
    return () => {
      if (showTimerRef.current) {
        clearTimeout(showTimerRef.current);
      }
    };
  }, []);

  const startLoading = useCallback((estimatedDurationMs?: number) => {
    // Clear any pending timer
    if (showTimerRef.current) {
      clearTimeout(showTimerRef.current);
      showTimerRef.current = null;
    }

    // Check ETA threshold - don't show loader for quick operations
    if (estimatedDurationMs !== undefined && estimatedDurationMs < etaThreshold) {
      isPendingRef.current = false;
      return;
    }

    // Mark as pending and start delay timer
    isPendingRef.current = true;

    showTimerRef.current = setTimeout(() => {
      // Only show if still pending (not cancelled by tangible output)
      if (isPendingRef.current) {
        setIsVisible(true);
      }
    }, showDelay);
  }, [etaThreshold, showDelay]);

  const onTangibleOutput = useCallback(() => {
    // Cancel pending timer
    if (showTimerRef.current) {
      clearTimeout(showTimerRef.current);
      showTimerRef.current = null;
    }
    isPendingRef.current = false;
    setIsVisible(false);
  }, []);

  const reset = useCallback(() => {
    if (showTimerRef.current) {
      clearTimeout(showTimerRef.current);
      showTimerRef.current = null;
    }
    isPendingRef.current = false;
    setIsVisible(false);
  }, []);

  return useMemo(() => ({
    isVisible,
    startLoading,
    onTangibleOutput,
    reset,
  }), [isVisible, startLoading, onTangibleOutput, reset]);
}
