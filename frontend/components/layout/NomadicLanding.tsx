'use client';

import { addDays, addWeeks, nextSaturday } from 'date-fns';
import { motion } from 'framer-motion';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { BranchPanel } from '@/components/branches/BranchPanel';
import { ChatPanel, type ChatPanelHandle } from '@/components/chat/ChatPanel';
import { HeroSection, HERO_TAGLINE } from '@/components/layout/HeroSection';
import { useBranchManager } from '@/components/layout/hooks/useBranchManager';
import { useDateRangeSelector } from '@/components/layout/hooks/useDateRangeSelector';
import { useTripInputsEditor, type ChatPanelActions } from '@/components/layout/hooks/useTripInputsEditor';
import { SplitLayoutView } from '@/components/layout/SplitLayoutView';
import {
  TripDetailsForm,
  type TripInputsDraft,
} from '@/components/layout/TripDetailsForm';
import { VibesSection } from '@/components/layout/VibesSection';
import { FeaturesSection } from '@/components/nomadic/features-section';
import { Footer } from '@/components/nomadic/footer';
import { Card, CardContent } from '@/components/ui/card';
import { DEFAULT_TRIP_INPUTS, useDocumentStore } from '@/state/documentStore';
import type { DocumentTripInputs } from '@/types/document';

const HERO_TYPING_INTERVAL_MS = 200;
const HERO_TYPING_PAUSE_MS = 8000;

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

  const [toastMessage, setToastMessage] = useState<string | null>(null);
  const [chatKey, setChatKey] = useState(0);
  const chatPanelContainerRef = useRef<HTMLDivElement | null>(null);
  const chatPanelRef = useRef<ChatPanelHandle | null>(null);
  const [typedTagline, setTypedTagline] = useState('');

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
    onToast: setToastMessage,
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
    branchTileNotes,
    branchTileCounts,
    branchSelections,
    isGenerating,
    isHydratingSnapshot,
    selectedBranch,
    activeBranchSelection,
    branchesWithTileNotes,
    tiles,
    readyToGenerate,
    hasBranchesReady,
    setBranches,
    setSelectedBranchId,
    handleBranchSelect,
    handleStartNewSession,
    handlePlanResult,
    handleTileSelection,
    handleTilesTabChange,
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
    onToast: setToastMessage,
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
    onToast: setToastMessage,
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

  // Toast auto-dismiss effect
  useEffect(() => {
    if (!toastMessage) return undefined;
    const timer = window.setTimeout(() => setToastMessage(null), 4000);
    return () => window.clearTimeout(timer);
  }, [toastMessage]);

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

  // Always show trip details once user has chatted - grid layout with label + input per field
  const tripDetailsContent = (
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
    />
  );

  // Vibes section content - separate collapsible
  const vibesContent = (
    <VibesSection
      vibes={tripInputs.vibes ?? []}
      vibeInput={vibeInput}
      vibeInputExpanded={vibeInputExpanded}
      onAddVibe={handleAddVibe}
      onRemoveVibe={handleRemoveVibe}
      setVibeInput={setVibeInput}
      setVibeInputExpanded={setVibeInputExpanded}
    />
  );

  // Memoize prop objects to prevent unnecessary ChatPanel re-renders
  const tripDetailsSection = useMemo(
    () =>
      tripDetailsContent
        ? { content: tripDetailsContent, missingFields }
        : undefined,
    [tripDetailsContent, missingFields]
  );

  const vibesSectionMemo = useMemo(
    () => (vibesContent ? { content: vibesContent } : undefined),
    [vibesContent]
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
          tripDetails={tripDetailsSection}
          vibesSection={vibesSectionMemo}
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
              className="mt-8 w-full max-w-xl"
            >
              <Card className="bg-card/95 border-white/20 p-1 shadow-2xl backdrop-blur">
                <CardContent className="p-3 sm:p-4">
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
