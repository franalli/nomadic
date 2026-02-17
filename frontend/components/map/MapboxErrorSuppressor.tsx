'use client';

import { useEffect } from 'react';

import { isMapboxTimingError } from './mapbox-error-handler';

/**
 * MapboxErrorSuppressor
 *
 * Patches console.error / console.warn to suppress known Mapbox timing errors.
 * InteractiveMap's module-level handler covers window.onerror, error events, and
 * unhandled rejections. This component adds the console patching layer which runs
 * inside a React lifecycle (useEffect) for safe cleanup on unmount.
 *
 * Pattern list is owned by InteractiveMap (SUPPRESSED_ERROR_PATTERNS) and exposed
 * via the shared `isMapboxTimingError` function.
 *
 * @see https://github.com/mapbox/mapbox-gl-js/issues
 */

export function MapboxErrorSuppressor({ children }: { children: React.ReactNode }) {
  useEffect(() => {
    // This runs very early in the React lifecycle
    const originalConsoleError = console.error;

    // Suppress console.error for Mapbox timing errors
    console.error = function (...args: unknown[]) {
      const message = args.map((arg) => String(arg)).join(' ');
      if (isMapboxTimingError(message)) {
        return; // Suppress
      }
      originalConsoleError.apply(console, args);
    };

    // Also patch console.warn for completeness
    const originalConsoleWarn = console.warn;
    console.warn = function (...args: unknown[]) {
      const message = args.map((arg) => String(arg)).join(' ');
      if (isMapboxTimingError(message)) {
        return; // Suppress
      }
      originalConsoleWarn.apply(console, args);
    };

    // Note: window.onerror is handled by InteractiveMap's installGlobalMapboxErrorHandler()
    // which runs at module load time. No need to duplicate here.

    // Cleanup on unmount
    return () => {
      console.error = originalConsoleError;
      console.warn = originalConsoleWarn;
    };
  }, []);

  return <>{children}</>;
}

export default MapboxErrorSuppressor;
