'use client';

import { Loader2, Plus, X } from 'lucide-react';
import { memo } from 'react';

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
}: VibesSectionProps) {
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {vibes.map((vibe, idx) => {
        const { emoji, text } = parseVibe(vibe);
        return (
          <span
            key={`vibe-${idx}`}
            className="group relative inline-flex cursor-pointer items-center gap-1 rounded-full border border-accent/30 bg-accent/10 px-2.5 py-1.5 text-xs font-semibold transition-all hover:bg-accent/20"
          >
            <span className="text-sm">{emoji}</span>
            {text}
            <button
              type="button"
              onClick={() => onRemoveVibe(idx)}
              className="absolute -right-1 -top-1 flex h-3.5 w-3.5 items-center justify-center rounded-full bg-gray-500 text-white opacity-0 transition-opacity hover:bg-gray-600 group-hover:opacity-70"
              aria-label={`Remove ${text}`}
            >
              <X className="h-2.5 w-2.5" />
            </button>
          </span>
        );
      })}
      {/* Show pending vibe with loading spinner */}
      {pendingVibe && (
        <span className="inline-flex items-center gap-1 rounded-full border border-accent/30 bg-accent/10 px-2.5 py-1.5 text-xs font-semibold animate-pulse">
          <Loader2 className="h-3 w-3 text-accent animate-spin" />
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
            className="w-32 rounded-full border border-accent/30 bg-accent/5 px-3 py-1.5 text-xs placeholder:text-muted-foreground/50 focus:border-accent/50 focus:outline-none focus:ring-1 focus:ring-accent/30 transition-all"
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
          className="flex h-7 w-7 items-center justify-center rounded-full border border-dashed border-accent/40 bg-accent/5 text-accent/60 hover:border-accent/60 hover:bg-accent/10 hover:text-accent transition-all"
          aria-label="Add vibe"
          title={vibes.length === 0 ? "What's the vibe? Adventure, F1, relaxation..." : "Add another vibe"}
        >
          <Plus className="h-4 w-4" />
        </button>
      )}
    </div>
  );
}

export const VibesSection = memo(VibesSectionInner);
