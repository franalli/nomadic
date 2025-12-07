'use client';

import { addDays, addWeeks, nextSaturday } from 'date-fns';
import { AnimatePresence, motion } from 'framer-motion';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { BranchPanel } from '@/components/branches/BranchPanel';
import { ChatPanel, type ChatPanelHandle } from '@/components/chat/ChatPanel';
import { HERO_TAGLINE,HeroSection } from '@/components/layout/HeroSection';
import { useBranchManager } from '@/components/layout/hooks/useBranchManager';
import { useDateRangeSelector } from '@/components/layout/hooks/useDateRangeSelector';
import { useLocalBookingSettings } from '@/components/layout/hooks/useLocalBookingSettings';
import { useTripInputsEditor } from '@/components/layout/hooks/useTripInputsEditor';
import { SplitLayoutView } from '@/components/layout/SplitLayoutView';
import { TripDetailsForm } from '@/components/layout/TripDetailsForm';
import { VibesSection } from '@/components/layout/VibesSection';
import { FeaturesSection } from '@/components/nomadic/features-section';
import { Footer } from '@/components/nomadic/footer';
import { Card, CardContent } from '@/components/ui/card';
import { DEFAULT_TRIP_INPUTS, useDocumentStore } from '@/state/documentStore';
import type {
  BookingTypes,
  DocumentTripInputs,
} from '@/types/document';
import type { ChatPanelActions, ToastType } from '@/types/hooks';

const HERO_TYPING_INTERVAL_MS = 200;
const HERO_TYPING_PAUSE_MS = 8000;

// Toast notification system
const MAX_TOASTS = 3;
const TOAST_DISMISS_MS = 4000;
const TOAST_DISMISS_FAST_MS = 2000;
const TOAST_DISMISS_ERROR_MS = 5000;

export interface Toast {
  id: string;
  message: string;
  type: ToastType;
  createdAt: number;
}

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

export function NomadicLanding() {
  // Document store - single source of truth for trip inputs
  const documentStore = useDocumentStore();
  const storeTripInputs = documentStore.document?.trip_inputs;

  // Derive tripInputs from store (with defaults)
  const tripInputs: DocumentTripInputs = useMemo(() => {
    if (!storeTripInputs) return DEFAULT_TRIP_INPUTS;
    return { ...storeTripInputs };
  }, [storeTripInputs]);

  // Derive booking preferences from tripInputs (with defaults)
  const bookingTypes: BookingTypes = useMemo(() => {
    return tripInputs.booking_types ?? DEFAULT_TRIP_INPUTS.booking_types!;
  }, [tripInputs.booking_types]);

  // Toast notification state - supports multiple stacked toasts
  const [toasts, setToasts] = useState<Toast[]>([]);
  const toastIdRef = useRef(0);

  // Add a toast with optional type (defaults to 'info')
  const addToast = useCallback((message: string, type: ToastType = 'info') => {
    const id = `toast-${++toastIdRef.current}`;
    const newToast: Toast = { id, message, type, createdAt: Date.now() };

    setToasts((prev) => {
      // If at max, remove oldest toast
      const updated = prev.length >= MAX_TOASTS ? prev.slice(1) : prev;
      return [...updated, newToast];
    });
  }, []);

  // Remove a specific toast by ID
  const removeToast = useCallback((id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const [chatKey, setChatKey] = useState(0);
  const chatPanelContainerRef = useRef<HTMLDivElement | null>(null);
  const chatPanelRef = useRef<ChatPanelHandle | null>(null);
  const [typedTagline, setTypedTagline] = useState('');

  // Use hook for local booking settings state management
  const {
    flightSettings,
    hotelSettings,
    transportSettings,
    activitySettings,
    handleUpdateFlightSettings,
    handleUpdateHotelSettings,
    handleUpdateTransportSettings,
    handleUpdateActivitySettings,
  } = useLocalBookingSettings(storeTripInputs, chatPanelRef);

  // Create chat panel actions wrapper for the hook
  const chatPanelActions: ChatPanelActions | null = useMemo(
    () =>
      chatPanelRef.current
        ? { addAssistantMessage: chatPanelRef.current.addAssistantMessage }
        : null,
    // We need chatKey to re-create when panel resets
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [chatKey]
  );

  // Branch manager hook - manages branches, tiles, and generating state
  const branchManager = useBranchManager({
    tripInputs,
    chatPanelContainerRef,
    onToast: addToast,
    onChatKeyIncrement: useCallback(() => setChatKey((prev) => prev + 1), []),
    resetDraft: () => tripInputsEditorRef.current?.resetDraft(),
  });

  // Keep a ref to tripInputsEditor for the branchManager resetDraft callback
  const tripInputsEditorRef = useRef<ReturnType<typeof useTripInputsEditor> | null>(null);

  // Destructure commonly used values from the branch manager hook
  const {
    branches,
    selectedBranchId,
    tilesBranchId,
    branchSelections,
    isGenerating,
    isHydratingSnapshot,
    activeBranchSelection,
    tiles,
    readyToGenerate,
    hasBranchesReady,
    setBranches,
    setSelectedBranchId,
    handleBranchSelect,
    handleStartNewSession,
    handlePlanResult,
    handleTileSelection,
    handleBookTrip,
    handleGeneratePlanStart,
  } = branchManager;

  // Trip inputs editor hook - manages all trip input editing state and handlers
  const tripInputsEditor = useTripInputsEditor({
    tripInputs,
    storeTripInputs,
    branches,
    selectedBranchId,
    chatPanelActions,
    onBranchesChange: setBranches,
    onSelectedBranchIdChange: setSelectedBranchId,
    onToast: addToast,
  });

  // Update ref after tripInputsEditor is created
  tripInputsEditorRef.current = tripInputsEditor;

  // Destructure commonly used values from the hook
  // Note: resetDraft is accessed via tripInputsEditorRef.current in branchManager callback
  const {
    tripInputsDraft,
    editingField,
    selectedLocationBadge,
    vibeInput,
    vibeInputExpanded,
    destinationInput,
    destinationInputExpanded,
    originInput,
    originInputExpanded,
    pendingOrigin,
    pendingDestination,
    pendingVibe,
    setTripInputsDraft,
    setEditingField,
    setSelectedLocationBadge,
    setVibeInput,
    setVibeInputExpanded,
    setDestinationInput,
    setDestinationInputExpanded,
    setOriginInput,
    setOriginInputExpanded,
    handleStartEditingField,
    handleFieldChange,
    handleCommitField,
    handleSetOrigin,
    handleRemoveOrigin,
    handleRemoveTravelerCount,
    handleRemoveBudget,
    handleToggleMultiCity,
    handleAddDestination,
    handleRemoveDestination,
    handleAddVibe,
    handleRemoveVibe,
  } = tripInputsEditor;

  // Date range selector hook - manages calendar state and date selection
  const dateRangeSelector = useDateRangeSelector({
    tripInputs,
    tripInputsDraft,
    setTripInputsDraft,
    chatPanelActions,
    onToast: addToast,
  });

  // Destructure commonly used values from the date range hook
  const {
    calendarOpen,
    selectedDateRange,
    previewDays,
    hasDateValidationWarning,
    handleCalendarDayClick,
    handleCalendarDayMouseEnter,
    handleCalendarMouseLeave,
    handleCalendarOpenChange,
    handleDatePresetClick,
    handleResetDates,
  } = dateRangeSelector;

  // Toast auto-dismiss effect - handles multiple toasts with different timings
  useEffect(() => {
    if (toasts.length === 0) return undefined;

    const timers: NodeJS.Timeout[] = [];

    toasts.forEach((toast, index) => {
      // Calculate dismiss time based on type and queue position
      let dismissTime = TOAST_DISMISS_MS;
      if (toast.type === 'error') {
        dismissTime = TOAST_DISMISS_ERROR_MS;
      } else if (toasts.length >= MAX_TOASTS && index === 0) {
        // Oldest toast when queue is full dismisses faster
        dismissTime = TOAST_DISMISS_FAST_MS;
      }

      const elapsed = Date.now() - toast.createdAt;
      const remaining = Math.max(0, dismissTime - elapsed);

      const timer = setTimeout(() => {
        removeToast(toast.id);
      }, remaining);
      timers.push(timer);
    });

    return () => {
      timers.forEach((timer) => clearTimeout(timer));
    };
  }, [toasts, removeToast]);

  // Typing animation effect
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

  const missingFields = tripInputs.missing_fields ?? [];

  // Check if we have origin or destination to show route
  const hasOrigin = Boolean(tripInputs.origin);
  const hasDestination = (tripInputs.destinations ?? []).length > 0;

  // Check if we have dates to show
  const hasStartDate = Boolean(tripInputs.start_date);
  const hasEndDate = Boolean(tripInputs.end_date);
  const hasDates = hasStartDate || hasEndDate;

  // Trip details section content - passed to ChatPanel
  const tripDetailsSection = {
    content: (
      <TripDetailsForm
        tripInputs={tripInputs}
        tripInputsDraft={tripInputsDraft}
        editingField={editingField}
        hasOrigin={hasOrigin}
        hasDestination={hasDestination}
        hasDates={hasDates}
        hasStartDate={hasStartDate}
        hasEndDate={hasEndDate}
        calendarOpen={calendarOpen}
        selectedDateRange={selectedDateRange}
        previewDays={previewDays}
        hasDateValidationWarning={hasDateValidationWarning}
        selectedLocationBadge={selectedLocationBadge}
        datePresets={DATE_PRESETS}
        originInput={originInput}
        originInputExpanded={originInputExpanded}
        destinationInput={destinationInput}
        destinationInputExpanded={destinationInputExpanded}
        pendingOrigin={pendingOrigin}
        pendingDestination={pendingDestination}
        onStartEditingField={handleStartEditingField}
        onFieldChange={handleFieldChange}
        onCommitField={handleCommitField}
        setTripInputsDraft={setTripInputsDraft}
        setEditingField={setEditingField}
        onSetOrigin={handleSetOrigin}
        onRemoveOrigin={handleRemoveOrigin}
        setOriginInput={setOriginInput}
        setOriginInputExpanded={setOriginInputExpanded}
        onAddDestination={handleAddDestination}
        onRemoveDestination={handleRemoveDestination}
        setDestinationInput={setDestinationInput}
        setDestinationInputExpanded={setDestinationInputExpanded}
        onToggleMultiCity={handleToggleMultiCity}
        onCalendarOpenChange={handleCalendarOpenChange}
        onCalendarDayClick={handleCalendarDayClick}
        onCalendarDayMouseEnter={handleCalendarDayMouseEnter}
        onCalendarMouseLeave={handleCalendarMouseLeave}
        onDatePresetClick={handleDatePresetClick}
        onResetDates={handleResetDates}
        onRemoveTravelerCount={handleRemoveTravelerCount}
        onRemoveBudget={handleRemoveBudget}
        onSelectLocationBadge={setSelectedLocationBadge}
        bookingTypes={bookingTypes}
        flightSettings={flightSettings}
        hotelSettings={hotelSettings}
        activitySettings={activitySettings}
        transportSettings={transportSettings}
        onUpdateFlightSettings={handleUpdateFlightSettings}
        onUpdateHotelSettings={handleUpdateHotelSettings}
        onUpdateActivitySettings={handleUpdateActivitySettings}
        onUpdateTransportSettings={handleUpdateTransportSettings}
      />
    ),
    missingFields,
  };

  // Vibes section content - passed to ChatPanel
  const vibesSection = {
    content: (
      <VibesSection
        vibes={tripInputs.vibes ?? []}
        vibeInput={vibeInput}
        vibeInputExpanded={vibeInputExpanded}
        pendingVibe={pendingVibe}
        onAddVibe={handleAddVibe}
        onRemoveVibe={handleRemoveVibe}
        setVibeInput={setVibeInput}
        setVibeInputExpanded={setVibeInputExpanded}
      />
    ),
  };

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
          tripDetails={tripDetailsSection}
          vibesSection={vibesSection}
          fullHeight={fullHeight}
          hasBranches={hasBranchesReady}
          readyToGenerate={readyToGenerate}
          isGenerating={isGenerating}
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
            branches={branches}
            selectedBranchId={selectedBranchId}
            onBranchSelect={handleBranchSelect}
            branchSelections={branchSelections}
            tiles={tiles}
            tilesBranchId={tilesBranchId}
            selectedTiles={activeBranchSelection}
            onTileToggle={handleTileSelection}
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
      {/* Animated Toast Notifications - Stacked */}
      <div className="fixed left-1/2 top-4 z-50 flex -translate-x-1/2 flex-col items-center gap-2 sm:right-4 sm:left-auto sm:translate-x-0 sm:items-end">
        <AnimatePresence mode="popLayout">
          {toasts.map((toast) => {
            // Determine colors based on toast type
            const typeStyles = {
              error: 'border-destructive/40 bg-destructive/5 text-destructive/70',
              success: 'border-green-500/40 bg-green-500/5 text-green-600/70',
              info: 'border-green-500/40 bg-green-500/5 text-green-600/70',
            };
            const buttonStyles = {
              error: 'text-destructive/60 hover:text-destructive/50',
              success: 'text-green-600/60 hover:text-green-600/50',
              info: 'text-green-600/60 hover:text-green-600/50',
            };

            return (
              <motion.div
                key={toast.id}
                layout
                initial={{ opacity: 0, y: -50, scale: 0.9 }}
                animate={{ opacity: 1, y: 0, scale: 1 }}
                exit={{ opacity: 0, scale: 0.9, y: -20 }}
                transition={{
                  type: 'spring',
                  stiffness: 500,
                  damping: 35,
                  layout: { type: 'spring', stiffness: 500, damping: 35 },
                }}
                role="alert"
                aria-live="polite"
                className={`flex items-center gap-3 rounded-full border px-4 py-2.5 text-sm shadow-lg backdrop-blur-sm sm:rounded-lg sm:py-3 ${typeStyles[toast.type]}`}
              >
                <span className="max-w-[260px] truncate sm:max-w-[320px]">{toast.message}</span>
                <button
                  type="button"
                  className={`text-xs font-semibold transition-colors ${buttonStyles[toast.type]}`}
                  onClick={() => removeToast(toast.id)}
                  aria-label="Dismiss notification"
                >
                  ✕
                </button>
              </motion.div>
            );
          })}
        </AnimatePresence>
      </div>

      {/* Split layout when generating or branches are ready. Don't show split layout just for hydration
          unless we already have branches - otherwise we flash the branch view before knowing if there's a session. */}
      {(isGenerating || hasBranchesReady) ? (
        <SplitLayoutView
          sidebarContent={chatPanelContent(true)}
          mainContent={branchPanelContent}
          typedTagline={typedTagline}
          isGenerating={isGenerating}
          hasBranchesReady={hasBranchesReady}
        />
      ) : (
        /* Original centered layout when no branches */
        <>
          <HeroSection
            typedTagline={typedTagline}
            variant="full"
            chatPanelContainerRef={chatPanelContainerRef}
          >
            <motion.div
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.5, delay: 0.1 }}
              className="mt-2 w-full sm:max-w-[605px]"
            >
              <Card className="bg-card/95 border-white/20 p-0 shadow-2xl backdrop-blur rounded-none sm:rounded-xl border-x-0 sm:border-x">
                <CardContent className="p-0 sm:p-3 sm:pb-0">
                  {chatPanelContent(false)}
                </CardContent>
              </Card>
            </motion.div>
          </HeroSection>

          {hasBranchesReady ? (
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
