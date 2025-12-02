'use client';

import { addDays, addWeeks, eachDayOfInterval, format, isBefore, nextSaturday, parse, startOfDay } from 'date-fns';
import { motion } from 'framer-motion';
import {
  AlertCircle,
  CalendarRange,
  CheckCircle2,
  Circle,
  Compass,
  MapPin,
  Menu,
  Plus,
  Route,
  Sparkles,
  User,
  Users,
  Wallet,
  X,
} from 'lucide-react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { DateRange } from 'react-day-picker';

import { BranchPanel } from '@/components/branches/BranchPanel';
import { ChatPanel, type ChatPanelHandle } from '@/components/chat/ChatPanel';
import { GeneratingLoader } from '@/components/layout/GeneratingLoader';
import { FeaturesSection } from '@/components/nomadic/features-section';
import { Footer } from '@/components/nomadic/footer';
import {
  resolveTabForTile,
  TAB_CONFIG,
  type TileTabKey,
} from '@/components/tiles/TilesGrid';
import { Button } from '@/components/ui/button';
import { Calendar } from '@/components/ui/calendar';
import { Card, CardContent } from '@/components/ui/card';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { apiFetch, resetSession } from '@/lib/api';
import { saveTripSummary } from '@/lib/summary';
import { DEFAULT_TRIP_INPUTS, useDocumentStore } from '@/state/documentStore';
import type { DocumentBranch, PlanDocumentResponse } from '@/types/document';
import type { TripInputs } from '@/types/plan';
import type { TripSummaryPayload } from '@/types/summary';
import type { Tile, TileSelection } from '@/types/tile';

type BranchSelectionOverrides = {
  branch?: DocumentBranch;
  tripContextId?: number | null;
  errorMessageOverride?: string;
};

type TripInputsDraft = {
  destinations: string[];
  origin?: string | null;
  start_date?: string | null;
  end_date?: string | null;
  traveler_count?: string | null;
  budget?: string | null;
  vibes?: string[];
};

const formatDateForDisplay = (value?: string | null): string => {
  if (!value) return '';
  const isoMatch = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
  if (isoMatch) {
    try {
      const date = new Date(value + 'T00:00:00');
      return format(date, 'EEE, MMM d');
    } catch {
      return value;
    }
  }
  return value;
};

const formatBudgetValue = (value?: string | number | null): string => {
  if (value === null || value === undefined) return '';
  const parsed = Number(value);
  if (!Number.isFinite(parsed) || parsed <= 0) return '';
  return `$${Math.round(parsed).toLocaleString()}`;
};

const toTripInputsDraft = (inputs: TripInputs): TripInputsDraft => {
  return {
    destinations: inputs.destinations ?? [],
    origin: inputs.origin ?? null,
    start_date: inputs.start_date ?? null,
    end_date: inputs.end_date ?? null,
    traveler_count: inputs.traveler_count != null ? String(inputs.traveler_count) : null,
    budget: inputs.budget != null ? String(inputs.budget) : null,
    vibes: inputs.vibes ?? [],
  };
};

const HERO_IMAGE =
  'https://images.unsplash.com/photo-1500530855697-b586d89ba3ee?auto=format&fit=crop&w=2000&q=80';
const HERO_VIDEO = '/hiking_video.mp4';
const HERO_TAGLINE = 'We Plan the Rest.';
const HERO_TYPING_INTERVAL_MS = 200;
const HERO_TYPING_PAUSE_MS = 8000;

// Minimum time to show the generating loader for hype (in ms)
const GENERATING_MIN_DURATION_MS = 10000;

// Date presets for quick date selection - extracted to avoid duplication
const DATE_PRESETS = [
  {
    label: 'This weekend',
    getDates: () => {
      const sat = nextSaturday(new Date());
      return { from: sat, to: addDays(sat, 1) };
    },
  },
  {
    label: 'Next weekend',
    getDates: () => {
      const sat = nextSaturday(addWeeks(new Date(), 1));
      return { from: sat, to: addDays(sat, 1) };
    },
  },
  {
    label: '1 week',
    getDates: () => {
      const start = addDays(new Date(), 1);
      return { from: start, to: addDays(start, 6) };
    },
  },
  {
    label: '2 weeks',
    getDates: () => {
      const start = addDays(new Date(), 1);
      return { from: start, to: addDays(start, 13) };
    },
  },
];

type TileCounts = Record<TileTabKey, number>;

// Field progress indicator - shows which fields are complete
// Required fields: origin, destinations, dates (must be set to generate)
// Optional fields: traveler_count, budget, vibes, multi_city_intent (enhance the trip but not required)
type FieldConfig = { label: string; required: boolean };
const FIELD_CONFIG: Record<string, FieldConfig> = {
  origin: { label: 'From', required: true },
  destinations: { label: 'Where to', required: true },
  dates: { label: 'Dates', required: true },
  traveler_count: { label: 'Travelers', required: false },
  budget: { label: 'Budget', required: false },
  vibes: { label: 'Vibes', required: false },
  multi_city_intent: { label: 'Trip style', required: false },
};
// Backwards-compatible helper for existing code
const FIELD_LABELS: Record<string, string> = Object.fromEntries(
  Object.entries(FIELD_CONFIG).map(([k, v]) => [k, v.label])
);

// Helper to check if a field is complete based on actual values
const isFieldComplete = (field: string, tripInputs: TripInputs): boolean => {
  switch (field) {
    case 'origin':
      return Boolean(tripInputs.origin);
    case 'destinations':
      return (tripInputs.destinations ?? []).length > 0;
    case 'dates':
      return Boolean(tripInputs.start_date) && Boolean(tripInputs.end_date);
    case 'traveler_count':
      return tripInputs.traveler_count != null;
    case 'budget':
      return tripInputs.budget != null;
    case 'vibes':
      return (tripInputs.vibes ?? []).length > 0;
    case 'multi_city_intent':
      return tripInputs.multi_city_intent != null;
    default:
      return false;
  }
};

const countTilesByTab = (tileList: Tile[]): TileCounts =>
  tileList.reduce(
    (acc, tile) => {
      const tab = resolveTabForTile(tile);
      acc[tab] += 1;
      return acc;
    },
    { stays: 0, flights: 0, activities: 0 } as TileCounts
  );

const summarizeTileCounts = (counts: TileCounts): string => {
  const parts: string[] = [];
  if (counts.stays) parts.push(`${counts.stays} stay${counts.stays === 1 ? '' : 's'}`);
  if (counts.flights)
    parts.push(`${counts.flights} flight${counts.flights === 1 ? '' : 's'}`);
  if (counts.activities)
    parts.push(`${counts.activities} activit${counts.activities === 1 ? 'y' : 'ies'}`);

  if (!parts.length) {
    return 'No live tiles yet—still hunting for stays, flights, and activities.';
  }
  return `Coverage: ${parts.join(' · ')}.`;
};

type SelectionCategory = 'stay' | 'flight' | 'activity';

const resolveSelectionCategory = (tile: Tile): SelectionCategory => {
  const tab = resolveTabForTile(tile);
  if (tab === 'flights') return 'flight';
  if (tab === 'activities') return 'activity';
  return 'stay';
};

const parseDateValue = (value: unknown): Date | null => {
  if (!value || typeof value !== 'string') return null;
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
};

const extractActivityRange = (tile: Tile): { start?: Date | null; end?: Date | null } => {
  const meta = (tile.meta as Record<string, unknown> | undefined) ?? {};
  const startRaw =
    meta.start_date ?? meta.date ?? meta.date_time ?? meta.start ?? meta.activity_date;
  const endRaw = meta.end_date ?? meta.end ?? meta.activity_end;
  const start = parseDateValue(startRaw);
  const end = parseDateValue(endRaw) ?? start;
  return { start, end };
};

const activitiesOverlap = (a: Tile, b: Tile): boolean => {
  const rangeA = extractActivityRange(a);
  const rangeB = extractActivityRange(b);
  const startA = rangeA.start;
  const startB = rangeB.start;
  const endA = rangeA.end ?? startA;
  const endB = rangeB.end ?? startB;
  if (!startA || !startB || !endA || !endB) return false;
  return startA.getTime() <= endB.getTime() && startB.getTime() <= endA.getTime();
};

const summarizeSelections = (selection?: TileSelection): string | null => {
  if (!selection) return null;
  const parts: string[] = [];
  if (selection.stay) {
    parts.push(`Stay: ${selection.stay.title}`);
  }
  if (selection.flight) {
    parts.push(`Flight: ${selection.flight.title}`);
  }
  if (selection.activities.length > 0) {
    const activityNames = selection.activities
      .map((act) => act.title)
      .slice(0, 3)
      .join(', ');
    const suffix = selection.activities.length > 3 ? ' +' : '';
    parts.push(`Activities: ${activityNames}${suffix}`);
  }

  if (!parts.length) return null;
  return `Locked choices — ${parts.join(' · ')}`;
};

/**
 * Convert ID-based BranchSelections (from server) to object-based TileSelection (for UI).
 * Missing tiles are skipped with a warning.
 */
const selectionsToTileSelection = (
  selections: { stay?: string | null; flight?: string | null; activities: string[] } | undefined,
  tilesMap: Record<string, Tile>
): TileSelection => {
  const result: TileSelection = { activities: [] };
  if (!selections) return result;

  if (selections.stay) {
    const stayTile = tilesMap[selections.stay];
    if (stayTile) {
      result.stay = stayTile;
    } else {
      console.warn(`selectionsToTileSelection: stay tile "${selections.stay}" not found in tilesMap`);
    }
  }

  if (selections.flight) {
    const flightTile = tilesMap[selections.flight];
    if (flightTile) {
      result.flight = flightTile;
    } else {
      console.warn(`selectionsToTileSelection: flight tile "${selections.flight}" not found in tilesMap`);
    }
  }

  for (const activityId of selections.activities) {
    const activityTile = tilesMap[activityId];
    if (activityTile) {
      result.activities.push(activityTile);
    } else {
      console.warn(`selectionsToTileSelection: activity tile "${activityId}" not found in tilesMap`);
    }
  }

  return result;
};

// LocationBadge props interface - extracted to module level to prevent re-creation
interface LocationBadgeProps {
  type: 'origin' | 'destination';
  index?: number;
  value: string;
  isOrigin?: boolean;
  isSelected: boolean;
  onSelect: (key: 'origin' | number | null) => void;
  onRemove: () => void;
}

// LocationBadge component - extracted to module level to prevent re-creation on every render
const LocationBadge = ({
  type,
  index,
  value,
  isOrigin = false,
  isSelected,
  onSelect,
  onRemove,
}: LocationBadgeProps) => {
  const badgeKey = type === 'origin' ? 'origin' : index!;
  const badgeRef = useRef<HTMLSpanElement>(null);

  // Focus the badge when it becomes selected
  useEffect(() => {
    if (isSelected && badgeRef.current) {
      badgeRef.current.focus();
    }
  }, [isSelected]);

  const handleRemoveClick = (e: React.MouseEvent) => {
    e.stopPropagation();
    onRemove();
  };

  return (
    <span
      ref={badgeRef}
      className={`group relative inline-flex cursor-pointer items-center gap-1 text-xs font-semibold transition-all outline-none ${
        isSelected
          ? 'bg-primary/20 rounded-full px-1.5 py-0.5 ring-primary ring-2 ring-offset-1'
          : 'hover:bg-muted/60 rounded-full px-1 py-0.5'
      }`}
      role="button"
      tabIndex={0}
      onClick={(e) => {
        e.stopPropagation();
        onSelect(isSelected ? null : badgeKey);
      }}
      onKeyDown={(e) => {
        if (e.key === 'Delete' || e.key === 'Backspace') {
          e.preventDefault();
          onRemove();
        } else if (e.key === 'Escape') {
          e.preventDefault();
          onSelect(null);
          badgeRef.current?.blur();
        } else if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          onSelect(isSelected ? null : badgeKey);
        }
      }}
    >
      <MapPin
        className={`h-3 w-3 shrink-0 ${isOrigin ? 'text-muted-foreground' : 'text-accent'}`}
      />
      {value}
      <button
        type="button"
        onClick={handleRemoveClick}
        className="absolute -right-1 -top-1 flex h-3.5 w-3.5 items-center justify-center rounded-full bg-gray-500 text-white opacity-0 transition-opacity hover:bg-gray-600 group-hover:opacity-70"
        aria-label={`Remove ${value}`}
      >
        <X className="h-2.5 w-2.5" />
      </button>
    </span>
  );
};

export function NomadicLanding() {
  // Document store - single source of truth for trip inputs
  const documentStore = useDocumentStore();
  const storeTripInputs = documentStore.document?.trip_inputs;

  // Derive tripInputs from store (with defaults)
  const tripInputs: TripInputs = useMemo(() => {
    if (!storeTripInputs) return DEFAULT_TRIP_INPUTS;
    return { ...storeTripInputs };
  }, [storeTripInputs]);

  const [branches, setBranches] = useState<DocumentBranch[]>([]);
  const [selectedBranchId, setSelectedBranchId] = useState<string | null>(null);
  const [tilesMap, setTilesMap] = useState<Record<string, Tile>>({});
  const [tilesBranchId, setTilesBranchId] = useState<string | null>(null);
  const [branchTileNotes, setBranchTileNotes] = useState<Record<string, string>>({});
  const [branchTileCounts, setBranchTileCounts] = useState<Record<string, TileCounts>>(
    {}
  );
  const [branchTabNotes, setBranchTabNotes] = useState<Record<string, string>>({});
  const [branchSelections, setBranchSelections] = useState<Record<string, TileSelection>>(
    {}
  );

  // Draft state for UI editing (kept local)
  const [tripInputsDraft, setTripInputsDraft] = useState<TripInputsDraft>(() =>
    toTripInputsDraft(DEFAULT_TRIP_INPUTS)
  );

  const [editingField, setEditingField] = useState<keyof TripInputsDraft | null>(null);
  const [selectedLocationBadge, setSelectedLocationBadge] = useState<'origin' | number | null>(null);
  const [calendarOpen, setCalendarOpen] = useState(false);
  const [hoveredDate, setHoveredDate] = useState<Date | null>(null);
  const [isResettingDateRange, setIsResettingDateRange] = useState(false);
  const [vibeInput, setVibeInput] = useState('');
  const [vibeInputExpanded, setVibeInputExpanded] = useState(false);
  const [destinationInput, setDestinationInput] = useState('');
  const [destinationInputExpanded, setDestinationInputExpanded] = useState(false);
  const [originInput, setOriginInput] = useState('');
  const [originInputExpanded, setOriginInputExpanded] = useState(false);
  const [toastMessage, setToastMessage] = useState<string | null>(null);
  const [isHydratingSnapshot, setIsHydratingSnapshot] = useState(false);
  const [isResettingSession, setIsResettingSession] = useState(false);
  const [isGenerating, setIsGenerating] = useState(false);
  const generatingStartTimeRef = useRef<number | null>(null);
  const generatingTimerRef = useRef<NodeJS.Timeout | null>(null);
  const [chatKey, setChatKey] = useState(0);
  const tilesFetchControllerRef = useRef<AbortController | null>(null);
  const chatPanelContainerRef = useRef<HTMLDivElement | null>(null);
  const chatPanelRef = useRef<ChatPanelHandle | null>(null);
  const [typedTagline, setTypedTagline] = useState('');

  // Compute readyToGenerate from document state - show button when all required fields are filled
  // and no branches have been generated yet
  const readyToGenerate = useMemo(() => {
    const hasAllFields = documentStore.hasAllRequiredFields();
    const noBranches = branches.length === 0;
    return hasAllFields && noBranches;
  }, [documentStore, branches.length]);

  const selectedBranch = useMemo(
    () => branches.find((branch) => branch.id === selectedBranchId) ?? null,
    [branches, selectedBranchId]
  );

  const activeBranchSelection = useMemo(
    () =>
      selectedBranchId
        ? (branchSelections[selectedBranchId] ?? { activities: [] })
        : { activities: [] },
    [branchSelections, selectedBranchId]
  );

  const branchesWithTileNotes = useMemo(
    () =>
      branches.map((branch) => {
        const note = branchTileNotes[branch.id];
        const baseDescription = (branch.description ?? '').trim();
        const mergedDescription = [baseDescription, note]
          .filter(Boolean)
          .join(baseDescription && note ? ' ' : '');
        return { ...branch, description: mergedDescription };
      }),
    [branchTileNotes, branches]
  );

  // Compute tiles array for the selected branch from tilesMap
  const tiles = useMemo(() => {
    if (!selectedBranch) return [];
    const tileIds = [
      ...selectedBranch.tiles.stays,
      ...selectedBranch.tiles.flights,
      ...selectedBranch.tiles.activities,
    ];
    return tileIds
      .map((id) => tilesMap[id])
      .filter((tile): tile is Tile => tile !== undefined);
  }, [selectedBranch, tilesMap]);

  // Sync tripInputsDraft when store trip_inputs changes
  // Always sync destinations and vibes (they're modified by bot, not inline editing)
  // Only skip other fields if user is actively editing them
  useEffect(() => {
    if (!storeTripInputs) return;

    setTripInputsDraft((prev) => {
      // Always update destinations and vibes from store (source of truth)
      // This ensures bot-initiated changes are reflected in UI
      const newDraft: TripInputsDraft = {
        ...prev,
        destinations: storeTripInputs.destinations ?? [],
        vibes: storeTripInputs.vibes ?? [],
      };

      // Only update other fields if not actively editing
      if (editingField === null) {
        newDraft.origin = storeTripInputs.origin ?? null;
        newDraft.start_date = storeTripInputs.start_date ?? null;
        newDraft.end_date = storeTripInputs.end_date ?? null;
        newDraft.traveler_count = storeTripInputs.traveler_count != null
          ? String(storeTripInputs.traveler_count)
          : null;
        newDraft.budget = storeTripInputs.budget != null
          ? String(storeTripInputs.budget)
          : null;
      }

      return newDraft;
    });
  }, [storeTripInputs, editingField]);

  const abortTilesFetch = useCallback(() => {
    if (tilesFetchControllerRef.current) {
      tilesFetchControllerRef.current.abort();
      tilesFetchControllerRef.current = null;
    }
  }, []);

  const handleBranchSelect = useCallback(
    async (branchId: string, overrides?: BranchSelectionOverrides) => {
      abortTilesFetch();
      const controller = new AbortController();
      tilesFetchControllerRef.current = controller;

      const branchChanged = branchId !== selectedBranchId;
      setSelectedBranchId(branchId);
      setTilesBranchId(null);
      if (branchChanged) {
        setBranchSelections((prev) => {
          if (prev[branchId]) return prev;
          return { ...prev, [branchId]: { activities: [] } };
        });
      }
      const branch = overrides?.branch ?? branches.find((b) => b.id === branchId);
      if (!branch) return;
      setBranchTileNotes((prev) => ({
        ...prev,
        [branchId]: 'Refreshing booking options for this suggestion.',
      }));
      setBranchTileCounts((prev) => {
        const next = { ...prev };
        delete next[branchId];
        return next;
      });
      setBranchTabNotes((prev) => {
        const next = { ...prev };
        delete next[branchId];
        return next;
      });

      const errorMessageOverride = overrides?.errorMessageOverride;

      try {
        const res = await apiFetch(
          `/v1/document/tiles/${encodeURIComponent(branchId)}`,
          {
            method: 'POST',
            signal: controller.signal,
          }
        );

        if (!res.ok) {
          console.error('Failed to fetch tiles for branch', res.status);
          setToastMessage(
            errorMessageOverride ??
              'Unable to refresh options for that suggestion. Please try again.'
          );
          return;
        }

        const data: PlanDocumentResponse = await res.json();
        if (controller.signal.aborted) return;

        // Update state from the document response
        setBranches(data.document.branches);
        setTilesMap(data.document.tiles);
        setTilesBranchId(branchId);
      } catch (error) {
        if ((error as DOMException).name === 'AbortError') return;
        console.error('Failed to fetch tiles for branch', error);
        setToastMessage(
          errorMessageOverride ??
            'Unable to refresh options for that suggestion. Please try again.'
        );
      } finally {
        if (tilesFetchControllerRef.current === controller) {
          tilesFetchControllerRef.current = null;
        }
      }
    },
    [abortTilesFetch, branches, selectedBranchId]
  );

  useEffect(() => {
    if (!toastMessage) return undefined;
    const timer = window.setTimeout(() => setToastMessage(null), 4000);
    return () => window.clearTimeout(timer);
  }, [toastMessage]);

  useEffect(() => {
    let cancelled = false;

    async function hydrateSessionDocument() {
      try {
        setIsHydratingSnapshot(true);

        // Use the store to fetch and cache the document (single source of truth)
        await documentStore.fetchDocument();
        if (cancelled) return;

        const doc = documentStore.document;
        if (!doc) return;

        if (!doc.branches.length) return;

        setBranches(doc.branches);
        setTilesMap(doc.tiles);

        // Restore branchSelections from server-persisted selections
        const restoredSelections: Record<string, TileSelection> = {};
        for (const branch of doc.branches) {
          restoredSelections[branch.id] = selectionsToTileSelection(branch.selections, doc.tiles);
        }
        setBranchSelections(restoredSelections);

        const primaryBranch = doc.branches.find((b) => b.is_primary);
        const fallbackBranchId = primaryBranch?.id ?? doc.branches[0].id;

        setSelectedBranchId(fallbackBranchId);
        setTilesBranchId(fallbackBranchId);

        // Check if the primary branch has tiles, if not fetch them
        const hasTilesForBranch =
          primaryBranch &&
          (primaryBranch.tiles.stays.length > 0 ||
            primaryBranch.tiles.flights.length > 0 ||
            primaryBranch.tiles.activities.length > 0);

        if (!hasTilesForBranch && fallbackBranchId) {
          const overrides: BranchSelectionOverrides = {
            branch: primaryBranch ?? doc.branches[0],
            tripContextId: doc.trip_context_id ?? null,
            errorMessageOverride:
              'We restored your suggestions but could not refresh options automatically. Select a suggestion to try again.',
          };

          await handleBranchSelect(fallbackBranchId, overrides);
        }
      } catch (error) {
        console.error('Failed to hydrate session document', error);
        setToastMessage(
          'Unable to reload your previous session. You can still plan a new trip.'
        );
      } finally {
        setIsHydratingSnapshot(false);
      }
    }

    hydrateSessionDocument();

    return () => {
      cancelled = true;
    };
    // We intentionally run this only once on mount to restore the last session document.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleClearContext = useCallback(() => {
    abortTilesFetch();
    // Clear any pending generating state
    if (generatingTimerRef.current) {
      clearTimeout(generatingTimerRef.current);
      generatingTimerRef.current = null;
    }
    setIsGenerating(false);
    generatingStartTimeRef.current = null;

    setBranches([]);
    setSelectedBranchId(null);
    setTilesMap({});
    setTilesBranchId(null);
    setBranchTileNotes({});
    setBranchTileCounts({});
    setBranchTabNotes({});
    setBranchSelections({});
    // Reset the draft to defaults (store will be reset separately)
    setTripInputsDraft(toTripInputsDraft(DEFAULT_TRIP_INPUTS));
    // Reset the store
    documentStore.reset();
    // readyToGenerate is now computed automatically from document state
    setChatKey((prev) => prev + 1);
  }, [abortTilesFetch, documentStore]);

  const handleStartNewSession = useCallback(async () => {
    abortTilesFetch();
    setIsResettingSession(true);
    let didResetServerState = false;

    try {
      const res = await resetSession();
      didResetServerState = res.ok;
    } catch (error) {
      console.error('Failed to reset planning session', error);
    } finally {
      handleClearContext();
      setIsResettingSession(false);
      // Scroll to chat panel after reset
      setTimeout(() => {
        if (chatPanelContainerRef.current) {
          chatPanelContainerRef.current.scrollIntoView({
            behavior: 'smooth',
            block: 'start',
          });
          // Focus the input if it exists
          const input = chatPanelContainerRef.current.querySelector(
            'input[type="text"]'
          ) as HTMLInputElement;
          if (input) {
            input.focus();
          }
        }
      }, 100);
    }

    setToastMessage(
      didResetServerState
        ? 'Started a fresh planning session.'
        : 'Cleared your local planner, but the previous session may reappear if you refresh.'
    );
  }, [abortTilesFetch, handleClearContext]);

  const handleStartEditingField = useCallback((field: keyof TripInputsDraft) => {
    setEditingField(field);
  }, []);

  const handleFieldChange = useCallback((field: keyof TripInputsDraft, value: string) => {
    setTripInputsDraft((prev) => (prev ? { ...prev, [field]: value } : prev));
  }, []);

  const handleCommitField = useCallback(
    async (field?: keyof TripInputsDraft, value?: string) => {
      setEditingField(null);

      if (!field) return;

      const prevValue = tripInputs[field as keyof TripInputs];
      const trimmedValue = value?.trim();

      // If the user cleared the field, restore the previous value and don't commit
      if (!trimmedValue) {
        setTripInputsDraft((prev) => {
          if (!prev) return prev;
          return { ...prev, [field]: prevValue ?? '' };
        });
        return;
      }

      // For numeric fields, validate the value
      let parsedValue: string | number = trimmedValue;
      if (field === 'traveler_count') {
        const count = parseInt(trimmedValue, 10);
        if (Number.isNaN(count) || count <= 0) {
          setTripInputsDraft((prev) => ({
            ...toTripInputsDraft(tripInputs),
            ...prev,
            traveler_count: prevValue != null ? String(prevValue) : '',
          }));
          return;
        }
        parsedValue = count;
      } else if (field === 'budget') {
        const budget = parseInt(trimmedValue.replace(/[^\d]/g, ''), 10);
        if (Number.isNaN(budget) || budget <= 0) {
          setTripInputsDraft((prev) => ({
            ...toTripInputsDraft(tripInputs),
            ...prev,
            budget: prevValue != null ? String(prevValue) : '',
          }));
          return;
        }
        parsedValue = budget;
      }

      // Don't commit if value hasn't changed
      if (trimmedValue === String(prevValue ?? '')) {
        return;
      }

      // Update draft locally
      setTripInputsDraft((prev) => {
        const base = prev ?? toTripInputsDraft(tripInputs);
        return { ...base, [field]: trimmedValue };
      });

      // Commit to document store
      const updates: Record<string, string | number | null> = {};
      if (field === 'origin') {
        updates.origin = trimmedValue;
      } else if (field === 'traveler_count') {
        updates.traveler_count = typeof parsedValue === 'number' ? parsedValue : parseInt(trimmedValue, 10);
      } else if (field === 'budget') {
        updates.budget = typeof parsedValue === 'number' ? parsedValue : parseInt(trimmedValue.replace(/[^\d]/g, ''), 10);
      }

      const success = await documentStore.commitTripInputs(updates);

      if (!success) {
        setToastMessage(`Failed to update ${field.replace('_', ' ')}. Please try again.`);
        return;
      }

      // Add assistant message to acknowledge the change
      let message: string | null = null;

      if (field === 'origin') {
        message = `Got it! Departing from ${trimmedValue}. ✈️`;
      } else if (field === 'traveler_count') {
        const count = typeof parsedValue === 'number' ? parsedValue : parseInt(trimmedValue, 10);
        if (!Number.isNaN(count)) {
          message = count === 1
            ? 'Noted! Planning for a solo adventure. 🎒'
            : `Noted! Planning for ${count} travelers. 👥`;
        }
      } else if (field === 'budget') {
        const budget = typeof parsedValue === 'number' ? parsedValue : parseInt(trimmedValue.replace(/[^\d]/g, ''), 10);
        if (!Number.isNaN(budget) && budget > 0) {
          message = `Got it! Budget set to $${budget.toLocaleString()}. 💰`;
        }
      }

      if (message) {
        chatPanelRef.current?.addAssistantMessage(message);
      }
    },
    [tripInputs, documentStore]
  );

  // Track if we're waiting for the second click (end date)
  // This is needed because React state updates are async and onSelect may fire multiple times
  const isSelectingEndDateRef = useRef<boolean>(false);
  const pendingStartDateRef = useRef<string | null>(null);

  // Track if we had a complete range when selection started (for reset detection)
  const hadCompleteRangeRef = useRef<boolean>(false);

  // No-op handler for onSelect - we handle everything in onDayClick
  // This prevents react-day-picker from computing its own range
  const handleCalendarSelect = useCallback(() => {
    // Intentionally empty - all logic is in handleCalendarDayClick
  }, []);

  // Primary handler for date selection - handles all click logic
  // We use onDayClick instead of onSelect to have full control over range behavior
  const handleCalendarDayClick = useCallback(
    async (day: Date) => {
      const clickedIso = format(day, 'yyyy-MM-dd');

      // Check if we're waiting for the end date selection
      // If isSelectingEndDateRef is false, this is either the first click or we're resetting
      if (isSelectingEndDateRef.current && pendingStartDateRef.current) {
        // This is the second click - set end date
        const startIso = pendingStartDateRef.current;
        const startDate = parse(startIso, 'yyyy-MM-dd', new Date());

        let newStartIso: string;
        let newEndIso: string;

        if (isBefore(day, startDate)) {
          // Clicked before start - swap them
          newStartIso = clickedIso;
          newEndIso = startIso;
        } else {
          // Normal case - clicked date is end
          newStartIso = startIso;
          newEndIso = clickedIso;
        }

        // Reset the refs
        isSelectingEndDateRef.current = false;
        pendingStartDateRef.current = null;
        setHoveredDate(null);

        // Update draft
        setTripInputsDraft((prev) => {
          const base = prev ?? toTripInputsDraft(tripInputs);
          return { ...base, start_date: newStartIso, end_date: newEndIso };
        });

        // Close calendar and commit
        setCalendarOpen(false);

        const prevStartIso = tripInputs.start_date;
        const prevEndIso = tripInputs.end_date;
        if (newStartIso !== prevStartIso || newEndIso !== prevEndIso) {
          const success = await documentStore.commitTripInputs({
            start_date: newStartIso,
            end_date: newEndIso,
          });

          if (!success) {
            setToastMessage('Failed to update dates. Please try again.');
            return;
          }

          const startDisplay = formatDateForDisplay(newStartIso);
          const endDisplay = formatDateForDisplay(newEndIso);
          chatPanelRef.current?.addAssistantMessage(
            `Perfect! Travel dates set: ${startDisplay} – ${endDisplay}. 📅`
          );
        }
      } else {
        // This is the first click (or resetting from complete range) - set start date, wait for end

        // If we had a complete range when we started, show brief visual feedback that we're resetting
        if (hadCompleteRangeRef.current) {
          setIsResettingDateRange(true);
          // Brief flash effect, then clear
          setTimeout(() => setIsResettingDateRange(false), 150);
        }

        // Now we're selecting - no longer have a complete range
        hadCompleteRangeRef.current = false;
        isSelectingEndDateRef.current = true;
        pendingStartDateRef.current = clickedIso;
        setHoveredDate(null);

        // Update draft to show only start date selected - explicitly clear end_date
        setTripInputsDraft((prev) => {
          const base = prev ?? toTripInputsDraft(tripInputs);
          return { ...base, start_date: clickedIso, end_date: null };
        });
      }
    },
    [tripInputs, documentStore]
  );

  // Handler for mouse enter on calendar days - shows preview of range
  // Use refs to check state since React state may be stale in callbacks
  const handleCalendarDayMouseEnter = useCallback((day: Date) => {
    // Only show preview when we're waiting for the end date
    if (isSelectingEndDateRef.current && pendingStartDateRef.current) {
      setHoveredDate(day);
    }
  }, []);

  // Clear hover when mouse leaves the calendar
  const handleCalendarMouseLeave = useCallback(() => {
    setHoveredDate(null);
  }, []);

  // Handler for calendar popover open state change
  const handleCalendarOpenChange = useCallback((open: boolean) => {
    if (open) {
      // Sync draft with current tripInputs when opening
      setTripInputsDraft((prev) => ({
        ...prev,
        start_date: tripInputs.start_date ?? null,
        end_date: tripInputs.end_date ?? null,
      }));
      setHoveredDate(null);
      // Track if we have a complete range when opening - used for reset detection
      hadCompleteRangeRef.current = Boolean(tripInputs.start_date && tripInputs.end_date);
      // Reset selection refs - any click will start fresh selection
      isSelectingEndDateRef.current = false;
      pendingStartDateRef.current = null;
    } else {
      // Calendar closed - reset refs
      isSelectingEndDateRef.current = false;
      pendingStartDateRef.current = null;
    }
    setCalendarOpen(open);
  }, [tripInputs.start_date, tripInputs.end_date]);

  // Handler for preset date ranges (quick picks)
  const handleDatePresetClick = useCallback(
    async (range: DateRange) => {
      const startIso = range.from ? format(range.from, 'yyyy-MM-dd') : null;
      const endIso = range.to ? format(range.to, 'yyyy-MM-dd') : null;

      if (!startIso || !endIso) return;

      // Update draft
      setTripInputsDraft((prev) => {
        const base = prev ?? toTripInputsDraft(tripInputs);
        return {
          ...base,
          start_date: startIso,
          end_date: endIso,
        };
      });

      // Close calendar and commit
      setCalendarOpen(false);

      const prevStartIso = tripInputs.start_date;
      const prevEndIso = tripInputs.end_date;
      const startChanged = startIso !== prevStartIso;
      const endChanged = endIso !== prevEndIso;

      if (startChanged || endChanged) {
        const updates: { start_date: string | null; end_date: string | null } = {
          start_date: startIso,
          end_date: endIso,
        };
        const success = await documentStore.commitTripInputs(updates);

        if (!success) {
          setToastMessage('Failed to update dates. Please try again.');
          return;
        }

        const startDisplay = formatDateForDisplay(startIso);
        const endDisplay = formatDateForDisplay(endIso);
        const message = `Perfect! Travel dates set: ${startDisplay} – ${endDisplay}. 📅`;
        chatPanelRef.current?.addAssistantMessage(message);
      }
    },
    [tripInputs, documentStore]
  );

  // Handler to reset dates
  const handleResetDates = useCallback(async () => {
    setTripInputsDraft((prev) => {
      const base = prev ?? toTripInputsDraft(tripInputs);
      return {
        ...base,
        start_date: null,
        end_date: null,
      };
    });

    // Also commit the reset to the store
    if (tripInputs.start_date || tripInputs.end_date) {
      await documentStore.commitTripInputs({
        start_date: null,
        end_date: null,
      });
    }
  }, [tripInputs, documentStore]);

  const handleRemoveOrigin = useCallback(async () => {
    const removedOrigin = tripInputs.origin;
    if (!removedOrigin) {
      setSelectedLocationBadge(null);
      return;
    }

    // Optimistically update via documentStore.commitTripInputs
    const success = await documentStore.commitTripInputs({ origin: null });

    if (!success) {
      setToastMessage('Failed to remove origin. Please try again.');
      return;
    }

    // Add assistant message to acknowledge the removal
    chatPanelRef.current?.addAssistantMessage(`Removed "${removedOrigin}" as your departure city. 📍`);

    setSelectedLocationBadge(null);
  }, [tripInputs.origin, documentStore]);

  const handleRemoveTravelerCount = useCallback(async () => {
    if (tripInputs.traveler_count == null) return;

    const success = await documentStore.commitTripInputs({ traveler_count: null });

    if (!success) {
      setToastMessage('Failed to clear traveler count. Please try again.');
      return;
    }

    chatPanelRef.current?.addAssistantMessage('Cleared the traveler count. 👥');
  }, [tripInputs.traveler_count, documentStore]);

  const handleRemoveBudget = useCallback(async () => {
    if (tripInputs.budget == null) return;

    const success = await documentStore.commitTripInputs({ budget: null });

    if (!success) {
      setToastMessage('Failed to clear budget. Please try again.');
      return;
    }

    chatPanelRef.current?.addAssistantMessage('Cleared the budget. 💰');
  }, [tripInputs.budget, documentStore]);

  const handleToggleMultiCity = useCallback(async () => {
    const currentIntent = tripInputs.multi_city_intent;
    // Toggle: null/separate -> multi_city, multi_city -> separate
    const newIntent = currentIntent === 'multi_city' ? 'separate' : 'multi_city';

    const success = await documentStore.commitTripInputs({ multi_city_intent: newIntent });

    if (!success) {
      setToastMessage('Failed to update trip style. Please try again.');
      return;
    }

    const message = newIntent === 'multi_city'
      ? 'Switched to one combined itinerary visiting all destinations! 🗺️'
      : 'Switched to separate trip options for each destination! 📍';
    chatPanelRef.current?.addAssistantMessage(message);
  }, [tripInputs.multi_city_intent, documentStore]);

  const handleSetOrigin = useCallback(
    async (origin: string) => {
      const trimmedOrigin = origin.trim();
      if (!trimmedOrigin) return;

      // Optimistically update via documentStore.commitTripInputs
      const success = await documentStore.commitTripInputs({ origin: trimmedOrigin });

      if (!success) {
        setToastMessage('Failed to set origin. Please try again.');
        return;
      }

      setOriginInput('');

      // Add assistant message to acknowledge
      chatPanelRef.current?.addAssistantMessage(`Set "${trimmedOrigin}" as your departure city! ✈️`);
    },
    [documentStore]
  );

  const handleRemoveDestination = useCallback(
    async (index: number) => {
      const currentDestinations = tripInputs.destinations ?? [];
      if (index < 0 || index >= currentDestinations.length) return;

      // Get the destination being removed for the chat message
      const removedDestination = currentDestinations[index];

      // Compute new destinations array
      const newDestinations = currentDestinations.filter((_, i) => i !== index);

      // If we have branches, immediately prune any that include the removed destination
      if (branches.length > 0 && removedDestination) {
        const removedLower = removedDestination.toLowerCase();
        const prunedBranches = branches.filter((branch) => {
          // Keep branches that don't include the removed destination
          const branchDestinations = branch.destinations ?? [];
          return !branchDestinations.some(
            (d) => d.toLowerCase() === removedLower
          );
        });

        // If branches were pruned, update the UI immediately
        if (prunedBranches.length !== branches.length) {
          const removedCount = branches.length - prunedBranches.length;
          setBranches(prunedBranches);

          // If all branches were removed, readyToGenerate will be computed automatically
          if (prunedBranches.length === 0) {
            setSelectedBranchId(null);
            setToastMessage(
              `Removed ${removedDestination} — your trip options were reset. Click "Generate Plan" to create new options.`
            );
          } else {
            // Some branches remain - update selection if needed
            if (selectedBranchId && !prunedBranches.find((b) => b.id === selectedBranchId)) {
              const newSelectedId = prunedBranches.find((b) => b.is_primary)?.id ?? prunedBranches[0]?.id ?? null;
              setSelectedBranchId(newSelectedId);
            }
            setToastMessage(
              `Removed ${removedDestination} — ${removedCount} trip option${removedCount > 1 ? 's were' : ' was'} updated.`
            );
          }
        }
      }

      // Optimistically update via documentStore.commitTripInputs
      // This updates the UI immediately and syncs to backend in background
      const success = await documentStore.commitTripInputs({ destinations: newDestinations });

      if (!success) {
        // Show error toast on failure (store already rolled back)
        setToastMessage('Failed to remove destination. Please try again.');
        return;
      }

      // Add assistant message to acknowledge the removal
      if (removedDestination) {
        chatPanelRef.current?.addAssistantMessage(`Removed "${removedDestination}" from your destinations. 📍`);
      }

      setSelectedLocationBadge(null);
    },
    [tripInputs.destinations, documentStore, branches, selectedBranchId]
  );

  const handleAddDestination = useCallback(
    async (destination: string) => {
      const trimmedDestination = destination.trim();
      if (!trimmedDestination) return;

      const currentDestinations = tripInputs.destinations ?? [];
      // Don't add duplicates (case-insensitive)
      if (currentDestinations.some((d) => d.toLowerCase() === trimmedDestination.toLowerCase())) {
        setDestinationInput('');
        return;
      }

      const newDestinations = [...currentDestinations, trimmedDestination];

      // Optimistically update via documentStore.commitTripInputs
      const success = await documentStore.commitTripInputs({ destinations: newDestinations });

      if (!success) {
        setToastMessage('Failed to add destination. Please try again.');
        return;
      }

      setDestinationInput('');

      // Add assistant message to acknowledge the addition
      chatPanelRef.current?.addAssistantMessage(`Added "${trimmedDestination}" to your destinations! 📍`);
    },
    [tripInputs.destinations, documentStore]
  );

  const handleAddVibe = useCallback(
    async (vibe: string) => {
      const trimmedVibe = vibe.trim().toLowerCase();
      if (!trimmedVibe) return;

      const currentVibes = tripInputs.vibes ?? [];
      // Don't add duplicates (case-insensitive)
      if (currentVibes.some((v) => v.toLowerCase() === trimmedVibe)) {
        setVibeInput('');
        return;
      }

      const newVibes = [...currentVibes, trimmedVibe];

      // Optimistically update via documentStore.commitTripInputs (like handleRemoveVibe does)
      const success = await documentStore.commitTripInputs({ vibes: newVibes });

      if (!success) {
        setToastMessage('Failed to add vibe. Please try again.');
        return;
      }

      setVibeInput('');

      // Add an assistant message to confirm the vibe was added
      chatPanelRef.current?.addAssistantMessage(`Added "${trimmedVibe}" to your trip vibes! ✨`);
    },
    [tripInputs.vibes, documentStore]
  );

  const handleRemoveVibe = useCallback(
    async (index: number) => {
      const currentVibes = tripInputs.vibes ?? [];
      if (index < 0 || index >= currentVibes.length) return;

      const removedVibe = currentVibes[index];
      const newVibes = currentVibes.filter((_, i) => i !== index);

      // Optimistically update via documentStore.commitTripInputs
      const success = await documentStore.commitTripInputs({ vibes: newVibes });

      if (!success) {
        setToastMessage('Failed to remove vibe. Please try again.');
        return;
      }

      // Add an assistant message to confirm the vibe was removed
      if (removedVibe) {
        chatPanelRef.current?.addAssistantMessage(`Removed "${removedVibe}" from your trip vibes.`);
      }
    },
    [tripInputs.vibes, documentStore]
  );

  useEffect(
    () => () => {
      abortTilesFetch();
    },
    [abortTilesFetch]
  );

  useEffect(() => {
    let timeoutId: number | null = null;

    const typeNext = (index: number) => {
      setTypedTagline(HERO_TAGLINE.slice(0, index));
      const isComplete = index === HERO_TAGLINE.length;
      const nextIndex = isComplete ? 0 : index + 1;
      const delay = isComplete ? HERO_TYPING_PAUSE_MS : HERO_TYPING_INTERVAL_MS;
      timeoutId = window.setTimeout(() => typeNext(nextIndex), delay);
    };

    typeNext(0);

    return () => {
      if (timeoutId !== null) {
        window.clearTimeout(timeoutId);
      }
    };
  }, []);

  // Helper to finalize the generating state and show branches
  const finalizeGenerating = useCallback((result: {
    tripContextId: number | null;
    branches: DocumentBranch[];
    tiles: Record<string, Tile>;
    primaryBranchId: string | null;
    tripInputs?: TripInputs | null;
    readyToGenerate?: boolean;
    response?: PlanDocumentResponse;
  } | null) => {
    if (!result) return;

    if (result.response) {
      documentStore.setFromPlanResponse(result.response);
    }

    setBranches(result.branches);
    // readyToGenerate is now computed automatically from document state and branches
    setTilesMap(result.tiles);
    setTilesBranchId(result.primaryBranchId);
    setBranchTileNotes((prev) => {
      const allowedIds = new Set(result.branches.map((b) => b.id));
      const next: Record<string, string> = {};
      allowedIds.forEach((id) => {
        if (prev[id]) next[id] = prev[id];
      });
      return next;
    });
    setBranchTileCounts((prev) => {
      const allowedIds = new Set(result.branches.map((b) => b.id));
      const next: Record<string, TileCounts> = {};
      allowedIds.forEach((id) => {
        if (prev[id]) next[id] = prev[id];
      });
      return next;
    });
    setBranchTabNotes((prev) => {
      const allowedIds = new Set(result.branches.map((b) => b.id));
      const next: Record<string, string> = {};
      allowedIds.forEach((id) => {
        if (prev[id]) next[id] = prev[id];
      });
      return next;
    });
    setBranchSelections(() => {
      const next: Record<string, TileSelection> = {};
      result.branches.forEach((branch) => {
        next[branch.id] = selectionsToTileSelection(branch.selections, result.tiles);
      });
      return next;
    });
    setSelectedBranchId(result.primaryBranchId);

    // Clear generating state
    setIsGenerating(false);
    generatingStartTimeRef.current = null;
  }, [documentStore]);

  // Cleanup timer on unmount
  useEffect(() => {
    return () => {
      if (generatingTimerRef.current) {
        clearTimeout(generatingTimerRef.current);
      }
    };
  }, []);

  const handlePlanResult = useCallback(
    (result: {
      tripContextId: number | null;
      branches: DocumentBranch[];
      tiles: Record<string, Tile>;
      primaryBranchId: string | null;
      tripInputs?: TripInputs | null;
      readyToGenerate?: boolean;
      // Pass the full response so we can update the store
      response?: PlanDocumentResponse;
    }) => {
      const hasBranchesInResult = result.branches.length > 0;

      // If we're in generating state and branches were returned, apply minimum loading time
      if (isGenerating && hasBranchesInResult && generatingStartTimeRef.current) {
        const elapsed = Date.now() - generatingStartTimeRef.current;
        const remaining = GENERATING_MIN_DURATION_MS - elapsed;

        if (remaining > 0) {
          // Wait for the minimum time, then finalize
          generatingTimerRef.current = setTimeout(() => {
            finalizeGenerating(result);
          }, remaining);
          return;
        }

        // Minimum time already passed, finalize immediately
        finalizeGenerating(result);
        return;
      }

      // Not in generating state or no branches - process normally

      // If we have a full response, update the store (single source of truth)
      if (result.response) {
        documentStore.setFromPlanResponse(result.response);
      }

      setBranches(result.branches);
      // readyToGenerate is now computed automatically from document state and branches
      setTilesMap(result.tiles);
      setTilesBranchId(result.primaryBranchId);
      setBranchTileNotes((prev) => {
        const allowedIds = new Set(result.branches.map((b) => b.id));
        const next: Record<string, string> = {};
        allowedIds.forEach((id) => {
          if (prev[id]) {
            next[id] = prev[id];
          }
        });
        return next;
      });
      setBranchTileCounts((prev) => {
        const allowedIds = new Set(result.branches.map((b) => b.id));
        const next: Record<string, TileCounts> = {};
        allowedIds.forEach((id) => {
          if (prev[id]) {
            next[id] = prev[id];
          }
        });
        return next;
      });
      setBranchTabNotes((prev) => {
        const allowedIds = new Set(result.branches.map((b) => b.id));
        const next: Record<string, string> = {};
        allowedIds.forEach((id) => {
          if (prev[id]) {
            next[id] = prev[id];
          }
        });
        return next;
      });
      setBranchSelections(() => {
        const next: Record<string, TileSelection> = {};
        result.branches.forEach((branch) => {
          next[branch.id] = selectionsToTileSelection(branch.selections, result.tiles);
        });
        return next;
      });
      setSelectedBranchId(result.primaryBranchId);

      // If we were generating but got an error (no branches), clear the generating state
      if (isGenerating && !hasBranchesInResult) {
        setIsGenerating(false);
        generatingStartTimeRef.current = null;
        if (generatingTimerRef.current) {
          clearTimeout(generatingTimerRef.current);
          generatingTimerRef.current = null;
        }
      }
    },
    [documentStore, isGenerating, finalizeGenerating]
  );

  // NOTE: Auto-refresh removed - all trip input changes now flow through chat messages
  // which trigger /v1/plan and update the store via setFromPlanResponse.
  // The store's lastConfirmedVersion tracks what the backend has confirmed.

  const buildBranchNote = useCallback(
    (
      branchId: string,
      options?: {
        tabNote?: string;
        countsOverride?: TileCounts;
        selectionOverride?: TileSelection;
      }
    ) => {
      const selectionNote = summarizeSelections(
        options?.selectionOverride ?? branchSelections[branchId]
      );
      const counts = options?.countsOverride ?? branchTileCounts[branchId];
      const countsNote = counts ? summarizeTileCounts(counts) : null;
      const tabNote = options?.tabNote ?? branchTabNotes[branchId];
      return [selectionNote, countsNote, tabNote].filter(Boolean).join(' ');
    },
    [branchSelections, branchTabNotes, branchTileCounts]
  );

  const handleTileSelection = useCallback(
    (tile: Tile) => {
      const branchId = tilesBranchId ?? selectedBranchId;
      if (!branchId) return;

      setBranchSelections((prev) => {
        const current = prev[branchId] ?? { activities: [] };
        const nextSelection: TileSelection = {
          stay: current.stay,
          flight: current.flight,
          activities: [...current.activities],
        };

        const category = resolveSelectionCategory(tile);
        let isDeselect = false;

        if (category === 'stay') {
          isDeselect = Boolean(current.stay && current.stay.id === tile.id);
          nextSelection.stay = isDeselect ? undefined : tile;
        } else if (category === 'flight') {
          isDeselect = Boolean(current.flight && current.flight.id === tile.id);
          nextSelection.flight = isDeselect ? undefined : tile;
        } else {
          const existingIdx = nextSelection.activities.findIndex(
            (activity) => activity.id === tile.id
          );
          if (existingIdx >= 0) {
            isDeselect = true;
            nextSelection.activities.splice(existingIdx, 1);
          } else {
            const pruned = nextSelection.activities.filter(
              (activity) => !activitiesOverlap(activity, tile)
            );
            nextSelection.activities = [...pruned, tile];
          }
        }

        // Sync to document store (fire-and-forget)
        const tileType = category === 'stay' ? 'stay' : category === 'flight' ? 'flight' : 'activity';
        if (isDeselect) {
          documentStore.deselectTile(branchId, tileType, tile.id).catch((err) => {
            console.error('Failed to sync tile deselection:', err);
            setToastMessage('Failed to save selection. Please try again.');
          });
        } else {
          documentStore.selectTile(branchId, tile.id, tileType).catch((err) => {
            console.error('Failed to sync tile selection:', err);
            setToastMessage('Failed to save selection. Please try again.');
          });
        }

        setBranchTileNotes((prevNotes) => ({
          ...prevNotes,
          [branchId]: buildBranchNote(branchId, { selectionOverride: nextSelection }),
        }));

        return { ...prev, [branchId]: nextSelection };
      });
    },
    [buildBranchNote, documentStore, selectedBranchId, tilesBranchId]
  );

  const describeTileSelection = useCallback((tab: TileTabKey, filteredTiles: Tile[]) => {
    const label = TAB_CONFIG[tab].label;
    if (!filteredTiles.length) {
      return `${label}: no live options yet for this branch. I will keep it flexible until new results arrive.`;
    }

    const priceValues = filteredTiles
      .map((tile) => tile.price_estimate)
      .filter((value): value is number => typeof value === 'number');
    const currency = filteredTiles.find((tile) => tile.currency)?.currency ?? '';
    const priceSummary = (() => {
      if (!priceValues.length) return '';
      const min = Math.min(...priceValues);
      const max = Math.max(...priceValues);
      const formattedMin = Math.round(min).toLocaleString();
      const formattedMax = Math.round(max).toLocaleString();
      if (min === max) return `${formattedMin} ${currency}`.trim();
      return `${formattedMin}–${formattedMax} ${currency}`.trim();
    })();

    const parts: string[] = [];
    parts.push(
      `${label} tuned: ${filteredTiles.length} option${filteredTiles.length === 1 ? '' : 's'}.`
    );
    if (priceSummary) {
      parts.push(`Price band around ${priceSummary}.`);
    }
    const highlightTitle = filteredTiles[0]?.title;
    if (highlightTitle) {
      parts.push(`Highlighting ${highlightTitle}.`);
    }

    return parts.join(' ');
  }, []);

  useEffect(() => {
    if (!tilesBranchId) return;
    const counts = countTilesByTab(tiles);
    setBranchTileCounts((prev) => ({ ...prev, [tilesBranchId]: counts }));
    setBranchTileNotes((prev) => {
      const selectionNote = summarizeSelections(branchSelections[tilesBranchId]);
      const countsNote = summarizeTileCounts(counts);
      const tabNote = branchTabNotes[tilesBranchId];
      const note = [selectionNote, countsNote, tabNote].filter(Boolean).join(' ');
      return { ...prev, [tilesBranchId]: note };
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tiles, tilesBranchId]);

  const handleTilesTabChange = useCallback(
    (tab: TileTabKey, filteredTiles: Tile[]) => {
      if (!selectedBranchId) return;
      if (!tilesBranchId || tilesBranchId !== selectedBranchId) return;
      const tabNote = describeTileSelection(tab, filteredTiles);
      setBranchTabNotes((prev) => ({ ...prev, [selectedBranchId]: tabNote }));
      setBranchTileNotes((prev) => {
        const selectionNote = summarizeSelections(branchSelections[selectedBranchId]);
        const counts = branchTileCounts[selectedBranchId];
        const countsNote = counts ? summarizeTileCounts(counts) : null;
        const note = [selectionNote, countsNote, tabNote].filter(Boolean).join(' ');
        return { ...prev, [selectedBranchId]: note };
      });
    },
    [branchSelections, branchTileCounts, describeTileSelection, selectedBranchId, tilesBranchId]
  );

  const handleBookTrip = useCallback(
    (branchId: string) => {
      const branch = branches.find((b) => b.id === branchId);
      if (!branch) {
        console.error('handleBookTrip: branch not found', branchId);
        return;
      }
      const selection = branchSelections[branchId] ?? { activities: [] };
      const payload: TripSummaryPayload = {
        branch,
        selection: {
          stay: selection.stay,
          flight: selection.flight,
          activities: selection.activities ?? [],
        },
        tiles: tilesBranchId === branchId ? tiles : [],
        note: branchTileNotes[branchId] ?? null,
        generatedAt: new Date().toISOString(),
      };
      saveTripSummary(payload);
      window.location.href = '/summary';
    },
    [branchSelections, branchTileNotes, branches, tiles, tilesBranchId]
  );

  useEffect(() => {
    const branchIds = new Set([
      ...branches.map((b) => b.id),
      ...Object.keys(branchSelections),
      ...Object.keys(branchTileCounts),
      ...Object.keys(branchTabNotes),
    ]);
    if (branchIds.size === 0) return;

    setBranchTileNotes((prev) => {
      let didChange = false;
      const next = { ...prev };
      branchIds.forEach((branchId) => {
        const note = buildBranchNote(branchId);
        if (note) {
          if (next[branchId] !== note) {
            next[branchId] = note;
            didChange = true;
          }
        } else if (next[branchId]) {
          delete next[branchId];
          didChange = true;
        }
      });
      Object.keys(next).forEach((branchId) => {
        if (!branchIds.has(branchId)) {
          delete next[branchId];
          didChange = true;
        }
      });
      return didChange ? next : prev;
    });
  }, [branchSelections, branches, branchTabNotes, branchTileCounts, buildBranchNote]);

  // Handler for when generate plan is triggered - starts the loading screen
  const handleGeneratePlanStart = useCallback(() => {
    setIsGenerating(true);
    generatingStartTimeRef.current = Date.now();
    // Clear any existing timer
    if (generatingTimerRef.current) {
      clearTimeout(generatingTimerRef.current);
      generatingTimerRef.current = null;
    }
  }, []);

  const showResults = branches.length > 0;
  const hasBranchesReady = branches.length > 0;
  const missingFields = tripInputs.missing_fields ?? [];
  const formatTravelers = (value?: number | null) =>
    value != null ? `${value} traveler${value === 1 ? '' : 's'}` : null;
  const draftBase = tripInputsDraft ?? toTripInputsDraft(tripInputs);

  // Check if we have origin or destination to show route
  const hasOrigin = Boolean(tripInputs.origin);
  const hasDestination = (tripInputs.destinations ?? []).length > 0;

  // Check if we have dates to show
  const hasStartDate = Boolean(tripInputs.start_date);
  const hasEndDate = Boolean(tripInputs.end_date);
  const hasDates = hasStartDate || hasEndDate;

  // Parse dates for calendar - use draft state when calendar is open for smoother selection
  const calendarStartDate = (calendarOpen ? tripInputsDraft.start_date : tripInputs.start_date)
    ? parse((calendarOpen ? tripInputsDraft.start_date : tripInputs.start_date)!, 'yyyy-MM-dd', new Date())
    : undefined;
  const calendarEndDate = (calendarOpen ? tripInputsDraft.end_date : tripInputs.end_date)
    ? parse((calendarOpen ? tripInputsDraft.end_date : tripInputs.end_date)!, 'yyyy-MM-dd', new Date())
    : undefined;
  // When resetting, briefly show no selection for visual feedback
  const selectedDateRange: DateRange | undefined =
    isResettingDateRange
      ? undefined
      : calendarStartDate || calendarEndDate
        ? { from: calendarStartDate, to: calendarEndDate }
        : undefined;

  // Compute preview days for hover effect (days between start and hovered date)
  const previewDays = useMemo(() => {
    if (!calendarStartDate || !hoveredDate || calendarEndDate) {
      return [];
    }
    // Create interval between start and hovered date
    const start = calendarStartDate;
    const end = hoveredDate;
    if (isBefore(end, start)) {
      return eachDayOfInterval({ start: end, end: start });
    }
    return eachDayOfInterval({ start, end });
  }, [calendarStartDate, calendarEndDate, hoveredDate]);

  // Validation: check if dates are in the past
  const today = startOfDay(new Date());
  const isStartDatePast = calendarStartDate && isBefore(calendarStartDate, today);
  const isEndDatePast = calendarEndDate && isBefore(calendarEndDate, today);
  const hasDateValidationWarning = isStartDatePast || isEndDatePast;

  // Always show trip details once user has chatted - grid layout with label + input per field
  const tripDetailsContent = (
    <div className="flex flex-wrap items-start gap-x-3 gap-y-2">
      {/* From field */}
      <div className="flex flex-col gap-1">
        <div className={`flex items-center gap-1 text-xs transition-colors ${isFieldComplete('origin', tripInputs) ? 'text-accent' : 'text-muted-foreground/60'}`}>
          {isFieldComplete('origin', tripInputs) ? <CheckCircle2 className="h-3 w-3" /> : <Circle className="h-3 w-3" />}
          <span className={isFieldComplete('origin', tripInputs) ? 'font-medium' : ''}>{FIELD_LABELS.origin}</span>
        </div>
        {hasOrigin ? (
          <div
            className="border-border/60 bg-muted/40 inline-flex items-center gap-1 rounded-full border px-2.5 py-1.5"
            onClick={() => setSelectedLocationBadge(null)}
            onKeyDown={() => {}}
            role="presentation"
          >
            <LocationBadge
              type="origin"
              value={tripInputs.origin!}
              isOrigin
              isSelected={selectedLocationBadge === 'origin'}
              onSelect={setSelectedLocationBadge}
              onRemove={handleRemoveOrigin}
            />
          </div>
        ) : originInputExpanded ? (
          <form
            onSubmit={(e) => {
              e.preventDefault();
              handleSetOrigin(originInput);
              setOriginInputExpanded(false);
            }}
            className="inline-flex items-center"
          >
            <input
              type="text"
              value={originInput}
              onChange={(e) => setOriginInput(e.target.value)}
              placeholder="Enter city..."
              className="w-28 rounded-full border border-primary/30 bg-primary/5 px-3 py-1.5 text-xs placeholder:text-muted-foreground/50 focus:border-primary/50 focus:outline-none focus:ring-1 focus:ring-primary/30 transition-all"
              autoFocus
              onBlur={() => {
                setTimeout(() => {
                  if (!originInput.trim()) {
                    setOriginInputExpanded(false);
                  }
                }, 150);
              }}
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  e.preventDefault();
                  handleSetOrigin(originInput);
                  setOriginInputExpanded(false);
                } else if (e.key === 'Escape') {
                  e.preventDefault();
                  setOriginInput('');
                  setOriginInputExpanded(false);
                }
              }}
            />
            {originInput.trim() && (
              <button
                type="submit"
                className="ml-1 flex h-6 w-6 items-center justify-center rounded-full bg-primary text-white hover:bg-primary/90 transition-colors"
                aria-label="Set origin"
              >
                <Plus className="h-3.5 w-3.5" />
              </button>
            )}
          </form>
        ) : (
          <div
            className="border-border/40 bg-muted/20 hover:border-primary/40 hover:bg-primary/5 inline-flex cursor-pointer items-center gap-1.5 rounded-full border border-dashed px-2.5 py-1.5 transition-colors"
            onClick={() => setOriginInputExpanded(true)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                setOriginInputExpanded(true);
              }
            }}
            role="button"
            tabIndex={0}
          >
            <MapPin className="h-3 w-3 text-muted-foreground/40" />
            <span className="text-xs text-muted-foreground/60 italic">Click to set</span>
          </div>
        )}
      </div>

      {/* Where to field */}
      <div className="group flex flex-col gap-1">
        <div className={`flex items-center gap-1 text-xs transition-colors ${isFieldComplete('destinations', tripInputs) ? 'text-accent' : 'text-muted-foreground/60'}`}>
          {isFieldComplete('destinations', tripInputs) ? <CheckCircle2 className="h-3 w-3" /> : <Circle className="h-3 w-3" />}
          <span className={isFieldComplete('destinations', tripInputs) ? 'font-medium' : ''}>{FIELD_LABELS.destinations}</span>
        </div>
        {hasDestination ? (
          <div className="inline-flex items-center">
            <div
              className="border-border/60 bg-muted/40 inline-flex flex-wrap items-center gap-1 rounded-full border px-2.5 py-1.5"
              onClick={() => setSelectedLocationBadge(null)}
              onKeyDown={() => {}}
              role="presentation"
            >
              {(tripInputs.destinations ?? []).map((dest, idx) => (
                <LocationBadge
                  key={`dest-${idx}`}
                  type="destination"
                  index={idx}
                  value={dest}
                  isSelected={selectedLocationBadge === idx}
                  onSelect={setSelectedLocationBadge}
                  onRemove={() => handleRemoveDestination(idx)}
                />
              ))}
            </div>
            {/* Add destination button / input */}
            {destinationInputExpanded ? (
              <form
                onSubmit={(e) => {
                  e.preventDefault();
                  handleAddDestination(destinationInput);
                  setDestinationInputExpanded(false);
                }}
                className="inline-flex items-center ml-1.5"
              >
                <input
                  type="text"
                  value={destinationInput}
                  onChange={(e) => setDestinationInput(e.target.value)}
                  placeholder="Add destination..."
                  className="w-28 rounded-full border border-primary/30 bg-primary/5 px-3 py-1.5 text-xs placeholder:text-muted-foreground/50 focus:border-primary/50 focus:outline-none focus:ring-1 focus:ring-primary/30 transition-all"
                  autoFocus
                  onBlur={() => {
                    setTimeout(() => {
                      if (!destinationInput.trim()) {
                        setDestinationInputExpanded(false);
                      }
                    }, 150);
                  }}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') {
                      e.preventDefault();
                      handleAddDestination(destinationInput);
                      setDestinationInputExpanded(false);
                    } else if (e.key === 'Escape') {
                      e.preventDefault();
                      setDestinationInput('');
                      setDestinationInputExpanded(false);
                    }
                  }}
                />
                {destinationInput.trim() && (
                  <button
                    type="submit"
                    className="ml-1 flex h-6 w-6 items-center justify-center rounded-full bg-primary text-white hover:bg-primary/90 transition-colors"
                    aria-label="Add destination"
                  >
                    <Plus className="h-3.5 w-3.5" />
                  </button>
                )}
              </form>
            ) : (
              <button
                type="button"
                onClick={() => setDestinationInputExpanded(true)}
                className="-ml-2 flex h-6 w-6 items-center justify-center rounded-full border border-dashed border-primary/40 bg-card text-primary/60 hover:border-primary/60 hover:bg-primary/10 hover:text-primary transition-all opacity-0 group-hover:opacity-100 shadow-sm"
                aria-label="Add destination"
                title="Add another destination"
              >
                <Plus className="h-3 w-3" />
              </button>
            )}
          </div>
        ) : destinationInputExpanded ? (
          <form
            onSubmit={(e) => {
              e.preventDefault();
              handleAddDestination(destinationInput);
              setDestinationInputExpanded(false);
            }}
            className="inline-flex items-center"
          >
            <input
              type="text"
              value={destinationInput}
              onChange={(e) => setDestinationInput(e.target.value)}
              placeholder="Enter destination..."
              className="w-28 rounded-full border border-primary/30 bg-primary/5 px-3 py-1.5 text-xs placeholder:text-muted-foreground/50 focus:border-primary/50 focus:outline-none focus:ring-1 focus:ring-primary/30 transition-all"
              autoFocus
              onBlur={() => {
                setTimeout(() => {
                  if (!destinationInput.trim()) {
                    setDestinationInputExpanded(false);
                  }
                }, 150);
              }}
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  e.preventDefault();
                  handleAddDestination(destinationInput);
                  setDestinationInputExpanded(false);
                } else if (e.key === 'Escape') {
                  e.preventDefault();
                  setDestinationInput('');
                  setDestinationInputExpanded(false);
                }
              }}
            />
            {destinationInput.trim() && (
              <button
                type="submit"
                className="ml-1 flex h-6 w-6 items-center justify-center rounded-full bg-primary text-white hover:bg-primary/90 transition-colors"
                aria-label="Add destination"
              >
                <Plus className="h-3.5 w-3.5" />
              </button>
            )}
          </form>
        ) : (
          <div
            className="border-border/40 bg-muted/20 hover:border-primary/40 hover:bg-primary/5 inline-flex cursor-pointer items-center gap-1.5 rounded-full border border-dashed px-2.5 py-1.5 transition-colors"
            onClick={() => setDestinationInputExpanded(true)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                setDestinationInputExpanded(true);
              }
            }}
            role="button"
            tabIndex={0}
          >
            <MapPin className="h-3 w-3 text-muted-foreground/40" />
            <span className="text-xs text-muted-foreground/60 italic">Click to set</span>
          </div>
        )}
      </div>

      {/* Multi-city toggle (only shown when 2+ destinations) */}
      {(tripInputs.destinations ?? []).length >= 2 && (
        <div className="flex flex-col gap-1">
          <div className={`flex items-center gap-1 text-xs transition-colors ${isFieldComplete('multi_city_intent', tripInputs) ? 'text-accent' : 'text-muted-foreground/40'}`}>
            {isFieldComplete('multi_city_intent', tripInputs) ? <CheckCircle2 className="h-3 w-3" /> : <Circle className="h-3 w-3 opacity-60" strokeDasharray="2 2" />}
            <span className={isFieldComplete('multi_city_intent', tripInputs) ? 'font-medium' : ''}>{FIELD_LABELS.multi_city_intent}</span>
            {!isFieldComplete('multi_city_intent', tripInputs) && <span className="text-[10px] text-muted-foreground/40">(optional)</span>}
          </div>
          <button
            type="button"
            onClick={handleToggleMultiCity}
            className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1.5 cursor-pointer transition-colors ${
              tripInputs.multi_city_intent === 'multi_city'
                ? 'border-accent/40 bg-accent/10 text-accent'
                : 'border-border/60 bg-muted/40 text-foreground'
            }`}
          >
            <Route className="h-3.5 w-3.5" />
            <span className="text-xs font-semibold">
              {tripInputs.multi_city_intent === 'multi_city' ? 'One itinerary' : 'Separate options'}
            </span>
          </button>
        </div>
      )}

      {/* Dates field */}
      <div className="flex flex-col gap-1">
        <div className={`flex items-center gap-1 text-xs transition-colors ${isFieldComplete('dates', tripInputs) ? 'text-accent' : 'text-muted-foreground/60'}`}>
          {isFieldComplete('dates', tripInputs) ? <CheckCircle2 className="h-3 w-3" /> : <Circle className="h-3 w-3" />}
          <span className={isFieldComplete('dates', tripInputs) ? 'font-medium' : ''}>{FIELD_LABELS.dates}</span>
        </div>
        {hasDates ? (
          <Popover open={calendarOpen} onOpenChange={handleCalendarOpenChange}>
            <PopoverTrigger asChild>
              <div
                className={`inline-flex cursor-pointer items-center gap-1.5 rounded-full border px-2.5 py-1.5 transition-colors ${
                  hasDateValidationWarning
                    ? 'border-orange-400/60 bg-orange-50 hover:bg-orange-100'
                    : 'border-border/60 bg-muted/40 hover:bg-muted/60'
                }`}
                role="button"
                tabIndex={0}
                title={hasDateValidationWarning ? 'One or more dates are in the past' : undefined}
              >
                {hasDateValidationWarning ? (
                  <AlertCircle className="h-3.5 w-3.5 shrink-0 text-orange-500" />
                ) : (
                  <CalendarRange className="text-muted-foreground h-3.5 w-3.5 shrink-0" />
                )}
                <span className={`whitespace-nowrap text-xs font-semibold ${hasDateValidationWarning ? 'text-orange-700' : 'text-foreground'}`}>
                  {hasStartDate && formatDateForDisplay(tripInputs.start_date)}
                  {hasStartDate && hasEndDate && ' – '}
                  {hasEndDate && formatDateForDisplay(tripInputs.end_date)}
                </span>
              </div>
            </PopoverTrigger>
            <PopoverContent className="w-auto p-0" align="start">
              <div className="flex">
                {/* Quick preset buttons */}
                <div className="flex flex-col gap-1 border-r border-border/60 p-2">
                  <span className="px-2 pb-1 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
                    Quick picks
                  </span>
                  {DATE_PRESETS.map((preset) => (
                    <button
                      key={preset.label}
                      type="button"
                      onClick={() => handleDatePresetClick(preset.getDates())}
                      className="whitespace-nowrap rounded-md px-3 py-1.5 text-left text-xs font-medium text-foreground hover:bg-muted transition-colors"
                    >
                      {preset.label}
                    </button>
                  ))}
                  {/* Reset button to clear dates and allow re-selection */}
                  {(calendarStartDate || calendarEndDate) && (
                    <>
                      <div className="my-1 border-t border-border/40" />
                      <button
                        type="button"
                        onClick={handleResetDates}
                        className="whitespace-nowrap rounded-md px-3 py-1.5 text-left text-xs font-medium text-muted-foreground hover:bg-muted hover:text-foreground transition-colors"
                      >
                        Reset dates
                      </button>
                    </>
                  )}
                </div>
                <div onMouseLeave={handleCalendarMouseLeave}>
                  <Calendar
                    mode="range"
                    defaultMonth={calendarStartDate ?? new Date()}
                    selected={selectedDateRange}
                    onSelect={handleCalendarSelect}
                    onDayClick={handleCalendarDayClick}
                    onDayMouseEnter={handleCalendarDayMouseEnter}
                    numberOfMonths={2}
                    disabled={{ before: new Date() }}
                    modifiers={{ preview: previewDays }}
                    modifiersClassNames={{ preview: 'bg-muted/50' }}
                  />
                </div>
              </div>
            </PopoverContent>
          </Popover>
        ) : (
          <Popover open={calendarOpen} onOpenChange={handleCalendarOpenChange}>
            <PopoverTrigger asChild>
              <div
                className="border-border/40 bg-muted/20 hover:border-primary/40 hover:bg-primary/5 inline-flex cursor-pointer items-center gap-1.5 rounded-full border border-dashed px-2.5 py-1.5 transition-colors"
                role="button"
                tabIndex={0}
              >
                <CalendarRange className="h-3.5 w-3.5 text-muted-foreground/40" />
                <span className="text-xs text-muted-foreground/60 italic">Click to set</span>
              </div>
            </PopoverTrigger>
            <PopoverContent className="w-auto p-0" align="start">
              <div className="flex">
                {/* Quick preset buttons */}
                <div className="flex flex-col gap-1 border-r border-border/60 p-2">
                  <span className="px-2 pb-1 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
                    Quick picks
                  </span>
                  {DATE_PRESETS.map((preset) => (
                    <button
                      key={preset.label}
                      type="button"
                      onClick={() => handleDatePresetClick(preset.getDates())}
                      className="whitespace-nowrap rounded-md px-3 py-1.5 text-left text-xs font-medium text-foreground hover:bg-muted transition-colors"
                    >
                      {preset.label}
                    </button>
                  ))}
                </div>
                <div onMouseLeave={handleCalendarMouseLeave}>
                  <Calendar
                    mode="range"
                    defaultMonth={new Date()}
                    selected={selectedDateRange}
                    onSelect={handleCalendarSelect}
                    onDayClick={handleCalendarDayClick}
                    onDayMouseEnter={handleCalendarDayMouseEnter}
                    numberOfMonths={2}
                    disabled={{ before: new Date() }}
                    modifiers={{ preview: previewDays }}
                    modifiersClassNames={{ preview: 'bg-muted/50' }}
                  />
                </div>
              </div>
            </PopoverContent>
          </Popover>
        )}
      </div>

      {/* Travelers field (optional) */}
      <div className="flex flex-col gap-1">
        <div className={`flex items-center gap-1 text-xs transition-colors ${isFieldComplete('traveler_count', tripInputs) ? 'text-accent' : 'text-muted-foreground/40'}`}>
          {isFieldComplete('traveler_count', tripInputs) ? <CheckCircle2 className="h-3 w-3" /> : <Circle className="h-3 w-3 opacity-60" strokeDasharray="2 2" />}
          <span className={isFieldComplete('traveler_count', tripInputs) ? 'font-medium' : ''}>{FIELD_LABELS.traveler_count}</span>
          {!isFieldComplete('traveler_count', tripInputs) && <span className="text-[10px] text-muted-foreground/40">(optional)</span>}
        </div>
        {(() => {
          const field = 'traveler_count' as const;
          const isEditing = editingField === field;
          const draftValueRaw = draftBase ? draftBase[field] : '';
          const draftValue = draftValueRaw == null ? '' : String(draftValueRaw);
          const displayValue = tripInputs.traveler_count != null ? (formatTravelers(tripInputs.traveler_count) ?? '') : '';
          const hasValue = tripInputs.traveler_count != null;
          return (
            <div className="group relative inline-flex">
              <div
                className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1.5 cursor-pointer transition-colors ${
                  hasValue
                    ? `border-border/60 bg-muted/40 ${isEditing ? 'ring-primary ring-1' : ''}`
                    : 'border-border/40 bg-muted/20 border-dashed hover:border-primary/40 hover:bg-primary/5'
                }`}
                role="button"
                tabIndex={0}
                onClick={() => handleStartEditingField(field)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    handleStartEditingField(field);
                  }
                }}
              >
                <span className={hasValue ? 'text-muted-foreground shrink-0' : 'shrink-0'}><Users className={`h-3.5 w-3.5 ${hasValue ? '' : 'text-muted-foreground/40'}`} /></span>
                {isEditing ? (
                  <input
                    type="number"
                    value={draftValue}
                    onChange={(e) => handleFieldChange(field, e.target.value)}
                    className="text-foreground placeholder:text-muted-foreground w-16 bg-transparent text-xs font-semibold focus:outline-none"
                    placeholder="#"
                    onClick={(e) => e.stopPropagation()}
                    onBlur={(e) => handleCommitField(field, e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') {
                        e.preventDefault();
                        handleCommitField(field, (e.target as HTMLInputElement).value);
                      } else if (e.key === 'Escape') {
                        e.preventDefault();
                        const originalValue = tripInputs.traveler_count;
                        setTripInputsDraft((prev) =>
                          prev ? { ...prev, traveler_count: originalValue != null ? String(originalValue) : null } : prev
                        );
                        setEditingField(null);
                      }
                    }}
                    autoFocus
                  />
                ) : hasValue ? (
                  <span className="text-foreground whitespace-nowrap text-xs font-semibold">
                    {displayValue}
                  </span>
                ) : (
                  <span className="text-xs text-muted-foreground/60 italic">Click to set</span>
                )}
              </div>
              {hasValue && !isEditing && (
                <button
                  type="button"
                  onClick={(e) => { e.stopPropagation(); handleRemoveTravelerCount(); }}
                  className="absolute -right-1 -top-1 flex h-3.5 w-3.5 items-center justify-center rounded-full bg-gray-500 text-white opacity-0 transition-opacity hover:bg-gray-600 group-hover:opacity-70"
                  aria-label="Clear traveler count"
                >
                  <X className="h-2.5 w-2.5" />
                </button>
              )}
            </div>
          );
        })()}
      </div>

      {/* Budget field (optional) */}
      <div className="flex flex-col gap-1">
        <div className={`flex items-center gap-1 text-xs transition-colors ${isFieldComplete('budget', tripInputs) ? 'text-accent' : 'text-muted-foreground/40'}`}>
          {isFieldComplete('budget', tripInputs) ? <CheckCircle2 className="h-3 w-3" /> : <Circle className="h-3 w-3 opacity-60" strokeDasharray="2 2" />}
          <span className={isFieldComplete('budget', tripInputs) ? 'font-medium' : ''}>{FIELD_LABELS.budget}</span>
          {!isFieldComplete('budget', tripInputs) && <span className="text-[10px] text-muted-foreground/40">(optional)</span>}
        </div>
        {(() => {
          const field = 'budget' as const;
          const isEditing = editingField === field;
          const draftValueRaw = draftBase ? draftBase[field] : '';
          const draftValue = draftValueRaw == null ? '' : String(draftValueRaw);
          const displayValue = tripInputs.budget != null ? formatBudgetValue(tripInputs.budget) : '';
          const hasValue = tripInputs.budget != null;
          return (
            <div className="group relative inline-flex">
              <div
                className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1.5 cursor-pointer transition-colors ${
                  hasValue
                    ? `border-border/60 bg-muted/40 ${isEditing ? 'ring-primary ring-1' : ''}`
                    : 'border-border/40 bg-muted/20 border-dashed hover:border-primary/40 hover:bg-primary/5'
                }`}
                role="button"
                tabIndex={0}
                onClick={() => handleStartEditingField(field)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    handleStartEditingField(field);
                  }
                }}
              >
                <span className={hasValue ? 'text-muted-foreground shrink-0' : 'shrink-0'}><Wallet className={`h-3.5 w-3.5 ${hasValue ? '' : 'text-muted-foreground/40'}`} /></span>
                {isEditing ? (
                  <input
                    type="number"
                    value={draftValue}
                    onChange={(e) => handleFieldChange(field, e.target.value)}
                    className="text-foreground placeholder:text-muted-foreground w-16 bg-transparent text-xs font-semibold focus:outline-none"
                    placeholder="$"
                    onClick={(e) => e.stopPropagation()}
                    onBlur={(e) => handleCommitField(field, e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') {
                        e.preventDefault();
                        handleCommitField(field, (e.target as HTMLInputElement).value);
                      } else if (e.key === 'Escape') {
                        e.preventDefault();
                        const originalValue = tripInputs.budget;
                        setTripInputsDraft((prev) =>
                          prev ? { ...prev, budget: originalValue != null ? String(originalValue) : null } : prev
                        );
                        setEditingField(null);
                      }
                    }}
                    autoFocus
                  />
                ) : hasValue ? (
                  <span className="text-foreground whitespace-nowrap text-xs font-semibold">
                    {displayValue}
                  </span>
                ) : (
                  <span className="text-xs text-muted-foreground/60 italic">Click to set</span>
                )}
              </div>
              {hasValue && !isEditing && (
                <button
                  type="button"
                  onClick={(e) => { e.stopPropagation(); handleRemoveBudget(); }}
                  className="absolute -right-1 -top-1 flex h-3.5 w-3.5 items-center justify-center rounded-full bg-gray-500 text-white opacity-0 transition-opacity hover:bg-gray-600 group-hover:opacity-70"
                  aria-label="Clear budget"
                >
                  <X className="h-2.5 w-2.5" />
                </button>
              )}
            </div>
          );
        })()}
      </div>
    </div>
  );

  // Vibes section content - separate collapsible
  const vibesContent = (
    <div className="flex flex-wrap items-center gap-1.5">
      {(tripInputs.vibes ?? []).map((vibe, idx) => (
        <span
          key={`vibe-${idx}`}
          className="group relative inline-flex cursor-pointer items-center gap-1 rounded-full border border-accent/30 bg-accent/10 px-2.5 py-1.5 text-xs font-semibold transition-all hover:bg-accent/20"
        >
          <Sparkles className="h-3 w-3 text-accent" />
          {vibe}
          <button
            type="button"
            onClick={() => handleRemoveVibe(idx)}
            className="absolute -right-1 -top-1 flex h-3.5 w-3.5 items-center justify-center rounded-full bg-gray-500 text-white opacity-0 transition-opacity hover:bg-gray-600 group-hover:opacity-70"
            aria-label={`Remove ${vibe}`}
          >
            <X className="h-2.5 w-2.5" />
          </button>
        </span>
      ))}
      {/* Plus button or expanded input */}
      {vibeInputExpanded ? (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            handleAddVibe(vibeInput);
            setVibeInputExpanded(false);
          }}
          className="inline-flex items-center"
        >
          <input
            type="text"
            value={vibeInput}
            onChange={(e) => setVibeInput(e.target.value)}
            placeholder="Type a vibe..."
            className="w-32 rounded-full border border-accent/30 bg-accent/5 px-3 py-1.5 text-xs placeholder:text-muted-foreground/50 focus:border-accent/50 focus:outline-none focus:ring-1 focus:ring-accent/30 transition-all"
            autoFocus
            onBlur={() => {
              // Collapse if empty after a short delay (allows click on submit to work)
              setTimeout(() => {
                if (!vibeInput.trim()) {
                  setVibeInputExpanded(false);
                }
              }, 150);
            }}
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                e.preventDefault();
                handleAddVibe(vibeInput);
                setVibeInputExpanded(false);
              } else if (e.key === 'Escape') {
                e.preventDefault();
                setVibeInput('');
                setVibeInputExpanded(false);
              }
            }}
          />
          {vibeInput.trim() && (
            <button
              type="submit"
              className="ml-1 flex h-6 w-6 items-center justify-center rounded-full bg-accent text-white hover:bg-accent/90 transition-colors"
              aria-label="Add vibe"
            >
              <Plus className="h-3.5 w-3.5" />
            </button>
          )}
        </form>
      ) : (
        <button
          type="button"
          onClick={() => setVibeInputExpanded(true)}
          className="flex h-7 w-7 items-center justify-center rounded-full border border-dashed border-accent/40 bg-accent/5 text-accent/60 hover:border-accent/60 hover:bg-accent/10 hover:text-accent transition-all"
          aria-label="Add vibe"
          title={(tripInputs.vibes ?? []).length === 0 ? "What's the vibe? Adventure, F1, relaxation..." : "Add another vibe"}
        >
          <Plus className="h-4 w-4" />
        </button>
      )}
    </div>
  );

  // Chat panel content that can be reused in both layouts
  const chatPanelContent = (fullHeight = false) => (
    <div className={fullHeight ? 'flex h-full min-h-0 flex-col' : ''}>
      <div className={fullHeight ? 'min-h-0 flex-1' : ''}>
        <ChatPanel
          ref={chatPanelRef}
          key={chatKey}
          selectedBranchId={selectedBranchId}
          onPlanResult={handlePlanResult}
          onGeneratePlanStart={handleGeneratePlanStart}
          onFreshStart={handleStartNewSession}
          tripDetails={
            tripDetailsContent
              ? { content: tripDetailsContent, missingFields }
              : undefined
          }
          vibesSection={vibesContent ? { content: vibesContent } : undefined}
          fullHeight={fullHeight}
          hasBranches={hasBranchesReady}
          readyToGenerate={readyToGenerate}
        />
      </div>
    </div>
  );

  // Branch panel content
  const branchPanelContent = (
    <Card className="from-primary/10 via-card/95 to-background relative overflow-hidden border-none bg-gradient-to-br shadow-xl backdrop-blur">
      <div className="bg-primary/25 pointer-events-none absolute -left-20 -top-24 h-48 w-48 rounded-full blur-3xl" />
      <div className="bg-accent/15 pointer-events-none absolute bottom-0 right-0 h-40 w-40 rounded-full blur-3xl" />
      <div className="relative flex flex-wrap items-start justify-between gap-4 px-5 py-4">
        <div className="space-y-1">
          <h3 className="text-foreground font-display text-xl font-bold">
            Explore each suggestion and its booking options in one sweep
          </h3>
          <p className="text-muted-foreground text-sm">
            Branch cards now stretch across the page and carry tiles with them.
          </p>
        </div>
        {branches.length > 0 ? (
          <div className="text-muted-foreground text-xs font-semibold uppercase tracking-wide">
            {branches.length} suggestion{branches.length === 1 ? '' : 's'} ready
          </div>
        ) : null}
      </div>
      <CardContent className="relative overflow-hidden">
        {isHydratingSnapshot && branches.length === 0 ? (
          <p className="text-muted-foreground text-sm">Restoring your last session…</p>
        ) : branches.length === 0 ? (
          <p className="text-muted-foreground text-sm">
            Start chatting to generate suggestions for you.
          </p>
        ) : (
          <BranchPanel
            branches={branchesWithTileNotes}
            selectedBranchId={selectedBranchId}
            onBranchSelect={handleBranchSelect}
            branchTileCounts={branchTileCounts}
            branchSelections={branchSelections}
            tiles={tiles}
            tilesBranchId={tilesBranchId}
            selectedTiles={activeBranchSelection}
            onTileToggle={handleTileSelection}
            onTilesTabChange={handleTilesTabChange}
            onBookTrip={handleBookTrip}
            canBookTrip={missingFields.length === 0}
            tripInputs={tripInputs}
          />
        )}
      </CardContent>
    </Card>
  );

  return (
    <div className="bg-background text-foreground min-h-screen">
      {toastMessage && (
        <div className="border-border/60 bg-card/95 text-foreground fixed right-4 top-4 z-50 flex items-start gap-3 rounded-lg border px-4 py-3 text-sm shadow-lg">
          <span>{toastMessage}</span>
          <button
            type="button"
            className="text-primary text-xs font-semibold uppercase tracking-wide"
            onClick={() => setToastMessage(null)}
          >
            Dismiss
          </button>
        </div>
      )}

      {/* Split layout when generating or branches are ready */}
      {(isGenerating || hasBranchesReady) ? (
        <div className="flex min-h-screen">
          {/* Left sidebar - Chat Panel (25% width, sticky) */}
          <motion.div
            initial={{ x: '-100%', opacity: 0 }}
            animate={{ x: 0, opacity: 1 }}
            transition={{ duration: 0.5, ease: 'easeOut' }}
            className="no-scrollbar fixed left-0 top-0 z-40 h-screen w-1/4 min-w-[320px] overflow-y-auto border-r border-white/10 bg-gradient-to-b from-black/90 via-black/80 to-black/90 shadow-2xl"
          >
            <div className="flex h-full flex-col p-4">
              {/* Header */}
              <header className="mb-4 flex items-center justify-between text-white">
                <div className="flex items-center gap-2">
                  <Compass className="h-5 w-5" />
                  <span className="font-display text-lg font-bold tracking-tight">
                    Nomadic
                  </span>
                </div>
                <div className="flex items-center gap-2">
                  <Button
                    variant="ghost"
                    size="icon"
                    type="button"
                    className="h-8 w-8 text-white hover:bg-white/10"
                  >
                    <User className="h-4 w-4" />
                  </Button>
                  <Button
                    variant="ghost"
                    size="icon"
                    type="button"
                    className="h-8 w-8 text-white hover:bg-white/10"
                  >
                    <Menu className="h-4 w-4" />
                  </Button>
                </div>
              </header>
              {/* Chat Panel */}
              <div className="flex-1 overflow-hidden">
                <Card className="bg-card/95 flex h-full flex-col border-white/20 shadow-xl backdrop-blur">
                  <CardContent className="flex h-full min-h-0 flex-col p-3">
                    {chatPanelContent(true)}
                  </CardContent>
                </Card>
              </div>
            </div>
          </motion.div>

          {/* Right content - Loader or Branches (75% width, with left margin for fixed sidebar) */}
          <motion.div
            initial={{ x: '100%', opacity: 0 }}
            animate={{ x: 0, opacity: 1 }}
            transition={{ duration: 0.5, ease: 'easeOut', delay: 0.1 }}
            className="ml-[25%] min-w-0 flex-1"
            style={{ marginLeft: 'max(25%, 320px)' }}
          >
            <div className="min-h-screen">
              {/* Hero section (condensed) */}
              <div className="relative overflow-hidden">
                <div className="absolute inset-0">
                  <div className="flex h-full w-full">
                    <div className="h-full w-1/2">
                      <img
                        src={HERO_IMAGE}
                        alt="Nomadic hero"
                        className="h-full w-full object-cover"
                      />
                    </div>
                    <div className="h-full w-1/2">
                      <video
                        className="h-full w-full object-cover"
                        src={HERO_VIDEO}
                        poster={HERO_IMAGE}
                        autoPlay
                        loop
                        muted
                        playsInline
                        aria-hidden="true"
                      />
                    </div>
                  </div>
                  <div className="to-background absolute inset-0 bg-gradient-to-b from-black/65 via-black/35" />
                </div>
                <div className="relative z-10 px-6 py-8">
                  <div className="space-y-2 text-white">
                    <h1
                      className="font-display text-3xl font-bold leading-tight"
                      aria-label={`Roam freely. ${HERO_TAGLINE}`}
                    >
                      Roam freely. <span className="text-accent">{typedTagline}</span>
                    </h1>
                  </div>
                </div>
              </div>

              {/* Show loader when generating, branches when ready */}
              <section className="bg-background px-6 pb-14 pt-6">
                {isGenerating && !hasBranchesReady ? (
                  <motion.div
                    key="generating-loader"
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    exit={{ opacity: 0 }}
                    transition={{ duration: 0.5 }}
                  >
                    <GeneratingLoader />
                  </motion.div>
                ) : (
                  <motion.div
                    key="branch-panel"
                    initial={{ opacity: 0, y: 20 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ duration: 0.5, ease: 'easeOut' }}
                  >
                    {branchPanelContent}
                  </motion.div>
                )}
              </section>

              <Footer />
            </div>
          </motion.div>
        </div>
      ) : (
        /* Original centered layout when no branches */
        <>
          <div className="relative overflow-hidden">
            <div className="absolute inset-0">
              <div className="flex h-full w-full">
                <div className="h-full w-1/2">
                  <img
                    src={HERO_IMAGE}
                    alt="Nomadic hero"
                    className="h-full w-full object-cover"
                  />
                </div>
                <div className="h-full w-1/2">
                  <video
                    className="h-full w-full object-cover"
                    src={HERO_VIDEO}
                    poster={HERO_IMAGE}
                    autoPlay
                    loop
                    muted
                    playsInline
                    aria-hidden="true"
                  />
                </div>
              </div>
              <div className="to-background absolute inset-0 bg-gradient-to-b from-black/65 via-black/35" />
            </div>

            <div className="relative z-10">
              <header className="mx-auto flex max-w-6xl items-center justify-between px-4 py-6 text-white">
                <div className="flex items-center gap-2">
                  <Compass className="h-6 w-6" />
                  <span className="font-display text-xl font-bold tracking-tight">
                    Nomadic
                  </span>
                </div>
                <div className="flex items-center gap-3">
                  <Button
                    variant="ghost"
                    size="icon"
                    type="button"
                    className="text-white hover:bg-white/10 focus:ring-white"
                  >
                    <User className="h-5 w-5" />
                  </Button>
                  <Button
                    variant="ghost"
                    size="icon"
                    type="button"
                    className="text-white hover:bg-white/10 focus:ring-white"
                  >
                    <Menu className="h-5 w-5" />
                  </Button>
                </div>
              </header>

              <div
                ref={chatPanelContainerRef}
                className="mx-auto flex max-w-6xl flex-col items-center gap-6 px-4 pb-12 pt-6"
              >
                <div className="-mt-8 space-y-6 text-center text-white">
                  <h1
                    className="font-display text-4xl font-bold leading-tight sm:text-5xl lg:text-6xl"
                    aria-label={`Roam freely. ${HERO_TAGLINE}`}
                  >
                    Roam freely.{' '}
                    <span className="text-accent relative inline-block">
                      <span className="invisible">{HERO_TAGLINE}</span>
                      <span
                        className="absolute left-0 top-0 whitespace-nowrap"
                        aria-live="polite"
                      >
                        {typedTagline}
                      </span>
                    </span>
                  </h1>
                </div>

                <motion.div
                  initial={{ opacity: 0, y: 20 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ duration: 0.5, delay: 0.1 }}
                  className="mt-8 w-full max-w-xl"
                >
                  <Card className="bg-card/95 border-white/20 p-1 shadow-2xl backdrop-blur">
                    <CardContent className="p-3 sm:p-4">
                      {chatPanelContent(false)}
                    </CardContent>
                  </Card>
                </motion.div>
              </div>
            </div>
          </div>

          {showResults ? (
            <motion.section
              initial={{ opacity: 0, y: 40 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.5, ease: 'easeOut' }}
              className="bg-background pb-14 pt-10"
            >
              <div className="mx-auto flex max-w-6xl flex-col gap-6 px-4">
                <motion.div
                  initial={{ opacity: 0, y: 20 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ duration: 0.4, delay: 0.1, ease: 'easeOut' }}
                  className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between"
                >
                  <div>
                    <h2 className="text-foreground font-display text-2xl font-bold sm:text-3xl">
                      Branches stretched wide with tiles nested inside
                    </h2>
                  </div>
                </motion.div>

                <motion.div
                  initial={{ opacity: 0, y: 20 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ duration: 0.4, delay: 0.2, ease: 'easeOut' }}
                >
                  {branchPanelContent}
                </motion.div>
              </div>
            </motion.section>
          ) : null}

          <FeaturesSection />
          <Footer />
        </>
      )}
    </div>
  );
}
