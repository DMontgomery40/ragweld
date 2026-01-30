import React from 'react';

type FallbackRender = (args: { error: any; context?: string; reset: () => void }) => React.ReactNode;

type Props = {
  children: React.ReactNode;
  fallback?: React.ReactNode | FallbackRender;
  context?: string;
  onError?: (error: any, info: React.ErrorInfo) => void;
  onReset?: () => void;
  resetKeys?: Array<unknown>;
};

type State = { hasError: boolean; error?: any };

export class ErrorBoundary extends React.Component<Props, State> {
  state: State = { hasError: false, error: undefined };

  static getDerivedStateFromError(error: any) {
    return { hasError: true, error } as State;
  }

  componentDidCatch(error: any, info: React.ErrorInfo) {
    const contextLabel = this.props.context ? ` (${this.props.context})` : '';
    // eslint-disable-next-line no-console
    console.error(`[ErrorBoundary] Caught error${contextLabel}:`, error);
    this.props.onError?.(error, info);
  }

  componentDidUpdate(prevProps: Props) {
    if (!this.state.hasError) {
      return;
    }

    if (!areResetKeysEqual(prevProps.resetKeys, this.props.resetKeys)) {
      this.resetErrorBoundary();
    }
  }

  private resetErrorBoundary = () => {
    this.setState({ hasError: false, error: undefined });
    this.props.onReset?.();
  };

  render() {
    if (this.state.hasError) {
      if (typeof this.props.fallback === 'function') {
        return (this.props.fallback as FallbackRender)({
          error: this.state.error,
          context: this.props.context,
          reset: this.resetErrorBoundary,
        }) as React.ReactElement;
      }

      return (
        this.props.fallback ?? (
          <div style={{ padding: '16px', border: '1px solid var(--err)', background: 'var(--bg-elev1)', color: 'var(--fg)' }}>
            <div style={{ fontWeight: 700, marginBottom: '8px' }}>Subtab failed to render</div>
            <div style={{ fontSize: '12px', opacity: 0.8 }}>An error occurred inside this panel. Please check console for details.</div>
          </div>
        )
      );
    }

    return this.props.children as React.ReactElement;
  }
}

function areResetKeysEqual(a?: Array<unknown>, b?: Array<unknown>) {
  if (a === b) {
    return true;
  }
  if (!a || !b || a.length !== b.length) {
    return false;
  }
  for (let i = 0; i < a.length; i += 1) {
    if (!Object.is(a[i], b[i])) {
      return false;
    }
  }
  return true;
}

