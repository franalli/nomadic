'use client';

import { eachDayOfInterval, format, isBefore, parse, startOfDay } from 'date-fns';
import { useCallback, useMemo, useRef, useState } from 'react';
import type { DateRange } from 'react-day-picker';

import {
  formatDateForDisplay,
  toTripInputsDraft,
  type TripInputsDraft,
} from '@/components/layout/TripDetailsForm';
import { useDocumentStore } from '@/state/documentStore';
import type { DocumentTripInputs } from '@/types/document';

export interface ChatPanelActions {
  addAssistantMessage: (message: string) => void;
}

export interface DateRangeSelectorOptions {
  tripInputs: DocumentTripInputs;
  tripInputsDraft: TripInputsDraft;
  setTripInputsDraft: React.Dispatch<React.SetStateAction<TripInputsDraft>>;
  chatPanelActions: ChatPanelActions | null;
  onToast: (message: string) => void;
}

export interface DateRangeSelectorState {
  calendarOpen: boolean;
  hoveredDate: Date | null;
  isResettingDateRange: boolean;
}

export interface DateRangeSelectorComputed {
  calendarStartDate: Date | undefined;
  calendarEndDate: Date | undefined;
  selectedDateRange: DateRange | undefined;
  previewDays: Date[];
  hasDateValidationWarning: boolean;
}

export interface DateRangeSelectorActions {
  setCalendarOpen: React.Dispatch<React.SetStateAction<boolean>>;
  setHoveredDate: React.Dispatch<React.SetStateAction<Date | null>>;
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

  // Track if we're waiting for the second click (end date)
  // This is needed because React state updates are async and onSelect may fire multiple times
  const isSelectingEndDateRef = useRef<boolean>(false);
  const pendingStartDateRef = useRef<string | null>(null);

  // Track if we had a complete range when selection started (for reset detection)
  const hadCompleteRangeRef = useRef<boolean>(false);

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
      // If isSelectingEndDateRef is false, this is either the first click or we're resetting
      if (isSelectingEndDateRef.current && pendingStartDateRef.current) {
        // This is the second click - set end date
        const startIso = pendingStartDateRef.current;
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

        // Reset the refs
        isSelectingEndDateRef.current = false;
        pendingStartDateRef.current = null;
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
            onToast('Failed to update dates. Please try again.');
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
        if (hadCompleteRangeRef.current) {
          setIsResettingDateRange(true);
          // Brief flash effect, then clear
          setTimeout(() => setIsResettingDateRange(false), 150);
        }

        // Now we're selecting - no longer have a complete range
        hadCompleteRangeRef.current = false;
        isSelectingEndDateRef.current = true;
        pendingStartDateRef.current = clickedIso;
        setHoveredDate(null);

        // Update draft to show only start date selected - explicitly clear end_date
        setTripInputsDraft((prev) => {
          const base = prev ?? toTripInputsDraft(tripInputs);
          return { ...base, start_date: clickedIso, end_date: null };
        });
      }
    },
    [tripInputs, documentStore, setTripInputsDraft, onToast, chatPanelActions]
  );

  // Handler for mouse enter on calendar days - shows preview of range
  // Use refs to check state since React state may be stale in callbacks
  const handleCalendarDayMouseEnter = useCallback((day: Date) => {
    // Only show preview when we're waiting for the end date
    if (isSelectingEndDateRef.current && pendingStartDateRef.current) {
      setHoveredDate(day);
    }
  }, []);

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
        // Track if we have a complete range when opening - used for reset detection
        hadCompleteRangeRef.current = Boolean(tripInputs.start_date && tripInputs.end_date);
        // Reset selection refs - any click will start fresh selection
        isSelectingEndDateRef.current = false;
        pendingStartDateRef.current = null;
      } else {
        // Calendar closed - reset refs
        isSelectingEndDateRef.current = false;
        pendingStartDateRef.current = null;
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
          onToast('Failed to update dates. Please try again.');
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
    /** @internal Kept for debugging and potential future use */
    hoveredDate,
    /** @internal Kept for debugging and potential future use */
    isResettingDateRange,
    // Computed
    /** @internal Kept for debugging and potential future use */
    calendarStartDate,
    /** @internal Kept for debugging and potential future use */
    calendarEndDate,
    selectedDateRange,
    previewDays,
    hasDateValidationWarning,
    // Actions
    /** @internal Kept for API completeness */
    setCalendarOpen,
    /** @internal Kept for API completeness */
    setHoveredDate,
    handleCalendarDayClick,
    handleCalendarDayMouseEnter,
    handleCalendarMouseLeave,
    handleCalendarOpenChange,
    handleDatePresetClick,
    handleResetDates,
  };
}
