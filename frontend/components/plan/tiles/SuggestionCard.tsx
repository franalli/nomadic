'use client';
/* eslint no-unused-vars: ["error", { "args": "none" }] */
/**
 * SuggestionCard
 *
 * Renders a tile as a "suggestion" with AI reasoning in PLANNING mode.
 * Shows "Why this?" explanation, "Save to Trip" action, and "Change" button.
 *
 * @see docs/ux_unified_architecture.md Section I.B - Booking Suggestions Pattern
 */
import type { Tile } from '@/types/tile';

import { SuggestionCardContent } from './SuggestionCardContent';
import { SuggestionCardCompact } from './suggestionCardSections';

// =============================================================================
// Types
// =============================================================================

interface SuggestionCardProps {
  tile: Tile;
  /** AI reasoning for why this tile was suggested */
  reasoning?: string;
  /** Whether tile is saved to trip */
  isSaved?: boolean;
  /** Callback when user saves/unsaves */
  onSave?: (tile: Tile) => void;
  /** Callback to view alternatives */
  onViewAlternatives?: () => void;
  /** Callback for tile details */
  onDetailsClick?: (tile: Tile) => void;
  /** Callback to open stays settings sheet (for hotel tiles) */
  onOpenStaysSettings?: () => void;
  /** Compact or expanded variant */
  variant?: 'compact' | 'expanded';
  className?: string;
}

// =============================================================================
// Component
// =============================================================================

export function SuggestionCard({
  tile,
  reasoning,
  isSaved = false,
  onSave,
  onViewAlternatives,
  onDetailsClick,
  onOpenStaysSettings: _onOpenStaysSettings,
  variant = 'expanded',
  className,
}: SuggestionCardProps) {
  if (variant === 'compact') {
    return (
      <SuggestionCardCompact
        tile={tile}
        isSaved={isSaved}
        onSave={onSave}
        className={className}
      />
    );
  }

  // Expanded variant - full card (extracted to SuggestionCardContent)
  return (
    <SuggestionCardContent
      tile={tile}
      reasoning={reasoning}
      isSaved={isSaved}
      onSave={onSave}
      onViewAlternatives={onViewAlternatives}
      onDetailsClick={onDetailsClick}
      className={className}
    />
  );
}

export default SuggestionCard;
