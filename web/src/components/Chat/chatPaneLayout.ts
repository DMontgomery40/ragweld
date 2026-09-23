// Per-viewer Chat workbench layout (GUI-050): whether the conversation is expanded to the whole
// pane, and the height the operator dragged it to. UI-only state, kept in localStorage per
// surface (main pane vs Dock) so expanding the docked chat never rearranges the main pane.
// Pure module: no React, no path aliases, so `node --test` can load it directly.

export type ChatPaneSurface = 'main' | 'dock';

export type ChatPaneLayout = {
  expanded: boolean;
  /** Operator-chosen workbench height in CSS px; null fills the pane. */
  height: number | null;
};

/**
 * Below this the message list shrinks to a strip and citation/feedback controls collide with
 * the status bar (the reason the old fixed clamp started at 560px). The pane scrolls instead.
 */
export const CHAT_WORKBENCH_MIN_PX = 560;
export const CHAT_WORKBENCH_KEY_STEP_PX = 24;
export const CHAT_WORKBENCH_PAGE_STEP_PX = 120;

const STORAGE_PREFIX = 'ragweld-chat-layout:v1:';

export const DEFAULT_CHAT_PANE_LAYOUT: ChatPaneLayout = { expanded: false, height: null };

type LayoutStorage = Pick<Storage, 'getItem' | 'setItem'>;

export function chatPaneLayoutKey(surface: ChatPaneSurface): string {
  return `${STORAGE_PREFIX}${surface}`;
}

export function readChatPaneLayout(storage: LayoutStorage | null | undefined, surface: ChatPaneSurface): ChatPaneLayout {
  try {
    const raw = storage?.getItem(chatPaneLayoutKey(surface));
    if (!raw) return DEFAULT_CHAT_PANE_LAYOUT;
    const parsed: unknown = JSON.parse(raw);
    if (!parsed || typeof parsed !== 'object') return DEFAULT_CHAT_PANE_LAYOUT;
    const record = parsed as Record<string, unknown>;
    const height = record.height;
    return {
      expanded: record.expanded === true,
      height:
        typeof height === 'number' && Number.isFinite(height) && height >= CHAT_WORKBENCH_MIN_PX
          ? Math.round(height)
          : null,
    };
  } catch {
    return DEFAULT_CHAT_PANE_LAYOUT;
  }
}

export function writeChatPaneLayout(
  storage: LayoutStorage | null | undefined,
  surface: ChatPaneSurface,
  layout: ChatPaneLayout,
): void {
  try {
    storage?.setItem(chatPaneLayoutKey(surface), JSON.stringify(layout));
  } catch {
    // Private windows and blocked site data: the layout still works for this page view.
  }
}

/** The tallest the workbench may be: the room left in the pane, never below the floor. */
export function chatWorkbenchMaxHeight(availablePx: number | null): number {
  if (availablePx === null || !Number.isFinite(availablePx)) return CHAT_WORKBENCH_MIN_PX;
  return Math.max(CHAT_WORKBENCH_MIN_PX, Math.floor(availablePx));
}

export function clampChatWorkbenchHeight(heightPx: number, availablePx: number | null): number {
  const max = chatWorkbenchMaxHeight(availablePx);
  return Math.min(max, Math.max(CHAT_WORKBENCH_MIN_PX, Math.round(heightPx)));
}

/**
 * A height the operator chose, clamped; reaching the pane's full height stores "fill" (null)
 * so the workbench keeps filling when the window later grows.
 */
export function normalizeChatWorkbenchHeight(heightPx: number, availablePx: number | null): number | null {
  const clamped = clampChatWorkbenchHeight(heightPx, availablePx);
  return clamped >= chatWorkbenchMaxHeight(availablePx) ? null : clamped;
}

/** Expanded or unsized, the workbench fills the pane; otherwise the dragged height, clamped. */
export function resolveChatWorkbenchHeight(layout: ChatPaneLayout, availablePx: number | null): number {
  const max = chatWorkbenchMaxHeight(availablePx);
  if (layout.expanded || layout.height === null) return max;
  return clampChatWorkbenchHeight(layout.height, availablePx);
}

/**
 * Keyboard contract of the bottom-edge separator: ArrowUp/ArrowDown move the edge one step,
 * PageUp/PageDown a larger step, Home goes to the floor, End fills the pane again (height null).
 * Returns undefined for keys the separator does not handle.
 */
export function chatWorkbenchHeightForKey(
  key: string,
  currentPx: number,
  availablePx: number | null,
): { height: number | null } | undefined {
  switch (key) {
    case 'ArrowUp':
      return { height: normalizeChatWorkbenchHeight(currentPx - CHAT_WORKBENCH_KEY_STEP_PX, availablePx) };
    case 'ArrowDown':
      return { height: normalizeChatWorkbenchHeight(currentPx + CHAT_WORKBENCH_KEY_STEP_PX, availablePx) };
    case 'PageUp':
      return { height: normalizeChatWorkbenchHeight(currentPx - CHAT_WORKBENCH_PAGE_STEP_PX, availablePx) };
    case 'PageDown':
      return { height: normalizeChatWorkbenchHeight(currentPx + CHAT_WORKBENCH_PAGE_STEP_PX, availablePx) };
    case 'Home':
      return { height: normalizeChatWorkbenchHeight(CHAT_WORKBENCH_MIN_PX, availablePx) };
    case 'End':
      return { height: null };
    default:
      return undefined;
  }
}
