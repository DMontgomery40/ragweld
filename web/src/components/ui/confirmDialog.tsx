import { useEffect, useRef, useState } from 'react';
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
  /**
   * Gate an IRREVERSIBLE action behind a deliberate typed step. When set, the
   * dialog renders a text input and keeps the confirm button disabled until the
   * operator types `expected` verbatim (trimmed). Enter cannot activate a
   * disabled button, so a stray keypress right after the dialog opens does
   * nothing (D-01: the delete-index dialog used to autofocus the destructive
   * button, so one Enter destroyed the index). A single dialog carries the
   * input because `confirmDialog` cancels any dialog already open, so a second
   * chained "type the name" dialog would resolve the first as declined.
   */
  requireTyped?: {
    /** The exact string the operator must type, e.g. the corpus id. */
    expected: string;
    /** Label above the input. Defaults to "Type to confirm". */
    label?: string;
    placeholder?: string;
  };
};

function ConfirmDialogView({
  options,
  onResolve,
}: {
  options: ConfirmDialogOptions;
  onResolve: (accepted: boolean) => void;
}) {
  const confirmRef = useRef<HTMLButtonElement>(null);
  const cancelRef = useRef<HTMLButtonElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const [typed, setTyped] = useState('');

  const expected = options.requireTyped?.expected ?? '';
  const typedMatches = !options.requireTyped || typed.trim() === expected.trim();

  useEffect(() => {
    // Where focus lands governs what a bare Enter does the instant the dialog
    // opens. A typed-confirmation dialog focuses the input (Enter can't fire the
    // disabled confirm anyway). A danger dialog with no typed gate focuses
    // Cancel, so an accidental Enter/Space declines rather than destroys
    // (D-01). A benign confirmation (an estimate, an acknowledgement) keeps the
    // old behaviour: focus the confirm button so Enter accepts NATIVELY. Enter
    // is never intercepted globally — a keyboard user who tabs to Cancel must
    // get Cancel, not a document-level confirm.
    if (options.requireTyped) {
      inputRef.current?.focus();
    } else if (options.danger) {
      cancelRef.current?.focus();
    } else {
      confirmRef.current?.focus();
    }
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault();
        onResolve(false);
      }
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [onResolve, options.danger, options.requireTyped]);

  const accent = options.danger ? 'var(--error, #e5484d)' : 'var(--accent)';
  const confirmDisabled = !typedMatches;

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
          style={{ whiteSpace: 'pre-wrap', fontSize: '14px', lineHeight: 1.5, marginBottom: options.requireTyped ? 14 : 18 }}
        >
          {options.message}
        </div>
        {options.requireTyped ? (
          <label
            style={{ display: 'block', fontSize: '0.8rem', color: 'var(--fg)', marginBottom: 18 }}
          >
            <span style={{ display: 'block', marginBottom: 6 }}>
              {options.requireTyped.label ?? `Type ${expected} to confirm`}
            </span>
            <input
              ref={inputRef}
              data-testid="confirm-dialog-typed-input"
              type="text"
              value={typed}
              placeholder={options.requireTyped.placeholder}
              autoComplete="off"
              spellCheck={false}
              onChange={(e) => setTyped(e.target.value)}
              onKeyDown={(e) => {
                // Enter submits only once the text matches; otherwise it does nothing.
                if (e.key === 'Enter' && typedMatches) {
                  e.preventDefault();
                  onResolve(true);
                }
              }}
              style={{
                width: '100%',
                padding: '8px 10px',
                borderRadius: 6,
                border: `1px solid ${typed.length > 0 && !typedMatches ? 'var(--error, #e5484d)' : 'var(--line)'}`,
                background: 'var(--input-bg, var(--card-bg))',
                color: 'var(--fg)',
                fontSize: '0.85rem',
                boxSizing: 'border-box',
              }}
            />
          </label>
        ) : null}
        <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
          <button
            ref={cancelRef}
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
            disabled={confirmDisabled}
            aria-disabled={confirmDisabled}
            onClick={() => {
              if (confirmDisabled) return;
              onResolve(true);
            }}
            style={{
              padding: '8px 16px',
              borderRadius: 6,
              border: `1px solid ${confirmDisabled ? 'var(--line)' : accent}`,
              background: confirmDisabled ? 'var(--btn-disabled-bg, #3a3a3a)' : accent,
              color: confirmDisabled ? 'var(--fg-muted, #9aa0a6)' : 'var(--accent-contrast, #fff)',
              cursor: confirmDisabled ? 'not-allowed' : 'pointer',
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
