import { DS } from '@/lib/design-system';
import { cn } from '@/lib/utils';

export const STAR_OPTIONS = [
  { value: 0, label: 'Any' },
  { value: 3, label: '3\u2605+' },
  { value: 4, label: '4\u2605+' },
  { value: 5, label: '5\u2605' },
];

export const AMENITY_OPTIONS = [
  { value: 'wifi', label: 'WiFi' },
  { value: 'pool', label: 'Pool' },
  { value: 'parking', label: 'Parking' },
  { value: 'gym', label: 'Gym' },
  { value: 'spa', label: 'Spa' },
  { value: 'breakfast', label: 'Breakfast' },
  { value: 'pet_friendly', label: 'Pet friendly' },
];

function OptionButton({
  selected,
  onClick,
  className,
  children,
}: {
  selected: boolean;
  onClick: () => void;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        className,
        'rounded-lg text-sm font-medium',
        'transition-all duration-150',
        selected
          ? 'bg-zinc-900 text-white border-2 border-zinc-900 shadow-md dark:bg-white dark:text-black dark:border-transparent'
          : cn(
              'bg-white border-2 border-zinc-200 text-zinc-600',
              'hover:border-zinc-900 hover:bg-zinc-50 hover:text-zinc-900',
              'dark:bg-white/5 dark:border-2 dark:border-white/15 dark:text-zinc-400',
              'dark:hover:bg-white/10 dark:hover:text-white dark:hover:border-white/40'
            )
      )}
    >
      {children}
    </button>
  );
}

interface StarRatingSectionProps {
  minStars: number;
  onChange: (value: number) => void;
}

export function StarRatingSection({ minStars, onChange }: StarRatingSectionProps) {
  return (
    <div>
      <h3 className={cn(DS.text.label, 'mb-2')}>
        Minimum stars
      </h3>
      <div className="flex gap-2">
        {STAR_OPTIONS.map((option) => (
          <OptionButton
            key={option.value}
            selected={minStars === option.value}
            onClick={() => onChange(option.value)}
            className="flex-1 px-3 py-2.5"
          >
            {option.label}
          </OptionButton>
        ))}
      </div>
    </div>
  );
}

interface AmenitiesSectionProps {
  amenities: string[];
  onToggle: (amenity: string) => void;
}

export function AmenitiesSection({ amenities, onToggle }: AmenitiesSectionProps) {
  return (
    <div>
      <h3 className={cn(DS.text.label, 'mb-2')}>
        Preferred amenities
      </h3>
      <div className="flex flex-wrap gap-2">
        {AMENITY_OPTIONS.map((option) => (
          <OptionButton
            key={option.value}
            selected={amenities.includes(option.value)}
            onClick={() => onToggle(option.value)}
            className="px-4 py-2.5"
          >
            {option.label}
          </OptionButton>
        ))}
      </div>
    </div>
  );
}
