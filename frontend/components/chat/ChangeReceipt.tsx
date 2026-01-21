'use client';

import { Undo2 } from 'lucide-react';
import { memo, useEffect, useState } from 'react';

export type ReceiptType =
  | 'updated'           // Changes applied: "Updated: X, Y · Undo"
  | 'partial'           // One constraint only: "Updated: X · Waiting for dates..."
  | 'no_constraints'    // Nothing found: "No constraints found..."
  | 'intent_only'       // Intent but no constraints: "Add a destination..."
  | 'reverted';         // After undo: "Reverted: X, Y" (no undo button)

export interface ChangeReceiptData {
  type: ReceiptType;
  fields?: string[];        // For 'updated' and 'partial' types
  canUndo?: boolean;        // Whether undo is available
}

interface ChangeReceiptProps {
  receipt: ChangeReceiptData | null;
  onUndo?: () => void;
  onDismiss?: () => void;
  autoDismissMs?: number;   // Default: 5000ms
}

/**
 * ChangeReceipt - Inline status shown after constraint extraction.
 *
 * Shows:
 * - "Updated: Destination, Dates · Undo" (changes applied)
 * - "Updated: Destination · Waiting for dates (or duration)." (partial)
 * - "No constraints found. Add a destination and dates (or duration) to start the plan." (nothing)
 * - "Add a destination and dates (or duration). Budget is optional." (intent but no constraints)
 *
 * Animation: 120ms fade in, 150ms fade out, 4-5s auto-dismiss.
 */
export const ChangeReceipt = memo(function ChangeReceipt({
  receipt,
  onUndo,
  onDismiss,
  autoDismissMs = 5000,
}: ChangeReceiptProps) {
  const [visible, setVisible] = useState(false);
  const [exiting, setExiting] = useState(false);

  // Handle visibility and auto-dismiss
  useEffect(() => {
    if (!receipt) {
      setVisible(false);
      setExiting(false);
      return;
    }

    // Fade in
    setVisible(true);
    setExiting(false);

    // Auto-dismiss timer
    const timer = setTimeout(() => {
      setExiting(true);
      // Wait for fade out animation then dismiss
      setTimeout(() => {
        onDismiss?.();
      }, 150);
    }, autoDismissMs);

    return () => clearTimeout(timer);
  }, [receipt, autoDismissMs, onDismiss]);

  if (!receipt) return null;

  const handleUndo = () => {
    onUndo?.();
    onDismiss?.();
  };

  // Format fields for display: ["start_date", "end_date"] → "Dates"
  const formatFields = (fields: string[]): string => {
    const fieldMap: Record<string, string> = {
      destinations: 'Destination',
      origin: 'Origin',
      start_date: 'Dates',
      end_date: 'Dates',
      budget: 'Budget',
      adults: 'Travelers',
      children: 'Travelers',
    };

    const unique = new Set<string>();
    fields.forEach((f) => {
      const mapped = fieldMap[f] || f.charAt(0).toUpperCase() + f.slice(1).replace(/_/g, ' ');
      unique.add(mapped);
    });

    return Array.from(unique).join(', ');
  };

  const renderContent = () => {
    switch (receipt.type) {
      case 'updated':
        return (
          <>
            <span className="text-foreground/80">
              Updated: {formatFields(receipt.fields || [])}
            </span>
            {receipt.canUndo && onUndo && (
              <>
                <span className="text-muted-foreground/50 mx-1.5">·</span>
                <button
                  type="button"
                  onClick={handleUndo}
                  className="inline-flex items-center gap-1 text-primary hover:text-primary/80 transition-colors"
                >
                  <Undo2 className="h-3 w-3" />
                  <span>Undo</span>
                </button>
              </>
            )}
          </>
        );

      case 'partial':
        return (
          <>
            <span className="text-foreground/80">
              Updated: {formatFields(receipt.fields || [])}
            </span>
            <span className="text-muted-foreground/50 mx-1.5">·</span>
            <span className="text-muted-foreground">
              Waiting for dates (or duration).
            </span>
            {receipt.canUndo && onUndo && (
              <>
                <span className="text-muted-foreground/50 mx-1.5">·</span>
                <button
                  type="button"
                  onClick={handleUndo}
                  className="inline-flex items-center gap-1 text-primary hover:text-primary/80 transition-colors"
                >
                  <Undo2 className="h-3 w-3" />
                  <span>Undo</span>
                </button>
              </>
            )}
          </>
        );

      case 'no_constraints':
        return (
          <span className="text-muted-foreground">
            No constraints found. Add a destination and dates (or duration) to start the plan.
          </span>
        );

      case 'intent_only':
        return (
          <span className="text-muted-foreground">
            Add a destination and dates (or duration). Budget is optional.
          </span>
        );

      case 'reverted':
        return (
          <span className="text-foreground/80">
            Reverted: {formatFields(receipt.fields || [])}
          </span>
        );

      default:
        return null;
    }
  };

  return (
    <div
      className={`flex items-center justify-start text-xs py-2 transition-opacity ${
        exiting ? 'opacity-0 duration-150' : visible ? 'opacity-100 duration-[120ms]' : 'opacity-0'
      }`}
      style={{ transitionTimingFunction: exiting ? 'ease-in' : 'ease-out' }}
    >
      {renderContent()}
    </div>
  );
});
