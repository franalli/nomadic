'use client';

import { cn } from '@/lib/utils';

interface SkeletonProps extends React.HTMLAttributes<HTMLDivElement> {
  className?: string;
}

export function Skeleton({ className, ...props }: SkeletonProps) {
  return (
    <div
      className={cn(
        'animate-pulse rounded-md bg-muted/60',
        className
      )}
      {...props}
    />
  );
}

export function TileCardSkeleton() {
  return (
    <div className="rounded-xl border border-border/40 bg-card p-4 space-y-3">
      <Skeleton className="h-32 w-full rounded-lg" />
      <div className="space-y-2">
        <Skeleton className="h-4 w-3/4" />
        <Skeleton className="h-3 w-1/2" />
      </div>
      <div className="flex justify-between items-center pt-2">
        <Skeleton className="h-5 w-20 rounded-full" />
        <Skeleton className="h-8 w-8 rounded-full" />
      </div>
    </div>
  );
}

export function TilesGridSkeleton({ count = 6 }: { count?: number }) {
  return (
    <div
      className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3"
      role="status"
      aria-label="Loading trip options"
    >
      {Array.from({ length: count }).map((_, i) => (
        <TileCardSkeleton key={i} />
      ))}
      <span className="sr-only">Loading trip options...</span>
    </div>
  );
}

export function BranchCardSkeleton() {
  return (
    <div className="rounded-2xl border border-border/40 overflow-hidden">
      <div className="relative h-48 bg-muted/40">
        <Skeleton className="h-full w-full" />
        <div className="absolute inset-0 p-4 flex flex-col justify-between">
          <div className="flex justify-between">
            <Skeleton className="h-6 w-20 rounded-full" />
            <Skeleton className="h-6 w-24 rounded-full" />
          </div>
          <div className="space-y-2">
            <Skeleton className="h-6 w-3/4" />
            <Skeleton className="h-4 w-full" />
            <div className="flex justify-between pt-2">
              <Skeleton className="h-4 w-16" />
              <Skeleton className="h-4 w-16" />
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

export function BranchPanelSkeleton({ branchCount = 3 }: { branchCount?: number }) {
  return (
    <div
      className="space-y-4"
      role="status"
      aria-label="Loading trip suggestions"
    >
      <div className="space-y-2">
        <Skeleton className="h-4 w-24" />
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {Array.from({ length: branchCount }).map((_, i) => (
            <BranchCardSkeleton key={i} />
          ))}
        </div>
      </div>
      <span className="sr-only">Loading trip suggestions...</span>
    </div>
  );
}
