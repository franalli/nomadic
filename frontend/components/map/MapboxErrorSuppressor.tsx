'use client';

import { useEffect } from 'react';

/**
 * MapboxErrorSuppressor
 *
 * A component that suppresses known Mapbox timing errors at the earliest possible point.
 * This must be rendered near the root of the app to catch errors before they reach
 * Next.js's error overlay.
 *
 * Known issue: Mapbox-gl throws "this.errorCb is not a function" when the map is
 * destroyed while async operations (SKU token validation, tile fetching) are in flight.
 * This is a known Mapbox timing issue, not a real error.
 *
 * @see https://github.com/mapbox/mapbox-gl-js/issues
 */

const SUPPRESSED_PATTERNS = [
  'errorCb is not a function',
  'this.errorCb is not a function',
  'Map container is already removed',
  'sku_token',
];

function shouldSuppressError(message: string, stack?: string): boolean {
  const combined = `${message} ${stack || ''}`;
  return SUPPRESSED_PATTERNS.some((pattern) => combined.includes(pattern));
}

export function MapboxErrorSuppressor({ children }: { children: React.ReactNode }) {
  useEffect(() => {
    // This runs very early in the React lifecycle
    const originalConsoleError = console.error;

    // Suppress console.error for Mapbox timing errors
    console.error = function (...args: unknown[]) {
      const message = args.map((arg) => String(arg)).join(' ');
      if (shouldSuppressError(message)) {
        return; // Suppress
      }
      originalConsoleError.apply(console, args);
    };

    // Also patch console.warn for completeness
    const originalConsoleWarn = console.warn;
    console.warn = function (...args: unknown[]) {
      const message = args.map((arg) => String(arg)).join(' ');
      if (shouldSuppressError(message)) {
        return; // Suppress
      }
      originalConsoleWarn.apply(console, args);
    };

    // Store original onerror
    const originalOnError = window.onerror;

    // Override window.onerror at this level too
    window.onerror = function (
      message: string | Event,
      source?: string,
      lineno?: number,
      colno?: number,
      error?: Error
    ): boolean {
      const msgStr = typeof message === 'string' ? message : '';
      const stack = error?.stack || '';
      const srcStr = source || '';

      if (
        shouldSuppressError(msgStr, stack) ||
        srcStr.includes('mapbox-gl') ||
        srcStr.includes('sku_token')
      ) {
        return true; // Suppress
      }

      if (originalOnError) {
        return originalOnError.call(window, message, source, lineno, colno, error);
      }
      return false;
    };

    // Cleanup on unmount
    return () => {
      console.error = originalConsoleError;
      console.warn = originalConsoleWarn;
      window.onerror = originalOnError;
    };
  }, []);

  return <>{children}</>;
}

export default MapboxErrorSuppressor;
