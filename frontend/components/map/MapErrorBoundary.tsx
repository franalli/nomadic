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
  private recoverTimer: ReturnType<typeof setTimeout> | null = null;

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

  private clearRecoverTimer() {
    if (this.recoverTimer !== null) {
      clearTimeout(this.recoverTimer);
      this.recoverTimer = null;
    }
  }

  private scheduleRecovery() {
    if (this.recoverTimer !== null) return;
    this.recoverTimer = setTimeout(() => {
      this.recoverTimer = null;
      this.setState({ hasError: false, error: null });
    }, 100);
  }

  // Reset error state when children change (allows recovery on re-render)
  componentDidUpdate(prevProps: Props, prevState: State) {
    if (this.state.hasError && prevProps.children !== this.props.children) {
      this.clearRecoverTimer();
      this.setState({ hasError: false, error: null });
      return;
    }

    if (!this.state.hasError) {
      this.clearRecoverTimer();
      return;
    }

    // Recoverable map errors can auto-reset after a brief delay.
    const message = this.state.error?.message || '';
    const isRecoverable =
      message.includes('errorCb is not a function') ||
      message.includes('Map container is already removed');
    if (isRecoverable && (!prevState.hasError || prevState.error !== this.state.error)) {
      this.scheduleRecovery();
    } else if (!isRecoverable) {
      this.clearRecoverTimer();
    }
  }

  componentWillUnmount() {
    this.clearRecoverTimer();
  }

  render() {
    if (this.state.hasError) {
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
