'use client';

import * as Collapsible from '@radix-ui/react-collapsible';
import type { LucideIcon } from 'lucide-react';
import { ChevronDown } from 'lucide-react';
import { memo, type ReactNode } from 'react';

// ─────────────────────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────────────────────

export interface ExpandablePillProps {
  /** Display label for the field (shown in the pill) */
  label: string;
  /** Icon component to display */
  icon: LucideIcon;
  /** Whether the expanded section is open */
  isOpen: boolean;
  /** Called when the expanded state changes */
  onOpenChange: (open: boolean) => void;
  /** Content to display when expanded (e.g., current value + input fields) */
  expandedContent: ReactNode;
}

// ─────────────────────────────────────────────────────────────────────────────
// ExpandablePill Component
// ─────────────────────────────────────────────────────────────────────────────

function ExpandablePillInner({
  label,
  icon: Icon,
  isOpen,
  onOpenChange,
  expandedContent,
}: ExpandablePillProps) {
  return (
    <Collapsible.Root
      className="flex flex-col"
      open={isOpen}
      onOpenChange={onOpenChange}
    >
      <Collapsible.Trigger asChild>
        <button
          type="button"
          className="group inline-flex items-center gap-1.5 border rounded-full px-2.5 py-1 transition-colors border-border/40 bg-muted/20 text-muted-foreground hover:bg-muted/40"
        >
          <Icon className="h-3.5 w-3.5" />
          <span className="text-xs font-semibold">{label}</span>
          <ChevronDown
            className={`h-3.5 w-3.5 transition-all opacity-0 group-hover:opacity-100 ${isOpen ? 'rotate-180 opacity-100' : ''}`}
          />
        </button>
      </Collapsible.Trigger>

      {/* Expanded content */}
      <Collapsible.Content className="overflow-hidden data-[state=open]:animate-collapsible-down data-[state=closed]:animate-collapsible-up">
        <div className="pt-2 flex flex-wrap gap-2">
          {expandedContent}
        </div>
      </Collapsible.Content>
    </Collapsible.Root>
  );
}

export const ExpandablePill = memo(ExpandablePillInner);
