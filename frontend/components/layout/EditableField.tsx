'use client';

import type { LucideIcon } from 'lucide-react';
import { CheckCircle2, Circle, X } from 'lucide-react';
import { memo } from 'react';

// ─────────────────────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────────────────────

export interface EditableFieldProps {
  /** Display label for the field */
  label: string;
  /** Icon component to display */
  icon: LucideIcon;
  /** Input placeholder text */
  placeholder: string;
  /** Placeholder text shown when field has no value (e.g. "e.g. 2") */
  emptyPlaceholder?: string;
  /** Whether the field is currently complete */
  isComplete: boolean;
  /** Whether this field is currently being edited */
  isEditing: boolean;
  /** Current draft value (string) */
  draftValue: string;
  /** Formatted display value when not editing */
  displayValue: string;
  /** Whether the field has a value */
  hasValue: boolean;
  /** Called when user clicks to start editing */
  onStartEditing: () => void;
  /** Called when draft value changes */
  onValueChange: (value: string) => void;
  /** Called to commit the value (on blur or Enter) */
  onCommit: (value: string) => void;
  /** Called to cancel editing (on Escape) */
  onCancel: () => void;
  /** Called to remove/clear the value */
  onRemove: () => void;
}

// ─────────────────────────────────────────────────────────────────────────────
// EditableField Component
// ─────────────────────────────────────────────────────────────────────────────

function EditableFieldInner({
  label,
  icon: Icon,
  placeholder,
  emptyPlaceholder,
  isComplete,
  isEditing,
  draftValue,
  displayValue,
  hasValue,
  onStartEditing,
  onValueChange,
  onCommit,
  onCancel,
  onRemove,
}: EditableFieldProps) {
  return (
    <div className="flex flex-col gap-1">
      {/* Field label with completion indicator */}
      <div
        className={`flex items-center gap-1 text-xs transition-colors ${
          isComplete ? 'text-accent' : 'text-muted-foreground/40'
        }`}
      >
        {isComplete ? (
          <CheckCircle2 className="h-3 w-3" />
        ) : (
          <Circle className="h-3 w-3 opacity-60" strokeDasharray="2 2" />
        )}
        <span className={isComplete ? 'font-medium' : ''}>{label}</span>
        {!isComplete && (
          <span className="text-[10px] text-muted-foreground/40">(optional)</span>
        )}
      </div>

      {/* Field input/display */}
      <div className="group relative inline-flex">
        <div
          className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1.5 cursor-pointer transition-colors ${
            hasValue
              ? `border-border/60 bg-muted/40 ${isEditing ? 'ring-primary ring-1' : ''}`
              : 'border-border/40 bg-muted/20 border-dashed hover:border-primary/40 hover:bg-primary/5'
          }`}
          role="button"
          tabIndex={0}
          onClick={onStartEditing}
          onKeyDown={(e) => {
            if (e.key === 'Enter' || e.key === ' ') {
              e.preventDefault();
              onStartEditing();
            }
          }}
        >
          <span className={hasValue ? 'text-muted-foreground shrink-0' : 'shrink-0'}>
            <Icon className={`h-3.5 w-3.5 ${hasValue ? '' : 'text-muted-foreground/40'}`} />
          </span>

          {isEditing ? (
            <input
              type="number"
              value={draftValue}
              onChange={(e) => onValueChange(e.target.value)}
              className="text-foreground placeholder:text-muted-foreground w-16 bg-transparent text-xs font-semibold focus:outline-none"
              placeholder={placeholder}
              onClick={(e) => e.stopPropagation()}
              onBlur={(e) => onCommit(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  e.preventDefault();
                  onCommit((e.target as HTMLInputElement).value);
                } else if (e.key === 'Escape') {
                  e.preventDefault();
                  onCancel();
                }
              }}
              autoFocus
            />
          ) : hasValue ? (
            <span className="text-foreground whitespace-nowrap text-xs font-semibold">
              {displayValue}
            </span>
          ) : (
            <span className="text-xs text-muted-foreground/60 italic">{emptyPlaceholder ?? 'Click to set'}</span>
          )}
        </div>

        {/* Remove button */}
        {hasValue && !isEditing && (
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              onRemove();
            }}
            className="absolute -right-1 -top-1 flex h-3.5 w-3.5 items-center justify-center rounded-full bg-gray-500 text-white opacity-0 transition-opacity hover:bg-gray-600 group-hover:opacity-70"
            aria-label={`Clear ${label.toLowerCase()}`}
          >
            <X className="h-2.5 w-2.5" />
          </button>
        )}
      </div>
    </div>
  );
}

export const EditableField = memo(EditableFieldInner);
