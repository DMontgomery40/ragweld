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
      // Don't collapse if clicking on help icon
      if ((e.target as Element).closest('.tooltip-wrap')) return;

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

  // Theme selectors (topbar + misc) -> live apply + sync
  const selTop = $('#theme-mode') as HTMLSelectElement | null;
  const selMisc = $('#misc-theme-mode') as HTMLSelectElement | null;

  // Restore theme from store
  const currentTheme = store.themeMode;
  if (selTop) selTop.value = currentTheme;
  if (selMisc) selMisc.value = currentTheme;

  function onThemeChange(src: HTMLSelectElement): void {
    const v = src.value as 'auto' | 'dark' | 'light';
    if (selTop && selTop !== src) selTop.value = v;
    if (selMisc && selMisc !== src) selMisc.value = v;

    // Update Zustand store
    useUIStore.getState().setThemeMode(v);

    // Call legacy theme apply if available
    if (typeof (window as any).Theme?.applyTheme === 'function') {
      (window as any).Theme.applyTheme(v);
    }
  }

  if (selTop) selTop.addEventListener('change', () => onThemeChange(selTop));
  if (selMisc) selMisc.addEventListener('change', () => onThemeChange(selMisc));
}

// ---------------- Resizable Sidepanel ----------------
// Binds mouse drag handler to resize-handle, syncs with Zustand store
function bindResizableSidepanel(): void {
  const handle = $('.resize-handle') as HTMLElement | null;
  if (!handle) return;

  const store = useUIStore.getState();

  // Restore saved width from Zustand store
  const savedWidth = store.sidepanelWidth;
  const maxAllowed = Math.min(UI_CONSTANTS.MAX_SIDEPANEL_WIDTH, window.innerWidth * 0.45);
  if (savedWidth >= UI_CONSTANTS.MIN_SIDEPANEL_WIDTH && savedWidth <= maxAllowed) {
    document.documentElement.style.setProperty('--sidepanel-width', savedWidth + 'px');
  } else {
    document.documentElement.style.setProperty('--sidepanel-width', UI_CONSTANTS.DEFAULT_SIDEPANEL_WIDTH + 'px');
    store.setSidepanelWidth(UI_CONSTANTS.DEFAULT_SIDEPANEL_WIDTH);
  }

  // Export reset function for use in other modules
  (window as any).resetSidepanelWidth = function() {
    document.documentElement.style.setProperty('--sidepanel-width', UI_CONSTANTS.DEFAULT_SIDEPANEL_WIDTH + 'px');
    useUIStore.getState().setSidepanelWidth(UI_CONSTANTS.DEFAULT_SIDEPANEL_WIDTH);
    console.log('Sidepanel width reset to default');
  };

  let isDragging = false;
  let startX = 0;
  let startWidth = 0;

  function getCurrentWidth(): number {
    const rootStyle = getComputedStyle(document.documentElement);
    const widthStr = rootStyle.getPropertyValue('--sidepanel-width').trim();
    return parseInt(widthStr, 10) || UI_CONSTANTS.DEFAULT_SIDEPANEL_WIDTH;
  }

  function setWidth(width: number): void {
    const viewportMax = Math.floor(window.innerWidth * 0.6);
    const hardMax = Math.min(UI_CONSTANTS.MAX_SIDEPANEL_WIDTH, viewportMax);
    const clampedWidth = Math.max(UI_CONSTANTS.MIN_SIDEPANEL_WIDTH, Math.min(hardMax, width));
    document.documentElement.style.setProperty('--sidepanel-width', clampedWidth + 'px');
    useUIStore.getState().setSidepanelWidth(clampedWidth);
  }

  handle.addEventListener('mousedown', (e: MouseEvent) => {
    isDragging = true;
    startX = e.clientX;
    startWidth = getCurrentWidth();
    handle.classList.add('dragging');
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';
    e.preventDefault();
  });

  document.addEventListener('mousemove', (e: MouseEvent) => {
    if (!isDragging) return;
    const deltaX = startX - e.clientX;
    const newWidth = startWidth + deltaX;
    setWidth(newWidth);
  });

  document.addEventListener('mouseup', () => {
    if (!isDragging) return;
    isDragging = false;
    handle.classList.remove('dragging');
    document.body.style.cursor = '';
    document.body.style.userSelect = '';
  });
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

// Expose on window for legacy JS modules (app.js, etc.)
if (typeof window !== 'undefined') {
  (window as any).UiHelpers = UiHelpers;
  console.log('[UiHelpers] Loaded from TypeScript (Zustand-backed)');
}
