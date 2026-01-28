'use client';

import { Map } from 'lucide-react';

interface DestinationMapPlaceholderProps {
  /** Hero image URL to display as backdrop */
  imageUrl?: string | null;
  /** Destination name for alt text */
  destination?: string;
}

/**
 * DestinationMapPlaceholder
 *
 * Placeholder component for future map integration.
 * Shows the destination hero image with a map overlay hint.
 * Will be replaced with Mapbox/react-map-gl in future iteration.
 */
export function DestinationMapPlaceholder({
  imageUrl,
  destination = 'Destination',
}: DestinationMapPlaceholderProps) {
  return (
    <div className="relative h-full w-full overflow-hidden bg-muted/20">
      {/* Background image */}
      {imageUrl ? (
        <img
          src={imageUrl}
          alt={destination}
          className="absolute inset-0 h-full w-full object-cover opacity-60"
        />
      ) : (
        <div className="absolute inset-0 bg-gradient-to-br from-muted/30 to-muted/10" />
      )}

      {/* Overlay gradient */}
      <div className="absolute inset-0 bg-gradient-to-t from-background/80 via-background/20 to-transparent" />

      {/* Map placeholder content */}
      <div className="absolute inset-0 flex flex-col items-center justify-center text-muted-foreground/60">
        <div className="p-4 rounded-full bg-muted/30 backdrop-blur-sm mb-4">
          <Map className="w-12 h-12 opacity-40" />
        </div>
        <p className="text-sm font-medium">Interactive Map</p>
        <p className="text-xs mt-1 opacity-75">Updates as you scroll</p>
      </div>

      {/* Coming soon badge */}
      <div className="absolute top-4 right-4 px-2 py-1 rounded-full bg-muted/50 backdrop-blur-sm text-xs text-muted-foreground">
        Coming soon
      </div>
    </div>
  );
}

export default DestinationMapPlaceholder;
