'use client';

/**
 * useChatSse — SSE/streaming connection manager for ChatPanel.
 *
 * Owns the `streamGraphPlan` call and all of its callbacks (onToken,
 * onNodeStatus, onPartial, onComplete, onError).  ChatPanel passes in
 * all required state-setters and refs; this hook returns a single
 * `executeStream` function that ChatPanel calls inside sendMessageCore.
 *
 * No JSX — pure side-effect hook.
 */

import { useCallback, useEffect, useRef } from 'react';

import { isBootstrap, isStrategyReady } from '@/components/plan/planStateHelpers';
import { useToast } from '@/components/ui/toast';
import { useMapSync } from '@/hooks/useMapSync';
import { trackEvent } from '@/lib/analytics';
import {
  type DayCardsPartialPayload,
  type SpecialistPreviewActivity,
  type SpecialistPreviewPayload,
  type SpecialistPreviewSection,
  type SSEFeasibilityWarningEvent,
  type SSENodeStatusEvent,
  type SSEPartialEvent,
  streamGraphPlan,
} from '@/lib/api-streaming';
import { debugLog } from '@/lib/debug';
import { classifyNodeAction, shouldShowLoaderForNode } from '@/lib/loaderConfig';
import { useChatStore } from '@/state/chatStore';
import { useDocumentStore } from '@/state/documentStore';
import { useMobileNavStore } from '@/state/mobileNavStore';
import type { GraphPlanResponse, PlanDocumentData } from '@/types/document';
import type { DayBlock, DayCard, StrategySection } from '@/types/plan-envelope';

// Re-exported helpers kept colocated with their consumer
const READY_MESSAGE_ID_PREFIX = 'ready_';

/**
 * Block `activity_type` values that do NOT count as a real, scheduled activity
 * when deciding whether a graph response actually built an itinerary. Mirrors
 * the anchor/placeholder handling in lib/dayIntensity.ts — arrival, departure,
 * check-in and check-out are logistics anchors that arrive as `activity_type`
 * (not `buffer_type`), and free_day/placeholder are empty-day markers.
 */
const NON_ACTIVITY_BLOCK_TYPES = new Set([
  'free_day',
  'placeholder',
  'arrival',
  'departure',
  'check-in',
  'check-out',
]);

function getErrorMessage(error: Error): string {
  const message = error.message?.toLowerCase() ?? '';
  if (
    message.includes('session_state exceeds 64kb limit') ||
    message.includes('64kb limit')
  ) {
    return 'This trip got too large to send in one chat turn. Refresh the page to reload the saved plan, then try again.';
  }
  if (
    message.includes('network') ||
    message.includes('fetch') ||
    message.includes('failed to fetch')
  ) {
    return "Couldn't connect to the server. Please check your internet connection and try again.";
  }
  if (message.includes('timeout') || message.includes('timed out')) {
    return 'The request took too long. Try a simpler query or check your connection.';
  }
  if (
    message.includes('rate limit') ||
    message.includes('too many requests') ||
    message.includes('429')
  ) {
    return "You're sending requests too quickly. Please wait a moment before trying again.";
  }
  if (
    message.includes('unauthorized') ||
    message.includes('401') ||
    message.includes('authentication')
  ) {
    return 'Session expired. Please refresh the page and try again.';
  }
  if (
    message.includes('500') ||
    message.includes('internal server') ||
    message.includes('server error')
  ) {
    return 'Something went wrong on our end. Please try again in a few moments.';
  }
  if (message.includes('invalid') || message.includes('validation')) {
    return 'Invalid request. Try rephrasing or adjusting trip details.';
  }
  return 'An issue occurred. Try again or adjust the message.';
}

function fingerprintDayCard(card: DayCard): string {
  return JSON.stringify(card);
}

function findFirstChangedDay(
  previousDayCards: DayCard[] | undefined,
  nextDayCards: DayCard[] | undefined
): number | null {
  if (!previousDayCards?.length || !nextDayCards?.length) return null;

  const previousByDay = new Map(
    previousDayCards.map((card) => [card.day_number, fingerprintDayCard(card)])
  );
  const nextByDay = new Map(
    nextDayCards.map((card) => [card.day_number, fingerprintDayCard(card)])
  );
  const orderedDays = Array.from(
    new Set([...previousByDay.keys(), ...nextByDay.keys()])
  ).sort((a, b) => a - b);

  for (const dayNumber of orderedDays) {
    if (previousByDay.get(dayNumber) !== nextByDay.get(dayNumber)) {
      return nextByDay.has(dayNumber) ? dayNumber : (nextDayCards[0]?.day_number ?? null);
    }
  }

  return null;
}

function normalizePreviewText(value: string | null | undefined): string | undefined {
  const trimmed = value?.trim();
  return trimmed ? trimmed : undefined;
}

function uniqueNonEmptyStrings(values: Array<string | null | undefined> | undefined): string[] {
  if (!values?.length) return [];

  return Array.from(
    new Set(
      values
        .map((value) => value?.trim())
        .filter((value): value is string => Boolean(value))
    )
  );
}

function formatPreviewTitle(value: string | undefined): string {
  if (!value) return 'Specialist Preview';

  return value
    .split('_')
    .filter(Boolean)
    .map((segment) => segment.charAt(0).toUpperCase() + segment.slice(1))
    .join(' ');
}

function previewToStrategySection(
  preview: SpecialistPreviewSection,
  fallbackTopic?: string
): StrategySection | null {
  if (!preview) return null;

  const specialistType =
    normalizePreviewText(preview.specialist_type) ?? normalizePreviewText(fallbackTopic);
  const title = normalizePreviewText(preview.title) ?? formatPreviewTitle(specialistType);
  const oneLiner = normalizePreviewText(preview.one_liner);
  const highlights = uniqueNonEmptyStrings(preview.highlights).slice(0, 5);
  const previewTitles = highlights.length > 0 ? highlights : [title];
  const contentAdded = previewTitles
    .map((itemTitle) => ({
      title: itemTitle,
      ...(oneLiner && { description: oneLiner }),
    }))
    .slice(0, 3);

  return {
    id:
      normalizePreviewText(preview.id) ??
      `preview_${(specialistType ?? title).toLowerCase().replace(/\s+/g, '_')}`,
    title,
    specialist_type: specialistType,
    one_liner: oneLiner,
    principles: oneLiner ? [oneLiner] : [],
    must_dos: highlights,
    optional_upgrades: [],
    logistics_notes: [],
    ...(normalizePreviewText(preview.hero_image) && {
      hero_image: normalizePreviewText(preview.hero_image),
    }),
    ...(preview.feasibility_status && {
      feasibility_status: preview.feasibility_status,
    }),
    ...(normalizePreviewText(preview.feasibility_reason) && {
      feasibility_reason: normalizePreviewText(preview.feasibility_reason),
    }),
    ...(normalizePreviewText(preview.alternative_suggestion) && {
      alternative_suggestion: normalizePreviewText(preview.alternative_suggestion),
    }),
    ...(contentAdded.length > 0 && { content_added: contentAdded }),
    bullets: highlights.length > 0 ? highlights : oneLiner ? [oneLiner] : [],
  };
}

function deriveStrategySectionsFromSpecialistPreview(
  payload: SpecialistPreviewPayload
): StrategySection[] {
  if (Array.isArray(payload.strategy_sections) && payload.strategy_sections.length > 0) {
    return payload.strategy_sections;
  }

  if (!Array.isArray(payload.sections) || payload.sections.length === 0) {
    return [];
  }

  return payload.sections
    .map((section, index) => previewToStrategySection(section, payload.topics?.[index]))
    .filter((section): section is StrategySection => section !== null);
}

function derivePreviewActivitiesFromSpecialistPreview(
  payload: SpecialistPreviewPayload
): SpecialistPreviewActivity[] {
  if (Array.isArray(payload.activities) && payload.activities.length > 0) {
    return payload.activities.filter((activity) => Boolean(activity?.title?.trim()));
  }

  if (!Array.isArray(payload.sections) || payload.sections.length === 0) {
    return [];
  }

  const activities: SpecialistPreviewActivity[] = [];

  payload.sections.forEach((section, index) => {
    const specialistType =
      normalizePreviewText(section.specialist_type) ??
      normalizePreviewText(payload.topics?.[index]);
    if (!specialistType) return;

    const titles = uniqueNonEmptyStrings(section.highlights);
    const fallbackTitle =
      normalizePreviewText(section.title) ?? formatPreviewTitle(specialistType);

    for (const title of (titles.length > 0 ? titles : [fallbackTitle])) {
      activities.push({
        title,
        specialist_type: specialistType,
        description: normalizePreviewText(section.one_liner),
        duration_hours: 3,
      });
    }
  });

  return activities.slice(0, 6);
}

function normalizeSpecialistPreviewPayload(
  payload: SpecialistPreviewPayload,
  currentSections: StrategySection[] | undefined
): SpecialistPreviewPayload {
  const previewActivities = derivePreviewActivitiesFromSpecialistPreview(payload);
  const hasAuthoritativeStrategySections =
    Array.isArray(payload.strategy_sections) && payload.strategy_sections.length > 0;
  const previewStrategySections: StrategySection[] = hasAuthoritativeStrategySections
    ? payload.strategy_sections ?? []
    : deriveStrategySectionsFromSpecialistPreview(payload);
  const mergedStrategySections =
    hasAuthoritativeStrategySections
      ? previewStrategySections
      : previewStrategySections.length > 0
      ? mergePreviewStrategySections(currentSections, previewStrategySections)
      : [];

  return {
    ...payload,
    ...(previewActivities.length > 0 && { activities: previewActivities }),
    ...(mergedStrategySections.length > 0 && {
      strategy_sections: mergedStrategySections,
    }),
  };
}

function mergePreviewSection(existing: StrategySection, incoming: StrategySection): StrategySection {
  return {
    ...existing,
    ...incoming,
    title: incoming.title || existing.title,
    specialist_type: incoming.specialist_type ?? existing.specialist_type,
    one_liner: incoming.one_liner ?? existing.one_liner,
    editorial_one_liner: incoming.editorial_one_liner ?? existing.editorial_one_liner,
    principles: incoming.principles.length > 0 ? incoming.principles : existing.principles,
    must_dos: incoming.must_dos.length > 0 ? incoming.must_dos : existing.must_dos,
    optional_upgrades:
      incoming.optional_upgrades.length > 0
        ? incoming.optional_upgrades
        : existing.optional_upgrades,
    logistics_notes:
      incoming.logistics_notes.length > 0
        ? incoming.logistics_notes
        : existing.logistics_notes,
    bullets: incoming.bullets.length > 0 ? incoming.bullets : existing.bullets,
    content_added:
      incoming.content_added && incoming.content_added.length > 0
        ? incoming.content_added
        : existing.content_added,
    hero_image: incoming.hero_image ?? existing.hero_image,
    feasibility_status: incoming.feasibility_status ?? existing.feasibility_status,
    feasibility_reason: incoming.feasibility_reason ?? existing.feasibility_reason,
    alternative_suggestion:
      incoming.alternative_suggestion ?? existing.alternative_suggestion,
  };
}

function mergePreviewStrategySections(
  currentSections: StrategySection[] | undefined,
  incomingSections: StrategySection[]
): StrategySection[] {
  if (!currentSections?.length) {
    return incomingSections;
  }

  const merged = [...currentSections];

  for (const incoming of incomingSections) {
    const existingIndex = merged.findIndex((section) => {
      if (incoming.specialist_type && section.specialist_type) {
        return section.specialist_type === incoming.specialist_type;
      }

      return section.id === incoming.id;
    });

    if (existingIndex === -1) {
      merged.push(incoming);
      continue;
    }

    merged[existingIndex] = mergePreviewSection(merged[existingIndex], incoming);
  }

  return merged;
}

// ─────────────────────────────────────────────────────────────────────────────
// Types (canonical definitions live in ./chatSseTypes.ts)
// ─────────────────────────────────────────────────────────────────────────────

export type {
  ChatSseCallbacks,
  ChatSseRefs,
  ExecuteStreamParams,
} from './chatSseTypes';

import type {
  ChatSseCallbacks,
  ChatSseRefs,
  ExecuteStreamParams,
} from './chatSseTypes';

type ActiveNodeStatus = Exclude<Parameters<ChatSseCallbacks['setNodeStatus']>[0], null>;

// ─────────────────────────────────────────────────────────────────────────────
// Hook
// ─────────────────────────────────────────────────────────────────────────────

export function useChatSse(refs: ChatSseRefs, callbacks: ChatSseCallbacks) {
  const { toast } = useToast();
  const {
    abortStreamRef,
    isSendingRef,
    activeStreamRequestIdRef,
    autoExpandTimeoutRef,
    prevSpecialistTypesRef,
    prevTileTypesRef,
    prevTripInputsRef,
  } = refs;

  const {
    setHasReceivedFirstToken,
    setNodeStatus,
    setStreamingMessageId,
    setTriggerContext,
    setSuggestedResponses,
    setSuggestedResponseMeta,
    setSuggestionChips,
    setIsLoading,
    setSessionState,
    appendToMessage,
    updateMessage,
    updateMessageId,
    filterMessages,
    onPlanResult,
    onAutoExpandItinerary,
    onFeasibilityWarning,
    onRetry,
    scrollToBottom,
    scrollPanelIntoView,
  } = callbacks;

  const reconcileTimerRef = useRef<NodeJS.Timeout | null>(null);
  const pendingPlanScrollTimeoutRef = useRef<number | null>(null);
  const watchdogTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const tripCreatedFiredRef = useRef(false);
  const itineraryGeneratedFiredRef = useRef(false);
  const queueCompletionScroll = useCallback(() => {
    requestAnimationFrame(() => {
      scrollPanelIntoView();
      scrollToBottom(true);
    });
  }, [scrollToBottom, scrollPanelIntoView]);

  useEffect(() => {
    return () => {
      if (reconcileTimerRef.current) {
        clearTimeout(reconcileTimerRef.current);
        reconcileTimerRef.current = null;
      }
      if (pendingPlanScrollTimeoutRef.current !== null) {
        window.clearTimeout(pendingPlanScrollTimeoutRef.current);
        pendingPlanScrollTimeoutRef.current = null;
      }
      if (watchdogTimerRef.current !== null) {
        clearTimeout(watchdogTimerRef.current);
        watchdogTimerRef.current = null;
      }
    };
  }, []);

  const executeStream = useCallback(
    (params: ExecuteStreamParams): Promise<'complete' | 'error' | 'stale'> => {
      const {
        body,
        requestId,
        streamingMsgId,
        isSilentPlanGeneration,
        selectedBranchId,
        envelopeGeneration,
        triggerContext,
        delayedLoader,
        actionLoader,
      } = params;

      useDocumentStore.setState({ _specialistPreview: null, dateFlexSuggestion: null });

      return new Promise<'complete' | 'error' | 'stale'>((resolve) => {
        const isStaleRequest = () => activeStreamRequestIdRef.current !== requestId;
        const activeNodeStatuses = new Map<string, ActiveNodeStatus>();
        const nodeStatusKey = (node: string, topic?: string) => `${node}::${topic ?? ''}`;
        let visibleNodeKey: string | null = null;
        let previewStrategySectionsPending = false;
        let deferredStrategySectionsPayload: StrategySection[] | null = null;
        let deferredStrategySectionsFrameId: number | null = null;
        const emittedBuilderWarnings = new Set<string>();

        if (reconcileTimerRef.current) {
          clearTimeout(reconcileTimerRef.current);
          reconcileTimerRef.current = null;
        }
        if (pendingPlanScrollTimeoutRef.current !== null) {
          window.clearTimeout(pendingPlanScrollTimeoutRef.current);
          pendingPlanScrollTimeoutRef.current = null;
        }

        if (isStaleRequest()) {
          debugLog('[SSE] Skipping stream setup for stale request');
          resolve('stale');
          return;
        }

        // Track whether this SSE stream set the regeneration overlay
        // so we can clear it on complete/error.
        let sseSetRegenFlag = false;

        const applyNodeStatusUi = (
          status: ActiveNodeStatus,
          allowRegenOverlay: boolean
        ) => {
          const classification = classifyNodeAction(
            status.node,
            triggerContext ?? undefined
          );

          if (classification) {
            const store = useDocumentStore.getState();
            const tiles = store.document?.tiles;
            const hasTiles = tiles && Object.keys(tiles).length > 0;

            actionLoader.startLoading(
              classification.actionType,
              status.estimatedDurationMs,
              {
                verticalType: classification.verticalType,
                hasTiles,
              }
            );

            if (
              allowRegenOverlay &&
              !sseSetRegenFlag &&
              (classification.actionType === 'generate_plan' ||
                classification.actionType === 'update_plan' ||
                classification.actionType === 'create_itinerary')
            ) {
              const existingDayCards = store.document?.day_cards;
              if (existingDayCards && existingDayCards.length > 0) {
                store.setRegenerationState({ isRegenerating: true });
                sseSetRegenFlag = true;
              }
            }
          }

          const shouldShow = shouldShowLoaderForNode(
            status.node,
            status.estimatedDurationMs
          );
          if (shouldShow) {
            delayedLoader.startLoading(status.estimatedDurationMs);
          }

          setNodeStatus(status);
          visibleNodeKey = nodeStatusKey(status.node, status.topic);
        };

        const syncActiveNodeStatusUi = () => {
          const nextActiveStatus = Array.from(activeNodeStatuses.values()).at(-1) ?? null;
          if (!nextActiveStatus) {
            visibleNodeKey = null;
            setNodeStatus(null);
            delayedLoader.reset();
            actionLoader.reset();
            return;
          }

          if (nodeStatusKey(nextActiveStatus.node, nextActiveStatus.topic) === visibleNodeKey) {
            setNodeStatus(nextActiveStatus);
            return;
          }

          applyNodeStatusUi(nextActiveStatus, false);
        };

        const mergeStrategySectionsPartial = (
          strategySections: StrategySection[]
        ) => {
          const store = useDocumentStore.getState();
          store.mergeEnvelope(
            { strategy_sections: strategySections },
            envelopeGeneration
          );
        };

        const emitBuilderWarnings = (warnings: string[] | undefined) => {
          if (!warnings?.length) return;

          for (const warning of warnings) {
            const normalizedWarning = warning.trim();
            if (!normalizedWarning || emittedBuilderWarnings.has(normalizedWarning)) {
              continue;
            }
            emittedBuilderWarnings.add(normalizedWarning);
            toast(normalizedWarning, { type: 'warning', duration: 4000 });
          }
        };

        // Connection watchdog — detect dead streams
        const WATCHDOG_TIMEOUT_MS = 15_000;

        const resetWatchdog = () => {
          if (watchdogTimerRef.current !== null) clearTimeout(watchdogTimerRef.current);
          watchdogTimerRef.current = setTimeout(() => {
            if (isStaleRequest()) return;
            abortStreamRef.current?.();
            abortStreamRef.current = null;
            toast('Connection lost. Your progress is saved.', {
              type: 'error',
              duration: 8000,
              action: { label: 'Retry', onClick: () => onRetry?.(body.message) },
            });
            // Clean up streaming state
            setStreamingMessageId(null);
            activeNodeStatuses.clear();
            visibleNodeKey = null;
            setNodeStatus(null);
            delayedLoader.reset();
            actionLoader.reset();
            setTriggerContext(null);
            setIsLoading(false);
            isSendingRef.current = false;
            activeStreamRequestIdRef.current = null;
            if (sseSetRegenFlag) {
              useDocumentStore.getState().setRegenerationState({ isRegenerating: false });
              sseSetRegenFlag = false;
            }
            resolve('error');
          }, WATCHDOG_TIMEOUT_MS);
        };

        resetWatchdog(); // Start watchdog

        abortStreamRef.current = streamGraphPlan(body, {
          onToken: (token: string) => {
            resetWatchdog();
            if (isStaleRequest()) return;
            setHasReceivedFirstToken(true);
            delayedLoader.onTangibleOutput();
            actionLoader.onTangibleOutput();
            if (!isSilentPlanGeneration) {
              appendToMessage(streamingMsgId, token);
            }
          },

          onNodeStatus: (status: SSENodeStatusEvent['data']) => {
            resetWatchdog();
            if (isStaleRequest()) return;
            if (status.status === 'started') {
              const nextStatus: ActiveNodeStatus = {
                active: true,
                node: status.node,
                label: status.label,
                iconKey: status.icon_key,
                estimatedDurationMs: status.estimated_duration_ms,
                startTime: Date.now(),
                stage: status.stage,
                topic: status.topic,
              };

              activeNodeStatuses.set(
                nodeStatusKey(status.node, status.topic),
                nextStatus
              );
              applyNodeStatusUi(nextStatus, true);
            } else if (status.status === 'completed') {
              activeNodeStatuses.delete(nodeStatusKey(status.node, status.topic));
              syncActiveNodeStatusUi();
            }
          },

          onPartial: (data: SSEPartialEvent['data']) => {
            resetWatchdog();
            if (isStaleRequest()) return;
            try {
              const store = useDocumentStore.getState();
              if (data.kind === 'strategy_sections') {
                if (
                  previewStrategySectionsPending &&
                  typeof window.requestAnimationFrame === 'function'
                ) {
                  previewStrategySectionsPending = false;
                  deferredStrategySectionsPayload = data.payload;
                  if (deferredStrategySectionsFrameId !== null) {
                    window.cancelAnimationFrame(deferredStrategySectionsFrameId);
                  }
                  deferredStrategySectionsFrameId = window.requestAnimationFrame(() => {
                    const queuedStrategySections = deferredStrategySectionsPayload;
                    deferredStrategySectionsFrameId = null;
                    deferredStrategySectionsPayload = null;
                    if (isStaleRequest() || !queuedStrategySections) return;
                    mergeStrategySectionsPartial(queuedStrategySections);
                  });
                } else {
                  if (deferredStrategySectionsFrameId !== null) {
                    window.cancelAnimationFrame(deferredStrategySectionsFrameId);
                    deferredStrategySectionsFrameId = null;
                    deferredStrategySectionsPayload = null;
                  }
                  mergeStrategySectionsPartial(data.payload);
                }
              } else if (data.kind === 'specialist_preview') {
                const normalizedPreviewPayload = normalizeSpecialistPreviewPayload(
                  data.payload,
                  store.document?.strategy_sections
                );

                if (
                  (normalizedPreviewPayload.activities?.length ?? 0) > 0 ||
                  (normalizedPreviewPayload.strategy_sections?.length ?? 0) > 0
                ) {
                  previewStrategySectionsPending = true;
                  store.setSpecialistPreview(normalizedPreviewPayload);
                }
              } else if (data.kind === 'tiles') {
                store.mergeEnvelope(
                  {
                    tiles: data.payload,
                    ...(data.tiles_replaced ? { tiles_replaced: true } : {}),
                  },
                  envelopeGeneration
                );
              } else if (data.kind === 'tile_enrichment') {
                store.mergeTileEnrichment(
                  data.payload,
                  envelopeGeneration,
                  data.tiles_replaced === true
                );
                emitBuilderWarnings(
                  data.payload.warnings ?? data.payload.context?.warnings
                );
              } else if (data.kind === 'trip_inputs') {
                store.mergeEnvelope(
                  {
                    trip_inputs: data.payload as PlanDocumentData['trip_inputs'],
                  },
                  envelopeGeneration
                );
              } else if (data.kind === 'day_cards') {
                store.setPartialDayCards(
                  data.payload as DayCardsPartialPayload,
                  envelopeGeneration
                );
                emitBuilderWarnings(data.payload.warnings);
              } else if (data.kind === 'date_flex_suggestion') {
                store.setDateFlexSuggestion(data.payload);
              }
            } catch (partialError) {
              debugLog(
                '[SSE] Partial merge failed (will reconcile on complete):',
                partialError
              );
            }
          },

          onFeasibilityWarning: (data: SSEFeasibilityWarningEvent['data']) => {
            resetWatchdog();
            if (isStaleRequest()) return;
            onFeasibilityWarning?.(data);
          },

          onHeartbeat: () => {
            resetWatchdog();
          },

          onComplete: (response) => {
            if (watchdogTimerRef.current !== null) { clearTimeout(watchdogTimerRef.current); watchdogTimerRef.current = null; }
            if (isStaleRequest()) {
              debugLog('[SSE] Ignoring stale stream complete event');
              if (sseSetRegenFlag) {
                useDocumentStore
                  .getState()
                  .setRegenerationState({ isRegenerating: false });
                sseSetRegenFlag = false;
              }
              resolve('stale');
              return;
            }

            setStreamingMessageId(null);
            if (deferredStrategySectionsFrameId !== null) {
              window.cancelAnimationFrame(deferredStrategySectionsFrameId);
              deferredStrategySectionsFrameId = null;
            }
            deferredStrategySectionsPayload = null;
            activeNodeStatuses.clear();
            visibleNodeKey = null;
            setNodeStatus(null);
            abortStreamRef.current = null;
            delayedLoader.reset();
            actionLoader.reset();
            setTriggerContext(null);

            if (sseSetRegenFlag) {
              useDocumentStore.getState().setRegenerationState({ isRegenerating: false });
              sseSetRegenFlag = false;
            }

            if (!isSilentPlanGeneration) {
              const msgs = useChatStore.getState().messages;
              const streamedMsg = msgs.find((m) => m.id === streamingMsgId);
              if (
                streamedMsg?.content?.startsWith('"') &&
                streamedMsg.content.endsWith('"') &&
                streamedMsg.content.length > 2
              ) {
                updateMessage(streamingMsgId, {
                  content: streamedMsg.content.slice(1, -1),
                });
              }
            }

            const data = response as unknown as GraphPlanResponse;

            setSessionState(data.session_state ?? null);

            const doc = data.document;
            const previousDayCards =
              useDocumentStore.getState().document?.day_cards ?? [];
            const wasChatPage = useMobileNavStore.getState().activePage === 0;

            const prevSpecialistTypes = prevSpecialistTypesRef.current;
            const prevTileTypes = prevTileTypesRef.current;

            const primaryBranch =
              doc.branches?.find((b) => b.is_primary) ?? doc.branches?.[0];
            const targetUpdatedDayNumber =
              wasChatPage && previousDayCards.length > 0
                ? findFirstChangedDay(previousDayCards, doc.day_cards ?? [])
                : null;
            let planResultApplied = true;
            try {
              onPlanResult({
                tripContextId: doc.trip_context_id ?? null,
                branches: doc.branches ?? [],
                tiles: doc.tiles ?? {},
                primaryBranchId: primaryBranch?.id ?? selectedBranchId ?? null,
                tripInputs: doc.trip_inputs ?? null,
                readyToGenerate: doc.ready_to_generate ?? false,
                response: data,
              });
            } catch (planResultError) {
              planResultApplied = false;
              console.error(
                '[ChatPanel] Failed to apply stream result, reconciling from server:',
                planResultError
              );
            }

            if (planResultApplied && targetUpdatedDayNumber) {
              pendingPlanScrollTimeoutRef.current = window.setTimeout(() => {
                pendingPlanScrollTimeoutRef.current = null;
                if (
                  activeStreamRequestIdRef.current !== null &&
                  activeStreamRequestIdRef.current !== requestId
                ) {
                  return;
                }
                requestAnimationFrame(() => {
                  if (
                    activeStreamRequestIdRef.current !== null &&
                    activeStreamRequestIdRef.current !== requestId
                  ) {
                    return;
                  }
                  useMapSync.getState().requestScrollTo(targetUpdatedDayNumber);
                });
              }, 250);
            }

            const hasTiles = doc.tiles && Object.keys(doc.tiles).length > 0;

            debugLog('[ChatPanel] Response received:', {
              hasTiles,
              tileCount: doc.tiles ? Object.keys(doc.tiles).length : 0,
              tileIds: doc.tiles ? Object.keys(doc.tiles).slice(0, 5) : [],
              plan_view_state: doc.plan_view_state,
              hasDestination: Boolean(doc.trip_inputs?.destination),
              destination: doc.trip_inputs?.destination,
              strategy_sections_count: doc.strategy_sections?.length ?? 0,
              strategy_section_ids: doc.strategy_sections?.map((s) => s.id),
              executed_strategy_topic_count: doc.executed_strategy_topics?.length ?? 0,
              pending_strategy_topic_count: doc.pending_strategy_topics?.length ?? 0,
            });

            // Analytics: trip_created (first time strategy is ready with destination)
            if (
              !tripCreatedFiredRef.current &&
              isStrategyReady(doc.plan_view_state) &&
              doc.trip_inputs?.destination
            ) {
              tripCreatedFiredRef.current = true;
              trackEvent('trip_created', doc.trip_inputs.destination, {
                activities: doc.trip_inputs?.activity_settings?.categories,
                has_budget: !!doc.trip_inputs?.budget,
              });
            }

            // Analytics: itinerary_generated (first time day_cards arrive)
            if (
              !itineraryGeneratedFiredRef.current &&
              (doc.day_cards?.length ?? 0) > 0
            ) {
              itineraryGeneratedFiredRef.current = true;
              trackEvent('itinerary_generated', doc.trip_inputs?.destination, {
                day_count: doc.day_cards?.length ?? 0,
              });
            }

            // Check for degraded response (LLM failure with fallback message)
            if (response.response_degraded) {
              const errorType = response.response_error_type;
              toast(
                errorType === 'rate_limit'
                  ? 'Response was limited due to high demand. Your plan changes were saved.'
                  : 'Response generation had an issue. Your plan changes were saved.',
                {
                  type: 'warning',
                  duration: 6000,
                  action: { label: 'Retry', onClick: () => onRetry?.(body.message) },
                }
              );
            }

            // Fallback: if streaming produced no tokens but envelope has a message,
            // populate the empty bubble so user sees content instead of blank.
            if (!isSilentPlanGeneration && response.response_degraded) {
              const msgs = useChatStore.getState().messages;
              const streamedMsg = msgs.find((m) => m.id === streamingMsgId);
              if (streamedMsg && !streamedMsg.content?.trim()) {
                const fallbackMsg = doc?.assistant_message;
                if (fallbackMsg?.trim()) {
                  updateMessage(streamingMsgId, { content: fallbackMsg });
                }
              }
            }

            if (hasTiles) {
              const rightPanel = document.getElementById('plan-panel');
              if (rightPanel && window.innerWidth < 768) {
                rightPanel.scrollIntoView({ behavior: 'smooth' });
              }
            }

            const isReadyToGenerate = doc.ready_to_generate === true;

            debugLog(
              `[ChatPanel] 🏷️ SSE complete:`,
              `suggestions=${JSON.stringify(doc.suggested_responses?.slice(0, 3))}`,
              `meta=${JSON.stringify(doc.suggested_response_meta?.slice(0, 2))}`,
              `viewState=${doc.plan_view_state}`,
              `dayCards=${doc.day_cards?.length ?? 'null'}`
            );
            setSuggestedResponses(doc.suggested_responses || []);
            setSuggestedResponseMeta(doc.suggested_response_meta || []);
            setSuggestionChips(doc.suggestion_chips || []);

            if (doc.origin_just_set && doc.trip_inputs?.origin) {
              debugLog(
                '[ChatPanel] Origin set via chat:',
                doc.trip_inputs.origin,
                '- flights fetched by backend'
              );
            }

            const freshState = useDocumentStore.getState();
            const hasItinerary = (freshState.document?.day_cards?.length ?? 0) > 0;

            // A graph response counts as a *finished* build only if it actually
            // placed at least one real activity. A degenerate response whose
            // day_cards are all Free-Day / buffer / logistics-anchor
            // placeholders is NOT a build — accepting it would lock in an empty
            // plan. Mirrors lib/dayIntensity.ts, which treats arrival/departure/
            // check-in/check-out as anchors (they arrive as `activity_type`, not
            // `buffer_type`) and excludes free_day/buffers from real activities.
            const isRealActivityBlock = (block: DayBlock): boolean =>
              !block.is_buffer &&
              !block.buffer_type &&
              !NON_ACTIVITY_BLOCK_TYPES.has(block.activity_type);
            const graphDayCards = doc.day_cards ?? [];
            const graphHasRealActivity = graphDayCards.some((card) =>
              (card.blocks ?? []).some(isRealActivityBlock)
            );
            const graphBuiltItinerary = graphDayCards.length > 0 && graphHasRealActivity;
            const graphDegenerateDayCards = graphDayCards.length > 0 && !graphHasRealActivity;
            if (graphBuiltItinerary) {
              debugLog(
                `[EXPAND] SKIPPED — graph response included ${graphDayCards.length} day_cards with real activities`
              );
            } else if (graphDegenerateDayCards) {
              debugLog(
                `[EXPAND] graph response had ${graphDayCards.length} day_cards but no real activity blocks (all Free-Day/buffer) — eligible for corrective rebuild`
              );
            }

            const freshInputs = freshState.document?.trip_inputs;
            const freshHasDates =
              (Boolean(freshInputs?.start_date) && Boolean(freshInputs?.end_date)) ||
              (freshInputs?.date_flex === true && freshInputs?.trip_duration != null);

            const newSpecialistTypes =
              doc.strategy_sections
                ?.map((s) => s.specialist_type)
                .filter((t): t is string => !!t) ?? [];
            const getTileCategory = (t: {
              type: string;
              meta?: Record<string, unknown>;
            }) =>
              t.type === 'activity' && t.meta?.category
                ? String(t.meta.category)
                : t.type;
            const newTileCategories = new Set(
              Object.values(doc.tiles ?? {}).map(getTileCategory)
            );

            const hasNewSpecialist = newSpecialistTypes.some(
              (t) => !prevSpecialistTypes.has(t)
            );
            const hasNewTileType = [...newTileCategories].some(
              (t) => !prevTileTypes.has(t)
            );
            const hasStructuralNewTileType = [...newTileCategories].some(
              (t) => t !== 'flight' && !prevTileTypes.has(t)
            );

            prevSpecialistTypesRef.current = new Set(newSpecialistTypes);
            prevTileTypesRef.current = newTileCategories;

            const tileCount = Object.keys(doc.tiles ?? {}).length;
            const viewState = doc.plan_view_state ?? 'unknown';
            const prevInputs = prevTripInputsRef.current;
            const newTripInputs = freshState.document?.trip_inputs;
            const hasStrategyContent = (doc.strategy_sections?.length ?? 0) > 0;

            const shouldExpandStructural =
              (hasItinerary || freshHasDates) &&
              (hasNewSpecialist || hasStructuralNewTileType) &&
              !isSilentPlanGeneration;
            const datesChanged =
              prevInputs &&
              (prevInputs.start_date !== newTripInputs?.start_date ||
                prevInputs.end_date !== newTripInputs?.end_date);
            const shouldExpandDates =
              datesChanged && hasStrategyContent && !isSilentPlanGeneration;
            const travelersChanged =
              prevInputs &&
              (prevInputs.adults !== newTripInputs?.adults ||
                prevInputs.children !== newTripInputs?.children);
            const budgetChanged =
              prevInputs && prevInputs.budget !== newTripInputs?.budget;
            const originChanged =
              prevInputs && prevInputs.origin !== newTripInputs?.origin;
            const otherInputsChanged = Boolean(
              travelersChanged || budgetChanged || originChanged
            );
            const shouldExpandTripInputs =
              hasItinerary &&
              Boolean(prevInputs) &&
              otherInputsChanged &&
              !isSilentPlanGeneration;
            const shouldExpandCatchAll =
              hasStrategyContent &&
              !hasItinerary &&
              freshHasDates &&
              !isSilentPlanGeneration &&
              !isBootstrap(doc.plan_view_state);

            // Belt-and-suspenders: a graph response whose day_cards are ALL
            // Free-Day/buffer placeholders is degenerate (the root cause is
            // fixed in the backend builder; this only catches a regression).
            // Only correct it when an expand could actually place something —
            // activities are not turned off AND at least one activity tile
            // exists to schedule. This is gated tightly to avoid (a) re-firing
            // (single onComplete per turn + expandInProgress mutex) and (b)
            // mis-classifying a legitimately activity-free trip.
            const activitiesBookingState =
              freshInputs?.booking_types?.activities ?? 'on';
            const activitiesEnabled = activitiesBookingState !== 'off';
            const hasActivityTile = Object.values(doc.tiles ?? {}).some(
              (t) => t.type === 'activity'
            );
            const shouldExpandDegenerate =
              graphDegenerateDayCards &&
              activitiesEnabled &&
              hasActivityTile &&
              freshHasDates &&
              !isSilentPlanGeneration &&
              !isBootstrap(doc.plan_view_state);

            debugLog(
              `[EXPAND] gate check: strategy=${newSpecialistTypes.length} tiles=${tileCount} ` +
                `viewState=${viewState} hasItinerary=${hasItinerary} freshHasDates=${freshHasDates} silent=${isSilentPlanGeneration} graphBuilt=${graphBuiltItinerary} ` +
                `newSpecialist=${hasNewSpecialist} newTileType=${hasNewTileType} structuralTileType=${hasStructuralNewTileType} datesChanged=${!!datesChanged} ` +
                `travelersChanged=${!!travelersChanged} budgetChanged=${!!budgetChanged} originChanged=${!!originChanged} ` +
                `prevCategories=[${[...prevTileTypes]}] newCategories=[${[...newTileCategories]}]`
            );

            const blockingViolations =
              freshState.document?.constraint_violations?.filter(
                (v) => v.severity === 'blocking'
              ) ?? [];
            if (blockingViolations.length > 0) {
              debugLog(
                '[EXPAND] BLOCKED — blocking constraint violations exist:',
                blockingViolations.map((v) => v.code)
              );
            }

            let expandReason:
              | 'DEGENERATE_REBUILD'
              | 'STRUCTURAL'
              | 'DATE_CHANGE'
              | 'TRIP_INPUTS'
              | 'CATCH_ALL'
              | null = null;
            if (!graphBuiltItinerary && blockingViolations.length === 0) {
              if (shouldExpandDegenerate) {
                expandReason = 'DEGENERATE_REBUILD';
              } else if (shouldExpandStructural) {
                expandReason = 'STRUCTURAL';
              } else if (shouldExpandDates) {
                expandReason = 'DATE_CHANGE';
              } else if (shouldExpandTripInputs) {
                expandReason = 'TRIP_INPUTS';
              } else if (shouldExpandCatchAll) {
                expandReason = 'CATCH_ALL';
              }
            }

            if (!expandReason && hasItinerary && !hasNewSpecialist && !hasNewTileType) {
              debugLog('[ChatPanel] Additive change only, itinerary preserved');
            }

            if (expandReason) {
              debugLog('[ChatPanel] Auto-expand scheduled:', {
                reason: expandReason,
                prevDates: prevInputs
                  ? `${prevInputs.start_date ?? 'null'} - ${prevInputs.end_date ?? 'null'}`
                  : null,
                newDates: `${newTripInputs?.start_date ?? 'null'} - ${newTripInputs?.end_date ?? 'null'}`,
              });

              if (autoExpandTimeoutRef.current)
                clearTimeout(autoExpandTimeoutRef.current);
              autoExpandTimeoutRef.current = setTimeout(() => {
                const activeRequestId = activeStreamRequestIdRef.current;
                if (activeRequestId !== null && activeRequestId !== requestId) {
                  debugLog(`[ChatPanel] ⏭️ ${expandReason} skipped - stale request`);
                  return;
                }
                const latest = useDocumentStore.getState();
                if (latest.expandInProgress) {
                  debugLog(
                    `[ChatPanel] ⏭️ ${expandReason} skipped - expand already in progress`
                  );
                  return;
                }
                if (
                  expandReason === 'CATCH_ALL' &&
                  (latest.document?.day_cards?.length ?? 0) > 0
                ) {
                  debugLog('[ChatPanel] ⏭️ CATCH_ALL skipped - itinerary already exists');
                  return;
                }
                onAutoExpandItinerary?.({ forceFullRebuild: true });
              }, 100);
            }

            if (isSilentPlanGeneration) {
              filterMessages((msg) => msg.id !== streamingMsgId);
            } else {
              if (isReadyToGenerate) {
                updateMessageId(
                  streamingMsgId,
                  `${READY_MESSAGE_ID_PREFIX}${streamingMsgId}`
                );
              }
            }

            // Reconcile from persisted document when stream payload looks incomplete
            // or the in-memory apply path threw. This prevents "manual refresh required".
            const responseHasStrategy = (doc.strategy_sections?.length ?? 0) > 0;
            const responseHasDayCards = (doc.day_cards?.length ?? 0) > 0;
            const expectsDayCards = Boolean(
              (doc.trip_inputs?.start_date && doc.trip_inputs?.end_date) ||
              (doc.trip_inputs?.date_flex === true &&
                doc.trip_inputs?.trip_duration != null)
            );
            const needsReconcile =
              !planResultApplied ||
              (!responseHasStrategy && !isBootstrap(doc.plan_view_state) && hasTiles) ||
              (expectsDayCards && !responseHasDayCards);

            if (needsReconcile) {
              const reconcileTimer = setTimeout(async () => {
                if (isSendingRef.current) return;
                try {
                  await useDocumentStore.getState().fetchDocument();
                } catch {
                  debugLog('[ChatPanel] Reconcile fetch failed');
                }
                if (reconcileTimerRef.current === reconcileTimer) {
                  reconcileTimerRef.current = null;
                }
              }, 1500);
              reconcileTimerRef.current = reconcileTimer;
            }

            setIsLoading(false);
            isSendingRef.current = false;
            activeStreamRequestIdRef.current = null;
            queueCompletionScroll();
            resolve('complete');
          },

          onError: (error: Error) => {
            if (watchdogTimerRef.current !== null) { clearTimeout(watchdogTimerRef.current); watchdogTimerRef.current = null; }
            if (isStaleRequest()) {
              debugLog('[SSE] Ignoring stale stream error event');
              if (sseSetRegenFlag) {
                useDocumentStore
                  .getState()
                  .setRegenerationState({ isRegenerating: false });
                sseSetRegenFlag = false;
              }
              resolve('stale');
              return;
            }

            useDocumentStore.setState({ _specialistPreview: null });
            setStreamingMessageId(null);
            if (deferredStrategySectionsFrameId !== null) {
              window.cancelAnimationFrame(deferredStrategySectionsFrameId);
              deferredStrategySectionsFrameId = null;
            }
            deferredStrategySectionsPayload = null;
            activeNodeStatuses.clear();
            visibleNodeKey = null;
            setNodeStatus(null);
            abortStreamRef.current = null;
            delayedLoader.reset();
            actionLoader.reset();
            setTriggerContext(null);

            if (sseSetRegenFlag) {
              useDocumentStore.getState().setRegenerationState({ isRegenerating: false });
              sseSetRegenFlag = false;
            }

            if (reconcileTimerRef.current) {
              clearTimeout(reconcileTimerRef.current);
              reconcileTimerRef.current = null;
            }
            if (pendingPlanScrollTimeoutRef.current !== null) {
              window.clearTimeout(pendingPlanScrollTimeoutRef.current);
              pendingPlanScrollTimeoutRef.current = null;
            }
            console.error('Failed to plan trip', error);

            if (!isSilentPlanGeneration) {
              const errorMessage = getErrorMessage(error);
              const errorMsgId = `a_err_${Date.now()}`;
              updateMessageId(streamingMsgId, errorMsgId);
              updateMessage(errorMsgId, { content: errorMessage });
            } else {
              useChatStore.getState().addMessage({
                id: `a_err_${Date.now()}`,
                role: 'assistant',
                content: getErrorMessage(error),
              });
            }

            setIsLoading(false);
            isSendingRef.current = false;
            activeStreamRequestIdRef.current = null;
            queueCompletionScroll();
            resolve('error');
          },
        });
      });
    },

    [
      abortStreamRef,
      isSendingRef,
      activeStreamRequestIdRef,
      autoExpandTimeoutRef,
      prevSpecialistTypesRef,
      prevTileTypesRef,
      prevTripInputsRef,
      setHasReceivedFirstToken,
      setNodeStatus,
      setStreamingMessageId,
      setTriggerContext,
      setSuggestedResponses,
      setSuggestedResponseMeta,
      setSuggestionChips,
      setIsLoading,
      setSessionState,
      appendToMessage,
      updateMessage,
      updateMessageId,
      filterMessages,
      onPlanResult,
      onAutoExpandItinerary,
      onFeasibilityWarning,
      onRetry,
      queueCompletionScroll,
      toast,
    ]
  );

  return { executeStream };
}
