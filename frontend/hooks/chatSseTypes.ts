/**
 * Type definitions for useChatSse hook.
 *
 * Extracted from useChatSse.ts to reduce file size.
 * Canonical imports come from this file; useChatSse.ts re-exports for
 * backward compatibility.
 */

import type { useActionLoader } from '@/hooks/useActionLoader';
import type { useDelayedLoader } from '@/hooks/useDelayedLoader';
import type { SSEFeasibilityWarningEvent, streamGraphPlan } from '@/lib/api-streaming';
import type { ChatMessage } from '@/types/chat';
import type {
  DocumentBranch,
  DocumentTripInputs,
  GraphPlanResponse,
  SuggestionChip,
  SuggestionChipMeta,
} from '@/types/document';
import type { TriggerContext } from '@/types/loader';
import type { Tile } from '@/types/tile';

export interface ChatSseRefs {
  abortStreamRef: React.MutableRefObject<(() => void) | null>;
  isSendingRef: React.MutableRefObject<boolean>;
  activeStreamRequestIdRef: React.MutableRefObject<string | null>;
  autoExpandTimeoutRef: React.MutableRefObject<NodeJS.Timeout | null>;
  prevSpecialistTypesRef: React.MutableRefObject<Set<string>>;
  prevTileTypesRef: React.MutableRefObject<Set<string>>;
  prevTripInputsRef: React.MutableRefObject<{
    start_date: string | null;
    end_date: string | null;
    adults: number | null;
    children: number | null;
    budget: number | null;
    origin: string | null;
  } | null>;
}

export interface ChatSseCallbacks {
  setHasReceivedFirstToken: (v: boolean) => void;
  setNodeStatus: (
    v: {
      active: boolean;
      node: string;
      label: string;
      iconKey: string;
      estimatedDurationMs: number;
      startTime: number;
      stage?: number;
      topic?: string;
    } | null
  ) => void;
  setStreamingMessageId: (v: string | null) => void;
  setTriggerContext: (v: TriggerContext | null) => void;
  setSuggestedResponses: (v: string[]) => void;
  setSuggestedResponseMeta: (v: SuggestionChipMeta[]) => void;
  setSuggestionChips: (v: SuggestionChip[]) => void;
  setIsLoading: (v: boolean) => void;
  setSessionState: (v: Record<string, unknown> | null) => void;
  appendToMessage: (id: string, token: string) => void;
  updateMessage: (
    id: string,
    updates: Partial<ChatMessage>
  ) => void;
  updateMessageId: (oldId: string, newId: string) => void;
  filterMessages: (
    predicate: (msg: ChatMessage) => boolean
  ) => void;
  onPlanResult: (result: {
    tripContextId: number | null;
    branches: DocumentBranch[];
    tiles: Record<string, Tile>;
    primaryBranchId: string | null;
    tripInputs?: DocumentTripInputs | null;
    readyToGenerate?: boolean;
    response?: GraphPlanResponse;
  }) => void;
  onAutoExpandItinerary?: (options?: { forceFullRebuild?: boolean }) => void;
  onFeasibilityWarning?: (data: SSEFeasibilityWarningEvent['data']) => void;
  scrollToBottom: (force?: boolean) => void;
  scrollPanelIntoView: () => void;
}

export interface ExecuteStreamParams {
  body: Parameters<typeof streamGraphPlan>[0];
  requestId: string;
  streamingMsgId: string;
  isSilentPlanGeneration: boolean;
  selectedBranchId: string | null;
  envelopeGeneration: number;
  triggerContext: TriggerContext | null;
  delayedLoader: ReturnType<typeof useDelayedLoader>;
  actionLoader: ReturnType<typeof useActionLoader>;
}
