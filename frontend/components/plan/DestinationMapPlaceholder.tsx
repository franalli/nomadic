'use client';

import { Loader2, Map } from 'lucide-react';

interface DestinationMapPlaceholderProps {
  /** Hero image URL to display as backdrop */
  imageUrl?: string | null;
  /** Destination name for alt text */
  destination?: string;
  /** Show loading state during itinerary generation */
  isLoading?: boolean;
}

/**
 * DestinationMapPlaceholder
 *
 * Placeholder component for map display.
 * Shows the destination hero image with overlay.
 * During loading, shows "Map loading..." instead of "Coming soon".
 */
export function DestinationMapPlaceholder({
  imageUrl,
  destination = 'Destination',
  isLoading = false,
}: DestinationMapPlaceholderProps) {
  return (
    <div className="relative h-full w-full overflow-hidden bg-zinc-900/50">
      {/* Background image */}
      {imageUrl ? (
        <img
          src={imageUrl}
          alt={destination}
          className="absolute inset-0 h-full w-full object-cover opacity-40 blur-sm"
        />
      ) : (
        <div className="absolute inset-0 bg-gradient-to-br from-zinc-800/50 to-zinc-900/50" />
      )}

      {/* Overlay gradient */}
      <div className="absolute inset-0 bg-gradient-to-t from-zinc-900/90 via-zinc-900/40 to-zinc-900/60" />

      {/* Map placeholder content */}
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <div className="p-4 rounded-full bg-zinc-800/60 backdrop-blur-sm mb-4 border border-zinc-700/30">
          {isLoading ? (
            <Loader2 className="w-10 h-10 text-emerald-500/60 animate-spin" />
          ) : (
            <Map className="w-10 h-10 text-zinc-500/60" />
          )}
        </div>
        <p className="text-sm font-medium text-zinc-400">
          {isLoading ? 'Mapping locations...' : 'Interactive Map'}
        </p>
        <p className="text-xs mt-1 text-zinc-500">
          {isLoading ? 'Locations appear as they load' : 'Updates as you scroll'}
        </p>
      </div>

      {/* Status badge */}
      <div className="absolute top-4 right-4 px-3 py-1.5 rounded-full bg-zinc-800/70 backdrop-blur-sm text-xs font-medium border border-zinc-700/30">
        {isLoading ? (
          <span className="text-emerald-400 flex items-center gap-1.5">
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
            Building
          </span>
        ) : (
          <span className="text-zinc-400">Coming soon</span>
        )}
      </div>
    </div>
  );
}

export default DestinationMapPlaceholder;
