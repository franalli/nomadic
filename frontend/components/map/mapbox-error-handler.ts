// =============================================================================
// Comprehensive Global Error Suppression for Mapbox
// =============================================================================

/**
 * Error patterns that are unambiguously Mapbox — safe to suppress on message alone.
 */
const SUPPRESSED_ERROR_PATTERNS = [
  'errorCb is not a function',
  'this.errorCb is not a function',
  'Map container is already removed',
  'sku_token',
  'mapbox-gl',
];

/**
 * Generic null-ref patterns that many JS errors share. Only suppress these
 * when the stack trace confirms the error originated from Mapbox code.
 */
const MAPBOX_SCOPED_PATTERNS = [
  'Cannot read properties of undefined',
  'Cannot read properties of null',
];

/** Returns true if the Error's stack trace points to Mapbox source code. */
function hasMapboxStack(input: unknown): boolean {
  if (input instanceof Error && input.stack) {
    return input.stack.includes('mapbox-gl') || input.stack.includes('sku_token');
  }
  return false;
}

/**
 * Check if an error matches known Mapbox timing issues.
 * Exported so MapboxErrorSuppressor can reuse the canonical pattern list.
 *
 * - Mapbox-specific patterns (errorCb, sku_token, etc.) are always suppressed.
 * - Generic null-ref patterns are only suppressed when the Error's stack trace
 *   contains Mapbox source files, preventing real app bugs from being swallowed.
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

  // Always suppress Mapbox-specific patterns
  if (SUPPRESSED_ERROR_PATTERNS.some((pattern) => message.includes(pattern))) {
    return true;
  }

  // For generic null-ref errors, only suppress if the stack trace points to Mapbox
  if (MAPBOX_SCOPED_PATTERNS.some((pattern) => message.includes(pattern))) {
    return hasMapboxStack(input);
  }

  return false;
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
