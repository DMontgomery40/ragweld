// Remembers the height an operator drags a resizable panel to. The resizing itself is CSS
// (`resize: vertical` on `.settings-section, [data-resizable]` in styles/main.css); this only
// saves the inline height the browser writes, per viewer, and puts it back when the panel
// mounts again. UI state in localStorage, never config. A panel opts in with a key,
// `data-resizable="<key>"`, plus `ref={rememberPanelHeight}`; it is remembered separately for
// the main pane and the Dock. Nothing global runs: each keyed panel watches only its own
// style attribute, and the height is written once, after the drag settles, never per frame.
// Pure helpers first: `node --test` loads this module without a DOM or path aliases.

const STORAGE_PREFIX = 'ragweld-panel-height:v1:';
/** A drag rewrites the inline height every frame; the height is stored once it rests this long. */
export const PANEL_HEIGHT_WRITE_DELAY_MS = 250;

export type PanelSurface = 'main' | 'dock';

export function panelHeightStorageKey(panelKey: string | null | undefined, surface: PanelSurface): string | null {
  const key = String(panelKey ?? '').trim();
  return key ? `${STORAGE_PREFIX}${surface}:${key}` : null;
}

/** A stored or inline CSS height ("412px" or "412") as whole px; anything else is no height. */
export function parsePanelHeight(raw: string | null | undefined): number | null {
  const match = /^\s*(\d+(?:\.\d+)?)(px)?\s*$/.exec(String(raw ?? ''));
  const px = match ? Math.round(Number(match[1])) : NaN;
  return Number.isFinite(px) && px > 0 ? px : null;
}

/**
 * Ref callback for a keyed resizable panel (React 19 runs the returned cleanup on unmount):
 * restores the remembered height before first paint, then stores the dragged height once the
 * drag has rested for PANEL_HEIGHT_WRITE_DELAY_MS (or at once on unmount or page hide).
 */
export function rememberPanelHeight(el: HTMLElement | null): (() => void) | undefined {
  if (!el) return undefined;
  const docked = el.closest('.dock-native') !== null || new URLSearchParams(window.location.search).get('dock') === '1';
  const key = panelHeightStorageKey(el.dataset.resizable, docked ? 'dock' : 'main');
  if (!key) return undefined;
  try {
    const px = parsePanelHeight(window.localStorage.getItem(key));
    if (px !== null) el.style.height = `${px}px`;
  } catch {
    // Blocked site data: the panel keeps its default size.
  }
  let timer: number | undefined;
  const write = () => {
    timer = undefined;
    const px = parsePanelHeight(el.style.height);
    try {
      if (px === null) window.localStorage.removeItem(key);
      else window.localStorage.setItem(key, String(px));
    } catch {
      // Private windows: the size still holds for this page view.
    }
  };
  // A pending height is written now when the panel unmounts or the page goes away (a reload
  // straight after a drag), never lost to the delay.
  const flush = () => {
    if (timer === undefined) return;
    window.clearTimeout(timer);
    write();
  };
  const observer = new MutationObserver(() => {
    window.clearTimeout(timer);
    timer = window.setTimeout(write, PANEL_HEIGHT_WRITE_DELAY_MS);
  });
  observer.observe(el, { attributes: true, attributeFilter: ['style'] });
  window.addEventListener('pagehide', flush);
  return () => {
    observer.disconnect();
    window.removeEventListener('pagehide', flush);
    flush();
  };
}
