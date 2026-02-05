/**
 * Debug logging utility
 *
 * Controlled by NEXT_PUBLIC_DEBUG_LOGS env variable:
 * - "debug" = verbose logging enabled
 * - "off" = silent (default for demos)
 */

const DEBUG_MODE = process.env.NEXT_PUBLIC_DEBUG_LOGS === 'debug';

/**
 * Console.log wrapper that respects debug flag
 */
export function debugLog(...args: unknown[]): void {
  if (DEBUG_MODE) {
    console.log(...args);
  }
}

/**
 * Console.warn wrapper that respects debug flag
 */
export function debugWarn(...args: unknown[]): void {
  if (DEBUG_MODE) {
    console.warn(...args);
  }
}

/**
 * Check if debug mode is enabled
 */
export function isDebugMode(): boolean {
  return DEBUG_MODE;
}
