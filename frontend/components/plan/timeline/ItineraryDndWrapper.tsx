'use client';

import type { DragEndEvent, DragStartEvent } from '@dnd-kit/core';
import {
  closestCorners,
  DndContext,
  DragOverlay,
  PointerSensor,
  TouchSensor,
  useSensor,
  useSensors,
} from '@dnd-kit/core';
import type { ReactNode } from 'react';
import { useCallback, useEffect, useRef, useState } from 'react';

import { useToast } from '@/components/ui/toast';
import { applyArrangement, validateArrangement } from '@/lib/api';
import { useDocumentStore } from '@/state/documentStore';
import type { DayBlock } from '@/types/plan-envelope';

import { DragPreviewCard } from './DragPreviewCard';

interface BlockViolation {
  block_id: string;
  violation_code: string;
  severity: 'blocking' | 'warning';
  message: string;
  target_day: number;
}

interface ItineraryDndWrapperProps {
  children: ReactNode;
}

export function ItineraryDndWrapper({ children }: ItineraryDndWrapperProps) {
  const [activeBlock, setActiveBlock] = useState<DayBlock | null>(null);
  // violations retained for future inline highlight usage (Stage 14)
  const [_violations, setViolations] = useState<BlockViolation[]>([]);
  const violationTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const { toast } = useToast();

  useEffect(() => {
    return () => {
      if (violationTimeoutRef.current) clearTimeout(violationTimeoutRef.current);
    };
  }, []);

  const sensors = useSensors(
    useSensor(PointerSensor, {
      activationConstraint: { distance: 8 },
    }),
    useSensor(TouchSensor, {
      activationConstraint: { delay: 300, tolerance: 5 },
    })
  );

  const handleDragStart = useCallback((event: DragStartEvent) => {
    setActiveBlock(event.active.data.current?.block as DayBlock ?? null);
    setViolations([]);
    // Prevent MobileSwipeLayout's horizontal scroll-snap from firing during drag
    document.body.setAttribute('data-dnd-active', 'true');
    if (typeof navigator !== 'undefined' && navigator.vibrate) navigator.vibrate(50);
  }, []);

  const handleDragCancel = useCallback(() => {
    setActiveBlock(null);
    document.body.removeAttribute('data-dnd-active');
  }, []);

  const handleDragEnd = useCallback(async (event: DragEndEvent) => {
    const { active, over } = event;
    setActiveBlock(null);
    document.body.removeAttribute('data-dnd-active');

    if (!over) return;

    // Guard: only accept droppable day targets (activity days use 'day-N', free days use 'free-day-N')
    const overId = over.id as string;
    let toDay: number;
    if (overId.startsWith('free-day-')) {
      toDay = parseInt(overId.replace('free-day-', ''), 10);
    } else if (overId.startsWith('day-')) {
      toDay = parseInt(overId.replace('day-', ''), 10);
    } else {
      return;
    }
    if (isNaN(toDay)) return;

    const blockId = active.id as string;
    const fromDay = active.data.current?.dayNumber as number;

    if (fromDay === toDay) return; // same day — no-op

    const move = { block_id: blockId, from_day: fromDay, to_day: toDay };

    const store = useDocumentStore.getState();
    store.claimMutation();
    try {
      // Step 1: Validate
      const result = await validateArrangement([move]);

      if (!result.valid) {
        const blocking = result.violations.filter(v => v.severity === 'blocking');
        setViolations(result.violations);
        toast(
          blocking[0]?.message ?? 'Move not allowed',
          { type: 'error', duration: 4000 }
        );
        if (violationTimeoutRef.current) clearTimeout(violationTimeoutRef.current);
        violationTimeoutRef.current = setTimeout(() => setViolations([]), 3000);
        return;
      }

      // Step 2: Apply
      const version = useDocumentStore.getState().version;
      const applied = await applyArrangement([move], version);

      if (applied.day_cards != null && applied.version != null) {
        useDocumentStore.getState().mergeEnvelope({
          day_cards: applied.day_cards as import('@/types/plan-envelope').DayCard[],
        });
        useDocumentStore.setState({ version: applied.version });
      }

      // Show warnings as toast (non-blocking — move succeeded)
      const warnings = applied.violations?.filter(v => v.severity === 'warning') ?? [];
      if (warnings.length > 0) {
        toast(warnings[0].message, { type: 'warning', duration: 4000 });
      }
    } catch (err) {
      if ((err as Error).message === 'VERSION_CONFLICT') {
        toast('Plan was updated — refreshing...', { type: 'info', duration: 3000 });
        useDocumentStore.getState().fetchDocument().catch((e: unknown) => {
          console.error('[DnD] fetchDocument failed after version conflict:', e);
        });
      } else {
        console.error('[DnD] Arrangement failed:', err);
        toast('Could not move block — try again', { type: 'error', duration: 4000 });
      }
    } finally {
      store.releaseMutation();
    }
  }, [toast]);

  return (
    <DndContext
      sensors={sensors}
      collisionDetection={closestCorners}
      onDragStart={handleDragStart}
      onDragEnd={handleDragEnd}
      onDragCancel={handleDragCancel}
    >
      {children}
      <DragOverlay dropAnimation={null} zIndex={9999}>
        {activeBlock && <DragPreviewCard block={activeBlock} />}
      </DragOverlay>
    </DndContext>
  );
}
