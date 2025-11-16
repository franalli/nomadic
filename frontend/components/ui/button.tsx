import * as React from 'react';

type ButtonProps = React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: 'primary' | 'outline' | 'ghost';
};

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className = '', variant = 'primary', ...props }, ref) => {
    const base =
      'inline-flex items-center justify-center px-3 py-2 text-sm font-semibold rounded-md transition focus:outline-none focus:ring-2 focus:ring-offset-2';

    const variants: Record<string, string> = {
      primary: 'bg-primary text-white hover:bg-primary/90 focus:ring-primary',
      outline:
        'border border-primary text-primary bg-white hover:bg-primary/5 focus:ring-primary',
      ghost: 'text-slate-700 hover:bg-slate-100 focus:ring-slate-300',
    };

    return (
      <button
        ref={ref}
        className={`${base} ${variants[variant]} ${className}`}
        {...props}
      />
    );
  }
);

Button.displayName = 'Button';
