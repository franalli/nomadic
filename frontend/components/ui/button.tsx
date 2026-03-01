/**
 * Button Component
 *
 * Follows design-system.md DS.actions tokens:
 * - primary: Black light / Emerald dark with glow
 * - secondary: Grey text, darkens/whitens on hover
 * - outline: Border-defined with glass fill in dark
 * - ghost: Transparent with subtle hover
 */
import * as React from 'react';

import { DS } from '@/lib/design-system';
import { cn } from '@/lib/utils';

type ButtonVariant = 'primary' | 'outline' | 'ghost' | 'secondary';
type ButtonSize = 'default' | 'sm' | 'lg' | 'icon';

type ButtonProps = React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: ButtonVariant;
  size?: ButtonSize;
};

// DS.actions tokens - explicit light/dark mode styling per design-system.md
const variantClasses: Record<ButtonVariant, string> = {
  // DS.actions.primary: Black light / Emerald dark with glow
  primary: cn(
    'bg-zinc-900 text-white border border-zinc-900',
    'hover:bg-zinc-800 hover:border-zinc-800',
    'dark:bg-emerald-600 dark:border-emerald-600 dark:text-white',
    `dark:${DS.glowClass.lg}`,
    'dark:hover:bg-emerald-500 dark:hover:border-emerald-500'
  ),
  // DS.actions.secondary: Grey text, darkens/whitens on hover
  secondary: cn(
    'bg-transparent text-zinc-500 border border-transparent',
    'hover:text-zinc-900 hover:bg-zinc-100',
    'dark:text-zinc-500 dark:hover:text-white dark:hover:bg-white/5'
  ),
  // Outline: Border-defined with glass fill in dark (DS pills.inactive pattern)
  outline: cn(
    'bg-white text-zinc-700 border border-zinc-200',
    'hover:bg-zinc-50 hover:border-zinc-900 hover:text-zinc-900',
    'dark:bg-white/5 dark:text-zinc-400 dark:border-white/15',
    'dark:hover:bg-white/10 dark:hover:border-white/40 dark:hover:text-white'
  ),
  // Ghost: Transparent with subtle hover
  ghost: cn(
    'bg-transparent text-zinc-600 border border-transparent',
    'hover:bg-zinc-100 hover:text-zinc-900',
    'dark:text-zinc-400 dark:hover:bg-white/5 dark:hover:text-white'
  ),
};

const sizeClasses: Record<ButtonSize, string> = {
  default: 'px-4 py-2 text-sm',
  sm: 'px-3 py-1.5 text-xs',
  lg: 'px-6 py-3 text-base',
  icon: 'h-9 w-9 p-0',
};

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className = '', variant = 'primary', size = 'default', ...props }, ref) => {
    const base = cn(
      'inline-flex items-center justify-center gap-2',
      'font-semibold rounded-xl',
      'transition-all duration-200 active:scale-[0.98]',
      'focus:outline-none focus-visible:ring-2 focus-visible:ring-zinc-900/20',
      'dark:focus-visible:ring-emerald-500/20',
      'disabled:opacity-50 disabled:cursor-not-allowed disabled:pointer-events-none'
    );

    return (
      <button
        ref={ref}
        className={cn(base, variantClasses[variant], sizeClasses[size], className)}
        {...props}
      />
    );
  }
);

Button.displayName = 'Button';
