'use client';

/* eslint no-unused-vars: ["error", { "args": "none" }] */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import {
  FALLBACK_TIMEOUT_MS,
  getLoaderCopy,
  STEP_DURATION_MS,
} from '@/lib/loaderCopyConfig';
import type {
  ActionLoaderState,
  LoaderActionType,
  VerticalFetchType,
} from '@/types/loader';

interface UseActionLoaderOptions {
  /** Delay before showing loader (ms). Default: 400ms */
  showDelay?: number;
  /** ETA threshold - only show if estimated duration > this (ms). Default: 600ms */
  minEtaThreshold?: number;
}

interface UseActionLoaderReturn {
  /** Whether the loader should be visible */
  isVisible: boolean;
  /** Current loader state (null if not loading) */
  loaderState: ActionLoaderState | null;
  /** Current title to display */
  title: string;
  /** Current subtext to display */
  subtext: string;

  /**
   * Start loading with an action type.
   * @param actionType - The type of action being performed
   * @param estimatedDurationMs - Estimated duration from backend
   * @param options - Additional options (verticalType, hasTiles)
   */
  startLoading: (
    actionType: LoaderActionType,
    estimatedDurationMs: number,
    options?: {
      verticalType?: VerticalFetchType;
      hasTiles?: boolean;
    }
  ) => void;

  /** Call when tangible output is received (first token, skeleton, etc.) */
  onTangibleOutput: () => void;

  /** Force reset the loader state */
  reset: () => void;
}

/**
 * Hook for managing an action-aware delayed loader.
 *
 * Features:
 * - Shows loader after `showDelay` ms (default 400ms) to avoid flicker
 * - Skips showing if `estimatedDurationMs < minEtaThreshold` (default 600ms)
 * - Auto-progresses through subtext steps based on STEP_DURATION_MS
 * - Shows fallback subtext after FALLBACK_TIMEOUT_MS
 * - Action-specific titles and subtexts
 *
 * @example
 * const loader = useActionLoader({ showDelay: 400, minEtaThreshold: 600 });
 *
 * // When backend job starts
 * loader.startLoading('generate_plan', estimatedMs);
 *
 * // When first token arrives
 * loader.onTangibleOutput();
 *
 * // In JSX
 * {loader.isVisible && <NodeProgress title={loader.title} subtext={loader.subtext} ... />}
 */
export function useActionLoader(
  options: UseActionLoaderOptions = {}
): UseActionLoaderReturn {
  const { showDelay = 400, minEtaThreshold = 600 } = options;

  const [isVisible, setIsVisible] = useState(false);
  const [loaderState, setLoaderState] = useState<ActionLoaderState | null>(
    null
  );
  const [stepIndex, setStepIndex] = useState(0);
  const [useFallback, setUseFallback] = useState(false);

  const showTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const stepTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const fallbackTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const isPendingRef = useRef(false);

  // Get copy config based on current loader state
  const copyConfig = loaderState
    ? getLoaderCopy(loaderState.actionType, {
        verticalType: loaderState.verticalType,
        hasTiles: loaderState.hasTiles,
      })
    : null;

  // Compute current title and subtext
  const title = copyConfig?.title ?? '';
  const subtext = useFallback && copyConfig?.fallbackSubtext
    ? copyConfig.fallbackSubtext
    : (copyConfig?.subtexts[stepIndex] ?? copyConfig?.subtexts[0] ?? '');

  // Cleanup all timers
  const clearAllTimers = useCallback(() => {
    if (showTimerRef.current) {
      clearTimeout(showTimerRef.current);
      showTimerRef.current = null;
    }
    if (stepTimerRef.current) {
      clearInterval(stepTimerRef.current);
      stepTimerRef.current = null;
    }
    if (fallbackTimerRef.current) {
      clearTimeout(fallbackTimerRef.current);
      fallbackTimerRef.current = null;
    }
  }, []);

  // Step progression effect - advances subtext every STEP_DURATION_MS
  useEffect(() => {
    if (!isVisible || !loaderState || !copyConfig) return;

    // Only set up step timer if there are multiple subtexts
    if (copyConfig.subtexts.length <= 1) return;

    stepTimerRef.current = setInterval(() => {
      setStepIndex((prev) => {
        const nextStep = prev + 1;
        // Stay on last step if we've reached the end
        return nextStep < copyConfig.subtexts.length ? nextStep : prev;
      });
    }, STEP_DURATION_MS);

    return () => {
      if (stepTimerRef.current) {
        clearInterval(stepTimerRef.current);
        stepTimerRef.current = null;
      }
    };
  }, [isVisible, loaderState, copyConfig]);

  // Fallback timer effect - show fallback subtext after 30s
  useEffect(() => {
    if (!isVisible || !loaderState) return;

    fallbackTimerRef.current = setTimeout(() => {
      setUseFallback(true);
    }, FALLBACK_TIMEOUT_MS);

    return () => {
      if (fallbackTimerRef.current) {
        clearTimeout(fallbackTimerRef.current);
        fallbackTimerRef.current = null;
      }
    };
  }, [isVisible, loaderState]);

  const startLoading = useCallback(
    (
      actionType: LoaderActionType,
      estimatedDurationMs: number,
      loaderOptions?: {
        verticalType?: VerticalFetchType;
        hasTiles?: boolean;
      }
    ) => {
      // Clear any pending timers
      clearAllTimers();

      // Check ETA threshold - don't show loader for quick operations
      if (estimatedDurationMs < minEtaThreshold) {
        isPendingRef.current = false;
        return;
      }

      const newState: ActionLoaderState = {
        actionType,
        verticalType: loaderOptions?.verticalType,
        startTime: Date.now(),
        estimatedDurationMs,
        stepIndex: 0,
        hasTiles: loaderOptions?.hasTiles,
      };

      setLoaderState(newState);
      setStepIndex(0);
      setUseFallback(false);
      isPendingRef.current = true;

      // Delay before showing
      showTimerRef.current = setTimeout(() => {
        if (isPendingRef.current) {
          setIsVisible(true);
        }
      }, showDelay);
    },
    [showDelay, minEtaThreshold, clearAllTimers]
  );

  const onTangibleOutput = useCallback(() => {
    // Cancel pending timer and hide loader
    clearAllTimers();
    isPendingRef.current = false;
    setIsVisible(false);
  }, [clearAllTimers]);

  const reset = useCallback(() => {
    clearAllTimers();
    isPendingRef.current = false;
    setIsVisible(false);
    setLoaderState(null);
    setStepIndex(0);
    setUseFallback(false);
  }, [clearAllTimers]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      clearAllTimers();
    };
  }, [clearAllTimers]);

  return useMemo(() => ({
    isVisible,
    loaderState,
    title,
    subtext,
    startLoading,
    onTangibleOutput,
    reset,
  }), [isVisible, loaderState, title, subtext, startLoading, onTangibleOutput, reset]);
}
