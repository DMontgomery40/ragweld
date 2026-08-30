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

// One dialog at a time, held in a slot rather than a promise chain.
//
// This used to be `dialogQueue = dialogQueue.then(() => new Promise(...))`: every request
// awaited the previous one, so a single dialog whose promise never settled -- a render that
// threw, a host removed by something other than its own handler -- wedged the chain and every
// later confirmation hung silently. No dialog, no error, and the caller awaiting it never
// returned. Serializing on a pending promise is what made an unsettled dialog contagious.
//
// The slot keeps the property that motivated the queue (a double-triggered action can never
// stack two overlays a single keypress resolves together) without the coupling: opening a
// dialog while one is already open CANCELS the open one first. Cancelling is the safe answer
// -- every caller treats false as "the operator declined" and does nothing.
let openDialog: { cancel: () => void } | null = null;

export function confirmDialog(options: ConfirmDialogOptions): Promise<boolean> {
  openDialog?.cancel();

  return new Promise<boolean>((resolve) => {
    const host = document.createElement('div');
    document.body.appendChild(host);
    const root = createRoot(host);
    let settled = false;
    const done = (accepted: boolean) => {
      if (settled) return;
      settled = true;
      if (openDialog === slot) openDialog = null;
      // Defer unmount out of the dispatching event so React never
      // unmounts a root from inside its own event handler.
      setTimeout(() => {
        root.unmount();
        host.remove();
      }, 0);
      resolve(accepted);
    };
    const slot = { cancel: () => done(false) };
    openDialog = slot;
    try {
      root.render(<ConfirmDialogView options={options} onResolve={done} />);
    } catch (error) {
      // A dialog that cannot render must answer its caller, not hang it.
      done(false);
      throw error;
    }
  });
}
