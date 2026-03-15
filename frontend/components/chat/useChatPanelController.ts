'use client';

import { useMemo, useRef, useState } from 'react';

import { useToast } from '@/components/ui/toast';
import { useChatEffects } from '@/hooks/useChatEffects';
import { useChatMessagePipeline } from '@/hooks/useChatMessagePipeline';
import { useChatScrolling } from '@/hooks/useChatScrolling';
import { useChatSend } from '@/hooks/useChatSend';
import { useIsDesktop } from '@/hooks/useIsDesktop';
import { useChatStore } from '@/state/chatStore';
import { useDocumentStore } from '@/state/documentStore';

import type { ChatPanelProps } from './ChatPanel.types';
import type { ActiveStatus } from './SmartLoader';

export function useChatPanelController({
  fullHeight,
  hasBranches,
  isGenerating,
  onAutoExpandItinerary,
  onGeneratePlanStart,
  onPlanResult,
  onUserMessageSubmit,
  planState,
  readyToGenerate,
  selectedBranchId,
}: ChatPanelProps) {
  const isInputDisabledByPlanState = planState === 'RESOLVING';
  const isDesktop = useIsDesktop();
  const { toast } = useToast();
  const isRegenerating = useDocumentStore((s) => s.isRegenerating);

  const messages = useChatStore((s) => s.messages);
  const isLoadingHistory = useChatStore((s) => s.isLoadingHistory);
  const loadHistory = useChatStore((s) => s.loadHistory);
  const filterMessages = useChatStore((s) => s.filterMessages);

  const [isSetupHeaderCollapsed, setIsSetupHeaderCollapsed] = useState(false);
  const [generateTriggered, setGenerateTriggered] = useState(false);
  const [activeStatus, setActiveStatus] = useState<ActiveStatus | null>(null);
  const [openModuleSheet, setOpenModuleSheet] = useState<
    'flights' | 'stays' | 'activities' | null
  >(null);

  const panelRef = useRef<HTMLDivElement | null>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  const {
    scrollContainerRef,
    bottomSentinelRef,
    scrollToBottom,
    handleScroll,
    scrollPanelIntoView,
  } = useChatScrolling({
    panelRef,
    isDesktop,
    onSetupHeaderCollapse: setIsSetupHeaderCollapsed,
  });

  const chatSend = useChatSend({
    onPlanResult,
    onGeneratePlanStart,
    onAutoExpandItinerary,
    onUserMessageSubmit,
    selectedBranchId,
    hasBranches,
    setGenerateTriggered,
    setActiveStatus,
    scrollPanelIntoView,
    scrollToBottom,
    inputRef,
    toast,
  });

  useChatEffects({
    isLoading: chatSend.isLoading,
    isLoadingHistory,
    messages,
    scrollToBottom,
    scrollPanelIntoView,
    inputRef,
    readyToGenerate,
    hasBranches,
    generateTriggered,
    setGenerateTriggered,
    loadHistory,
    filterMessages,
    nodeStatus: chatSend.nodeStatus,
    setActiveStatus,
    autoExpandTimeoutRef: chatSend.autoExpandTimeoutRef,
    focusTimeoutRef: chatSend.focusTimeoutRef,
  });

  const effectiveSuggestions = useMemo(() => {
    if (chatSend.suggestedResponses.length === 0) return [];
    const seen = new Set<string>();
    const filtered = chatSend.suggestedResponses.filter((suggestion) => {
      const isFieldCta = /^(set|add|change)\s/i.test(suggestion);
      if (!isFieldCta) return true;
      const lower = suggestion.toLowerCase();
      if (seen.has(lower)) return false;
      seen.add(lower);
      return true;
    });
    if (!isDesktop) return filtered;
    return filtered.filter((suggestion) => suggestion.toLowerCase() !== 'build plan');
  }, [chatSend.suggestedResponses, isDesktop]);

  const panelHeightClass = fullHeight ? 'h-full' : !isDesktop ? 'h-full' : 'min-h-[300px]';
  const visibleMessages = useChatMessagePipeline(
    messages,
    chatSend.streamingMessageId,
    isGenerating ?? false,
    hasBranches ?? false
  );

  return {
    activeStatus,
    bottomSentinelRef,
    chatSend,
    effectiveSuggestions,
    handleScroll,
    inputRef,
    isDesktop,
    isInputDisabledByPlanState,
    isLoadingHistory,
    isRegenerating,
    isSetupHeaderCollapsed,
    openModuleSheet,
    panelHeightClass,
    panelRef,
    scrollContainerRef,
    setOpenModuleSheet,
    toast,
    visibleMessages,
  };
}
