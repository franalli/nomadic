import { addDays } from 'date-fns/addDays';
import { startOfDay } from 'date-fns/startOfDay';

export interface DatePreset {
  label: string;
  getDates: () => { from: Date; to: Date };
}

export function getThisWeekend(): { from: Date; to: Date } {
  const today = startOfDay(new Date());
  const dayOfWeek = today.getDay();
  const daysUntilSaturday = (6 - dayOfWeek + 7) % 7 || 7;
  const saturday = addDays(today, daysUntilSaturday);
  const sunday = addDays(saturday, 1);
  return { from: saturday, to: sunday };
}

export function getNextWeekend(): { from: Date; to: Date } {
  const thisWeekend = getThisWeekend();
  return { from: addDays(thisWeekend.from, 7), to: addDays(thisWeekend.to, 7) };
}

export function getWeekFromNow(weeks: number): { from: Date; to: Date } {
  const today = startOfDay(new Date());
  const from = addDays(today, 1);
  const to = addDays(from, weeks * 7 - 1);
  return { from, to };
}

export const DATE_PRESETS: DatePreset[] = [
  { label: 'This Weekend', getDates: () => getThisWeekend() },
  { label: 'Next Weekend', getDates: () => getNextWeekend() },
  { label: '1 Week', getDates: () => getWeekFromNow(1) },
  { label: '2 Weeks', getDates: () => getWeekFromNow(2) },
];
