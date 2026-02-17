'use client';

import { AlertCircle } from 'lucide-react';
import { Component, type ReactNode } from 'react';

interface Props {
  children: ReactNode;
  /** Label shown in the fallback UI and logged to console */
  label?: string;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

/**
 * Generic error boundary for route-level and panel components.
 * Shows a minimal fallback UI and logs the error.
 */
export class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, errorInfo: React.ErrorInfo) {
    console.error(`[ErrorBoundary${this.props.label ? `:${this.props.label}` : ''}]`, error, errorInfo);
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="flex items-center justify-center p-8 text-center">
          <div>
            <AlertCircle className="w-8 h-8 text-muted-foreground/40 mx-auto mb-2" />
            <p className="text-sm text-muted-foreground">
              Something went wrong{this.props.label ? ` in ${this.props.label}` : ''}.
            </p>
            <button
              type="button"
              onClick={() => this.setState({ hasError: false, error: null })}
              className="mt-2 text-xs text-muted-foreground/60 hover:text-muted-foreground underline"
            >
              Try again
            </button>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}
