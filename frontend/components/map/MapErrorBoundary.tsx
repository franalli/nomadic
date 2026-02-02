'use client';

import { MapPin } from 'lucide-react';
import { Component, type ReactNode } from 'react';

import { cn } from '@/lib/utils';

interface Props {
  children: ReactNode;
  className?: string;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

/**
 * Error boundary specifically for Mapbox components.
 * Catches internal Mapbox errors (like errorCb race conditions) and shows fallback UI.
 */
export class MapErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, errorInfo: React.ErrorInfo) {
    // Suppress known Mapbox timing errors
    const message = error.message || '';
    if (
      message.includes('errorCb is not a function') ||
      message.includes('Map container is already removed') ||
      message.includes('Cannot read properties of undefined')
    ) {
      console.warn('[MapErrorBoundary] Suppressed Mapbox timing error:', message);
      return;
    }
    console.error('[MapErrorBoundary] Map error:', error, errorInfo);
  }

  // Reset error state when children change (allows recovery on re-render)
  componentDidUpdate(prevProps: Props) {
    if (this.state.hasError && prevProps.children !== this.props.children) {
      this.setState({ hasError: false, error: null });
    }
  }

  render() {
    if (this.state.hasError) {
      // Check if it's a recoverable Mapbox error
      const message = this.state.error?.message || '';
      const isRecoverable =
        message.includes('errorCb is not a function') ||
        message.includes('Map container is already removed');

      if (isRecoverable) {
        // Auto-recover by resetting state after a brief delay
        setTimeout(() => {
          this.setState({ hasError: false, error: null });
        }, 100);
      }

      return (
        <div
          className={cn(
            'w-full h-full rounded-xl overflow-hidden border border-white/10 bg-zinc-900 flex items-center justify-center',
            this.props.className
          )}
        >
          <div className="text-center p-6">
            <MapPin className="w-12 h-12 text-muted-foreground/30 mx-auto mb-3" />
            <p className="text-sm text-muted-foreground">Map loading...</p>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}
