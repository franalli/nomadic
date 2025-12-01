'use client';

import { addDays, addWeeks, format, isBefore, nextSaturday, parse, startOfDay } from 'date-fns';
import { motion } from 'framer-motion';
import {
  AlertCircle,
  ArrowRight,
  CalendarRange,
  CheckCircle2,
  Circle,
  Compass,
  MapPin,
  Menu,
  Plus,
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
import { useDocumentStore } from '@/state/documentStore';
import type { DocumentBranch, DocumentTripInputs, PlanDocumentResponse } from '@/types/document';
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

const parseDisplayDate = (value: string): string | null => {
  const trimmed = value.trim();
  if (!trimmed) return null;

  // Try parsing ISO format (this is what we store in draft)
  const isoMatch = /^(\d{4})-(\d{2})-(\d{2})$/.exec(trimmed);
  if (isoMatch) {
    const parsed = new Date(trimmed + 'T00:00:00');
    if (Number.isNaN(parsed.getTime())) return null;
    return trimmed;
  }

  // Try parsing old DD-MM-YYYY format for backwards compatibility
  const displayMatch = /^(\d{2})-(\d{2})-(\d{4})$/.exec(trimmed);
  if (displayMatch) {
    const [, day, month, year] = displayMatch;
    const iso = `${year}-${month}-${day}`;
    const parsed = new Date(iso + 'T00:00:00');
    if (Number.isNaN(parsed.getTime())) return null;
    return iso;
  }

  return null;
};

const parseBudgetValue = (value?: string | number | null): number | null => {
  if (value === null || value === undefined) return null;
  const asText = typeof value === 'number' ? value.toString() : value;
  const numericText = asText.replace(/[^\d.]/g, '');
  if (!numericText) return null;
  const parsed = Number(numericText);
  if (!Number.isFinite(parsed) || parsed <= 0) return null;
  return Math.round(parsed);
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

const normalizeTripInputsDraft = (draft: TripInputsDraft): TripInputs => {
  const destinations = (draft.destinations ?? [])
    .map((d) => d.trim())
    .filter((d) => d.length > 0);
  const origin = typeof draft.origin === 'string' ? draft.origin.trim() || null : null;
  const startDate = draft.start_date ? parseDisplayDate(draft.start_date) : null;
  const endDate = draft.end_date ? parseDisplayDate(draft.end_date) : null;
  const travelerText =
    draft.traveler_count != null ? String(draft.traveler_count).trim() : '';
  const parsedTravelerCount = travelerText === '' ? null : Number(travelerText);
  const travelerCount =
    Number.isFinite(parsedTravelerCount) && parsedTravelerCount != null
      ? Math.min(20, Math.max(1, parsedTravelerCount))
      : null;
  const budget = parseBudgetValue(draft.budget ?? null);

  const missingFields: string[] = [];
  if (destinations.length === 0) missingFields.push('destinations');
  if (!origin) missingFields.push('origin');
  if (!startDate) missingFields.push('start_date');
  if (!endDate) missingFields.push('end_date');
  if (travelerCount == null) missingFields.push('traveler_count');
  if (!budget) missingFields.push('budget');

  return {
    destinations,
    origin,
    start_date: startDate,
    end_date: endDate,
    traveler_count: travelerCount,
    budget,
    missing_fields: missingFields,
  };
};

const DEFAULT_TRIP_INPUTS: TripInputs = {
  destinations: [],
  origin: null,
  start_date: null,
  end_date: null,
  traveler_count: null,
  budget: null,
  missing_fields: [
    'destinations',
    'origin',
    'start_date',
    'end_date',
    'traveler_count',
    'budget',
  ],
};

const HERO_IMAGE =
  'https://images.unsplash.com/photo-1500530855697-b586d89ba3ee?auto=format&fit=crop&w=2000&q=80';
const HERO_VIDEO = '/hiking_video.mp4';
const HERO_TAGLINE = 'We Plan the Rest.';
const HERO_TYPING_INTERVAL_MS = 200;
const HERO_TYPING_PAUSE_MS = 8000;

type TileCounts = Record<TileTabKey, number>;

// Field progress indicator - shows which of the 5 fields are complete
const FIELD_LABELS: Record<string, string> = {
  origin: 'From',
  destinations: 'Where to',
  dates: 'Dates',
  traveler_count: 'Travelers',
  budget: 'Budget',
  vibes: 'Vibes',
};

const FIELD_ORDER = [
  'origin',
  'destinations',
  'dates',
  'traveler_count',
  'budget',
] as const;

type FieldProgressProps = {
  tripInputs: TripInputs;
};

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

export function NomadicLanding() {
  // Document store - single source of truth for trip inputs
  const documentStore = useDocumentStore();
  const storeTripInputs = documentStore.document?.trip_inputs;

  // Derive tripInputs from store (with defaults)
  const tripInputs: TripInputs = useMemo(() => {
    if (!storeTripInputs) return DEFAULT_TRIP_INPUTS;
    return {
      ...storeTripInputs,
      // Include deprecated destination field for backward compat
      destination: storeTripInputs.destinations?.[0] ?? null,
    };
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
  const [tripContextId, setTripContextId] = useState<number | null>(null);

  // Draft state for UI editing (kept local)
  const [tripInputsDraft, setTripInputsDraft] = useState<TripInputsDraft>(() =>
    toTripInputsDraft(DEFAULT_TRIP_INPUTS)
  );

  // Track last confirmed version to prevent auto-refresh loops
  const lastConfirmedVersionRef = useRef<number>(0);

  const [editingField, setEditingField] = useState<keyof TripInputsDraft | null>(null);
  const [selectedLocationBadge, setSelectedLocationBadge] = useState<'origin' | number | null>(null);
  const [calendarOpen, setCalendarOpen] = useState(false);
  const [vibeInput, setVibeInput] = useState('');
  const [vibeInputExpanded, setVibeInputExpanded] = useState(false);
  const [toastMessage, setToastMessage] = useState<string | null>(null);
  const [isHydratingSnapshot, setIsHydratingSnapshot] = useState(false);
  const [isResettingSession, setIsResettingSession] = useState(false);
  const [hasTriggeredChat, setHasTriggeredChat] = useState(false);
  const [hasUserMessages, setHasUserMessages] = useState(false);
  const [readyToGenerate, setReadyToGenerate] = useState(false);
  const [chatKey, setChatKey] = useState(0);
  const tilesFetchControllerRef = useRef<AbortController | null>(null);
  const tripInputsPlanControllerRef = useRef<AbortController | null>(null);
  const chatPanelContainerRef = useRef<HTMLDivElement | null>(null);
  const chatPanelRef = useRef<ChatPanelHandle | null>(null);
  const [typedTagline, setTypedTagline] = useState('');

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

  // Update draft and close editing (used when committing field edits)
  const updateDraftAndCloseEditing = useCallback(
    (draft: TripInputsDraft) => {
      setTripInputsDraft(draft);
      setEditingField(null);
    },
    []
  );

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
        if (data.document.trip_context_id) {
          setTripContextId(data.document.trip_context_id);
        }
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

        if (doc.trip_context_id) {
          setTripContextId(doc.trip_context_id);
          setHasTriggeredChat(true);
        }

        // Update lastConfirmedVersion from the store
        lastConfirmedVersionRef.current = documentStore.lastConfirmedVersion;

        if (!doc.branches.length) return;

        setBranches(doc.branches);
        setTilesMap(doc.tiles);

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
    if (tripInputsPlanControllerRef.current) {
      tripInputsPlanControllerRef.current.abort();
      tripInputsPlanControllerRef.current = null;
    }
    setTripContextId(null);
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
    lastConfirmedVersionRef.current = 0;
    setHasTriggeredChat(false);
    setHasUserMessages(false);
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
    (field?: keyof TripInputsDraft, value?: string) => {
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

      // Send chat message for field changes (this will update the store via backend response)
      let message: string | null = null;

      if (field === 'origin') {
        message = `I'm traveling from ${trimmedValue}`;
      } else if (field === 'traveler_count') {
        const count = typeof parsedValue === 'number' ? parsedValue : parseInt(trimmedValue, 10);
        if (!Number.isNaN(count)) {
          message = count === 1 ? "I'm traveling solo" : `We are ${count} travelers`;
        }
      } else if (field === 'budget') {
        const budget = typeof parsedValue === 'number' ? parsedValue : parseInt(trimmedValue.replace(/[^\d]/g, ''), 10);
        if (!Number.isNaN(budget) && budget > 0) {
          message = `My budget is $${budget.toLocaleString()}`;
        }
      }

      if (message) {
        chatPanelRef.current?.sendMessage(message);
      }
    },
    [tripInputs]
  );

  const handleDateRangeChange = useCallback(
    async (range: DateRange | undefined) => {
      const startIso = range?.from ? format(range.from, 'yyyy-MM-dd') : null;
      const endIso = range?.to ? format(range.to, 'yyyy-MM-dd') : null;

      // Get previous values to check what changed
      const prevStartIso = tripInputs.start_date;
      const prevEndIso = tripInputs.end_date;

      // Update draft locally
      setTripInputsDraft((prev) => {
        const base = prev ?? toTripInputsDraft(tripInputs);
        return {
          ...base,
          start_date: startIso,
          end_date: endIso,
        };
      });

      // Only close calendar when both dates are selected
      if (startIso && endIso) {
        setCalendarOpen(false);
      }

      // Check what changed
      const startChanged = startIso !== prevStartIso;
      const endChanged = endIso !== prevEndIso;

      // Commit dates to store directly (don't rely solely on chat message)
      if (startChanged || endChanged) {
        const updates: Partial<{ start_date: string | null; end_date: string | null }> = {};
        if (startChanged) updates.start_date = startIso;
        if (endChanged) updates.end_date = endIso;
        await documentStore.commitTripInputs(updates);
      }

      // Send a chat message when dates are updated (for LLM context)
      if (startIso && endIso && (startChanged || endChanged)) {
        // Both dates selected - send message about the date range
        const startDisplay = formatDateForDisplay(startIso);
        const endDisplay = formatDateForDisplay(endIso);
        const message = `I'll be traveling from ${startDisplay} to ${endDisplay}`;
        chatPanelRef.current?.sendMessage(message);
      } else if (startIso && !endIso && startChanged) {
        // Only start date selected
        const startDisplay = formatDateForDisplay(startIso);
        const message = `My trip starts on ${startDisplay}`;
        chatPanelRef.current?.sendMessage(message);
      } else if (!startIso && endIso && endChanged) {
        // Only end date selected
        const endDisplay = formatDateForDisplay(endIso);
        const message = `My trip ends on ${endDisplay}`;
        chatPanelRef.current?.sendMessage(message);
      }
    },
    [tripInputs, documentStore]
  );

  const handleRemoveOrigin = useCallback(() => {
    // Origin cannot be removed once set - do nothing
    // Just deselect the badge if it was selected
    setSelectedLocationBadge(null);
  }, []);

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

          // If all branches were removed, reset to "ready to generate" state
          if (prunedBranches.length === 0) {
            setReadyToGenerate(true);
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

      // Send a chat message to record the removal so the LLM knows about it
      if (removedDestination) {
        chatPanelRef.current?.sendMessage(`Remove ${removedDestination}`);
      }

      setSelectedLocationBadge(null);
    },
    [tripInputs.destinations, documentStore, branches, selectedBranchId]
  );

  const handleDestinationsChange = useCallback(
    (destinations: string[], sendChatMessage = false) => {
      const prevDestinations = tripInputs.destinations ?? [];

      // If the user cleared all destinations, restore the previous value
      if (destinations.length === 0) {
        setTripInputsDraft((prev) => {
          if (!prev) return prev;
          return {
            ...prev,
            destinations: prevDestinations,
          };
        });
        return;
      }

      // Update draft locally
      setTripInputsDraft((prev) => {
        const base = prev ?? toTripInputsDraft(tripInputs);
        return {
          ...base,
          destinations,
        };
      });

      // Send chat message if destinations changed and sendChatMessage is true
      // (this will update the store via backend response)
      if (sendChatMessage && destinations.length > 0) {
        const destinationsChanged =
          destinations.length !== prevDestinations.length ||
          destinations.some((d, i) => d !== prevDestinations[i]);

        if (destinationsChanged) {
          const message =
            destinations.length === 1
              ? `I want to go to ${destinations[0]}`
              : `I want to visit ${destinations.join(', ')}`;
          chatPanelRef.current?.sendMessage(message);
        }
      }
    },
    [tripInputs]
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

      // Send a chat message to record the removal so the LLM knows about it
      if (removedVibe) {
        chatPanelRef.current?.sendMessage(`Removing vibe ${removedVibe}`);
      }
    },
    [tripInputs.vibes, documentStore]
  );

  useEffect(
    () => () => {
      abortTilesFetch();
      if (tripInputsPlanControllerRef.current) {
        tripInputsPlanControllerRef.current.abort();
        tripInputsPlanControllerRef.current = null;
      }
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
      const primaryBranch =
        result.branches.find((b) => b.id === result.primaryBranchId) ??
        result.branches[0];

      // If we have a full response, update the store (single source of truth)
      if (result.response) {
        documentStore.setFromPlanResponse(result.response);
        lastConfirmedVersionRef.current = result.response.version;
      }

      setTripContextId(result.tripContextId);
      setBranches(result.branches);
      // Update readyToGenerate state - reset to false if branches exist
      setReadyToGenerate(result.branches.length === 0 && (result.readyToGenerate ?? false));
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
          next[branch.id] = { activities: [] };
        });
        return next;
      });
      setSelectedBranchId(result.primaryBranchId);
      setHasTriggeredChat(true);
    },
    [documentStore]
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
        if (category === 'stay') {
          nextSelection.stay =
            current.stay && current.stay.id === tile.id ? undefined : tile;
        } else if (category === 'flight') {
          nextSelection.flight =
            current.flight && current.flight.id === tile.id ? undefined : tile;
        } else {
          const existingIdx = nextSelection.activities.findIndex(
            (activity) => activity.id === tile.id
          );
          if (existingIdx >= 0) {
            nextSelection.activities.splice(existingIdx, 1);
          } else {
            const pruned = nextSelection.activities.filter(
              (activity) => !activitiesOverlap(activity, tile)
            );
            nextSelection.activities = [...pruned, tile];
          }
        }

        setBranchTileNotes((prevNotes) => ({
          ...prevNotes,
          [branchId]: buildBranchNote(branchId, { selectionOverride: nextSelection }),
        }));

        return { ...prev, [branchId]: nextSelection };
      });
    },
    [buildBranchNote, selectedBranchId, tilesBranchId]
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

  const handleChatTriggered = useCallback(() => {
    setHasTriggeredChat(true);
  }, []);

  const handleHasUserMessage = useCallback((has: boolean) => {
    setHasUserMessages(has);
  }, []);

  const showResults = branches.length > 0;
  const hasBranchesReady = branches.length > 0;
  const missingFields = tripInputs.missing_fields ?? [];
  const blockingMissingFields = missingFields.filter((field) => field !== 'budget');
  const formatTravelers = (value?: number | null) =>
    value != null ? `${value} traveler${value === 1 ? '' : 's'}` : null;
  const draftBase = tripInputsDraft ?? toTripInputsDraft(tripInputs);

  // Helper to check if a field has a value (non-null)
  const hasFieldValue = (field: keyof TripInputsDraft): boolean => {
    if (field === 'traveler_count') return tripInputs.traveler_count != null;
    if (field === 'budget') return tripInputs.budget != null;
    if (field === 'destinations') return (tripInputs.destinations ?? []).length > 0;
    return Boolean(tripInputs[field as keyof TripInputs]);
  };

  // Check if we have origin or destination to show route
  const hasOrigin = Boolean(tripInputs.origin);
  const hasDestination =
    Boolean(tripInputs.destination) || (tripInputs.destinations ?? []).length > 0;
  const destinationsDisplay =
    (tripInputs.destinations ?? []).length > 0
      ? tripInputs.destinations!.join(', ')
      : (tripInputs.destination ?? '');

  // Check if we have dates to show
  const hasStartDate = Boolean(tripInputs.start_date);
  const hasEndDate = Boolean(tripInputs.end_date);
  const hasDates = hasStartDate || hasEndDate;

  // Parse dates for calendar
  const calendarStartDate = tripInputs.start_date
    ? parse(tripInputs.start_date, 'yyyy-MM-dd', new Date())
    : undefined;
  const calendarEndDate = tripInputs.end_date
    ? parse(tripInputs.end_date, 'yyyy-MM-dd', new Date())
    : undefined;
  const selectedDateRange: DateRange | undefined =
    calendarStartDate || calendarEndDate
      ? { from: calendarStartDate, to: calendarEndDate }
      : undefined;

  // Validation: check if dates are in the past
  const today = startOfDay(new Date());
  const isStartDatePast = calendarStartDate && isBefore(calendarStartDate, today);
  const isEndDatePast = calendarEndDate && isBefore(calendarEndDate, today);
  const hasDateValidationWarning = isStartDatePast || isEndDatePast;

  // Only show fields that have been defined via chat or manual input
  const definedFields = (['traveler_count', 'budget'] as const).filter(hasFieldValue);

  // Location badge component for origin and destinations
  const LocationBadge = ({
    type,
    index,
    value,
    isOrigin = false,
  }: {
    type: 'origin' | 'destination';
    index?: number;
    value: string;
    isOrigin?: boolean;
  }) => {
    const badgeKey = type === 'origin' ? 'origin' : index!;
    const isSelected = selectedLocationBadge === badgeKey;
    const badgeRef = useRef<HTMLSpanElement>(null);

    // Focus the badge when it becomes selected
    useEffect(() => {
      if (isSelected && badgeRef.current) {
        badgeRef.current.focus();
      }
    }, [isSelected]);

    const handleRemoveClick = (e: React.MouseEvent) => {
      e.stopPropagation();
      if (typeof index === 'number') {
        handleRemoveDestination(index);
      }
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
          setSelectedLocationBadge(isSelected ? null : badgeKey);
        }}
        onKeyDown={(e) => {
          if (e.key === 'Delete' || e.key === 'Backspace') {
            e.preventDefault();
            if (type === 'origin') {
              handleRemoveOrigin();
            } else if (typeof index === 'number') {
              handleRemoveDestination(index);
            }
          } else if (e.key === 'Escape') {
            e.preventDefault();
            setSelectedLocationBadge(null);
            badgeRef.current?.blur();
          } else if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            setSelectedLocationBadge(isSelected ? null : badgeKey);
          }
        }}
      >
        <MapPin
          className={`h-3 w-3 shrink-0 ${isOrigin ? 'text-muted-foreground' : 'text-accent'}`}
        />
        {value}
        {!isOrigin && (
          <button
            type="button"
            onClick={handleRemoveClick}
            className="absolute -right-1 -top-1 flex h-3.5 w-3.5 items-center justify-center rounded-full bg-gray-500 text-white opacity-0 transition-opacity hover:bg-gray-600 group-hover:opacity-70"
            aria-label={`Remove ${value}`}
          >
            <X className="h-2.5 w-2.5" />
          </button>
        )}
      </span>
    );
  };

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
            <LocationBadge type="origin" value={tripInputs.origin!} isOrigin />
          </div>
        ) : (
          <div className="border-border/40 bg-muted/20 inline-flex items-center gap-1.5 rounded-full border border-dashed px-2.5 py-1.5">
            <MapPin className="h-3 w-3 text-muted-foreground/40" />
            <span className="text-xs text-muted-foreground/50">Not set</span>
          </div>
        )}
      </div>

      {/* Where to field */}
      <div className="flex flex-col gap-1">
        <div className={`flex items-center gap-1 text-xs transition-colors ${isFieldComplete('destinations', tripInputs) ? 'text-accent' : 'text-muted-foreground/60'}`}>
          {isFieldComplete('destinations', tripInputs) ? <CheckCircle2 className="h-3 w-3" /> : <Circle className="h-3 w-3" />}
          <span className={isFieldComplete('destinations', tripInputs) ? 'font-medium' : ''}>{FIELD_LABELS.destinations}</span>
        </div>
        {hasDestination ? (
          <div
            className="border-border/60 bg-muted/40 inline-flex flex-wrap items-center gap-1 rounded-full border px-2.5 py-1.5"
            onClick={() => setSelectedLocationBadge(null)}
            onKeyDown={() => {}}
            role="presentation"
          >
            {(tripInputs.destinations ?? []).map((dest, idx) => (
              <LocationBadge key={`dest-${idx}`} type="destination" index={idx} value={dest} />
            ))}
          </div>
        ) : (
          <div className="border-border/40 bg-muted/20 inline-flex items-center gap-1.5 rounded-full border border-dashed px-2.5 py-1.5">
            <MapPin className="h-3 w-3 text-muted-foreground/40" />
            <span className="text-xs text-muted-foreground/50">Not set</span>
          </div>
        )}
      </div>

      {/* Dates field */}
      <div className="flex flex-col gap-1">
        <div className={`flex items-center gap-1 text-xs transition-colors ${isFieldComplete('dates', tripInputs) ? 'text-accent' : 'text-muted-foreground/60'}`}>
          {isFieldComplete('dates', tripInputs) ? <CheckCircle2 className="h-3 w-3" /> : <Circle className="h-3 w-3" />}
          <span className={isFieldComplete('dates', tripInputs) ? 'font-medium' : ''}>{FIELD_LABELS.dates}</span>
        </div>
        {hasDates ? (
          <Popover open={calendarOpen} onOpenChange={setCalendarOpen}>
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
                  {[
                    { label: 'This weekend', getDates: () => {
                      const sat = nextSaturday(new Date());
                      return { from: sat, to: addDays(sat, 1) };
                    }},
                    { label: 'Next weekend', getDates: () => {
                      const sat = nextSaturday(addWeeks(new Date(), 1));
                      return { from: sat, to: addDays(sat, 1) };
                    }},
                    { label: '1 week', getDates: () => {
                      const start = addDays(new Date(), 1);
                      return { from: start, to: addDays(start, 6) };
                    }},
                    { label: '2 weeks', getDates: () => {
                      const start = addDays(new Date(), 1);
                      return { from: start, to: addDays(start, 13) };
                    }},
                  ].map((preset) => (
                    <button
                      key={preset.label}
                      type="button"
                      onClick={() => handleDateRangeChange(preset.getDates())}
                      className="whitespace-nowrap rounded-md px-3 py-1.5 text-left text-xs font-medium text-foreground hover:bg-muted transition-colors"
                    >
                      {preset.label}
                    </button>
                  ))}
                </div>
                <Calendar
                  mode="range"
                  defaultMonth={calendarStartDate}
                  selected={selectedDateRange}
                  onSelect={handleDateRangeChange}
                  numberOfMonths={2}
                  disabled={{ before: new Date() }}
                />
              </div>
            </PopoverContent>
          </Popover>
        ) : (
          <Popover open={calendarOpen} onOpenChange={setCalendarOpen}>
            <PopoverTrigger asChild>
              <div
                className="border-border/40 bg-muted/20 hover:bg-muted/40 inline-flex cursor-pointer items-center gap-1.5 rounded-full border border-dashed px-2.5 py-1.5 transition-colors"
                role="button"
                tabIndex={0}
              >
                <CalendarRange className="h-3.5 w-3.5 text-muted-foreground/40" />
                <span className="text-xs text-muted-foreground/50">Not set</span>
              </div>
            </PopoverTrigger>
            <PopoverContent className="w-auto p-0" align="start">
              <div className="flex">
                {/* Quick preset buttons */}
                <div className="flex flex-col gap-1 border-r border-border/60 p-2">
                  <span className="px-2 pb-1 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
                    Quick picks
                  </span>
                  {[
                    { label: 'This weekend', getDates: () => {
                      const sat = nextSaturday(new Date());
                      return { from: sat, to: addDays(sat, 1) };
                    }},
                    { label: 'Next weekend', getDates: () => {
                      const sat = nextSaturday(addWeeks(new Date(), 1));
                      return { from: sat, to: addDays(sat, 1) };
                    }},
                    { label: '1 week', getDates: () => {
                      const start = addDays(new Date(), 1);
                      return { from: start, to: addDays(start, 6) };
                    }},
                    { label: '2 weeks', getDates: () => {
                      const start = addDays(new Date(), 1);
                      return { from: start, to: addDays(start, 13) };
                    }},
                  ].map((preset) => (
                    <button
                      key={preset.label}
                      type="button"
                      onClick={() => handleDateRangeChange(preset.getDates())}
                      className="whitespace-nowrap rounded-md px-3 py-1.5 text-left text-xs font-medium text-foreground hover:bg-muted transition-colors"
                    >
                      {preset.label}
                    </button>
                  ))}
                </div>
                <Calendar
                  mode="range"
                  defaultMonth={new Date()}
                  selected={selectedDateRange}
                  onSelect={handleDateRangeChange}
                  numberOfMonths={2}
                  disabled={{ before: new Date() }}
                />
              </div>
            </PopoverContent>
          </Popover>
        )}
      </div>

      {/* Travelers field */}
      <div className="flex flex-col gap-1">
        <div className={`flex items-center gap-1 text-xs transition-colors ${isFieldComplete('traveler_count', tripInputs) ? 'text-accent' : 'text-muted-foreground/60'}`}>
          {isFieldComplete('traveler_count', tripInputs) ? <CheckCircle2 className="h-3 w-3" /> : <Circle className="h-3 w-3" />}
          <span className={isFieldComplete('traveler_count', tripInputs) ? 'font-medium' : ''}>{FIELD_LABELS.traveler_count}</span>
        </div>
        {tripInputs.traveler_count != null ? (() => {
          const field = 'traveler_count' as const;
          const isEditing = editingField === field;
          const draftValueRaw = draftBase ? draftBase[field] : '';
          const draftValue = draftValueRaw == null ? '' : String(draftValueRaw);
          const displayValue = formatTravelers(tripInputs.traveler_count) ?? '';
          return (
            <div
              className={`border-border/60 bg-muted/40 inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1.5 ${isEditing ? 'ring-primary ring-1' : ''}`}
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
              <span className="text-muted-foreground shrink-0"><Users className="h-3.5 w-3.5" /></span>
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
                      const originalValue = tripInputs[field as keyof TripInputs];
                      setTripInputsDraft((prev) =>
                        prev ? { ...prev, [field]: originalValue ?? '' } : prev
                      );
                      setEditingField(null);
                    }
                  }}
                  autoFocus
                />
              ) : (
                <span className="text-foreground whitespace-nowrap text-xs font-semibold">
                  {displayValue}
                </span>
              )}
            </div>
          );
        })() : (
          <div className="border-border/40 bg-muted/20 inline-flex items-center gap-1.5 rounded-full border border-dashed px-2.5 py-1.5">
            <Users className="h-3.5 w-3.5 text-muted-foreground/40" />
            <span className="text-xs text-muted-foreground/50">Not set</span>
          </div>
        )}
      </div>

      {/* Budget field */}
      <div className="flex flex-col gap-1">
        <div className={`flex items-center gap-1 text-xs transition-colors ${isFieldComplete('budget', tripInputs) ? 'text-accent' : 'text-muted-foreground/60'}`}>
          {isFieldComplete('budget', tripInputs) ? <CheckCircle2 className="h-3 w-3" /> : <Circle className="h-3 w-3" />}
          <span className={isFieldComplete('budget', tripInputs) ? 'font-medium' : ''}>{FIELD_LABELS.budget}</span>
        </div>
        {tripInputs.budget != null ? (() => {
          const field = 'budget' as const;
          const isEditing = editingField === field;
          const draftValueRaw = draftBase ? draftBase[field] : '';
          const draftValue = draftValueRaw == null ? '' : String(draftValueRaw);
          const displayValue = formatBudgetValue(tripInputs.budget);
          return (
            <div
              className={`border-border/60 bg-muted/40 inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1.5 ${isEditing ? 'ring-primary ring-1' : ''}`}
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
              <span className="text-muted-foreground shrink-0"><Wallet className="h-3.5 w-3.5" /></span>
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
                      const originalValue = tripInputs[field as keyof TripInputs];
                      setTripInputsDraft((prev) =>
                        prev ? { ...prev, [field]: originalValue ?? '' } : prev
                      );
                      setEditingField(null);
                    }
                  }}
                  autoFocus
                />
              ) : (
                <span className="text-foreground whitespace-nowrap text-xs font-semibold">
                  {displayValue}
                </span>
              )}
            </div>
          );
        })() : (
          <div className="border-border/40 bg-muted/20 inline-flex items-center gap-1.5 rounded-full border border-dashed px-2.5 py-1.5">
            <Wallet className="h-3.5 w-3.5 text-muted-foreground/40" />
            <span className="text-xs text-muted-foreground/50">Not set</span>
          </div>
        )}
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
          onChatTriggered={handleChatTriggered}
          onHasUserMessage={handleHasUserMessage}
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
      {(hasUserMessages || hasBranchesReady) ? (
        <div
          className={`flex w-full justify-end px-1 ${fullHeight ? 'shrink-0 pt-2' : 'pt-4'}`}
        >
          <Button
            variant="outline"
            size="sm"
            disabled={isResettingSession}
            onClick={handleStartNewSession}
            className="border-orange-500 bg-white/60 text-orange-500 hover:bg-white/70 hover:text-orange-600"
          >
            {isResettingSession ? 'Resetting…' : 'Start fresh'}
          </Button>
        </div>
      ) : null}
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
            canBookTrip={blockingMissingFields.length === 0}
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

      {/* Split layout when branches are ready */}
      {hasBranchesReady ? (
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

          {/* Right content - Branches (75% width, with left margin for fixed sidebar) */}
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

              {/* Branch panel section */}
              <section className="bg-background px-6 pb-14 pt-6">
                {branchPanelContent}
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
