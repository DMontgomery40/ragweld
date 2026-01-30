import { useMemo } from 'react';
import { Button } from '@/components/ui/Button';

type Props = {
  title: string;
  context?: string;
  error?: unknown;
  retryLabel?: string;
  onRetry?: () => void;
  className?: string;
};

function extractMessage(error?: unknown) {
  if (!error) {
    return '';
  }
  if (typeof error === 'string') {
    return error;
  }
  if (error instanceof Error) {
    return error.message || error.toString();
  }
  try {
    return JSON.stringify(error);
  } catch {
    return String(error);
  }
}

function extractStack(error?: unknown) {
  if (error instanceof Error && error.stack) {
    return error.stack;
  }
  return '';
}

export function SubtabErrorFallback({
  title,
  context,
  error,
  retryLabel = 'Retry render',
  onRetry,
  className,
}: Props) {
  const message = useMemo(() => extractMessage(error), [error]);
  const stack = useMemo(() => extractStack(error), [error]);

  return (
    <div
      className={[
        'rounded-2xl border border-err/40 bg-err/5 p-5 text-sm text-fg shadow-[0_15px_50px_rgba(0,0,0,0.35)] backdrop-blur space-y-3',
        className,
      ]
        .filter(Boolean)
        .join(' ')}
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-base font-semibold text-err">{title}</p>
          {context ? <p className="mt-1 text-xs text-muted">{context}</p> : null}
        </div>
        {onRetry ? (
          <Button variant="secondary" size="sm" onClick={onRetry} aria-label="Retry rendering this section">
            {retryLabel}
          </Button>
        ) : null}
      </div>

      {message ? (
        <div className="rounded-xl border border-err/30 bg-bgElev2/70 p-3 font-mono text-[12px] text-err/90">
          {message}
        </div>
      ) : null}

      {stack ? (
        <details className="rounded-xl border border-line/30 bg-bgElev1/70 p-3 font-mono text-[11px] text-muted">
          <summary className="cursor-pointer text-[12px] font-semibold text-fg">Stack trace</summary>
          <pre className="mt-2 whitespace-pre-wrap">{stack}</pre>
        </details>
      ) : null}

      <p className="text-xs text-muted">
        Check the browser console for additional diagnostics. If this keeps happening, capture the stack trace above and
        file it with the failing tab name.
      </p>
    </div>
  );
}


