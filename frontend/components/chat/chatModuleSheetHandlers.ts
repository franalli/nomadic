/**
 * chatModuleSheetHandlers — callback factories for ChatModuleSheets.
 *
 * Extracted to keep the main component under 200 lines.
 * Each factory reads fresh store state at invocation time (not stale props).
 */

import { guardedGeneratePlan, PLAN_ACTIVE_STATES } from '@/components/plan/planStateHelpers';
import { triggerRegeneration } from '@/hooks/usePreferenceAutoRegen';
import { GENERATE_PLAN_TRIGGER, useChatStore } from '@/state/chatStore';
import { DEFAULT_BOOKING_TYPES, useDocumentStore } from '@/state/documentStore';
import type {
  ActivitySettings,
  BookingTypes,
  DocumentTripInputsPatch,
  FlightSettings,
  HotelSettings,
  PlanDocumentPatch,
} from '@/types/document';
import type { Tile } from '@/types/tile';

// ─────────────────────────────────────────────────────────────────────────────
// Shared helpers
// ─────────────────────────────────────────────────────────────────────────────

function getCurrentPVS(): string | undefined {
  return useDocumentStore.getState().document?.plan_view_state;
}

function isS3(pvs: string | undefined): boolean {
  return ['S3_ITINERARY_READY', 'S3_EDITING'].includes(pvs ?? '');
}

function isS2(pvs: string | undefined): boolean {
  return pvs === 'S2_STRATEGY_READY';
}

/**
 * Gate a plan BUILD on dates: build when present, otherwise open the Dates
 * sheet + nudge chat instead of building a dateless plan (principle B).
 * Reads fresh trip_inputs from the store at invocation.
 */
function guardedBuild(
  sendMessageCore: (msg: string) => Promise<void>,
  openDates: () => void,
): void {
  guardedGeneratePlan({
    tripInputs: useDocumentStore.getState().document?.trip_inputs,
    sendBuild: () => void sendMessageCore(GENERATE_PLAN_TRIGGER),
    openDates,
    addNudge: (text) =>
      useChatStore.getState().addMessage({
        id: `a_ui_${Date.now()}`,
        role: 'assistant',
        content: text,
      }),
  });
}

// ─────────────────────────────────────────────────────────────────────────────
// Flights
// ─────────────────────────────────────────────────────────────────────────────

export function handleFlightsToggle(
  enabled: boolean,
  onUpdateBookingTypes: ((u: Partial<BookingTypes>) => void) | undefined,
  sendMessageCore: (msg: string) => Promise<void>,
  openDates: () => void,
) {
  if (onUpdateBookingTypes) {
    onUpdateBookingTypes({ flights: enabled ? 'on' : 'off' });
  }
  if (enabled) {
    const currentPVS = getCurrentPVS();
    if (PLAN_ACTIVE_STATES.has(currentPVS ?? '')) {
      guardedBuild(sendMessageCore, openDates);
    }
  }
}

export function handleFlightsSave(
  settings: Partial<FlightSettings>,
  onUpdateFlightSettings: ((u: Partial<FlightSettings>) => void) | undefined,
  toast: (msg: string) => void,
) {
  if (onUpdateFlightSettings) {
    onUpdateFlightSettings(settings);
  }
  toast('Flight preferences saved');
}

// ─────────────────────────────────────────────────────────────────────────────
// Stays
// ─────────────────────────────────────────────────────────────────────────────

export function handleStaysToggle(
  enabled: boolean,
  onUpdateBookingTypes: ((u: Partial<BookingTypes>) => void) | undefined,
  toast: (msg: string) => void,
) {
  if (onUpdateBookingTypes) {
    onUpdateBookingTypes({ hotels: enabled ? 'on' : 'off' });
  }
  toast(enabled ? 'Stays included' : 'Stays removed');
}

export function handleStaysSave(
  settings: Partial<HotelSettings>,
  onUpdateHotelSettings: ((u: Partial<HotelSettings>) => void) | undefined,
  toast: (msg: string) => void,
  sendMessageCore: (msg: string) => Promise<void>,
  openDates: () => void,
) {
  if (onUpdateHotelSettings) {
    onUpdateHotelSettings(settings);
  }
  toast('Stay preferences saved');
  const currentPVS = getCurrentPVS();
  if (isS3(currentPVS)) {
    triggerRegeneration(true);
  } else if (isS2(currentPVS)) {
    guardedBuild(sendMessageCore, openDates);
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// Activities
// ─────────────────────────────────────────────────────────────────────────────

export function handleActivitiesToggle(
  enabled: boolean,
  onUpdateBookingTypes: ((u: Partial<BookingTypes>) => void) | undefined,
  toast: (msg: string) => void,
) {
  if (onUpdateBookingTypes) {
    onUpdateBookingTypes({ activities: enabled ? 'on' : 'off' });
  }
  toast(enabled ? 'Activities included' : 'Activities removed');
}

export async function handleActivitiesSave(
  settings: ActivitySettings,
  prevActivitySettings: ActivitySettings | undefined,
  setActivityUserSaved: (v: boolean) => void,
  patchDocument: (patch: PlanDocumentPatch) => Promise<void>,
  commitTripInputs: (inputs: DocumentTripInputsPatch) => Promise<boolean>,
  sendMessageCore: (msg: string) => Promise<void>,
  toast: (msg: string) => void,
  openDates: () => void,
) {
  setActivityUserSaved(true);

  // Early visual feedback: show rebuild overlay immediately if we'll
  // need a regeneration (S3).
  const earlyPVS = getCurrentPVS();
  const willRebuild = isS3(earlyPVS);
  if (willRebuild) {
    useDocumentStore.getState().setRegenerationState({ isRegenerating: true });
  }

  const prevCats = new Set(prevActivitySettings?.categories || []);
  const newCats = new Set(settings.categories || []);

  // D3: Prune preferred_tile_ids for tiles belonging to removed categories.
  const removedCats = [...prevCats].filter((c) => !newCats.has(c));
  const { document: planDocument, version: docVersion } = useDocumentStore.getState();
  if (removedCats.length > 0 && planDocument) {
    const currentPreferred = planDocument.preferred_tile_ids ?? [];
    const tiles = planDocument.tiles ?? {};
    const removedCatSet = new Set(removedCats.map((c) => c.toLowerCase()));
    const prunedPreferred = currentPreferred.filter((tileId) => {
      const tile = tiles[tileId] as Tile | undefined;
      if (!tile) return true;
      const tileCategory = (
        ((tile.meta?.specialist_type as string | undefined) ??
          (tile.meta?.category as string | undefined)) ??
        ''
      ).toLowerCase();
      const tileTags = new Set((tile.tags ?? []).map((t) => t.toLowerCase()));
      const isRemovedCategory =
        (tileCategory && removedCatSet.has(tileCategory)) ||
        [...tileTags].some((t) => removedCatSet.has(t));
      return !isRemovedCategory;
    });
    if (prunedPreferred.length !== currentPreferred.length) {
      patchDocument({ version: docVersion, preferred_tile_ids: prunedPreferred });
    }
  }

  const shouldDisableActivities = (settings.categories?.length ?? 0) === 0;
  const nextBookingTypes = shouldDisableActivities
    ? {
        ...DEFAULT_BOOKING_TYPES,
        ...(useDocumentStore.getState().document?.trip_inputs?.booking_types ?? {}),
        activities: 'off' as const,
      }
    : undefined;

  await commitTripInputs({
    activity_settings: {
      ...settings,
      categories: settings.categories ?? [],
      day_preferences: settings.categories?.length ? (settings.day_preferences ?? {}) : {},
    },
    ...(nextBookingTypes ? { booking_types: nextBookingTypes } : {}),
  });

  toast('Activity preferences saved');
  const currentPVS = getCurrentPVS();
  if (isS3(currentPVS)) {
    const cats = settings.categories?.length ? settings.categories : undefined;
    triggerRegeneration(true, cats);
  } else {
    if (willRebuild) {
      useDocumentStore.getState().setRegenerationState({ isRegenerating: false });
    }
    if (isS2(currentPVS)) {
      guardedBuild(sendMessageCore, openDates);
    }
  }
}
