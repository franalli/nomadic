'use client';

import { X } from 'lucide-react';
import { memo, useEffect, useRef, useState } from 'react';

import { ConfirmDialog } from '@/components/ui/confirm-dialog';

// ─────────────────────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────────────────────

export interface LocationBadgeProps {
  type: 'origin' | 'destination';
  index?: number;
  value: string;
  isSelected: boolean;
  onSelect: (key: 'origin' | number | null) => void;
  onRemove: () => void;
}

// ─────────────────────────────────────────────────────────────────────────────
// LocationBadge Component
// ─────────────────────────────────────────────────────────────────────────────

export const LocationBadge = memo(function LocationBadge({
  type,
  index,
  value,
  isSelected,
  onSelect,
  onRemove,
}: LocationBadgeProps) {
  const badgeKey = type === 'origin' ? 'origin' : index!;
  const badgeRef = useRef<HTMLSpanElement>(null);
  const [showConfirm, setShowConfirm] = useState(false);

  useEffect(() => {
    if (isSelected && badgeRef.current) {
      badgeRef.current.focus();
    }
  }, [isSelected]);

  const handleRemoveClick = (e: React.MouseEvent) => {
    e.stopPropagation();
    setShowConfirm(true);
  };

  const handleConfirmRemove = () => {
    onRemove();
  };

  const typeLabel = type === 'origin' ? 'departure city' : 'destination';

  return (
    <>
      <span
        ref={badgeRef}
        className={`group relative inline-flex cursor-pointer items-center gap-1 text-xs font-semibold transition-all duration-150 outline-none ${
          isSelected
            ? 'bg-gradient-to-b from-primary/25 to-primary/15 rounded-full px-2 py-0.5 ring-primary ring-2 ring-offset-2 ring-offset-background shadow-pill-active'
            : 'hover:bg-gradient-to-b hover:from-muted/70 hover:to-muted/40 rounded-full px-1.5 py-0.5'
        }`}
        role="button"
        tabIndex={0}
        onClick={(e) => {
          e.stopPropagation();
          onSelect(isSelected ? null : badgeKey);
        }}
        onKeyDown={(e) => {
          if (e.key === 'Delete' || e.key === 'Backspace') {
            e.preventDefault();
            setShowConfirm(true);
          } else if (e.key === 'Escape') {
            e.preventDefault();
            onSelect(null);
            badgeRef.current?.blur();
          } else if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            onSelect(isSelected ? null : badgeKey);
          }
        }}
      >
        {value}
        <button
          type="button"
          onClick={handleRemoveClick}
          className="absolute -right-1 -top-1 flex h-4 w-4 items-center justify-center rounded-full bg-muted-foreground/80 text-background opacity-0 shadow-sm transition-all duration-150 hover:bg-destructive hover:scale-110 group-hover:opacity-80"
          aria-label={`Remove ${value}`}
        >
          <X className="h-2.5 w-2.5" />
        </button>
      </span>
      <ConfirmDialog
        isOpen={showConfirm}
        onClose={() => setShowConfirm(false)}
        onConfirm={handleConfirmRemove}
        title={`Remove ${value}?`}
        description={`Are you sure you want to remove "${value}" as your ${typeLabel}? This may affect your trip options.`}
        confirmLabel="Remove"
        cancelLabel="Keep it"
        variant="destructive"
      />
    </>
  );
});
