/**
 * RegenerateConfirmModal
 *
 * Confirmation dialog shown when user clicks "Update Itinerary" badge.
 * Displays thumbnails of preferred tiles and confirms regeneration.
 *
 * @see docs/ux_unified_architecture.md - Regeneration Flow
 */

'use client';

import { Heart, Loader2, RefreshCw, X } from 'lucide-react';
import { memo } from 'react';

import { cn } from '@/lib/utils';
import type { Tile } from '@/types/tile';

export interface RegenerateConfirmModalProps {
  /** Whether modal is open */
  open: boolean;
  /** Callback to change open state */
  onOpenChange: (open: boolean) => void;
  /** Number of preferences (for display) */
  preferenceCount: number;
  /** Preferred tiles to show thumbnails */
  preferredTiles: Tile[];
  /** Callback when user confirms regeneration */
  onConfirm: () => void;
  /** Whether regeneration is in progress */
  isLoading?: boolean;
}

export const RegenerateConfirmModal = memo(function RegenerateConfirmModal({
  open,
  onOpenChange,
  preferenceCount,
  preferredTiles,
  onConfirm,
  isLoading = false,
}: RegenerateConfirmModalProps) {
  if (!open) return null;

  const handleConfirm = () => {
    onConfirm();
    // Note: modal closes via onConfirm setting showModal = false
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      {/* Backdrop */}
      <div
        className="fixed inset-0 bg-black/50 backdrop-blur-sm animate-in fade-in-0"
        onClick={() => onOpenChange(false)}
      />

      {/* Dialog */}
      <div className="relative z-50 w-full max-w-md mx-4 rounded-2xl border border-border bg-card p-6 shadow-xl animate-in fade-in-0 zoom-in-95">
        {/* Close button */}
        <button
          type="button"
          onClick={() => onOpenChange(false)}
          className="absolute right-4 top-4 rounded-full p-1 text-muted-foreground hover:bg-muted hover:text-foreground transition-colors"
          aria-label="Close dialog"
        >
          <X className="h-4 w-4" />
        </button>

        {/* Header */}
        <div className="flex items-start gap-4">
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-emerald-500/10 text-emerald-500">
            <RefreshCw className="h-5 w-5" />
          </div>
          <div className="flex-1 space-y-2">
            <h3 className="text-lg font-semibold text-foreground">Update Itinerary?</h3>
            <p className="text-sm text-muted-foreground">
              Your itinerary will be regenerated to prioritize your{' '}
              <span className="font-medium text-emerald-400">
                {preferenceCount} preferred selection{preferenceCount !== 1 ? 's' : ''}
              </span>
              .
            </p>
          </div>
        </div>

        {/* Preferred tiles thumbnails */}
        {preferredTiles.length > 0 && (
          <div className="mt-4 flex gap-2 overflow-x-auto pb-1">
            {preferredTiles.slice(0, 5).map((tile) => (
              <div key={tile.id} className="flex-shrink-0">
                <div className="w-16 h-12 rounded-lg overflow-hidden bg-zinc-800 ring-1 ring-emerald-500/30">
                  {tile.image_url ? (
                    <img
                      src={tile.image_url}
                      alt={tile.title}
                      className="w-full h-full object-cover"
                    />
                  ) : (
                    <div className="w-full h-full flex items-center justify-center text-zinc-600">
                      <Heart className="h-4 w-4" />
                    </div>
                  )}
                </div>
                <span className="block text-[10px] mt-1 truncate w-16 text-zinc-400">
                  {tile.title}
                </span>
              </div>
            ))}
            {preferredTiles.length > 5 && (
              <div className="flex-shrink-0 w-16 h-12 rounded-lg bg-zinc-800 ring-1 ring-white/10 flex items-center justify-center">
                <span className="text-xs text-zinc-400">+{preferredTiles.length - 5}</span>
              </div>
            )}
          </div>
        )}

        {/* Actions */}
        <div className="mt-6 flex justify-end gap-3">
          <button
            type="button"
            onClick={() => onOpenChange(false)}
            disabled={isLoading}
            className={cn(
              'rounded-full border border-border bg-background px-4 py-2 text-sm font-medium text-foreground',
              'hover:bg-muted transition-colors',
              'disabled:opacity-50 disabled:cursor-not-allowed'
            )}
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={handleConfirm}
            disabled={isLoading}
            className={cn(
              'rounded-full px-4 py-2 text-sm font-medium transition-colors',
              'bg-emerald-600 text-white hover:bg-emerald-500',
              'disabled:opacity-50 disabled:cursor-not-allowed',
              'flex items-center gap-2'
            )}
          >
            {isLoading ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin" />
                Updating...
              </>
            ) : (
              <>
                <RefreshCw className="h-4 w-4" />
                Update Itinerary
              </>
            )}
          </button>
        </div>
      </div>
    </div>
  );
});
