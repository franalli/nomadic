'use client';

import { useCallback, useMemo } from 'react';
import { useShallow } from 'zustand/react/shallow';

import { useLocalExpertPolling } from '@/hooks/useLocalExpertPolling';
import { useMapSync } from '@/hooks/useMapSync';
import type { MapPOI } from '@/lib/ghost-timeline-adapter';
import { calculateMapCenter, extractPOIsFromSections } from '@/lib/ghost-timeline-adapter';
import { usePanelToggleStore } from '@/state/panelToggleStore';
import type { DocumentTripInputs } from '@/types/document';
import type { DestinationCard, PlanViewModel } from '@/types/plan-envelope';
import type { Tile } from '@/types/tile';

import { PdfExportButton } from './PdfExportButton';
import { ShareTripButton } from './ShareTripButton';

const DEFAULT_MAP_CENTER = { lat: 20, lng: 0, zoom: 2 };

interface UsePlanFullDensityDataParams {
  viewModel: PlanViewModel;
  fullModeSections: PlanViewModel['strategy_sections'];
  fullModePOIs: MapPOI[];
  effectiveTiles: Record<string, Tile>;
  effectiveTripInputs: DocumentTripInputs | undefined;
  destinationCard?: DestinationCard;
  isDesktop: boolean;
  isStreaming: boolean;
}

function countTiles(tiles: Record<string, Tile>, category: 'stay' | 'flight'): number {
  return Object.values(tiles).filter((tile) => {
    if (category === 'flight') return tile.type === 'flight';
    return tile.type === 'hotel' || tile.type === 'stay' || tile.type === 'accommodation';
  }).length;
}

function resolveDestinationCenter(tiles: Record<string, Tile>) {
  const hotelTile = Object.values(tiles).find(
    (tile) =>
      (tile.type === 'hotel' || tile.type === 'accommodation') &&
      tile.geo?.lat != null &&
      tile.geo?.lng != null
  );
  return hotelTile?.geo ? { lat: hotelTile.geo.lat, lng: hotelTile.geo.lng, zoom: 13 } : null;
}

export function usePlanFullDensityData({
  viewModel,
  fullModeSections,
  fullModePOIs,
  effectiveTiles,
  effectiveTripInputs,
  destinationCard,
  isDesktop,
  isStreaming,
}: UsePlanFullDensityDataParams) {
  const strategySections = useMemo(() => viewModel.strategy_sections ?? [], [viewModel.strategy_sections]);
  const effectiveFullDest = effectiveTripInputs?.destination ?? destinationCard?.title;
  const sectionFallbackPOIs = useMemo(
    () =>
      fullModePOIs.length === 0
        ? extractPOIsFromSections(fullModeSections ?? [], effectiveFullDest)
        : [],
    [effectiveFullDest, fullModePOIs, fullModeSections]
  );
  const fullModeMapItems = useMemo(() => (fullModePOIs.length > 0 ? fullModePOIs : sectionFallbackPOIs), [fullModePOIs, sectionFallbackPOIs]);
  const destinationCenter = useMemo(() => resolveDestinationCenter(effectiveTiles), [effectiveTiles]);
  const mapCenter = useMemo(
    () =>
      fullModeMapItems.length > 0
        ? (calculateMapCenter(fullModeMapItems) ?? DEFAULT_MAP_CENTER)
        : destinationCenter ?? DEFAULT_MAP_CENTER,
    [destinationCenter, fullModeMapItems]
  );
  const showDesktopMap = isDesktop && (fullModeMapItems.length > 0 || destinationCenter !== null);
  const venueLinksActions = useMemo(() => {
    const dayCards = viewModel.day_cards ?? [];
    if (dayCards.length === 0) return null;
    return (
      <>
        <ShareTripButton />
        <PdfExportButton tripInputs={effectiveTripInputs} dayCards={dayCards} tiles={effectiveTiles} />
      </>
    );
  }, [effectiveTiles, effectiveTripInputs, viewModel.day_cards]);
  const handleMarkerClick = useCallback(
    (itemId: string) => {
      const item = fullModeMapItems.find((mapItem) => mapItem.id === itemId);
      if (!item?.dayNumber) return;
      useMapSync.getState().requestScrollTo(item.dayNumber, itemId);
    },
    [fullModeMapItems]
  );
  const stayCount = useMemo(() => countTiles(effectiveTiles, 'stay'), [effectiveTiles]);
  const flightCount = useMemo(() => countTiles(effectiveTiles, 'flight'), [effectiveTiles]);

  const {
    staysExpanded,
    flightsExpanded,
    intelExpanded,
    onToggleStays,
    onToggleFlights,
    onToggleIntel,
  } = usePanelToggleStore(
    useShallow((store) => ({
      staysExpanded: store.staysExpanded,
      flightsExpanded: store.flightsExpanded,
      intelExpanded: store.intelExpanded,
      onToggleStays: store.toggleStays,
      onToggleFlights: store.toggleFlights,
      onToggleIntel: store.toggleIntel,
    }))
  );

  const localExpertSection = useMemo(() => strategySections.find((section) => section.specialist_type === 'local_expert'), [strategySections]);
  const localExpertSectionId = localExpertSection?.id ?? null;
  const localExpertHasTI = Boolean(
    localExpertSection?.travel_intelligence &&
    Object.keys(localExpertSection.travel_intelligence).length > 0
  );
  const localExpertReady = (() => {
    const raw = localExpertSection?.local_expert_enrichment?.state;
    if (typeof raw !== 'string') return false;
    return raw.trim().toLowerCase() === 'ready';
  })();

  const {
    effectiveStrategySections,
    intelCategories,
    travelIntelItemCount,
    isTravelIntelPending,
    hasDestinationIntel,
  } = useLocalExpertPolling({
    strategySections,
    effectiveFullDest,
    isStreaming,
    localExpertSectionId,
    localExpertReady,
    localExpertHasTI,
    localExpertSection,
  });

  return {
    effectiveStrategySections,
    fullModeMapItems,
    mapCenter,
    showDesktopMap,
    destinationCenter,
    venueLinksActions,
    handleMarkerClick,
    stayCount,
    flightCount,
    staysExpanded,
    flightsExpanded,
    intelExpanded,
    onToggleStays,
    onToggleFlights,
    onToggleIntel,
    intelCategories,
    travelIntelItemCount,
    isTravelIntelPending,
    hasDestinationIntel,
    showTravelAdviceSegment: hasDestinationIntel || isTravelIntelPending,
  };
}
