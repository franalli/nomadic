'use client';

/**
 * ChatInputHandler — Text input area + send/stop button row.
 *
 * Thin orchestration wrapper around ChatInputBar.
 * Converts the ChatPanel-level onSend/onStop callbacks into
 * the form-submit / stop-streaming signatures that ChatInputBar expects.
 */

import type { PlanViewState } from '@/types/plan-envelope';

import { ChatInputBar } from './ChatInputBar';

interface ChatInputHandlerProps {
  input: string;
  onInputChange: (value: string) => void;
  onSubmit: (e: React.FormEvent) => void;
  onStopStreaming: () => void;
  isLoading: boolean;
  isInputDisabledByPlanState: boolean;
  hasReceivedFirstToken: boolean;
  nodeStatus: { node: string } | null;
  readyToGenerate?: boolean;
  isGenerating?: boolean;
  hasBranches?: boolean;
  hasDestination?: boolean;
  planViewState?: PlanViewState;
  inputRef: React.RefObject<HTMLTextAreaElement | null>;
}

export function ChatInputHandler({
  input,
  onInputChange,
  onSubmit,
  onStopStreaming,
  isLoading,
  isInputDisabledByPlanState,
  hasReceivedFirstToken,
  nodeStatus,
  readyToGenerate,
  isGenerating,
  hasBranches,
  hasDestination,
  planViewState,
  inputRef,
}: ChatInputHandlerProps) {
  return (
    <ChatInputBar
      input={input}
      onInputChange={onInputChange}
      onSubmit={onSubmit}
      isLoading={isLoading}
      isInputDisabledByPlanState={isInputDisabledByPlanState}
      hasReceivedFirstToken={hasReceivedFirstToken}
      nodeStatus={nodeStatus}
      readyToGenerate={readyToGenerate}
      isGenerating={isGenerating}
      hasBranches={hasBranches}
      hasDestination={hasDestination}
      planViewState={planViewState}
      onStopStreaming={onStopStreaming}
      inputRef={inputRef}
    />
  );
}
