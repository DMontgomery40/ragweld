// UI Helpers - Common UI utilities and interactions
// Migrated from /modules/ui-helpers.js
// Uses useUIStore for persisted state, provides DOM binding for legacy modules

import { useUIStore, UI_CONSTANTS } from '@/stores/useUIStore';

const $ = (sel: string): Element | null => document.querySelector(sel);
const $$ = (sel: string): Element[] => Array.from(document.querySelectorAll(sel));

// ---------------- Collapsible Sections ----------------
// Binds click handlers to collapsible headers, syncs with Zustand store
function bindCollapsibleSections(): void {
  const headers = $$('.collapsible-header');
  const store = useUIStore.getState();

  headers.forEach(header => {
    const targetId = header.getAttribute('data-target');
    if (!targetId) return;

    // Restore collapsed state from Zustand store
    const isCollapsed = store.isCollapsed(targetId);
    const content = document.getElementById(targetId);
    if (isCollapsed && content) {
      content.classList.add('collapsed');
      header.classList.add('collapsed');
    }

    header.addEventListener('click', (e: Event) => {
      // Don't collapse if clicking on help icon or tooltip bubble
      if ((e.target as Element).closest('.tooltip-wrap, .tooltip-bubble')) return;

      const content = document.getElementById(targetId);
      if (!content) return;

      // Toggle collapsed state via Zustand store
      const newState = useUIStore.getState().toggleCollapsed(targetId);

      if (newState) {
        content.classList.add('collapsed');
        header.classList.add('collapsed');
      } else {
        content.classList.remove('collapsed');
        header.classList.remove('collapsed');
      }
    });
  });

}

// ---------------- Resizable Sidepanel ----------------
// Binds mouse drag handler to resize-handle, syncs with Zustand store
function bindResizableSidepanel(): void {
  const store = useUIStore.getState();

  const tryBind = (): boolean => {
    const handle = $('.resize-handle') as HTMLElement | null;
    if (!handle) return false;

    // Prevent duplicate listeners if bind is called multiple times.
    if (handle.dataset.sidepanelResizeBound === '1') return true;
    handle.dataset.sidepanelResizeBound = '1';

    // Prevent page scrolling during touch resizing (iPad).
    handle.style.touchAction = 'none';

    // If a previous build left an inline override, clear it so CSS var drives layout.
    const layout = document.querySelector('.layout') as HTMLElement | null;
    if (layout?.style.gridTemplateColumns) {
      layout.style.gridTemplateColumns = '';
    }

    const clampWidth = (width: number): number => {
      const viewportMax = Math.floor(window.innerWidth * 0.6);
      const hardMax = Math.min(UI_CONSTANTS.MAX_SIDEPANEL_WIDTH, viewportMax);
      const rounded = Math.round(width);
      return Math.max(UI_CONSTANTS.MIN_SIDEPANEL_WIDTH, Math.min(hardMax, rounded));
    };

    const applyWidth = (width: number): number => {
      const clamped = clampWidth(width);
      document.documentElement.style.setProperty('--sidepanel-width', clamped + 'px');
      store.setSidepanelWidth(clamped);
      return clamped;
    };

    // Restore saved width from Zustand store (clamped to current viewport constraints)
    const savedWidth = store.sidepanelWidth;
    const initialWidth =
      Number.isFinite(savedWidth) && savedWidth > 0
        ? savedWidth
        : UI_CONSTANTS.DEFAULT_SIDEPANEL_WIDTH;
    applyWidth(initialWidth);

    let isDragging = false;
    let activePointerId: number | null = null;
    let overlay: HTMLDivElement | null = null;
    let rafId = 0;
    let lastClientX = 0;

    const mountOverlay = (): void => {
      if (overlay) return;
      overlay = document.createElement('div');
      overlay.setAttribute('data-testid', 'resize-overlay');
      overlay.style.position = 'fixed';
      overlay.style.left = '0';
      overlay.style.top = '0';
      overlay.style.right = '0';
      overlay.style.bottom = '0';
      overlay.style.cursor = 'col-resize';
      overlay.style.background = 'transparent';
      overlay.style.zIndex = '2147483647'; // above iframes
      overlay.style.touchAction = 'none';
      document.body.appendChild(overlay);

      // Fallback: if pointer capture fails, the overlay will receive pointer events.
      // Attach listeners here so resizing still works on pages where capture is unreliable.
      overlay.addEventListener('pointermove', onPointerMove, { passive: false });
      overlay.addEventListener('pointerup', onPointerUpOrCancel);
      overlay.addEventListener('pointercancel', onPointerUpOrCancel);
    };

    const unmountOverlay = (): void => {
      if (!overlay) return;
      overlay.removeEventListener('pointermove', onPointerMove);
      overlay.removeEventListener('pointerup', onPointerUpOrCancel);
      overlay.removeEventListener('pointercancel', onPointerUpOrCancel);
      overlay.remove();
      overlay = null;
    };

    const applyFromClientX = (clientX: number): void => {
      const layoutEl = document.querySelector('.layout') as HTMLElement | null;
      const rect = layoutEl?.getBoundingClientRect();
      const right = rect?.right ?? window.innerWidth;
      const nextWidth = right - clientX;
      applyWidth(nextWidth);
    };

    const scheduleApply = (clientX: number): void => {
      lastClientX = clientX;
      if (rafId) return;
      rafId = window.requestAnimationFrame(() => {
        rafId = 0;
        applyFromClientX(lastClientX);
      });
    };

    const endDrag = (): void => {
      if (!isDragging) return;
      isDragging = false;
      activePointerId = null;
      if (rafId) {
        window.cancelAnimationFrame(rafId);
        rafId = 0;
        // If the drag ended before the next animation frame, flush the last position
        // so the final width is applied deterministically (important for tests + UX).
        applyFromClientX(lastClientX);
      }
      handle.classList.remove('dragging');
      unmountOverlay();
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
    };

    const onPointerDown = (e: PointerEvent): void => {
      // Only left-button drags for mouse; allow touch/pen.
      if (e.pointerType === 'mouse' && e.button !== 0) return;

      isDragging = true;
      activePointerId = e.pointerId;
      handle.classList.add('dragging');
      document.body.style.cursor = 'col-resize';
      document.body.style.userSelect = 'none';
      try {
        handle.setPointerCapture(e.pointerId);
      } catch {}
      mountOverlay();

      scheduleApply(e.clientX);
      e.preventDefault();
    };

    const onPointerMove = (e: PointerEvent): void => {
      if (!isDragging) return;
      if (activePointerId !== null && e.pointerId !== activePointerId) return;
      scheduleApply(e.clientX);
      e.preventDefault();
    };

    const onPointerUpOrCancel = (e: PointerEvent): void => {
      if (activePointerId !== null && e.pointerId !== activePointerId) return;
      try {
        handle.releasePointerCapture(e.pointerId);
      } catch {}
      endDrag();
    };

    const onLostPointerCapture = (): void => {
      endDrag();
    };

    handle.addEventListener('pointerdown', onPointerDown, { passive: false });
    handle.addEventListener('pointermove', onPointerMove, { passive: false });
    handle.addEventListener('pointerup', onPointerUpOrCancel);
    handle.addEventListener('pointercancel', onPointerUpOrCancel);
    handle.addEventListener('lostpointercapture', onLostPointerCapture);

    return true;
  };

  // Note: binding is triggered again from App.tsx once the layout is mounted.
  // This avoids fragile polling loops while still handling the loading-shell race.
  tryBind();
}

// ---------------- Number Formatting ----------------
function getNum(id: string): number {
  const v = document.getElementById(id) as HTMLInputElement | null;
  if (!v) return 0;
  return parseInt((v.value || '').toString().replace(/,/g, '').replace(/\s/g, ''), 10) || 0;
}

function setNum(id: string, n: number): void {
  const el = document.getElementById(id) as HTMLInputElement | null;
  if (!el) return;
  el.value = (Number(n) || 0).toLocaleString('en-US');
}

function attachCommaFormatting(ids: string[]): void {
  ids.forEach(id => {
    const el = document.getElementById(id) as HTMLInputElement | null;
    if (!el) return;
    el.addEventListener('focus', () => {
      el.value = el.value.replace(/,/g, '');
    });
    el.addEventListener('blur', () => {
      const num = getNum(id);
      if (num >= 0) el.value = num.toLocaleString('en-US');
    });
  });
}

function wireDayConverters(): void {
  const recalc = () => {
    const rpd = getNum('cost-rpd');
    const inDay = getNum('cost-in-day');
    const outDay = getNum('cost-out-day');
    if (rpd > 0) {
      if (inDay > 0) setNum('cost-in', Math.floor(inDay / rpd));
      if (outDay > 0) setNum('cost-out', Math.floor(outDay / rpd));
    }
  };
  ['cost-in-day', 'cost-out-day', 'cost-rpd'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.addEventListener('input', recalc);
  });
  recalc();
}

// Export for TypeScript imports
export const UiHelpers = {
  bindCollapsibleSections,
  bindResizableSidepanel,
  getNum,
  setNum,
  attachCommaFormatting,
  wireDayConverters
};
