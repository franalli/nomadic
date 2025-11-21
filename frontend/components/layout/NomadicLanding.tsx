'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { motion } from 'framer-motion';
import {
  CalendarRange,
  Compass,
  MapPin,
  Menu,
  Sparkles,
  User,
  Users,
} from 'lucide-react';

import { BranchPanel } from '@/components/branches/BranchPanel';
import { ChatPanel } from '@/components/chat/ChatPanel';
import { BookingOption } from '@/components/nomadic/booking-option';
import { FeaturesSection } from '@/components/nomadic/features-section';
import { Footer } from '@/components/nomadic/footer';
import { TripCard } from '@/components/nomadic/trip-card';
import { TilesGrid } from '@/components/tiles/TilesGrid';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { MOCK_TRAVEL_OPTIONS, MOCK_TRIPS } from '@/lib/mock-data';
import { API_BASE } from '@/lib/api';
import { clearSessionId, getOrCreateSessionId } from '@/lib/session';
import type {
  SessionSnapshot,
  TilesSearchRequest,
  TilesSearchResponse,
} from '@/types/api';
import type { PlanBranch, TripInputs } from '@/types/plan';
import type { Tile } from '@/types/tile';

type BranchSelectionOverrides = {
  branch?: PlanBranch;
  tripContextId?: number | null;
  errorMessageOverride?: string;
};

type TripInputsDraft = {
  destination?: string | null;
  origin: string;
  start_date: string;
  end_date: string;
  traveler_count: string;
};

const DISPLAY_DATE_FORMAT = 'dd-mm-yyyy';
const today = new Date();
const pad = (value: number) => value.toString().padStart(2, '0');
const TODAY_DISPLAY = `${pad(today.getDate())}-${pad(today.getMonth() + 1)}-${today.getFullYear()}`;
const TODAY_ISO = `${today.getFullYear()}-${pad(today.getMonth() + 1)}-${pad(today.getDate())}`;

const formatDateForDisplay = (value?: string | null): string => {
  if (!value) return '';
  const isoMatch = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
  if (isoMatch) {
    const [, year, month, day] = isoMatch;
    return `${day}-${month}-${year}`;
  }
  return value;
};

const parseDisplayDate = (value: string): string | null => {
  const trimmed = value.trim();
  if (!trimmed) return null;
  const displayMatch = /^(\d{2})-(\d{2})-(\d{4})$/.exec(trimmed);
  if (displayMatch) {
    const [, day, month, year] = displayMatch;
    const iso = `${year}-${month}-${day}`;
    const parsed = new Date(iso);
    if (Number.isNaN(parsed.getTime())) return null;
    return iso;
  }
  const isoMatch = /^(\d{4})-(\d{2})-(\d{2})$/.exec(trimmed);
  if (isoMatch) {
    const parsed = new Date(trimmed);
    if (Number.isNaN(parsed.getTime())) return null;
    return trimmed;
  }
  return null;
};

const toTripInputsDraft = (inputs: TripInputs): TripInputsDraft => ({
  destination: inputs.destination ?? null,
  origin: inputs.origin ?? '',
  start_date: formatDateForDisplay(inputs.start_date) || TODAY_DISPLAY,
  end_date: formatDateForDisplay(inputs.end_date) || TODAY_DISPLAY,
  traveler_count: inputs.traveler_count != null ? String(inputs.traveler_count) : '1',
});

const normalizeTripInputsDraft = (draft: TripInputsDraft): TripInputs => {
  const destination = draft.destination?.trim() || null;
  const origin = draft.origin.trim() || null;
  const startDate = parseDisplayDate(draft.start_date) ?? TODAY_ISO;
  const endDate = parseDisplayDate(draft.end_date) ?? TODAY_ISO;
  const travelerText = draft.traveler_count.trim();
  const parsedTravelerCount = travelerText === '' ? null : Number(travelerText);
  const travelerCount =
    Number.isFinite(parsedTravelerCount) && parsedTravelerCount != null
      ? Math.min(20, Math.max(1, parsedTravelerCount))
      : 1;

  const missingFields: string[] = [];
  if (!destination) missingFields.push('destination');
  if (!origin) missingFields.push('origin');

  return {
    destination,
    origin,
    start_date: startDate,
    end_date: endDate,
    traveler_count: travelerCount,
    missing_fields: missingFields,
  };
};

const DEFAULT_TRIP_INPUTS: TripInputs = {
  destination: null,
  origin: null,
  start_date: TODAY_ISO,
  end_date: TODAY_ISO,
  traveler_count: 1,
  missing_fields: ['destination', 'origin'],
};

const fillTripInputDefaults = (inputs?: TripInputs | null): TripInputs => {
  return normalizeTripInputsDraft(toTripInputsDraft(inputs ?? DEFAULT_TRIP_INPUTS));
};

const sanitizeOrigin = (origin: string | null, destination?: string | null): string | null => {
  if (!origin || !destination) return origin;
  const originNorm = origin.trim().toLowerCase();
  const destinationNorm = destination.trim().toLowerCase();
  if (originNorm && destinationNorm && originNorm === destinationNorm) {
    return null;
  }
  return origin;
};

const HERO_IMAGE =
  'https://images.unsplash.com/photo-1500530855697-b586d89ba3ee?auto=format&fit=crop&w=2000&q=80';
const HERO_VIDEO = '/hiking_video.mp4';

export function NomadicLanding() {
  const [branches, setBranches] = useState<PlanBranch[]>([]);
  const [selectedBranchId, setSelectedBranchId] = useState<string | null>(null);
  const [tiles, setTiles] = useState<Tile[]>([]);
  const [tilesRequestId, setTilesRequestId] = useState<string | null>(null);
  const [tripContextId, setTripContextId] = useState<number | null>(null);
  const [tripInputsDraft, setTripInputsDraft] = useState<TripInputsDraft>(() =>
    toTripInputsDraft(DEFAULT_TRIP_INPUTS)
  );
  const [tripInputs, setTripInputs] = useState<TripInputs>(() =>
    normalizeTripInputsDraft(toTripInputsDraft(DEFAULT_TRIP_INPUTS))
  );
  const [editingField, setEditingField] = useState<keyof TripInputsDraft | null>(null);
  const [toastMessage, setToastMessage] = useState<string | null>(null);
  const [isHydratingSnapshot, setIsHydratingSnapshot] = useState(false);
  const [isResettingSession, setIsResettingSession] = useState(false);
  const [branchesExpanded, setBranchesExpanded] = useState(false);
  const [tilesExpanded, setTilesExpanded] = useState(false);
  const [hasTriggeredChat, setHasTriggeredChat] = useState(false);
  const [chatKey, setChatKey] = useState(0);
  const tilesFetchControllerRef = useRef<AbortController | null>(null);

  const selectedBranch = useMemo(
    () => branches.find((branch) => branch.id === selectedBranchId) ?? null,
    [branches, selectedBranchId]
  );

  const updateFromDraft = useCallback(
    (draft: TripInputsDraft, destinationHint?: string | null) => {
      const normalized = normalizeTripInputsDraft(draft);
      normalized.origin = sanitizeOrigin(
        normalized.origin,
        destinationHint ?? selectedBranch?.destination
      );
      setTripInputs(normalized);
      setTripInputsDraft(draft);
      setEditingField(null);
    },
    [selectedBranch?.destination]
  );

  const applyIncomingTripInputs = useCallback(
    (incoming?: TripInputs | null, destinationHint?: string | null) => {
      const filled = fillTripInputDefaults(incoming);
      filled.origin = sanitizeOrigin(filled.origin, destinationHint);
      filled.destination = filled.destination ?? destinationHint ?? null;
      const draft = toTripInputsDraft(filled);
      updateFromDraft(draft, destinationHint);
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

      setSelectedBranchId(branchId);
      const branch = overrides?.branch ?? branches.find((b) => b.id === branchId);
      if (!branch) return;

      const sessionId = getOrCreateSessionId();
      const parsedBranchId = Number(branchId);
      const branchIdNumber = Number.isFinite(parsedBranchId) ? parsedBranchId : undefined;

      const requestTripContextId = overrides?.tripContextId ?? tripContextId;
      const errorMessageOverride = overrides?.errorMessageOverride;

      const body: TilesSearchRequest = {
        branch_id: branchIdNumber,
        session_id: sessionId || undefined,
        trip_context_id: requestTripContextId ?? undefined,
        destination: branch.destination,
        destination_hint: branch.destination,
      };
      if (branch.origin) body.origin = branch.origin;
      if (branch.start_date) body.start_date = branch.start_date;
      if (branch.end_date) body.end_date = branch.end_date;
      if (branch.traveler_count != null) body.traveler_count = branch.traveler_count;

      try {
        const res = await fetch(`${API_BASE}/v1/tiles/search`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
          signal: controller.signal,
        });

        if (!res.ok) {
          console.error('Failed to fetch tiles for branch', res.status);
          setToastMessage(
            errorMessageOverride ??
              'Unable to refresh options for that suggestion. Please try again.'
          );
          return;
        }

        const data: TilesSearchResponse = await res.json();
        if (controller.signal.aborted) return;
        setTiles(data.tiles);
        setTilesRequestId(data.tiles_request_id ?? data.request_id ?? null);
        setTilesExpanded(true);
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
    [abortTilesFetch, branches, tripContextId]
  );

  useEffect(() => {
    if (!toastMessage) return undefined;
    const timer = window.setTimeout(() => setToastMessage(null), 4000);
    return () => window.clearTimeout(timer);
  }, [toastMessage]);

  useEffect(() => {
    let cancelled = false;

    async function hydrateSessionSnapshot() {
      try {
        setIsHydratingSnapshot(true);
        const sessionId = getOrCreateSessionId();
        if (!sessionId) return;

        const res = await fetch(
          `${API_BASE}/v1/session/snapshot?session_id=${sessionId}`
        );
        if (!res.ok) return;

        const data: SessionSnapshot = await res.json();
        if (cancelled) return;

        if (data.trip_context) {
          setTripContextId(data.trip_context.id);
          setHasTriggeredChat(true);
        }

        if (!data.branches.length) return;

        const hydratedBranches: PlanBranch[] = data.branches.map((branch) => ({
          id: String(branch.id),
          label: branch.label,
          description: branch.description,
          destination: branch.destination,
        }));

        setBranches(hydratedBranches);
        setBranchesExpanded(true);

        const fallbackBranchId =
          data.primary_branch_id != null
            ? String(data.primary_branch_id)
            : hydratedBranches[0].id;
        const fallbackBranch =
          hydratedBranches.find((branch) => branch.id === fallbackBranchId) ||
          hydratedBranches[0];

        setSelectedBranchId(fallbackBranchId);

        const snapshotTiles = data.tiles ?? [];
        setTiles(snapshotTiles);
        setTilesRequestId(null);

        if (snapshotTiles.length > 0) {
          setTilesExpanded(true);
        }

        const shouldFetchTiles = snapshotTiles.length === 0 && Boolean(fallbackBranch);
        if (shouldFetchTiles && fallbackBranch) {
          const overrides: BranchSelectionOverrides | undefined = data.trip_context
            ? {
                branch: fallbackBranch,
                tripContextId: data.trip_context.id,
                errorMessageOverride:
                  'We restored your suggestions but could not refresh options automatically. Select a suggestion to try again.',
              }
            : {
                branch: fallbackBranch,
                tripContextId: null,
                errorMessageOverride:
                  'We restored your suggestions but could not refresh options automatically. Select a suggestion to try again.',
              };

          await handleBranchSelect(fallbackBranchId, overrides);
        }
      } catch (error) {
        console.error('Failed to hydrate session snapshot', error);
        setToastMessage(
          'Unable to reload your previous session. You can still plan a new trip.'
        );
      } finally {
        setIsHydratingSnapshot(false);
      }
    }

    hydrateSessionSnapshot();

    return () => {
      cancelled = true;
    };
    // We intentionally run this only once on mount to restore the last session snapshot.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleClearContext = useCallback(() => {
    abortTilesFetch();
    setTripContextId(null);
    setBranches([]);
    setSelectedBranchId(null);
    setTiles([]);
    setTilesRequestId(null);
    applyIncomingTripInputs(DEFAULT_TRIP_INPUTS, null);
    setBranchesExpanded(false);
    setTilesExpanded(false);
    setHasTriggeredChat(false);
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
    }

    setToastMessage(
      didResetServerState
        ? 'Started a fresh planning session.'
        : 'Cleared your local planner, but the previous session may reappear if you refresh.'
    );
  }, [abortTilesFetch, handleClearContext]);

  const handleStartEditingField = useCallback(
    (field: keyof TripInputsDraft) => {
      setEditingField(field);
    },
    []
  );

  const handleFieldChange = useCallback((field: keyof TripInputsDraft, value: string) => {
    setTripInputsDraft((prev) => (prev ? { ...prev, [field]: value } : prev));
  }, []);

  const handleCommitField = useCallback(
    (field?: keyof TripInputsDraft, value?: string) => {
      setTripInputsDraft((prev) => {
        const base = prev ?? toTripInputsDraft(tripInputs);
        const next = field ? { ...base, [field]: value ?? base[field] } : base;
        updateFromDraft(next, selectedBranch?.destination);
        return next;
      });
    },
    [tripInputs, selectedBranch?.destination, updateFromDraft]
  );

  useEffect(() => () => abortTilesFetch(), [abortTilesFetch]);

  const handlePlanResult = useCallback(
    (result: {
      tripContextId: number | null;
      branches: PlanBranch[];
      tiles: Tile[];
      primaryBranchId: string | null;
      tilesRequestId: string | null;
      tripInputs?: TripInputs | null;
    }) => {
      setTripContextId(result.tripContextId);
      setBranches(result.branches);
      setTiles(result.tiles);
      setTilesRequestId(result.tilesRequestId);
      const destinationHint = result.branches[0]?.destination ?? null;
      applyIncomingTripInputs(result.tripInputs ?? undefined, destinationHint);
      setSelectedBranchId(result.primaryBranchId);
      setHasTriggeredChat(true);

      if (result.branches.length > 0) {
        setBranchesExpanded(true);
      }
      if (result.tiles.length > 0) {
        setTilesExpanded(true);
      }
    },
    [applyIncomingTripInputs]
  );

  const handleChatTriggered = useCallback(() => {
    setHasTriggeredChat(true);
  }, []);

  const showResults = hasTriggeredChat || branches.length > 0 || tiles.length > 0;
  const missingFields = tripInputs.missing_fields ?? [];
  const isMissingField = (key: string, value?: string | number | null) =>
    !value || missingFields.includes(key);
  const formatTravelers = (value?: number | null) =>
    value != null ? `${value} traveler${value === 1 ? '' : 's'}` : 'Needed';

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

          <div className="mx-auto flex max-w-6xl flex-col items-center gap-6 px-4 pb-12 pt-6">
            <div className="-mt-8 space-y-6 text-center text-white">
              <h1 className="font-display text-4xl font-bold leading-tight sm:text-5xl lg:text-6xl">
                Roam freely. <span className="text-accent">We plan the rest.</span>
              </h1>
            </div>

            <motion.div
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.5, delay: 0.1 }}
              className="mt-8 w-full max-w-2xl"
            >
              <Card className="bg-card/95 border-white/20 p-1 shadow-2xl backdrop-blur">
                <CardContent className="p-3 sm:p-4">
                  <ChatPanel
                    key={chatKey}
                    tripContextId={tripContextId}
                    selectedBranchId={selectedBranchId}
                    tripInputs={tripInputs}
                    onPlanResult={handlePlanResult}
                    onChatTriggered={handleChatTriggered}
                  />
                </CardContent>
              </Card>
            </motion.div>
          </div>
        </div>
      </div>

      <section className="bg-background pb-16 pt-12">
        <div className="mx-auto flex max-w-6xl flex-col gap-8 px-4">
          {showResults ? (
            <>
              <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                <div>
                  <p className="text-muted-foreground text-xs font-semibold uppercase tracking-wide">
                    Let's dive right into it
                  </p>
                  <h2 className="text-foreground font-display text-2xl font-bold sm:text-3xl">
                    Your Destinations and Best Booking Options
                  </h2>
                  <p className="text-muted-foreground text-sm">
                    Suggestions and options expand only after you spark the chat.
                  </p>
                </div>
                <Button
                  variant="outline"
                  size="sm"
                  disabled={isResettingSession}
                  onClick={handleStartNewSession}
                >
                  {isResettingSession ? 'Resetting…' : 'Start fresh'}
                </Button>
              </div>

              {tripInputs && (
                <Card className="border-primary/30 bg-card/90 border shadow-lg">
                  <CardContent className="flex flex-col gap-4 p-4">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <div>
                        <p className="text-muted-foreground text-xs font-semibold uppercase tracking-wide">
                          Trip details I'm tracking
                        </p>
                        <p className="text-muted-foreground text-sm">
                          Update them here or in chat—I’ll keep prompting until each field is locked in.
                        </p>
                        <p className="text-muted-foreground text-xs">
                          Click any field to edit it instantly.
                        </p>
                      </div>
                      <div className="flex items-center gap-2">
                        <span
                          className={`rounded-full px-3 py-1 text-[11px] font-semibold uppercase tracking-wide ${
                            missingFields.length > 0
                              ? 'bg-amber-100 text-amber-700'
                              : 'bg-emerald-100 text-emerald-700'
                          }`}
                        >
                          {missingFields.length > 0 ? 'Need more info' : 'Ready to search'}
                        </span>
                      </div>
                    </div>
                    <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
                      {(['origin', 'start_date', 'end_date', 'traveler_count'] as const).map(
                        (field) => {
                          const isEditing = editingField === field;
                          const draftBase = tripInputsDraft ?? toTripInputsDraft(tripInputs);
                          const draftValue = draftBase ? draftBase[field] : '';

                          let displayValue = 'Needed';
                          if (field === 'traveler_count') {
                            displayValue =
                              tripInputs.traveler_count != null
                                ? formatTravelers(tripInputs.traveler_count)
                                : '1 traveler';
                          } else if (field === 'start_date' || field === 'end_date') {
                            const formatted = formatDateForDisplay(
                              tripInputs[field as keyof TripInputs] as string | null | undefined
                            );
                            displayValue = formatted || 'Needed';
                          } else {
                            displayValue =
                              (tripInputs[field as keyof TripInputs] as string | null | undefined) ||
                              'Needed';
                          }

                          const icon =
                            field === 'origin' ? (
                              <MapPin className="h-4 w-4" />
                            ) : field === 'traveler_count' ? (
                              <Users className="h-4 w-4" />
                            ) : (
                              <CalendarRange className="h-4 w-4" />
                            );

                          const label =
                            field === 'origin'
                              ? 'Origin'
                              : field === 'start_date'
                                ? 'Start'
                                : field === 'end_date'
                                  ? 'End'
                                  : 'Travelers';

                          const inputType = field === 'traveler_count' ? 'number' : 'text';

                          return (
                            <div
                              key={field}
                              className="border-border/60 bg-muted/40 rounded-lg border px-3 py-2"
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
                              <div className="text-muted-foreground flex items-center gap-2 text-xs font-semibold uppercase tracking-wide">
                                {icon}
                                {label}
                              </div>
                              {isEditing ? (
                                <div className="mt-2 space-y-2">
                                  <input
                                    type={inputType}
                                    value={draftValue}
                                    onChange={(e) =>
                                      handleFieldChange(field, e.target.value)
                                    }
                                    className="border-border/60 bg-card/30 text-foreground placeholder:text-muted-foreground w-full rounded-md border px-2 py-1 text-sm focus:border-primary focus:outline-none"
                                    placeholder={
                                      field === 'traveler_count'
                                        ? 'Number of travelers'
                                        : field === 'origin'
                                          ? 'City or airport'
                                          : DISPLAY_DATE_FORMAT
                                    }
                                    onClick={(e) => e.stopPropagation()}
                                    onBlur={(e) => handleCommitField(field, e.target.value)}
                                    onKeyDown={(e) => {
                                      if (e.key === 'Enter') {
                                        e.preventDefault();
                                        handleCommitField(field, (e.target as HTMLInputElement).value);
                                      }
                                    }}
                                    autoFocus
                                  />
                                </div>
                              ) : (
                                <div
                                  className={`text-sm font-semibold ${
                                    isMissingField(field, tripInputs[field as keyof TripInputs])
                                      ? 'text-amber-600'
                                      : 'text-foreground'
                                  }`}
                                >
                                  {displayValue}
                                </div>
                              )}
                            </div>
                          );
                        }
                      )}
                    </div>
                  </CardContent>
                </Card>
              )}

              <div className="grid gap-6 lg:grid-cols-[1.2fr_1fr]">
                <Card className="from-primary/10 via-card/95 to-background relative overflow-hidden border-none bg-gradient-to-br shadow-xl backdrop-blur">
                  <div className="bg-primary/25 pointer-events-none absolute -left-20 -top-24 h-48 w-48 rounded-full blur-3xl" />
                  <div className="bg-accent/15 pointer-events-none absolute bottom-0 right-0 h-40 w-40 rounded-full blur-3xl" />
                  <div className="relative flex items-center justify-between gap-3 px-5 py-4">
                    <div className="space-y-1">
                      <div className="bg-primary/15 text-primary inline-flex items-center gap-2 rounded-full px-3 py-1 text-[11px] font-semibold uppercase tracking-wide">
                        <Sparkles className="h-4 w-4" />
                        Suggestions for You
                      </div>
                      <h3 className="text-foreground font-display text-xl font-bold">
                        Curated suggestions from the chat
                      </h3>
                      <p className="text-muted-foreground text-sm">
                        Trip ideas show here after your first prompt.
                      </p>
                    </div>
                    <Button
                      variant="secondary"
                      size="sm"
                      onClick={() => setBranchesExpanded((prev) => !prev)}
                      disabled={!hasTriggeredChat}
                      className="bg-white/5 text-white shadow-sm hover:bg-white/10 disabled:opacity-60"
                    >
                      {branchesExpanded ? 'Hide' : 'Show'}
                    </Button>
                  </div>
                  <div
                    className={`grid transition-[grid-template-rows] duration-300 ease-out ${
                      branchesExpanded && hasTriggeredChat
                        ? 'grid-rows-[1fr]'
                        : 'grid-rows-[0fr]'
                    }`}
                  >
                    <CardContent className="overflow-hidden">
                      {isHydratingSnapshot && branches.length === 0 ? (
                        <p className="text-muted-foreground text-sm">
                          Restoring your last session…
                        </p>
                      ) : branches.length === 0 ? (
                        <p className="text-muted-foreground text-sm">
                          Start chatting to generate suggestions for you.
                        </p>
                      ) : (
                        <BranchPanel
                          branches={branches}
                          selectedBranchId={selectedBranchId}
                          onBranchSelect={handleBranchSelect}
                        />
                      )}
                    </CardContent>
                  </div>
                </Card>

                <Card className="from-accent/10 via-card/95 to-background relative overflow-hidden border-none bg-gradient-to-br shadow-xl backdrop-blur">
                  <div className="bg-accent/25 pointer-events-none absolute -left-16 -top-10 h-40 w-40 rounded-full blur-3xl" />
                  <div className="bg-primary/15 pointer-events-none absolute bottom-0 right-0 h-36 w-36 rounded-full blur-3xl" />
                  <div className="relative flex items-center justify-between gap-3 px-5 py-4">
                    <div className="space-y-1">
                      <div className="bg-accent/15 text-accent inline-flex items-center gap-2 rounded-full px-3 py-1 text-[11px] font-semibold uppercase tracking-wide">
                        <Sparkles className="h-4 w-4" />
                        Your Best Options
                      </div>
                      <h3 className="text-foreground font-display text-xl font-bold">
                        Live options tailored to your suggestions
                      </h3>
                      <p className="text-muted-foreground text-sm">
                        Live options refresh after you pick a suggestion.
                      </p>
                    </div>
                    <Button
                      variant="secondary"
                      size="sm"
                      onClick={() => setTilesExpanded((prev) => !prev)}
                      disabled={!hasTriggeredChat}
                      className="bg-white/5 text-white shadow-sm hover:bg-white/10 disabled:opacity-60"
                    >
                      {tilesExpanded ? 'Hide' : 'Show'}
                    </Button>
                  </div>
                  <div
                    className={`grid transition-[grid-template-rows] duration-300 ease-out ${
                      tilesExpanded && hasTriggeredChat
                        ? 'grid-rows-[1fr]'
                        : 'grid-rows-[0fr]'
                    }`}
                  >
                    <CardContent className="overflow-hidden">
                      {tiles.length === 0 ? (
                        <p className="text-muted-foreground text-sm">
                          Pick a suggestion to see your best options.
                        </p>
                      ) : (
                        <TilesGrid
                          tiles={tiles}
                          activeBranch={selectedBranch}
                          tilesRequestId={tilesRequestId}
                        />
                      )}
                    </CardContent>
                  </div>
                </Card>
              </div>
            </>
          ) : (
            <>
              <div className="flex items-center justify-between gap-4">
                <div>
                  <p className="text-muted-foreground text-xs font-semibold uppercase tracking-wide">
                    Inspiration
                  </p>
                  <h2 className="text-foreground font-display text-2xl font-bold sm:text-3xl">
                    Curated escapes while you plan
                  </h2>
                  <p className="text-muted-foreground text-sm">
                    Explore a few AI-picked ideas before you kick off the planner chat.
                  </p>
                </div>
              </div>
              <div className="grid gap-6 lg:grid-cols-[1.4fr_1fr]">
                <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                  {MOCK_TRIPS.map((trip, idx) => (
                    <TripCard key={trip.id} trip={trip} index={idx} />
                  ))}
                </div>
                <Card className="border-border/70 bg-card/90 shadow-lg">
                  <CardContent className="space-y-4 p-5">
                    <div className="flex items-center justify-between">
                      <div>
                        <p className="text-muted-foreground text-xs font-semibold uppercase tracking-wide">
                          Sample suggestions
                        </p>
                        <h3 className="text-foreground font-display text-xl font-bold">
                          Travel options to spark ideas
                        </h3>
                      </div>
                    </div>
                    <div className="space-y-3">
                      {MOCK_TRAVEL_OPTIONS.map((option, idx) => (
                        <BookingOption key={option.id} option={option} index={idx} />
                      ))}
                    </div>
                  </CardContent>
                </Card>
              </div>
            </>
          )}
        </div>
      </section>

      <FeaturesSection />
      <Footer />
    </div>
  );
}
