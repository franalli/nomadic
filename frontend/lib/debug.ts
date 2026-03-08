/* eslint-disable no-console */
/**
 * Debug logging utility
 *
 * Controlled by NEXT_PUBLIC_DEBUG_LOGS env variable:
 * - unset (default) = enabled in development, disabled in production
 * - "debug" = enabled
 * - "off" = disabled
 */

const DEBUG_FLAG = (process.env.NEXT_PUBLIC_DEBUG_LOGS || '').toLowerCase();
const DEBUG_MODE =
  DEBUG_FLAG === 'off'
    ? false
    : (DEBUG_FLAG === 'debug' || process.env.NODE_ENV !== 'production');
const EXPLICIT_DEBUG_MODE = DEBUG_FLAG === 'debug';

/**
 * Convert arbitrary log values into compact, single-line, JSON-safe output.
 * This preserves payload detail in forwarded/browser logs where raw objects
 * are often collapsed to "[object Object]".
 */
function formatArg(value: unknown, seen: WeakSet<object>): string {
  if (value instanceof Error) {
    return JSON.stringify({
      name: value.name,
      message: value.message,
      stack: value.stack,
    });
  }

  if (typeof value === 'string') return value;
  if (typeof value === 'number' || typeof value === 'boolean' || value === null) {
    return String(value);
  }
  if (typeof value === 'bigint') return value.toString();
  if (typeof value === 'undefined') return 'undefined';

  try {
    return JSON.stringify(value, (_key, currentValue: unknown) => {
      if (typeof currentValue === 'bigint') return currentValue.toString();
      if (currentValue instanceof Set) return Array.from(currentValue);
      if (currentValue instanceof Map) return Object.fromEntries(currentValue.entries());
      if (currentValue instanceof Error) {
        return {
          name: currentValue.name,
          message: currentValue.message,
          stack: currentValue.stack,
        };
      }
      if (typeof currentValue === 'object' && currentValue !== null) {
        if (seen.has(currentValue as object)) return '[Circular]';
        seen.add(currentValue as object);
      }
      return currentValue;
    });
  } catch {
    return String(value);
  }
}

/**
 * Console.log wrapper that respects debug flag and emits compact log lines
 * without losing payload detail.
 */
export function debugLog(...args: unknown[]): void {
  if (!DEBUG_MODE) return;

  const seen = new WeakSet<object>();
  const line = args.map((arg) => formatArg(arg, seen)).join(' | ');
  console.log(line);
}

/**
 * Console.log wrapper for high-volume diagnostics that should only appear
 * when debug logging is explicitly enabled via NEXT_PUBLIC_DEBUG_LOGS=debug.
 */
export function explicitDebugLog(...args: unknown[]): void {
  if (!EXPLICIT_DEBUG_MODE) return;

  const seen = new WeakSet<object>();
  const line = args.map((arg) => formatArg(arg, seen)).join(' | ');
  console.log(line);
}
