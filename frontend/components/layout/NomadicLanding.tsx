'use client';

import { format, parse } from 'date-fns';
import { motion } from 'framer-motion';
import {
  ArrowRight,
  CalendarRange,
  Compass,
  MapPin,
  Menu,
  User,
  Users,
  Wallet,
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
import { API_BASE } from '@/lib/api';
import { clearSessionId, getOrCreateSessionId } from '@/lib/session';
import { saveTripSummary } from '@/lib/summary';
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

const fillTripInputDefaults = (inputs?: TripInputs | null): TripInputs => {
  return normalizeTripInputsDraft(toTripInputsDraft(inputs ?? DEFAULT_TRIP_INPUTS));
};

const sanitizeOrigin = (
  origin: string | null,
  destination?: string | null
): string | null => {
  if (!origin || !destination) return origin;
  const originNorm = origin.trim().toLowerCase();
  const destinationNorm = destination.trim().toLowerCase();
  if (originNorm && destinationNorm && originNorm === destinationNorm) {
    return null;
  }
  return origin;
};

const resolveTripInputs = (
  incoming?: TripInputs | null,
  destinationHint?: string | null
): TripInputs => {
  const filled = fillTripInputDefaults(incoming);
  filled.origin = sanitizeOrigin(filled.origin ?? null, destinationHint);
  // Note: We no longer auto-add destinationHint to destinations
  // This was causing removed destinations to reappear
  return filled;
};

const HERO_IMAGE =
  'https://images.unsplash.com/photo-1500530855697-b586d89ba3ee?auto=format&fit=crop&w=2000&q=80';
const HERO_VIDEO = '/hiking_video.mp4';
const HERO_TAGLINE = 'We Plan the Rest.';
const HERO_TYPING_INTERVAL_MS = 200;
const HERO_TYPING_PAUSE_MS = 8000;

type TileCounts = Record<TileTabKey, number>;

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

type TripInputSignature = {
  destinations: string[];
  origin: string | null;
  start_date: string | null;
  end_date: string | null;
  traveler_count: number | null;
  budget: string | null;
};

const toTripInputSignature = (inputs?: TripInputs | null): TripInputSignature => ({
  destinations: (inputs?.destinations ?? [])
    .map((d) => d.trim())
    .filter((d) => d.length > 0),
  origin: inputs?.origin?.trim() || null,
  start_date: inputs?.start_date ?? null,
  end_date: inputs?.end_date ?? null,
  traveler_count:
    inputs?.traveler_count != null
      ? Math.min(20, Math.max(1, Number(inputs.traveler_count)))
      : null,
  budget: inputs?.budget != null ? String(inputs.budget).trim() || null : null,
});

const tripInputSignaturesEqual = (
  a: TripInputSignature | null,
  b: TripInputSignature | null
): boolean => {
  if (!a && !b) return true;
  if (!a || !b) return false;
  const destinationsEqual =
    a.destinations.length === b.destinations.length &&
    a.destinations.every((d, i) => d === b.destinations[i]);
  return (
    destinationsEqual &&
    a.origin === b.origin &&
    a.start_date === b.start_date &&
    a.end_date === b.end_date &&
    a.traveler_count === b.traveler_count &&
    a.budget === b.budget
  );
};

export function NomadicLanding() {
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
  const [tripInputsDraft, setTripInputsDraft] = useState<TripInputsDraft>(() =>
    toTripInputsDraft(DEFAULT_TRIP_INPUTS)
  );
  const [tripInputs, setTripInputs] = useState<TripInputs>(() =>
    normalizeTripInputsDraft(toTripInputsDraft(DEFAULT_TRIP_INPUTS))
  );
  const [lastRegeneratedTripInputs, setLastRegeneratedTripInputs] =
    useState<TripInputSignature>(() => toTripInputSignature(DEFAULT_TRIP_INPUTS));
  const [editingField, setEditingField] = useState<keyof TripInputsDraft | null>(null);
  const [selectedLocationBadge, setSelectedLocationBadge] = useState<'origin' | number | null>(null);
  const [calendarOpen, setCalendarOpen] = useState(false);
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

  const updateFromDraft = useCallback(
    (draft: TripInputsDraft, destinationHint?: string | null) => {
      const normalized = normalizeTripInputsDraft(draft);
      const hint = destinationHint ?? selectedBranch?.destinations[0];
      normalized.origin = sanitizeOrigin(
        normalized.origin ?? null,
        hint
      );
      setTripInputs(normalized);
      setTripInputsDraft(draft);
      setEditingField(null);
    },
    [selectedBranch?.destinations]
  );

  const applyIncomingTripInputs = useCallback(
    (incoming?: TripInputs | null, destinationHint?: string | null): TripInputs => {
      const filled = resolveTripInputs(incoming, destinationHint);
      const draft = toTripInputsDraft(filled);
      updateFromDraft(draft, destinationHint);
      return filled;
    },
    [updateFromDraft]
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

      const sessionId = getOrCreateSessionId();
      const errorMessageOverride = overrides?.errorMessageOverride;

      try {
        const res = await fetch(
          `${API_BASE}/v1/document/tiles/${encodeURIComponent(branchId)}?session_id=${encodeURIComponent(sessionId || '')}`,
          {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
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
        const sessionId = getOrCreateSessionId();
        if (!sessionId) return;

        const res = await fetch(
          `${API_BASE}/v1/document?session_id=${encodeURIComponent(sessionId)}`
        );
        if (!res.ok) return;

        const data: PlanDocumentResponse = await res.json();
        if (cancelled) return;

        const doc = data.document;
        if (doc.trip_context_id) {
          setTripContextId(doc.trip_context_id);
          setHasTriggeredChat(true);
        }

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
    applyIncomingTripInputs(DEFAULT_TRIP_INPUTS, null);
    setLastRegeneratedTripInputs(toTripInputSignature(DEFAULT_TRIP_INPUTS));
    setHasTriggeredChat(false);
    setHasUserMessages(false);
    setChatKey((prev) => prev + 1);
  }, [abortTilesFetch, applyIncomingTripInputs]);

  const handleStartNewSession = useCallback(async () => {
    const sessionId = getOrCreateSessionId();
    abortTilesFetch();
    setIsResettingSession(true);
    let didResetServerState = false;

    try {
      if (sessionId) {
        const res = await fetch(
          `${API_BASE}/v1/session?session_id=${encodeURIComponent(sessionId)}`,
          {
            method: 'DELETE',
          }
        );

        if (!res.ok) {
          throw new Error(`Failed to reset session: ${res.status}`);
        }

        didResetServerState = true;
      }
    } catch (error) {
      console.error('Failed to reset planning session', error);
    } finally {
      clearSessionId();
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
      if (field === 'traveler_count') {
        const count = parseInt(trimmedValue, 10);
        if (Number.isNaN(count) || count <= 0) {
          setTripInputsDraft((prev) => {
            if (!prev) return prev;
            return { ...prev, [field]: prevValue ?? '' };
          });
          return;
        }
      } else if (field === 'budget') {
        const budget = parseInt(trimmedValue.replace(/[^\d]/g, ''), 10);
        if (Number.isNaN(budget) || budget <= 0) {
          setTripInputsDraft((prev) => {
            if (!prev) return prev;
            return { ...prev, [field]: prevValue ?? '' };
          });
          return;
        }
      }

      // Don't commit if value hasn't changed
      if (trimmedValue === String(prevValue ?? '')) {
        return;
      }

      setTripInputsDraft((prev) => {
        const base = prev ?? toTripInputsDraft(tripInputs);
        const next = { ...base, [field]: trimmedValue };
        updateFromDraft(next, selectedBranch?.destinations[0]);
        return next;
      });

      // Send chat message for field changes
      let message: string | null = null;

      if (field === 'origin') {
        message = `I'm traveling from ${trimmedValue}`;
      } else if (field === 'traveler_count') {
        const count = parseInt(trimmedValue, 10);
        if (!Number.isNaN(count)) {
          message = count === 1 ? "I'm traveling solo" : `We are ${count} travelers`;
        }
      } else if (field === 'budget') {
        const budget = parseInt(trimmedValue.replace(/[^\d]/g, ''), 10);
        if (!Number.isNaN(budget) && budget > 0) {
          message = `My budget is $${budget.toLocaleString()}`;
        }
      }

      if (message) {
        chatPanelRef.current?.sendMessage(message);
      }
    },
    [tripInputs, selectedBranch?.destinations, updateFromDraft]
  );

  const handleDateRangeChange = useCallback(
    (range: DateRange | undefined) => {
      const startIso = range?.from ? format(range.from, 'yyyy-MM-dd') : null;
      const endIso = range?.to ? format(range.to, 'yyyy-MM-dd') : null;

      // Get previous values to check what changed
      const prevStartIso = tripInputs.start_date;
      const prevEndIso = tripInputs.end_date;

      setTripInputsDraft((prev) => {
        const base = prev ?? toTripInputsDraft(tripInputs);
        const next = {
          ...base,
          start_date: startIso,
          end_date: endIso,
        };
        // Commit the changes as the user selects dates
        if (startIso || endIso) {
          updateFromDraft(next, selectedBranch?.destinations[0]);
        }
        // Only close calendar when both dates are selected
        if (startIso && endIso) {
          setCalendarOpen(false);
        }
        return next;
      });

      // Send a chat message when dates are updated
      const startChanged = startIso !== prevStartIso;
      const endChanged = endIso !== prevEndIso;

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
    [tripInputs, selectedBranch?.destinations, updateFromDraft]
  );

  const handleRemoveOrigin = useCallback(() => {
    const currentOrigin = tripInputs.origin;
    if (!currentOrigin) return;

    // Send chat message to backend - let the server response update the state
    const message = `Remove origin ${currentOrigin}`;
    chatPanelRef.current?.sendMessage(message);
    setSelectedLocationBadge(null);
  }, [tripInputs.origin]);

  const handleRemoveDestination = useCallback(
    (index: number) => {
      const currentDestinations = tripInputs.destinations ?? [];
      if (index < 0 || index >= currentDestinations.length) return;

      const removedDestination = currentDestinations[index];

      // Send chat message to backend - let the server response update the state
      const message = `Remove destination ${removedDestination}`;
      chatPanelRef.current?.sendMessage(message);
      setSelectedLocationBadge(null);
    },
    [tripInputs.destinations]
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

      setTripInputsDraft((prev) => {
        const base = prev ?? toTripInputsDraft(tripInputs);
        const next = {
          ...base,
          destinations,
        };
        updateFromDraft(next, selectedBranch?.destinations[0]);
        return next;
      });

      // Send chat message if destinations changed and sendChatMessage is true
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
    [tripInputs, selectedBranch?.destinations, updateFromDraft]
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
    }) => {
      const primaryBranch =
        result.branches.find((b) => b.id === result.primaryBranchId) ??
        result.branches[0];
      const mergedTripInputs = result.tripInputs ? { ...result.tripInputs } : undefined;
      if (mergedTripInputs?.budget != null) {
        mergedTripInputs.budget = Number(mergedTripInputs.budget);
      }
      if (primaryBranch && mergedTripInputs && mergedTripInputs.budget == null) {
        mergedTripInputs.budget = primaryBranch.budget ?? null;
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
      // Use tripInputs.destinations as fallback when no branches exist yet (during collection phase)
      const destinationHint =
        result.branches[0]?.destinations[0] ?? mergedTripInputs?.destinations?.[0] ?? null;
      const resolvedTripInputs = applyIncomingTripInputs(
        mergedTripInputs,
        destinationHint
      );
      setLastRegeneratedTripInputs(toTripInputSignature(resolvedTripInputs));
      setSelectedBranchId(result.primaryBranchId);
      setHasTriggeredChat(true);
    },
    [applyIncomingTripInputs]
  );

  // Auto-refresh branches and tiles whenever the core trip inputs change.
  useEffect(() => {
    const signature = toTripInputSignature(tripInputs);
    const destinationHint = selectedBranch?.destinations[0] ?? signature.destinations[0];
    const hasPlanContext =
      hasTriggeredChat || branches.length > 0 || tripContextId != null;
    const shouldRefresh =
      hasPlanContext &&
      destinationHint &&
      !tripInputSignaturesEqual(signature, lastRegeneratedTripInputs) &&
      !isHydratingSnapshot &&
      !isResettingSession;

    if (!shouldRefresh) return undefined;

    if (tripInputsPlanControllerRef.current) {
      tripInputsPlanControllerRef.current.abort();
      tripInputsPlanControllerRef.current = null;
    }

    const controller = new AbortController();
    tripInputsPlanControllerRef.current = controller;
    abortTilesFetch();

    const normalizedInputs = resolveTripInputs(tripInputs, destinationHint);
    const detailParts = [
      normalizedInputs.origin ? `origin ${normalizedInputs.origin}` : null,
      normalizedInputs.start_date ? `start ${normalizedInputs.start_date}` : null,
      normalizedInputs.end_date ? `end ${normalizedInputs.end_date}` : null,
      normalizedInputs.traveler_count != null
        ? `${normalizedInputs.traveler_count} traveler${normalizedInputs.traveler_count === 1 ? '' : 's'}`
        : null,
      normalizedInputs.budget
        ? `budget ${formatBudgetValue(normalizedInputs.budget)}`
        : null,
    ].filter(Boolean);

    const refreshMessage =
      detailParts.length > 0
        ? `Auto-refresh (fields changed): ${detailParts.join(', ')}. Regenerate branches and booking tiles.`
        : 'Auto-refresh triggered by updated trip details. Regenerate branches and booking tiles.';

    const sessionId = getOrCreateSessionId();

    const regenerate = async () => {
      try {
        const res = await fetch(`${API_BASE}/v1/plan`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            message: refreshMessage,
            session_id: sessionId || undefined,
            trip_context_id: tripContextId ?? undefined,
            trip_inputs: normalizedInputs,
          }),
          signal: controller.signal,
        });

        if (!res.ok) {
          console.error('Failed to regenerate plan after trip inputs change', res.status);
          setToastMessage(
            'Unable to refresh suggestions after updating your trip details. Try again.'
          );
          return;
        }

        const data: PlanDocumentResponse = await res.json();
        if (controller.signal.aborted) return;

        const doc = data.document;
        const primaryBranch = doc.branches.find((b) => b.is_primary);
        handlePlanResult({
          tripContextId: doc.trip_context_id ?? null,
          branches: doc.branches,
          tiles: doc.tiles,
          primaryBranchId:
            primaryBranch?.id ?? doc.branches[0]?.id ?? selectedBranchId ?? null,
          tripInputs: doc.trip_inputs
            ? {
                destination: doc.trip_inputs.destination,
                destinations: doc.trip_inputs.destinations ?? [],
                origin: doc.trip_inputs.origin,
                start_date: doc.trip_inputs.start_date,
                end_date: doc.trip_inputs.end_date,
                traveler_count: doc.trip_inputs.traveler_count,
                budget: doc.trip_inputs.budget,
                missing_fields: doc.trip_inputs.missing_fields,
              }
            : null,
        });
      } catch (error) {
        if ((error as DOMException).name === 'AbortError') return;
        console.error('Failed to regenerate plan after trip inputs change', error);
        setToastMessage(
          'Unable to refresh suggestions after updating your trip details. Try again.'
        );
      } finally {
        if (tripInputsPlanControllerRef.current === controller) {
          tripInputsPlanControllerRef.current = null;
        }
      }
    };

    regenerate();

    return () => controller.abort();
  }, [
    abortTilesFetch,
    branches.length,
    handlePlanResult,
    hasTriggeredChat,
    isHydratingSnapshot,
    isResettingSession,
    lastRegeneratedTripInputs,
    selectedBranch?.destinations,
    selectedBranchId,
    tripContextId,
    tripInputs,
  ]);

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
    if (field === 'destination')
      return (
        Boolean(tripInputs.destination) || (tripInputs.destinations ?? []).length > 0
      );
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

    return (
      <span
        ref={badgeRef}
        className={`inline-flex cursor-pointer items-center gap-1 rounded-full px-2 py-0.5 text-xs font-semibold transition-all outline-none ${
          isSelected
            ? 'bg-primary/20 ring-primary ring-2 ring-offset-1'
            : 'hover:bg-muted/60'
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
      </span>
    );
  };

  // Route display component (Origin -> Destinations as separate badges)
  const routeDisplay =
    hasOrigin || hasDestination ? (
      <div
        className="border-border/60 bg-muted/40 inline-flex flex-wrap items-center gap-1 rounded-full border px-1.5 py-1"
        onClick={() => setSelectedLocationBadge(null)}
        onKeyDown={() => {}}
        role="presentation"
      >
        {hasOrigin && (
          <LocationBadge type="origin" value={tripInputs.origin!} isOrigin />
        )}
        {hasOrigin && hasDestination && (
          <ArrowRight className="text-muted-foreground mx-0.5 h-3.5 w-3.5 shrink-0" />
        )}
        {(tripInputs.destinations ?? []).map((dest, idx) => (
          <LocationBadge key={`dest-${idx}`} type="destination" index={idx} value={dest} />
        ))}
      </div>
    ) : null;

  // Calendar display component with popover
  const calendarDisplay = hasDates ? (
    <Popover open={calendarOpen} onOpenChange={setCalendarOpen}>
      <PopoverTrigger asChild>
        <div
          className="border-border/60 bg-muted/40 hover:bg-muted/60 inline-flex cursor-pointer items-center gap-1.5 rounded-full border px-2.5 py-1 transition-colors"
          role="button"
          tabIndex={0}
        >
          <CalendarRange className="text-muted-foreground h-3.5 w-3.5 shrink-0" />
          <span className="text-foreground whitespace-nowrap text-xs font-semibold">
            {hasStartDate && formatDateForDisplay(tripInputs.start_date)}
            {hasStartDate && hasEndDate && ' – '}
            {hasEndDate && formatDateForDisplay(tripInputs.end_date)}
          </span>
        </div>
      </PopoverTrigger>
      <PopoverContent className="w-auto p-0" align="start">
        <Calendar
          mode="range"
          defaultMonth={calendarStartDate}
          selected={selectedDateRange}
          onSelect={handleDateRangeChange}
          numberOfMonths={2}
          disabled={{ before: new Date() }}
        />
      </PopoverContent>
    </Popover>
  ) : null;

  const tripDetailsContent =
    !routeDisplay && !calendarDisplay && definedFields.length === 0 ? null : (
      <div className="space-y-2">
        <div className="flex flex-wrap items-center gap-1.5">
          {routeDisplay}
          {calendarDisplay}
          {definedFields.map((field) => {
            const isEditing = editingField === field;
            const draftValueRaw = draftBase ? draftBase[field] : '';
            const draftValue = draftValueRaw == null ? '' : String(draftValueRaw);

            let displayValue = '';
            if (field === 'traveler_count') {
              displayValue = formatTravelers(tripInputs.traveler_count) ?? '';
            } else if (field === 'budget') {
              displayValue = formatBudgetValue(tripInputs.budget);
            }

            const inputType = 'number';
            const icon =
              field === 'traveler_count' ? (
                <Users className="h-3.5 w-3.5" />
              ) : (
                <Wallet className="h-3.5 w-3.5" />
              );

            return (
              <div
                key={field}
                className={`border-border/60 bg-muted/40 inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 ${isEditing ? 'ring-primary ring-1' : ''}`}
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
                <span className="text-muted-foreground shrink-0">{icon}</span>
                {isEditing ? (
                  <input
                    type={inputType}
                    value={draftValue}
                    onChange={(e) => handleFieldChange(field, e.target.value)}
                    className="text-foreground placeholder:text-muted-foreground w-16 bg-transparent text-xs font-semibold focus:outline-none"
                    placeholder={field === 'traveler_count' ? '#' : '$'}
                    onClick={(e) => e.stopPropagation()}
                    onBlur={(e) => handleCommitField(field, e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') {
                        e.preventDefault();
                        handleCommitField(field, (e.target as HTMLInputElement).value);
                      } else if (e.key === 'Escape') {
                        e.preventDefault();
                        // Restore original value and close
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
          })}
        </div>
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
