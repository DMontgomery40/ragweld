// Plain-function toast so non-hook code paths (and window.alert call sites
// being replaced) can surface transient feedback without a native dialog.
// useUIHelpers().showToast delegates here so there is exactly one behavior.

export type ToastType = 'success' | 'error' | 'info';

export function showToast(message: string, type: ToastType = 'info'): void {
  const toast = document.createElement('div');
  toast.className = `toast toast-${type}`;
  toast.textContent = message;
  toast.style.cssText = `
    position: fixed;
    bottom: 20px;
    right: 20px;
    padding: 12px 24px;
    border-radius: 6px;
    background: var(--card-bg);
    border: 1px solid var(--line);
    color: var(--fg);
    z-index: 9999;
    animation: fadeIn 0.2s ease-out;
  `;
  document.body.appendChild(toast);
  setTimeout(() => {
    toast.style.opacity = '0';
    setTimeout(() => toast.remove(), 200);
  }, 3000);
}
