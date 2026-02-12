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
