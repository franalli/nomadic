import type { ChangeEvent } from 'react';

const VIBE_OPTIONS = [
  { value: 'foodie', label: 'Foodie' },
  { value: 'nightlife', label: 'Nightlife' },
  { value: 'culture', label: 'Culture' },
  { value: 'outdoors', label: 'Outdoors' },
  { value: 'relaxation', label: 'Relaxation' },
  { value: 'family', label: 'Family' },
];

export interface TripContextFormProps {
  origin: string;
  onOriginChange: (value: string) => void;
  startDate: string;
  onStartDateChange: (value: string) => void;
  endDate: string;
  onEndDateChange: (value: string) => void;
  budgetBucket?: string;
  onBudgetBucketChange: (value: string | undefined) => void;
  groupSize?: number;
  onGroupSizeChange: (value: number | undefined) => void;
  vibes: string[];
  onToggleVibe: (value: string) => void;
  onStartNewSession: () => void;
  isStartingNewSession?: boolean;
}

export function TripContextForm({
  origin,
  onOriginChange,
  startDate,
  onStartDateChange,
  endDate,
  onEndDateChange,
  budgetBucket,
  onBudgetBucketChange,
  groupSize,
  onGroupSizeChange,
  vibes,
  onToggleVibe,
  onStartNewSession,
  isStartingNewSession = false,
}: TripContextFormProps) {
  function handleGroupSizeChange(event: ChangeEvent<HTMLInputElement>) {
    const { value } = event.target;
    onGroupSizeChange(value ? Number(value) : undefined);
  }

  return (
    <div className="flex flex-col gap-4 rounded-lg border bg-white p-4 shadow-sm">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm font-semibold text-slate-700">Trip context</p>
        <div className="flex items-center gap-2 text-xs">
          <button
            type="button"
            className="rounded-md border border-slate-200 px-3 py-1 font-semibold text-slate-700 transition hover:border-slate-300 disabled:cursor-not-allowed disabled:opacity-60"
            onClick={onStartNewSession}
            disabled={isStartingNewSession}
          >
            {isStartingNewSession ? 'Starting…' : 'Start new session'}
          </button>
        </div>
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <label className="flex flex-col gap-1 text-xs text-slate-600">
          <span className="font-semibold uppercase tracking-wide text-slate-500">
            Origin
          </span>
          <input
            className="rounded-md border border-slate-200 px-2 py-1 text-sm"
            placeholder="e.g. Amsterdam"
            value={origin}
            onChange={(event) => onOriginChange(event.target.value)}
          />
        </label>

        <label className="flex flex-col gap-1 text-xs text-slate-600">
          <span className="font-semibold uppercase tracking-wide text-slate-500">
            Budget
          </span>
          <select
            className="rounded-md border border-slate-200 px-2 py-1 text-sm"
            value={budgetBucket ?? ''}
            onChange={(event) => onBudgetBucketChange(event.target.value || undefined)}
          >
            <option value="">Flexible</option>
            <option value="value">Value</option>
            <option value="mid">Mid</option>
            <option value="premium">Premium</option>
            <option value="luxury">Luxury</option>
          </select>
        </label>

        <label className="flex flex-col gap-1 text-xs text-slate-600">
          <span className="font-semibold uppercase tracking-wide text-slate-500">
            Start
          </span>
          <input
            type="date"
            className="rounded-md border border-slate-200 px-2 py-1 text-sm"
            value={startDate}
            onChange={(event) => onStartDateChange(event.target.value)}
          />
        </label>

        <label className="flex flex-col gap-1 text-xs text-slate-600">
          <span className="font-semibold uppercase tracking-wide text-slate-500">
            End
          </span>
          <input
            type="date"
            className="rounded-md border border-slate-200 px-2 py-1 text-sm"
            value={endDate}
            onChange={(event) => onEndDateChange(event.target.value)}
          />
        </label>

        <label className="flex flex-col gap-1 text-xs text-slate-600">
          <span className="font-semibold uppercase tracking-wide text-slate-500">
            Group size
          </span>
          <input
            type="number"
            min={1}
            className="rounded-md border border-slate-200 px-2 py-1 text-sm"
            value={groupSize ?? ''}
            onChange={handleGroupSizeChange}
          />
        </label>
      </div>

      <div className="flex flex-col gap-2 text-xs text-slate-600">
        <span className="font-semibold uppercase tracking-wide text-slate-500">
          Vibes
        </span>
        <div className="flex flex-wrap gap-2">
          {VIBE_OPTIONS.map((option) => {
            const active = vibes.includes(option.value);
            const baseClasses =
              'rounded-full border px-3 py-1 text-[11px] font-medium transition-colors';
            const activeClasses = 'border-blue-500 bg-blue-50 text-blue-600';
            const inactiveClasses = 'border-slate-200 bg-white text-slate-600';

            return (
              <button
                key={option.value}
                type="button"
                onClick={() => onToggleVibe(option.value)}
                className={`${baseClasses} ${active ? activeClasses : inactiveClasses}`}
              >
                {option.label}
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
}
