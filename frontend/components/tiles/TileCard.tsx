import { Heart, MapPin, Star } from 'lucide-react';
import {
  type KeyboardEvent,
  memo,
  type MouseEvent,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';

import { TaxesFeesTooltip } from '@/components/tiles/TaxesFeesTooltip';
import { Button } from '@/components/ui/button';
import { Card, CardBody } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip';
import { apiFetch } from '@/lib/api';
import { placeholderImageForTile } from '@/lib/placeholders';
import { getDeepLinkParams } from '@/lib/tileUtils';
import { cn, isFlightType } from '@/lib/utils';
import type { Tile } from '@/types/tile';

type TileCardProps = {
  tile: Tile;
  branchId?: string;
  isSelected?: boolean;
  onToggleSelect?: (tile: Tile) => void;
  /** Callback to show a toast notification when tile is selected */
  onSelectionToast?: (message: string) => void;
  /** Whether this tile was saved/shortlisted (show "Saved" badge) */
  isSaved?: boolean;
};

/**
 * Extract features from tile metadata.
 * Returns empty array if no features - no mock data.
 */
const getFeaturesForTile = (tile: Tile): string[] => {
  const meta = tile.meta as Record<string, unknown> | undefined;

  // Use features from backend if available
  if (meta?.features && Array.isArray(meta.features)) {
    return meta.features as string[];
  }

  // For flights, extract real metadata as features
  if (isFlightType(tile.type || '')) {
    const features: string[] = [];
    if (typeof meta?.stops === 'string') features.push(meta.stops);
    if (typeof meta?.fare_class === 'string') features.push(meta.fare_class);
    if (typeof meta?.duration === 'string') features.push(meta.duration);
    return features;
  }

  // No mock fallback - return empty array
  return [];
};

export const TileCard = memo(function TileCard({
  tile,
  branchId,
  isSelected,
  onToggleSelect,
  onSelectionToast,
  isSaved = false,
}: TileCardProps) {
  const [isLiked, setIsLiked] = useState(isSaved);
  // Track just-selected state for animation feedback
  const [justSelected, setJustSelected] = useState(false);
  // Track previous selection state to detect transitions
  const prevSelectedRef = useRef(isSelected);
  // Tier 11.7: Track image loading state for skeleton feedback
  const [imageLoaded, setImageLoaded] = useState(false);
  const [imageError, setImageError] = useState(false);

  const features = useMemo(() => getFeaturesForTile(tile), [tile]);

  // Detect when tile becomes selected and trigger animation
  useEffect(() => {
    // Only animate when going from unselected to selected
    if (isSelected && !prevSelectedRef.current) {
      setJustSelected(true);
      // Reset animation state after animation completes
      const timer = setTimeout(() => setJustSelected(false), 300);
      return () => clearTimeout(timer);
    }
    prevSelectedRef.current = isSelected;
    return undefined;
  }, [isSelected]);

  // Memoize click tracking payload to avoid recreating on each render
  const trackClick = useCallback(() => {
    apiFetch('/api/tiles/click', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        tile_id: tile.id,
        branch_id: branchId ?? null,
        user_id: null,
      }),
    }).catch((error) => {
      if (process.env.NODE_ENV !== 'production') {
        console.warn('Click tracking failed:', error);
      }
    });
  }, [tile.id, branchId]);

  const handleClick = useCallback(() => {
    // Fire-and-forget click tracking (session is sent via cookie)
    trackClick();
    // Open partner deeplink immediately
    window.open(tile.deeplink_url, '_blank', 'noopener,noreferrer');
  }, [trackClick, tile.deeplink_url]);

  const handleToggleSelect = useCallback(
    (event: MouseEvent | KeyboardEvent<HTMLDivElement>) => {
      event.preventDefault();
      event.stopPropagation();

      // Show toast if we're selecting (not deselecting) and callback is provided
      if (!isSelected && onSelectionToast) {
        // Truncate long titles for the toast message
        const displayTitle = tile.title.length > 30 ? tile.title.slice(0, 27) + '...' : tile.title;
        onSelectionToast(`Added ${displayTitle} to your trip`);
      }

      onToggleSelect?.(tile);
    },
    [onToggleSelect, tile, isSelected, onSelectionToast]
  );

  const handleLikeToggle = useCallback((event: MouseEvent) => {
    event.preventDefault();
    event.stopPropagation();
    setIsLiked((prev) => !prev);
  }, []);

  const handleKeyDown = useCallback(
    (event: KeyboardEvent<HTMLDivElement>) => {
      if (event.key === 'Enter' || event.key === ' ') {
        handleToggleSelect(event);
      }
    },
    [handleToggleSelect]
  );

  const handleViewDetailsClick = useCallback(
    (event: MouseEvent) => {
      event.stopPropagation();
      handleClick();
    },
    [handleClick]
  );

  return (
    <Card
      onClick={handleToggleSelect}
      className={cn(
        'bg-card group relative flex h-full flex-col overflow-hidden rounded-2xl border shadow-sm transition-all hover:shadow-md',
        isSelected ? 'ring-primary border-primary ring-2' : 'border-border',
        // Scale animation on selection for visual feedback (Tier 10.19)
        justSelected && 'scale-[1.02]',
        'transition-transform duration-200 ease-out'
      )}
      role="button"
      tabIndex={0}
      onKeyDown={handleKeyDown}
    >
      <div className="relative aspect-[4/3] w-full overflow-hidden">
        {/* Tier 11.7: Skeleton shown while image loads */}
        {!imageLoaded && (
          <Skeleton className="absolute inset-0 h-full w-full rounded-none" />
        )}
        <img
          src={imageError ? placeholderImageForTile(tile) : (tile.image_url || placeholderImageForTile(tile))}
          alt={tile.title}
          loading="lazy"
          onLoad={() => setImageLoaded(true)}
          onError={() => setImageError(true)}
          className={cn(
            'h-full w-full object-cover transition duration-700 group-hover:scale-105',
            !imageLoaded && 'opacity-0'
          )}
        />
        <div className="absolute inset-0 bg-gradient-to-t from-black/40 via-transparent to-transparent" />

        {/* Tier 9: Increased touch target to 44x44px for mobile accessibility */}
        <button
          type="button"
          className="text-muted-foreground absolute right-2 top-2 inline-flex h-11 w-11 items-center justify-center rounded-full bg-card/90 shadow-sm transition touch-manipulation hover:bg-card hover:text-red-500 active:scale-95"
          onClick={handleLikeToggle}
          aria-label={isLiked ? 'Unlike option' : 'Like option'}
        >
          <Heart className={`h-5 w-5 ${isLiked ? 'fill-red-500 text-red-500' : ''}`} />
        </button>

        {/* Saved badge (from shortlist) */}
        {isSaved && (
          <div className="absolute left-2 top-2 rounded bg-emerald-500/90 px-2 py-0.5 text-xs font-medium text-white shadow-sm">
            Saved
          </div>
        )}
        {/* Refundable/Non-refundable badge - Expedia compliance */}
        {!isSaved && tile.is_refundable === false && (
          <div className="absolute left-2 top-2 rounded bg-zinc-500/90 px-2 py-0.5 text-xs font-medium text-white shadow-sm">
            Non-refundable
          </div>
        )}
        {!isSaved && tile.is_refundable === true && (
          <div className="absolute left-2 top-2 rounded bg-emerald-500/90 px-2 py-0.5 text-xs font-medium text-white shadow-sm">
            Free cancellation
          </div>
        )}
      </div>

      <CardBody className="flex flex-1 flex-col gap-3 p-4">
        <div className="flex items-start justify-between gap-2">
          <div className="font-display text-foreground text-lg font-semibold leading-tight">
            {tile.title}
          </div>
          {tile.rating != null && (
            <div className="text-foreground flex shrink-0 items-center gap-1 text-sm font-medium">
              <Star className="h-4 w-4 fill-emerald-400 text-emerald-400" />
              <span>{tile.rating.toFixed(1)}</span>
            </div>
          )}
        </div>

        {tile.location_label && (
          <div className="text-muted-foreground -mt-1 flex items-center gap-1.5 text-sm">
            <MapPin className="h-4 w-4 shrink-0" />
            <span className="line-clamp-1">{tile.location_label}</span>
          </div>
        )}

        <div className="flex flex-wrap gap-2">
          {features.map((feature) => (
            <span
              key={feature}
              className="bg-muted text-muted-foreground inline-flex items-center rounded-md px-2.5 py-1 text-xs font-medium"
            >
              {feature}
            </span>
          ))}
        </div>

        <div className="mt-auto flex items-end justify-between pt-2">
          <div className="flex flex-col gap-0.5">
            <span className="text-muted-foreground text-xs">
              {tile.total_inclusive != null ? 'Total from' : 'From'}
            </span>
            <div className="flex items-baseline gap-1">
              <span className="text-foreground text-lg font-bold">
                {(tile.total_inclusive ?? tile.price_estimate) != null
                  ? Math.round(tile.total_inclusive ?? tile.price_estimate!).toLocaleString()
                  : ''}
              </span>
              <span className="text-foreground text-sm font-medium">{tile.currency}</span>
              {tile.type?.toLowerCase().includes('stay') && !tile.total_inclusive && (
                <span className="text-muted-foreground text-xs">/night</span>
              )}
            </div>
            {(tile.total_inclusive ?? tile.price_estimate) == null && (
              <span className="text-foreground text-sm font-bold">Check price</span>
            )}
            {/* Expedia taxes & fees disclosure with legal tooltip */}
            <TaxesFeesTooltip
              taxAndServiceFee={tile.tax_and_service_fee}
              propertyFee={tile.property_fee}
              currency={tile.currency}
            />
          </div>
          <div className="flex flex-col items-end">
            <TooltipProvider delayDuration={400}>
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    variant="primary"
                    size="sm"
                    className="bg-primary hover:bg-primary/90 text-primary-foreground font-semibold shadow-sm"
                    onClick={handleViewDetailsClick}
                  >
                    View Details
                  </Button>
                </TooltipTrigger>
                <TooltipContent
                  side="top"
                  className="max-w-xs bg-slate-900 text-slate-100 text-xs font-mono p-3 rounded-lg shadow-lg"
                >
                  <div className="text-slate-400 text-[10px] uppercase tracking-wider mb-1.5">
                    API Params
                  </div>
                  <pre className="whitespace-pre-wrap break-all">
                    {JSON.stringify(getDeepLinkParams(tile), null, 2)}
                  </pre>
                </TooltipContent>
              </Tooltip>
            </TooltipProvider>
            <span className="text-[10px] text-muted-foreground mt-1">
              Opens partner site
            </span>
          </div>
        </div>
      </CardBody>
    </Card>
  );
});
