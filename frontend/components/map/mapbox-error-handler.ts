// =============================================================================
// Comprehensive Global Error Suppression for Mapbox
// =============================================================================

/**
 * Known Mapbox timing errors that are harmless and should be suppressed.
 * These occur when the map is destroyed during async operations.
 */
const SUPPRESSED_ERROR_PATTERNS = [
  'errorCb is not a function',
  'this.errorCb is not a function',
  'Map container is already removed',
  'Cannot read properties of undefined',
  'Cannot read properties of null',
  'sku_token',
  'mapbox-gl',
];

/**
 * Check if an error message matches known Mapbox timing issues.
 * Exported so MapboxErrorSuppressor can reuse the canonical pattern list.
 */
export function isMapboxTimingError(input: string | Error | unknown): boolean {
  let message = '';

  if (typeof input === 'string') {
    message = input;
  } else if (input instanceof Error) {
    message = input.message || input.toString();
  } else if (input && typeof input === 'object') {
    message = (input as { message?: string }).message || String(input);
  }

  return SUPPRESSED_ERROR_PATTERNS.some((pattern) => message.includes(pattern));
}

// Install comprehensive error suppression ONCE
let _globalHandlerInstalled = false;

function installGlobalMapboxErrorHandler(): void {
  if (_globalHandlerInstalled || typeof window === 'undefined') return;
  _globalHandlerInstalled = true;

  // Store original handlers
  const originalOnError = window.onerror;

  // Override window.onerror (catches errors before React/Next.js error boundary)
  window.onerror = function (
    message: string | Event,
    source?: string,
    lineno?: number,
    colno?: number,
    error?: Error
  ): boolean {
    const msgStr = typeof message === 'string' ? message : '';
    const isMapboxError = isMapboxTimingError(msgStr) || isMapboxTimingError(error);

    // Check if error is from mapbox-gl source files
    const isMapboxSource = source?.includes('mapbox-gl') || source?.includes('sku_token');

    if (isMapboxError || isMapboxSource) {
      // Suppress - return true to prevent default handling
      return true;
    }

    // Call original handler if exists
    if (originalOnError) {
      return originalOnError.call(window, message, source, lineno, colno, error);
    }
    return false;
  };

  // Capture phase listener (runs before bubble phase handlers)
  window.addEventListener(
    'error',
    (event) => {
      const errorEvent = event as globalThis.ErrorEvent;
      const message = errorEvent.message || errorEvent.error?.message || '';
      const filename = errorEvent.filename || '';

      const isMapboxError = isMapboxTimingError(message) || isMapboxTimingError(errorEvent.error);
      const isMapboxSource = filename.includes('mapbox-gl') || filename.includes('sku_token');

      if (isMapboxError || isMapboxSource) {
        event.preventDefault();
        event.stopImmediatePropagation();
        return true;
      }
    },
    true // Capture phase
  );

  // Bubble phase listener (backup)
  window.addEventListener('error', (event) => {
    const errorEvent = event as globalThis.ErrorEvent;
    const message = errorEvent.message || errorEvent.error?.message || '';
    if (isMapboxTimingError(message)) {
      event.preventDefault();
      event.stopImmediatePropagation();
      return true;
    }
  });

  // Handle unhandled promise rejections
  window.addEventListener(
    'unhandledrejection',
    (event: PromiseRejectionEvent) => {
      if (isMapboxTimingError(event.reason)) {
        event.preventDefault();
        return true;
      }
    },
    true
  );
}

// Install handler immediately when module loads
installGlobalMapboxErrorHandler();
