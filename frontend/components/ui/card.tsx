import * as React from 'react';

import { cn } from '@/lib/utils';

type CardElementProps = React.HTMLAttributes<HTMLDivElement>;

export const Card = React.forwardRef<HTMLDivElement, CardElementProps>(
  ({ className = '', ...props }, ref) => (
    <div
      ref={ref}
      className={cn(
        'border-border bg-card text-card-foreground rounded-xl border shadow-sm',
        className
      )}
      {...props}
    />
  )
);
Card.displayName = 'Card';

export const CardBody = React.forwardRef<HTMLDivElement, CardElementProps>(
  ({ className = '', ...props }, ref) => (
    <div ref={ref} className={cn('p-4', className)} {...props} />
  )
);
CardBody.displayName = 'CardBody';

export const CardContent = React.forwardRef<HTMLDivElement, CardElementProps>(
  ({ className = '', ...props }, ref) => (
    <div ref={ref} className={cn('p-4', className)} {...props} />
  )
);
CardContent.displayName = 'CardContent';
