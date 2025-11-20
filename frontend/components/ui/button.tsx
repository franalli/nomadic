import * as React from 'react';

import { cn } from '@/lib/utils';

type ButtonVariant = 'primary' | 'outline' | 'ghost';
type ButtonSize = 'default' | 'sm' | 'lg' | 'icon';

type ButtonProps = React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: ButtonVariant;
  size?: ButtonSize;
};

const variantClasses: Record<ButtonVariant, string> = {
  primary:
    'bg-primary text-primary-foreground border border-primary/80 hover:bg-primary/90 focus:ring-primary',
  outline:
    'border border-border bg-card text-foreground hover:bg-muted/60 focus:ring-ring shadow-sm',
  ghost: 'text-foreground hover:bg-muted/70 focus:ring-ring border border-transparent',
};

const sizeClasses: Record<ButtonSize, string> = {
  default: 'px-3 py-2 text-sm',
  sm: 'px-3 py-1.5 text-xs',
  lg: 'px-4 py-2.5 text-base',
  icon: 'h-9 w-9 p-0',
};

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className = '', variant = 'primary', size = 'default', ...props }, ref) => {
    const base =
      'inline-flex items-center justify-center gap-2 font-semibold rounded-md transition focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-offset-background disabled:opacity-60 disabled:cursor-not-allowed';

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
