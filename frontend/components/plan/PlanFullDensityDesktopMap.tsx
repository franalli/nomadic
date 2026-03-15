'use client';

import { motion } from 'framer-motion';

import { InteractiveMap } from '@/components/map/InteractiveMap';
import { MapErrorBoundary } from '@/components/map/MapErrorBoundary';
import type { MapPOI } from '@/lib/ghost-timeline-adapter';

interface PlanFullDensityDesktopMapProps {
  headerOffset: number;
  fullModeMapItems: MapPOI[];
  mapCenter: { lat: number; lng: number; zoom: number };
  onMarkerClick: (itemId: string) => void;
}

const FADE_INITIAL = { opacity: 0 } as const;
const FADE_VISIBLE = { opacity: 1 } as const;
const MAP_TRANSITION = {
  duration: 0.4,
  delay: 0.4,
  ease: [0.4, 0, 0.2, 1],
} as const;

export function PlanFullDensityDesktopMap({
  headerOffset,
  fullModeMapItems,
  mapCenter,
  onMarkerClick,
}: PlanFullDensityDesktopMapProps) {
  return (
    <motion.div
      initial={FADE_INITIAL}
      animate={FADE_VISIBLE}
      transition={MAP_TRANSITION}
      className="flex-1 min-w-[350px] self-stretch pt-10"
    >
      <div
        className="sticky top-0 relative overflow-hidden rounded-xl"
        style={{ height: `calc(100vh - ${headerOffset}px)` }}
      >
        <div className="pointer-events-none absolute left-0 top-0 bottom-0 z-10 w-6 bg-gradient-to-r from-zinc-950/15 via-zinc-950/5 to-transparent dark:from-zinc-950/35 dark:via-zinc-950/10" />
        <div className="h-full w-full">
          <MapErrorBoundary className="h-full w-full">
            <InteractiveMap
              items={fullModeMapItems}
              activeItemId={null}
              defaultCenter={mapCenter}
              className="h-full w-full"
              onMarkerClick={onMarkerClick}
            />
          </MapErrorBoundary>
        </div>
      </div>
    </motion.div>
  );
}
