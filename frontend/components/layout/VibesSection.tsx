'use client';

import { Loader2, Plus, X } from 'lucide-react';
import { memo } from 'react';

import { cn } from '@/lib/utils';

// ─────────────────────────────────────────────────────────────────────────────
// Helpers
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Extract emoji and text from a vibe string.
 * Vibes are stored as "emoji text" (e.g., "🏖️ beach").
 * Falls back to ✨ for legacy vibes without emoji prefix.
 */
function parseVibe(vibe: string): { emoji: string; text: string } {
  // Check if first character(s) form an emoji (emoji can be 1-2 chars due to variation selectors)
  const match = vibe.match(/^(\p{Emoji_Presentation}|\p{Emoji}\uFE0F?)\s*/u);
  if (match) {
    return {
      emoji: match[1],
      text: vibe.slice(match[0].length),
    };
  }
  // Legacy vibe without emoji
  return { emoji: '✨', text: vibe };
}

// ─────────────────────────────────────────────────────────────────────────────
// Props
// ─────────────────────────────────────────────────────────────────────────────

export interface VibesSectionProps {
  vibes: string[];
  vibeInput: string;
  vibeInputExpanded: boolean;
  pendingVibe: string | null;
  onAddVibe: (vibe: string) => void;
  onRemoveVibe: (index: number) => void;
  setVibeInput: (value: string) => void;
  setVibeInputExpanded: (expanded: boolean) => void;
  /** Whether vibes were recently updated by the LLM (shows sparkle animation) */
  isLLMUpdated?: boolean;
  /** Called when user interacts with vibes to acknowledge the LLM update */
  onAcknowledge?: () => void;
}

// ─────────────────────────────────────────────────────────────────────────────
// Component
// ─────────────────────────────────────────────────────────────────────────────

function VibesSectionInner({
  vibes,
  vibeInput,
  vibeInputExpanded,
  pendingVibe,
  onAddVibe,
  onRemoveVibe,
  setVibeInput,
  setVibeInputExpanded,
  isLLMUpdated = false,
  onAcknowledge,
}: VibesSectionProps) {
  const handleVibeClick = () => {
    if (isLLMUpdated && onAcknowledge) {
      onAcknowledge();
    }
  };

  return (
    <div className="flex flex-wrap items-center gap-2.5">
      {vibes.map((vibe, idx) => {
        const { emoji, text } = parseVibe(vibe);
        return (
          <span
            key={`vibe-${idx}`}
            onClick={handleVibeClick}
            className={cn(
              'group relative inline-flex cursor-pointer items-center gap-1.5 rounded-full border border-accent/40 bg-gradient-to-b from-accent/15 to-accent/10 px-3 py-1.5 text-xs font-semibold shadow-pill-accent transition-all duration-200 ease-out hover:from-accent/25 hover:to-accent/15 hover:border-accent/50 hover:shadow-md hover:shadow-accent/10 hover:-translate-y-0.5',
              isLLMUpdated && 'border-accent/60 shadow-md shadow-accent/15'
            )}
          >
            <span className={cn('text-xs', isLLMUpdated && 'sparkle-icon')}>{emoji}</span>
            {text}
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                onRemoveVibe(idx);
              }}
              className="absolute -right-1 -top-1 flex h-4 w-4 items-center justify-center rounded-full bg-muted-foreground/80 text-background opacity-0 shadow-sm transition-all duration-150 hover:bg-destructive hover:scale-110 group-hover:opacity-80"
              aria-label={`Remove ${text}`}
            >
              <X className="h-2.5 w-2.5" />
            </button>
          </span>
        );
      })}
      {/* Show pending vibe with loading spinner */}
      {pendingVibe && (
        <span className="inline-flex items-center gap-1.5 rounded-full border border-accent/40 bg-gradient-to-b from-accent/20 to-accent/15 px-3 py-1.5 text-xs font-semibold shadow-pill-accent animate-pulse">
          <Loader2 className="h-3.5 w-3.5 text-accent animate-spin" />
          <span className="text-accent/80">{pendingVibe}</span>
        </span>
      )}
      {/* Plus button or expanded input */}
      {vibeInputExpanded ? (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            onAddVibe(vibeInput);
            setVibeInputExpanded(false);
          }}
          className="inline-flex items-center"
        >
          <input
            type="text"
            value={vibeInput}
            onChange={(e) => setVibeInput(e.target.value)}
            placeholder="Type a vibe..."
            className="w-32 rounded-full border border-accent/40 bg-card text-foreground px-3 py-1.5 text-xs placeholder:text-muted-foreground/50 shadow-sm transition-all duration-200 focus:border-accent/60 focus:outline-none focus:ring-2 focus:ring-accent/25 focus:ring-offset-1 focus:shadow-pill-accent"
            autoFocus
            onBlur={() => {
              // Collapse if empty after a short delay (allows click on submit to work)
              setTimeout(() => {
                if (!vibeInput.trim()) {
                  setVibeInputExpanded(false);
                }
              }, 150);
            }}
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                e.preventDefault();
                onAddVibe(vibeInput);
                setVibeInputExpanded(false);
              } else if (e.key === 'Escape') {
                e.preventDefault();
                setVibeInput('');
                setVibeInputExpanded(false);
              }
            }}
          />
          {vibeInput.trim() && (
            <button
              type="submit"
              className="ml-1 flex h-6 w-6 items-center justify-center rounded-full bg-accent text-white hover:bg-accent/90 transition-colors"
              aria-label="Add vibe"
            >
              <Plus className="h-3.5 w-3.5" />
            </button>
          )}
        </form>
      ) : (
        <button
          type="button"
          onClick={() => setVibeInputExpanded(true)}
          className="flex h-7 w-7 items-center justify-center rounded-full border-2 border-dashed border-accent/30 bg-gradient-to-b from-accent/5 to-accent/10 text-accent/50 shadow-sm transition-all duration-200 ease-out hover:border-accent/50 hover:border-solid hover:from-accent/15 hover:to-accent/20 hover:text-accent hover:shadow-pill-accent hover:scale-105 active:scale-95"
          aria-label="Add vibe"
          title={vibes.length === 0 ? "What's the vibe? Adventure, F1, relaxation..." : "Add another vibe"}
        >
          <Plus className="h-3.5 w-3.5" />
        </button>
      )}
    </div>
  );
}

export const VibesSection = memo(VibesSectionInner);
