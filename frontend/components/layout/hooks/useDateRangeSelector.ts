'use client';

import { eachDayOfInterval, format, isBefore, parse, startOfDay } from 'date-fns';
import { useCallback, useMemo, useState } from 'react';
import type { DateRange } from 'react-day-picker';

import {
  toTripInputsDraft,
  type TripInputsDraft,
} from '@/components/layout/TripDetailsForm';
import { formatDateForDisplay } from '@/lib/utils';
import { useDocumentStore } from '@/state/documentStore';
import type { DocumentTripInputs } from '@/types/document';
import type { ChatPanelActions, ToastType } from '@/types/hooks';

/**
 * State machine for date range selection.
 * Replaces multiple refs with a single state object for clearer control flow.
 */
type SelectionPhase = 'idle' | 'selecting';

interface SelectionState {
  phase: SelectionPhase;
  pendingStartDate: string | null;
  hadCompleteRange: boolean;
}

export interface DateRangeSelectorOptions {
  tripInputs: DocumentTripInputs;
  tripInputsDraft: TripInputsDraft;
  setTripInputsDraft: React.Dispatch<React.SetStateAction<TripInputsDraft>>;
  chatPanelActions: ChatPanelActions | null;
  onToast: (message: string, type?: ToastType) => void;
}

export interface DateRangeSelectorState {
  calendarOpen: boolean;
}

export interface DateRangeSelectorComputed {
  selectedDateRange: DateRange | undefined;
  previewDays: Date[];
  hasDateValidationWarning: boolean;
}

export interface DateRangeSelectorActions {
  handleCalendarDayClick: (day: Date) => Promise<void>;
  handleCalendarDayMouseEnter: (day: Date) => void;
  handleCalendarMouseLeave: () => void;
  handleCalendarOpenChange: (open: boolean) => void;
  handleDatePresetClick: (range: DateRange) => Promise<void>;
  handleResetDates: () => Promise<void>;
}

export type UseDateRangeSelectorReturn = DateRangeSelectorState &
  DateRangeSelectorComputed &
  DateRangeSelectorActions;

export function useDateRangeSelector(
  options: DateRangeSelectorOptions
): UseDateRangeSelectorReturn {
  const {
    tripInputs,
    tripInputsDraft,
    setTripInputsDraft,
    chatPanelActions,
    onToast,
  } = options;

  const documentStore = useDocumentStore();

  // State
  const [calendarOpen, setCalendarOpen] = useState(false);
  const [hoveredDate, setHoveredDate] = useState<Date | null>(null);
  const [isResettingDateRange, setIsResettingDateRange] = useState(false);

  // State machine for tracking selection phase
  const [selection, setSelection] = useState<SelectionState>({
    phase: 'idle',
    pendingStartDate: null,
    hadCompleteRange: false,
  });

  // Parse dates for calendar - use draft state when calendar is open for smoother selection
  const calendarStartDate = useMemo(() => {
    const dateStr = calendarOpen ? tripInputsDraft.start_date : tripInputs.start_date;
    if (!dateStr) return undefined;
    return parse(dateStr, 'yyyy-MM-dd', new Date());
  }, [calendarOpen, tripInputsDraft.start_date, tripInputs.start_date]);

  const calendarEndDate = useMemo(() => {
    const dateStr = calendarOpen ? tripInputsDraft.end_date : tripInputs.end_date;
    if (!dateStr) return undefined;
    return parse(dateStr, 'yyyy-MM-dd', new Date());
  }, [calendarOpen, tripInputsDraft.end_date, tripInputs.end_date]);

  // When resetting, briefly show no selection for visual feedback
  const selectedDateRange: DateRange | undefined = useMemo(
    () =>
      isResettingDateRange
        ? undefined
        : calendarStartDate || calendarEndDate
          ? { from: calendarStartDate, to: calendarEndDate }
          : undefined,
    [isResettingDateRange, calendarStartDate, calendarEndDate]
  );

  // Compute preview days for hover effect (days between start and hovered date)
  const previewDays = useMemo(() => {
    if (!calendarStartDate || !hoveredDate || calendarEndDate) {
      return [];
    }
    // Create interval between start and hovered date
    const start = calendarStartDate;
    const end = hoveredDate;
    if (isBefore(end, start)) {
      return eachDayOfInterval({ start: end, end: start });
    }
    return eachDayOfInterval({ start, end });
  }, [calendarStartDate, calendarEndDate, hoveredDate]);

  // Validation: check if dates are in the past
  const hasDateValidationWarning = useMemo(() => {
    const today = startOfDay(new Date());
    const isStartDatePast = calendarStartDate && isBefore(calendarStartDate, today);
    const isEndDatePast = calendarEndDate && isBefore(calendarEndDate, today);
    return Boolean(isStartDatePast || isEndDatePast);
  }, [calendarStartDate, calendarEndDate]);

  // Primary handler for date selection - handles all click logic
  // We use onDayClick instead of onSelect to have full control over range behavior
  const handleCalendarDayClick = useCallback(
    async (day: Date) => {
      const clickedIso = format(day, 'yyyy-MM-dd');

      // Check if we're waiting for the end date selection
      if (selection.phase === 'selecting' && selection.pendingStartDate) {
        // This is the second click - set end date
        const startIso = selection.pendingStartDate;
        const startDate = parse(startIso, 'yyyy-MM-dd', new Date());

        let newStartIso: string;
        let newEndIso: string;

        if (isBefore(day, startDate)) {
          // Clicked before start - swap them
          newStartIso = clickedIso;
          newEndIso = startIso;
        } else {
          // Normal case - clicked date is end
          newStartIso = startIso;
          newEndIso = clickedIso;
        }

        // Reset selection state
        setSelection({ phase: 'idle', pendingStartDate: null, hadCompleteRange: false });
        setHoveredDate(null);

        // Update draft
        setTripInputsDraft((prev) => {
          const base = prev ?? toTripInputsDraft(tripInputs);
          return { ...base, start_date: newStartIso, end_date: newEndIso };
        });

        // Close calendar and commit
        setCalendarOpen(false);

        const prevStartIso = tripInputs.start_date;
        const prevEndIso = tripInputs.end_date;
        if (newStartIso !== prevStartIso || newEndIso !== prevEndIso) {
          const success = await documentStore.commitTripInputs({
            start_date: newStartIso,
            end_date: newEndIso,
          });

          if (!success) {
            onToast('Failed to update dates. Please try again.', 'error');
            return;
          }

          const startDisplay = formatDateForDisplay(newStartIso);
          const endDisplay = formatDateForDisplay(newEndIso);
          chatPanelActions?.addAssistantMessage(
            `Perfect! Travel dates set: ${startDisplay} – ${endDisplay}. 📅`
          );
        }
      } else {
        // This is the first click (or resetting from complete range) - set start date, wait for end

        // If we had a complete range when we started, show brief visual feedback that we're resetting
        if (selection.hadCompleteRange) {
          setIsResettingDateRange(true);
          // Brief flash effect, then clear
          setTimeout(() => setIsResettingDateRange(false), 150);
        }

        // Transition to selecting phase
        setSelection({
          phase: 'selecting',
          pendingStartDate: clickedIso,
          hadCompleteRange: false,
        });
        setHoveredDate(null);

        // Update draft to show only start date selected - explicitly clear end_date
        setTripInputsDraft((prev) => {
          const base = prev ?? toTripInputsDraft(tripInputs);
          return { ...base, start_date: clickedIso, end_date: null };
        });
      }
    },
    [tripInputs, documentStore, setTripInputsDraft, onToast, chatPanelActions, selection]
  );

  // Handler for mouse enter on calendar days - shows preview of range
  const handleCalendarDayMouseEnter = useCallback((day: Date) => {
    // Only show preview when we're waiting for the end date
    if (selection.phase === 'selecting' && selection.pendingStartDate) {
      setHoveredDate(day);
    }
  }, [selection]);

  // Clear hover when mouse leaves the calendar
  const handleCalendarMouseLeave = useCallback(() => {
    setHoveredDate(null);
  }, []);

  // Handler for calendar popover open state change
  const handleCalendarOpenChange = useCallback(
    (open: boolean) => {
      if (open) {
        // Sync draft with current tripInputs when opening
        setTripInputsDraft((prev) => ({
          ...prev,
          start_date: tripInputs.start_date ?? null,
          end_date: tripInputs.end_date ?? null,
        }));
        setHoveredDate(null);
        // Reset selection state - track if we have a complete range for reset detection
        setSelection({
          phase: 'idle',
          pendingStartDate: null,
          hadCompleteRange: Boolean(tripInputs.start_date && tripInputs.end_date),
        });
      } else {
        // Calendar closed - reset selection state
        setSelection({ phase: 'idle', pendingStartDate: null, hadCompleteRange: false });
      }
      setCalendarOpen(open);
    },
    [tripInputs.start_date, tripInputs.end_date, setTripInputsDraft]
  );

  // Handler for preset date ranges (quick picks)
  const handleDatePresetClick = useCallback(
    async (range: DateRange) => {
      const startIso = range.from ? format(range.from, 'yyyy-MM-dd') : null;
      const endIso = range.to ? format(range.to, 'yyyy-MM-dd') : null;

      if (!startIso || !endIso) return;

      // Update draft
      setTripInputsDraft((prev) => {
        const base = prev ?? toTripInputsDraft(tripInputs);
        return {
          ...base,
          start_date: startIso,
          end_date: endIso,
        };
      });

      // Close calendar and commit
      setCalendarOpen(false);

      const prevStartIso = tripInputs.start_date;
      const prevEndIso = tripInputs.end_date;
      const startChanged = startIso !== prevStartIso;
      const endChanged = endIso !== prevEndIso;

      if (startChanged || endChanged) {
        const updates: { start_date: string | null; end_date: string | null } = {
          start_date: startIso,
          end_date: endIso,
        };
        const success = await documentStore.commitTripInputs(updates);

        if (!success) {
          onToast('Failed to update dates. Please try again.', 'error');
          return;
        }

        const startDisplay = formatDateForDisplay(startIso);
        const endDisplay = formatDateForDisplay(endIso);
        const message = `Perfect! Travel dates set: ${startDisplay} – ${endDisplay}. 📅`;
        chatPanelActions?.addAssistantMessage(message);
      }
    },
    [tripInputs, documentStore, setTripInputsDraft, onToast, chatPanelActions]
  );

  // Handler to reset dates
  const handleResetDates = useCallback(async () => {
    setTripInputsDraft((prev) => {
      const base = prev ?? toTripInputsDraft(tripInputs);
      return {
        ...base,
        start_date: null,
        end_date: null,
      };
    });

    // Also commit the reset to the store
    if (tripInputs.start_date || tripInputs.end_date) {
      await documentStore.commitTripInputs({
        start_date: null,
        end_date: null,
      });
    }
  }, [tripInputs, documentStore, setTripInputsDraft]);

  return {
    // State
    calendarOpen,
    // Computed
    selectedDateRange,
    previewDays,
    hasDateValidationWarning,
    // Actions
    handleCalendarDayClick,
    handleCalendarDayMouseEnter,
    handleCalendarMouseLeave,
    handleCalendarOpenChange,
    handleDatePresetClick,
    handleResetDates,
  };
}
