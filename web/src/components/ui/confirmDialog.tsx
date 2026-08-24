import { useEffect, useRef } from 'react';
import { createRoot } from 'react-dom/client';

// In-app replacement for window.confirm. Native dialogs block the renderer's
// main thread (freezing SSE streams and any browser automation driving the
// workbench), so operator confirmations render as a normal React overlay and
// resolve a promise instead.

export type ConfirmDialogOptions = {
  title: string;
  message: string;
  confirmLabel?: string;
  cancelLabel?: string;
  danger?: boolean;
};

function ConfirmDialogView({
  options,
  onResolve,
}: {
  options: ConfirmDialogOptions;
  onResolve: (accepted: boolean) => void;
}) {
  const confirmRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    // Focus the confirm button so a bare Enter activates it NATIVELY; never
    // intercept Enter globally — a keyboard user who tabs to Cancel must get
    // Cancel, not a document-level confirm.
    confirmRef.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault();
        onResolve(false);
      }
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [onResolve]);

  const accent = options.danger ? 'var(--error, #e5484d)' : 'var(--accent)';

  return (
    <div
      data-testid="confirm-dialog"
      role="alertdialog"
      aria-modal="true"
      aria-label={options.title}
      style={{
        position: 'fixed',
        inset: 0,
        background: 'rgba(0,0,0,0.6)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        zIndex: 10000,
      }}
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onResolve(false);
      }}
    >
      <div
        style={{
          background: 'var(--card-bg)',
          border: '1px solid var(--line)',
          borderRadius: 8,
          minWidth: 360,
          maxWidth: 560,
          maxHeight: '80vh',
          overflow: 'auto',
          padding: '20px 24px',
          color: 'var(--fg)',
          boxShadow: '0 12px 40px rgba(0,0,0,0.45)',
        }}
      >
        <h3 style={{ margin: '0 0 10px', fontSize: '1rem' }}>{options.title}</h3>
        <div
          data-testid="confirm-dialog-message"
          style={{ whiteSpace: 'pre-wrap', fontSize: '0.85rem', lineHeight: 1.5, marginBottom: 18 }}
        >
          {options.message}
        </div>
        <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
          <button
            data-testid="confirm-dialog-cancel"
            onClick={() => onResolve(false)}
            style={{
              padding: '8px 16px',
              borderRadius: 6,
              border: '1px solid var(--line)',
              background: 'transparent',
              color: 'var(--fg)',
              cursor: 'pointer',
            }}
          >
            {options.cancelLabel ?? 'Cancel'}
          </button>
          <button
            ref={confirmRef}
            data-testid="confirm-dialog-accept"
            onClick={() => onResolve(true)}
            style={{
              padding: '8px 16px',
              borderRadius: 6,
              border: `1px solid ${accent}`,
              background: accent,
              color: 'var(--accent-contrast, #fff)',
              cursor: 'pointer',
              fontWeight: 600,
            }}
          >
            {options.confirmLabel ?? 'Confirm'}
          </button>
        </div>
      </div>
    </div>
  );
}

// One dialog at a time: concurrent requests queue behind the open one so a
// double-triggered action can never present two stacked overlays that a
// single keypress could resolve together.
let dialogQueue: Promise<unknown> = Promise.resolve();

export function confirmDialog(options: ConfirmDialogOptions): Promise<boolean> {
  const request = dialogQueue.then(
    () =>
      new Promise<boolean>((resolve) => {
        const host = document.createElement('div');
        document.body.appendChild(host);
        const root = createRoot(host);
        let settled = false;
        const done = (accepted: boolean) => {
          if (settled) return;
          settled = true;
          // Defer unmount out of the dispatching event so React never
          // unmounts a root from inside its own event handler.
          setTimeout(() => {
            root.unmount();
            host.remove();
          }, 0);
          resolve(accepted);
        };
        root.render(<ConfirmDialogView options={options} onResolve={done} />);
      })
  );
  dialogQueue = request.catch(() => undefined);
  return request;
}
