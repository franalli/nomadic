'use client';
// TODO: DS spacing audit — requires visual QA pass
/* eslint no-unused-vars: ["error", { "args": "none" }] */

import { type KeyboardEvent,useId, useMemo, useState } from 'react';

import type { StrategySection } from '@/types/plan-envelope';

import { StrategyHeroAccordion } from './StrategyHeroAccordion';
import { StrategyHeroCompact } from './StrategyHeroCompact';
import { StrategyHeroContent } from './StrategyHeroContent';
import {
  DEFAULT_STYLE,
  getHeroImage,
  getTopicLabel,
  SPECIALIST_STYLE_CLASSES,
} from './StrategyHeroUtils';
import { useStrategyHeroEnrichment } from './useStrategyHeroEnrichment';

interface StrategyHeroProps {
  section: StrategySection;
  variant: 'hero' | 'compact' | 'accordion';
  defaultExpanded?: boolean;
  isExpanded?: boolean;
  onExpandChange?: (expanded: boolean) => void;
  onExpand?: () => void;
}

export function StrategyHero({
  section,
  variant,
  defaultExpanded = false,
  isExpanded: controlledExpanded,
  onExpandChange,
  onExpand,
}: StrategyHeroProps) {
  const topic = section.specialist_type || 'general';
  const topicLabel = getTopicLabel(topic);
  const heroImage = getHeroImage(section);
  const constraints = useMemo(() => {
    const raw = section.constraints_applied;
    if (!raw || raw.length === 0) return [];
    const deduped = [...new Map(raw.map((constraint) => [constraint.rule || constraint.reason, constraint])).values()];
    return deduped.filter((constraint) => {
      const severity = (constraint as Record<string, string>).severity;
      return !severity || severity === 'blocking' || severity === 'strong';
    });
  }, [section.constraints_applied]);
  const constraintCount = constraints.length;
  const uniqueId = useId();
  const headerId = `${uniqueId}-header`;
  const contentId = `${uniqueId}-content`;
  const [isSheetOpen, setIsSheetOpen] = useState(false);
  const [internalExpanded, setInternalExpanded] = useState(defaultExpanded);
  const isAccordionExpanded =
    controlledExpanded !== undefined ? controlledExpanded : internalExpanded;
  const specialistColors = SPECIALIST_STYLE_CLASSES[topic] || DEFAULT_STYLE;
  const isInfeasible = section.feasibility_status === 'infeasible';
  const {
    displaySection,
    shouldShowEnrichmentNotice,
    enrichmentUiState,
    enrichmentErrorLabel,
    handleRetryEnrichment,
  } = useStrategyHeroEnrichment(section, isSheetOpen);

  const handleExpand = () => {
    onExpand?.();
    setIsSheetOpen(true);
  };

  const handleAccordionToggle = () => {
    const nextState = !isAccordionExpanded;
    if (controlledExpanded === undefined) setInternalExpanded(nextState);
    onExpandChange?.(nextState);
  };

  const handleKeyDown = (e: KeyboardEvent) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      handleAccordionToggle();
    } else if (e.key === 'Escape' && isAccordionExpanded) {
      e.preventDefault();
      if (controlledExpanded === undefined) setInternalExpanded(false);
      onExpandChange?.(false);
    }
  };

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

  if (variant === 'compact') {
    return (
      <StrategyHeroCompact
        section={section}
        displaySection={displaySection}
        topic={topic}
        topicLabel={topicLabel}
        heroImage={heroImage}
        constraints={constraints}
        constraintCount={constraintCount}
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
