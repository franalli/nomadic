'use client';

/**
 * RegenerationStatus
 *
 * Floating indicator that shows regeneration pending/in-progress state.
 * Appears when user makes changes that will trigger plan regeneration.
 *
 * Features:
 * - Countdown timer showing seconds until regeneration
 * - "Generate Now" button to bypass debounce
 * - Spinner when regeneration is in progress
 *
 * @see docs/ux_unified_architecture.md - Regeneration Flow
 */

import { useItineraryRegeneration } from '@/hooks/useItineraryRegeneration';

export function RegenerationStatus() {
  const { isPending, isRegenerating, remainingSeconds, triggerImmediateRegeneration } =
    useItineraryRegeneration();

  // Don't render if nothing is happening
  if (!isPending && !isRegenerating) {
    return null;
  }

  return (
    <div className="fixed bottom-4 right-4 z-50">
      <div className="bg-white border border-gray-200 rounded-lg shadow-lg px-4 py-3 flex items-center gap-3">
        {/* Spinner */}
        <div className="w-5 h-5 border-2 border-blue-500 border-t-transparent rounded-full animate-spin" />

        <div className="flex-1">
          {isPending ? (
            <>
              <p className="text-sm font-medium text-gray-900">
                Planning updates in {remainingSeconds}s...
              </p>
              <p className="text-xs text-gray-500">Make more changes or</p>
            </>
          ) : (
            <p className="text-sm font-medium text-gray-900">Regenerating plan...</p>
          )}
        </div>

        {isPending && (
          <button
            onClick={triggerImmediateRegeneration}
            className="text-xs text-blue-600 hover:text-blue-800 font-medium"
          >
            Generate Now
          </button>
        )}
      </div>
    </div>
  );
}
