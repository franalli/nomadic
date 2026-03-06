'use client';
// TODO: DS spacing audit — requires visual QA pass
/* eslint no-unused-vars: ["error", { "args": "none" }] */
/**
 * StrategyHero
 *
 * Magazine-style strategy card with three variants:
 * - `hero`: Full-width image with editorial typography (Bridge Mode)
 * - `compact`: Trip DNA Bar - single row summary (Full Mode)
 * - `accordion`: Collapsible inline card
 *
 * @see docs/ux_unified_architecture.md Section XII
 */

import {
  ChevronRight,
} from 'lucide-react';
import Image from 'next/image';
import React, { useEffect, useId, useMemo, useState } from 'react';

import { BottomSheet } from '@/components/ui/bottom-sheet';
import { DS } from '@/lib/design-system';
import {
  getCachedDestinationIntel,
  getSpecialistEnrichment,
  normalizeDestinationKey,
  setCachedDestinationIntel,
} from '@/lib/destination-intel-cache';
import { cn } from '@/lib/utils';
import { useDocumentStore } from '@/state/documentStore';
import type { StrategySection } from '@/types/plan-envelope';

import { StrategyHeroAccordion } from './StrategyHeroAccordion';
import { CompactSheetContent } from './StrategyHeroCompactSheet';
import { StrategyHeroContent } from './StrategyHeroContent';
import {
  DEFAULT_STYLE,
  getHeroImage,
  getTopicLabel,
  renderTopicIcon,
  SPECIALIST_STYLE_CLASSES,
} from './StrategyHeroUtils';

type EnrichmentUiState = 'idle' | 'loading' | 'pending' | 'ready' | 'failed';

// =============================================================================
// Main Component Props
// =============================================================================

interface StrategyHeroProps {
  section: StrategySection;
  variant: 'hero' | 'compact' | 'accordion';
  /** Default expanded state for accordion variant */
  defaultExpanded?: boolean;
  /** Controlled expanded state (for parent-managed expansion) */
  isExpanded?: boolean;
  /** Callback when accordion expansion changes */
  onExpandChange?: (expanded: boolean) => void;
  /** @deprecated Click handler - compact mode now self-manages expansion */
  onExpand?: () => void;
}

export function StrategyHero({
  section,
  variant,
  defaultExpanded = false,
  isExpanded: controlledExpanded,
  onExpandChange,
  onExpand
}: StrategyHeroProps) {
  const topic = section.specialist_type || 'general';
  const topicLabel = getTopicLabel(topic);
  const heroImage = getHeroImage(section);

  // Deduplicate constraints — backend may emit the same rule twice
  // Exclude soft/info severity — only count blocking + strong constraints
  const constraints = useMemo(() => {
    const raw = section.constraints_applied;
    if (!raw || raw.length === 0) return [];
    const deduped = [...new Map(raw.map(c => [c.rule || c.reason, c])).values()];
    return deduped.filter(c => {
      const sev = (c as Record<string, string>).severity;
      return !sev || sev === 'blocking' || sev === 'strong';
    });
  }, [section.constraints_applied]);
  const constraintCount = constraints.length;

  // Generate unique IDs for accessibility
  const uniqueId = useId();
  const headerId = `${uniqueId}-header`;
  const contentId = `${uniqueId}-content`;

  // Internal state for sheet (compact mode is now self-contained)
  const [isSheetOpen, setIsSheetOpen] = useState(false);

  // Enriched section data for local_expert fetch-on-open
  const [enrichedSection, setEnrichedSection] = useState<StrategySection | null>(null);
  const [enrichmentUiState, setEnrichmentUiState] = useState<EnrichmentUiState>('idle');
  const [enrichmentErrorCode, setEnrichmentErrorCode] = useState<string | null>(null);
  const [enrichmentRetryNonce, setEnrichmentRetryNonce] = useState(0);
  // Track document existence — becomes false on session reset, cancelling the poller
  const documentExists = useDocumentStore((s) => s.document !== null);
  const messageSendNonce = useDocumentStore((s) => s.messageSendNonce);
  const storeDestination = useDocumentStore((s) => s.document?.trip_inputs?.destination ?? null);

  const displaySection = enrichedSection ?? section;
  const hasTravelIntelligence = Boolean(
    displaySection.travel_intelligence &&
    Object.keys(displaySection.travel_intelligence).length > 0
  );

  // Clear enriched cache when the underlying section changes (e.g. new graph response)
  useEffect(() => {
    setEnrichedSection(null);
    setEnrichmentUiState('idle');
    setEnrichmentErrorCode(null);
  }, [section.id]);

  // Fetch-on-open: load local_expert enrichment when sheet opens and travel_intelligence is empty.
  // Poll while pending and expose terminal failed state with retry.
  useEffect(() => {
    if (!isSheetOpen) return;
    if (section.specialist_type !== 'local_expert') return;
    if (hasTravelIntelligence) {
      setEnrichmentUiState('ready');
      return;
    }

    // Check shared destination-intel cache before starting a network poll
    const destKey = normalizeDestinationKey(storeDestination);
    if (destKey) {
      const cached = getCachedDestinationIntel(destKey);
      if (cached) {
        setEnrichedSection(cached);
        setEnrichmentUiState('ready');
        return;
      }
    }

    let cancelled = false;
    const maxPendingMs = 75_000;
    const startedAt = Date.now();

    const run = async () => {
      setEnrichmentUiState('loading');
      setEnrichmentErrorCode(null);
      let transientErrors = 0;
      let pendingAttempts = 0;

      // Initial delay — give the backend time to start enrichment before first poll
      await new Promise((resolve) => setTimeout(resolve, 3000));
      if (cancelled) return;

      while (!cancelled) {
        let result: Awaited<ReturnType<typeof getSpecialistEnrichment>> = null;
        try {
          result = await getSpecialistEnrichment(section.id);
        } catch {
          transientErrors += 1;
          if (transientErrors >= 3) {
            setEnrichmentUiState('failed');
            setEnrichmentErrorCode('network_error');
            return;
          }
          await new Promise((resolve) => setTimeout(resolve, 2500));
          continue;
        }
        if (cancelled) return;
        transientErrors = 0;

        if (!result) {
          setEnrichmentUiState('failed');
          setEnrichmentErrorCode('not_found');
          return;
        }

        if (result.status === 'ready' && result.data) {
          const enriched = result.data as unknown as StrategySection;
          setEnrichedSection(enriched);
          setEnrichmentUiState('ready');
          // Write back to shared cache for other consumers (PlanFullDensityView)
          if (destKey) setCachedDestinationIntel(destKey, enriched);
          return;
        }

        if (result.status === 'failed') {
          setEnrichmentUiState('failed');
          setEnrichmentErrorCode(result.error_code || 'failed');
          return;
        }

        if (Date.now() - startedAt >= maxPendingMs) {
          setEnrichmentUiState('failed');
          setEnrichmentErrorCode('timeout');
          return;
        }

        setEnrichmentUiState('pending');
        pendingAttempts += 1;
        const suggestedWait = result.retry_after_ms ?? 1500;
        const waitMs = Math.max(2000, Math.min(suggestedWait + pendingAttempts * 150, 5000));
        await new Promise((resolve) => setTimeout(resolve, waitMs));
      }
    };

    run().catch(() => {
      if (!cancelled) {
        setEnrichmentUiState('failed');
        setEnrichmentErrorCode('network_error');
      }
    });

    return () => {
      cancelled = true;
    };

  }, [hasTravelIntelligence, isSheetOpen, section.id, section.specialist_type, enrichmentRetryNonce, documentExists, messageSendNonce, storeDestination]);

  const handleRetryEnrichment = () => {
    setEnrichmentUiState('idle');
    setEnrichmentErrorCode(null);
    setEnrichmentRetryNonce((n) => n + 1);
  };

  // Internal state for accordion expansion (used when not controlled)
  const [internalExpanded, setInternalExpanded] = useState(defaultExpanded);

  // Use controlled state if provided, otherwise use internal state
  const isAccordionExpanded = controlledExpanded !== undefined ? controlledExpanded : internalExpanded;

  // Get specialist colors
  const specialistColors = SPECIALIST_STYLE_CLASSES[topic] || DEFAULT_STYLE;

  // Infeasible state
  const isInfeasible = section.feasibility_status === 'infeasible';

  // Handler for opening the sheet (compact/hero modes)
  const handleExpand = () => {
    if (onExpand) onExpand();
    setIsSheetOpen(true);
  };

  // Handler for toggling accordion expansion
  const handleAccordionToggle = () => {
    const newState = !isAccordionExpanded;
    if (controlledExpanded === undefined) setInternalExpanded(newState);
    onExpandChange?.(newState);
  };

  // Keyboard handler for accordion
  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      handleAccordionToggle();
    } else if (e.key === 'Escape' && isAccordionExpanded) {
      e.preventDefault();
      if (controlledExpanded === undefined) setInternalExpanded(false);
      onExpandChange?.(false);
    }
  };

  const shouldShowEnrichmentNotice =
    section.specialist_type === 'local_expert' &&
    !hasTravelIntelligence &&
    (enrichmentUiState === 'loading' || enrichmentUiState === 'pending' || enrichmentUiState === 'failed');

  const enrichmentErrorLabel =
    enrichmentErrorCode === 'timeout'
      ? 'Local intelligence timed out. You can retry now.'
      : 'Local intelligence failed to load. You can retry now.';

  // --- RENDER: ACCORDION MODE ---
  if (variant === 'accordion') {
    return (
      <StrategyHeroAccordion
        section={section}
        topic={topic}
        topicLabel={topicLabel}
        constraints={constraints}
        headerId={headerId}
        contentId={contentId}
        isAccordionExpanded={isAccordionExpanded}
        specialistColors={specialistColors}
        isInfeasible={isInfeasible}
        onToggle={handleAccordionToggle}
        onKeyDown={handleKeyDown}
      />
    );
  }

  // --- RENDER: COMPACT MODE (Trip DNA Bar) ---
  if (variant === 'compact') {
    return (
      <>
        <button
          type="button"
          onClick={handleExpand}
          className={cn(
            'w-full flex items-center gap-3 p-3 rounded-xl mb-3 text-left transition-all group',
            'bg-zinc-50 dark:bg-white/5 border border-zinc-200 dark:border-white/10',
            'cursor-pointer',
            'hover:border-zinc-300 dark:hover:border-white/20',
            'hover:bg-zinc-100 dark:hover:bg-white/10',
            'hover:shadow-card active:scale-[0.995]',
            isInfeasible && 'opacity-60'
          )}
        >
          <div className="relative w-10 h-10 rounded-lg overflow-hidden shrink-0 bg-zinc-200 dark:bg-zinc-800">
            <Image src={heroImage} alt={section.title} fill className="object-cover" sizes="40px" />
          </div>
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2">
              {renderTopicIcon(topic, "w-3.5 h-3.5 text-emerald-600 dark:text-emerald-400 shrink-0")}
              <span className="text-xs font-bold text-zinc-900 dark:text-white truncate">{topicLabel}</span>
              {!isInfeasible && <span className="text-emerald-600 dark:text-emerald-400 text-xs">✓</span>}
              {isInfeasible && <span className={`px-1.5 py-0.5 rounded ${DS.textSize.nano} font-bold bg-red-100 dark:bg-red-900/30 text-red-600 dark:text-red-400`}>Unavailable</span>}
              {constraintCount > 0 && !isInfeasible && (
                <span className={`px-1.5 py-0.5 rounded-full bg-amber-100 dark:bg-amber-900/30 ${DS.textSize.nano} font-bold text-amber-700 dark:text-amber-400`}>
                  {constraintCount} {constraintCount === 1 ? 'Rule' : 'Rules'}
                </span>
              )}
            </div>
            <p className="text-xs text-zinc-500 dark:text-zinc-400 line-clamp-2 mt-0.5 group-hover:text-zinc-700 dark:group-hover:text-zinc-300">
              {section.one_liner || section.editorial_one_liner ||
                (section.principles?.length > 0 ? section.principles[0] : null) ||
                (constraintCount > 0 ? `${constraintCount} constraint${constraintCount > 1 ? 's' : ''} active` : null) ||
                section.subtitle || 'Tap to view details'}
            </p>
          </div>
          <ChevronRight className="w-4 h-4 text-zinc-400 dark:text-zinc-500 shrink-0 group-hover:text-zinc-600 dark:group-hover:text-zinc-300 transition-colors" />
        </button>
        <BottomSheet open={isSheetOpen} onOpenChange={setIsSheetOpen} title={`${topicLabel} Strategy`} hint="Tap outside to close">
          <div className="space-y-6 pb-24">
            {shouldShowEnrichmentNotice && (
              <div className="rounded-xl border border-zinc-200 bg-zinc-50 px-3 py-2 text-sm text-zinc-700 dark:border-zinc-700 dark:bg-zinc-900/40 dark:text-zinc-300">
                {(enrichmentUiState === 'loading' || enrichmentUiState === 'pending') && (
                  <p>Loading local travel intelligence...</p>
                )}
                {enrichmentUiState === 'failed' && (
                  <div className="flex items-center justify-between gap-3">
                    <p>{enrichmentErrorLabel}</p>
                    <button
                      type="button"
                      onClick={handleRetryEnrichment}
                      className="shrink-0 rounded-md border border-zinc-300 px-2 py-1 text-xs font-semibold text-zinc-800 hover:bg-zinc-100 dark:border-zinc-600 dark:text-zinc-100 dark:hover:bg-zinc-800"
                    >
                      Retry
                    </button>
                  </div>
                )}
              </div>
            )}
            <CompactSheetContent section={displaySection} constraints={constraints} />
          </div>
        </BottomSheet>
      </>
    );
  }

  // --- RENDER: HERO MODE (Magazine Style) ---
  // CRITICAL: Hero mode must also be clickable to open BottomSheet
  return (
    <StrategyHeroContent
      section={section}
      displaySection={displaySection}
      topic={topic}
      topicLabel={topicLabel}
      heroImage={heroImage}
      constraints={constraints}
      isInfeasible={isInfeasible}
      isSheetOpen={isSheetOpen}
      onSheetOpenChange={setIsSheetOpen}
      onExpand={handleExpand}
      shouldShowEnrichmentNotice={shouldShowEnrichmentNotice}
      enrichmentUiState={enrichmentUiState}
      enrichmentErrorLabel={enrichmentErrorLabel}
      onRetryEnrichment={handleRetryEnrichment}
    />
  );
}

export default StrategyHero;
