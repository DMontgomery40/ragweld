import { useCallback } from 'react';

/**
 * useUIHelpers Hook
 * Provides UI utility functions for DOM manipulation, formatting, and interactions
 * Converts ui-helpers.js functionality to React
 */
/**
 * ---agentspec
 * what: |
 *   Provides memoized DOM query helper functions for React components.
 *   Exports two functions: $ (single element query) and $$ (multiple elements query).
 *   $ takes a CSS selector string and returns a single Element or null using document.querySelector.
 *   $$ takes a CSS selector string and returns an array of Elements using document.querySelectorAll.
 *   Both functions are generic and accept a type parameter to properly type the returned elements.
 *   Wrapped in useCallback to maintain referential equality across re-renders.
 *
 * why: |
 *   Centralizes DOM querying logic into reusable React hooks rather than scattering querySelector calls throughout components.
 *   useCallback memoization prevents unnecessary function recreation on every render, improving performance in components that pass these functions as dependencies.
 *   Generic type parameters allow consumers to get proper TypeScript typing for specific element types (e.g., HTMLInputElement, SVGElement).
 *
 * guardrails:
 *   - DO NOT use these helpers for frequent DOM queries in render loops; consider useRef or useEffect for performance-critical selections
 *   - ALWAYS prefer React refs (useRef) over DOM queries when managing component state or focus; these helpers are for read-only queries only
 *   - NOTE: These functions query the live DOM directly; they do not integrate with React's virtual DOM and may return stale references if DOM structure changes
 *   - ASK USER: Before using in event handlers or effects, confirm whether a ref-based approach would be more appropriate for your use case
 * ---/agentspec
 */
export function useUIHelpers() {
  // DOM query selectors
  const $ = useCallback(<T extends Element = Element>(selector: string): T | null => {
    return document.querySelector<T>(selector);
  }, []);

  const $$ = useCallback(<T extends Element = Element>(selector: string): T[] => {
    return Array.from(document.querySelectorAll<T>(selector));
  }, []);

  // Number formatting helpers
  const getNum = useCallback((id: string): number => {
    const el = document.getElementById(id) as HTMLInputElement | null;
    if (!el) return 0;
    const value = (el.value || '').toString().replace(/,/g, '').replace(/\s/g, '');
    return parseInt(value, 10) || 0;
  }, []);

  const setNum = useCallback((id: string, n: number): void => {
    const el = document.getElementById(id) as HTMLInputElement | null;
    if (!el) return;
    el.value = (Number(n) || 0).toLocaleString('en-US');
  }, []);

  const attachCommaFormatting = useCallback((ids: string[]): void => {
    ids.forEach(id => {
      const el = document.getElementById(id) as HTMLInputElement | null;
      if (!el) return;

      const onFocus = () => {
        el.value = el.value.replace(/,/g, '');
      };

      const onBlur = () => {
        const num = getNum(id);
        if (num >= 0) {
          el.value = num.toLocaleString('en-US');
        }
      };

      el.addEventListener('focus', onFocus);
      el.addEventListener('blur', onBlur);
    });
  }, [getNum]);

  // Collapsible sections management
  const bindCollapsibleSections = useCallback(() => {
    const headers = $$<HTMLElement>('.collapsible-header');

    headers.forEach(header => {
      const onClick = (e: Event) => {
        // Don't collapse if clicking on help icon or tooltip bubble
        if ((e.target as HTMLElement).closest('.tooltip-wrap, .tooltip-bubble')) return;

        const targetId = header.getAttribute('data-target');
        const content = targetId ? document.getElementById(targetId) : null;

        if (!content) return;

        // Toggle collapsed state
        const isCollapsed = content.classList.contains('collapsed');

        if (isCollapsed) {
          content.classList.remove('collapsed');
          header.classList.remove('collapsed');
        } else {
          content.classList.add('collapsed');
          header.classList.add('collapsed');
        }

        // Save state to localStorage
        const storageKey = `collapsed-${targetId}`;
        localStorage.setItem(storageKey, isCollapsed ? '0' : '1');
      };

      header.addEventListener('click', onClick);

      // Restore collapsed state from localStorage
      const targetId = header.getAttribute('data-target');
      if (targetId) {
        const storageKey = `collapsed-${targetId}`;
        const savedState = localStorage.getItem(storageKey);

        if (savedState === '1') {
          const content = document.getElementById(targetId);
          if (content) {
            content.classList.add('collapsed');
            header.classList.add('collapsed');
          }
        }
      }
    });
  }, [$$]);

  // Resizable sidepanel management
  const bindResizableSidepanel = useCallback(() => {
    const handle = $<HTMLElement>('.resize-handle');
    if (!handle) return;

    const MIN_WIDTH = 280;
    const MAX_WIDTH = 900;
    const DEFAULT_WIDTH = 360;
    const STORAGE_KEY = 'tribrid-sidepanel-width';

    // Restore saved width with viewport constraints
    const savedWidth = localStorage.getItem(STORAGE_KEY);
    if (savedWidth) {
      const width = parseInt(savedWidth, 10);
      const maxAllowed = Math.min(MAX_WIDTH, window.innerWidth * 0.45);
      if (width >= MIN_WIDTH && width <= maxAllowed) {
        document.documentElement.style.setProperty('--sidepanel-width', width + 'px');
      } else {
        document.documentElement.style.setProperty('--sidepanel-width', DEFAULT_WIDTH + 'px');
        localStorage.setItem(STORAGE_KEY, DEFAULT_WIDTH.toString());
      }
    }

    let isDragging = false;
    let startX = 0;
    let startWidth = 0;

    /**
     * ---agentspec
     * what: |
     *   Manages the side panel width by reading and setting a CSS custom property (--sidepanel-width) on the document root element.
     *   getCurrentWidth() retrieves the current width value by parsing the CSS variable, defaulting to 400px if the variable is missing or unparseable.
     *   setWidth(width) constrains the input width to a maximum of 60% of viewport width or MAX_WIDTH (whichever is smaller), then applies it to the CSS variable.
     *   Returns a number (getCurrentWidth) or void (setWidth). Handles edge cases: missing CSS variable, invalid parseInt results, viewport resizing, and hardcoded maximum constraints.
     *
     * why: |
     *   CSS custom properties enable dynamic, responsive width management without direct DOM manipulation of element styles.
     *   Constraining to 60% of viewport prevents the panel from consuming excessive screen real estate on narrow displays.
     *   Centralizing width logic in these functions ensures consistent behavior across all panel resize operations and makes the constraint rules testable and maintainable.
     *
     * guardrails:
     *   - DO NOT remove the fallback default of 400 in getCurrentWidth; it prevents NaN propagation if the CSS variable is undefined
     *   - ALWAYS validate that MAX_WIDTH is defined and positive before calling setWidth; undefined MAX_WIDTH will cause unexpected constraint behavior
     *   - NOTE: This implementation reads/writes synchronously to computed styles, which may trigger layout recalculation; consider debouncing setWidth calls during rapid resizing
     *   - ASK USER: Confirm whether setWidth should persist the width value to localStorage or session storage for state recovery across page reloads
     * ---/agentspec
     */
    const getCurrentWidth = (): number => {
      const rootStyle = getComputedStyle(document.documentElement);
      const widthStr = rootStyle.getPropertyValue('--sidepanel-width').trim();
      return parseInt(widthStr, 10) || 400;
    };

    /**
     * ---agentspec
     * what: |
     *   Sets the side panel width with responsive constraints and persistence.
     *   Takes a width number parameter (in pixels) and applies it to the DOM and localStorage.
     *   Clamps the requested width between MIN_WIDTH and a dynamic maximum (60% of viewport or MAX_WIDTH, whichever is smaller).
     *   Updates both a CSS custom property (--sidepanel-width) and directly modifies the .layout element's inline styles.
     *   Persists the clamped width to localStorage using STORAGE_KEY for recovery across sessions.
     *
     * why: |
     *   Responsive clamping ensures the side panel never exceeds viewport constraints or predefined limits, preventing layout overflow.
     *   Dual update strategy (CSS variable + direct style) provides fallback in case CSS variable propagation fails in certain browsers or contexts.
     *   localStorage persistence allows the user's preferred width to survive page reloads and navigation.
     *
     * guardrails:
     *   - DO NOT remove the direct .layout style update; it exists as a fallback for CSS variable propagation failures and should only be removed after confirming all target browsers support CSS custom properties reliably
     *   - ALWAYS clamp width between MIN_WIDTH and the dynamic hardMax; removing clamping will cause layout overflow and accessibility issues
     *   - NOTE: The 60% viewport multiplier is hardcoded; if responsive breakpoints change, this ratio may need adjustment to prevent side panel from dominating small screens
     *   - ASK USER: Before modifying MIN_WIDTH, MAX_WIDTH, or the 0.6 viewport ratio, confirm the intended UX behavior and test on mobile/tablet viewports
     * ---/agentspec
     */
    const setWidth = (width: number): void => {
      const viewportMax = Math.floor(window.innerWidth * 0.6);
      const hardMax = Math.min(MAX_WIDTH, viewportMax);
      const clampedWidth = Math.max(MIN_WIDTH, Math.min(hardMax, width));
      document.documentElement.style.setProperty('--sidepanel-width', clampedWidth + 'px');
      localStorage.setItem(STORAGE_KEY, clampedWidth.toString());
      
      // Also update .layout directly in case CSS variable doesn't propagate
      const layout = document.querySelector('.layout') as HTMLElement;
      if (layout && window.innerWidth > 768) { // Only on desktop
        layout.style.gridTemplateColumns = `1fr ${clampedWidth}px`;
      }
    };

    /**
     * ---agentspec
     * what: |
     *   Initializes drag state for a resizable panel handle on mouse down event.
     *   Takes a MouseEvent parameter (e) from a mousedown listener on a resize handle element.
     *   Sets isDragging flag to true, captures initial cursor position (e.clientX), stores current panel width via getCurrentWidth(), adds 'dragging' CSS class to handle, and applies visual feedback (col-resize cursor, disabled text selection) to document.body.
     *   Returns void; side effects include DOM mutations (classList, style properties) and event prevention.
     *   Edge case: If getCurrentWidth() throws or returns invalid value, subsequent drag calculations may fail silently.
     *
     * why: |
     *   Establishes the baseline state needed for drag-to-resize interactions by capturing the starting point and locking UI feedback.
     *   Prevents text selection and provides visual affordance (cursor change) to signal to users that a resize operation is active.
     *   Centralizes initialization logic so the mousemove and mouseup handlers can reference consistent startX and startWidth values.
     *
     * guardrails:
     *   - DO NOT remove e.preventDefault() because it prevents unwanted text selection and browser default drag behaviors during resize
     *   - ALWAYS call getCurrentWidth() synchronously here to capture the width at drag start; calling it later during mousemove may read stale or intermediate values
     *   - NOTE: isDragging, startX, and startWidth are module-scoped variables; ensure they are properly reset in the mouseup handler to avoid state leaks
     *   - ASK USER: Confirm whether getCurrentWidth() can fail or return null/undefined, and whether error handling should be added before storing startWidth
     * ---/agentspec
     */
    const onMouseDown = (e: MouseEvent) => {
      isDragging = true;
      startX = e.clientX;
      startWidth = getCurrentWidth();
      handle.classList.add('dragging');
      document.body.style.cursor = 'col-resize';
      document.body.style.userSelect = 'none';
      e.preventDefault();
    };

    /**
     * ---agentspec
     * what: |
     *   Handles mouse movement during a drag operation to resize a UI element horizontally.
     *   Takes a MouseEvent parameter (e) containing clientX position data.
     *   Updates component width state by calculating the delta between current and starting mouse positions.
     *   Returns undefined; operates via side effect (setWidth state update).
     *   Early returns if isDragging is false, preventing unnecessary calculations when not actively dragging.
     *   Assumes startX and startWidth are captured from a prior mouseDown event and available in closure scope.
     *
     * why: |
     *   Separates drag logic into discrete handlers (onMouseMove, onMouseUp) following standard DOM event patterns.
     *   Calculating delta (startX - e.clientX) allows smooth, continuous resizing as the user moves the mouse.
     *   Early guard clause (if (!isDragging) return) prevents state updates and calculations when drag is inactive, improving performance.
     *
     * guardrails:
     *   - DO NOT remove the isDragging check; without it, onMouseMove will fire on every mouse movement globally, causing performance degradation
     *   - ALWAYS ensure startX and startWidth are initialized before onMouseMove is attached to the mousemove listener
     *   - NOTE: This handler does not constrain newWidth to min/max bounds; add validation if width should have limits
     *   - ASK USER: Confirm whether negative or zero widths should be allowed, or if min/max constraints should be enforced in this handler
     * ---/agentspec
     */
    const onMouseMove = (e: MouseEvent) => {
      if (!isDragging) return;
      const deltaX = startX - e.clientX;
      const newWidth = startWidth + deltaX;
      setWidth(newWidth);
    };

    /**
     * ---agentspec
     * what: |
     *   Handles the mouse-up event to terminate a drag operation on a UI handle element.
     *   Takes no parameters; operates on closure variables (isDragging flag) and DOM references (handle element, document.body).
     *   Returns undefined; produces side effects: sets isDragging to false, removes 'dragging' CSS class from handle, resets cursor style to default, restores userSelect property on document.body.
     *   Edge case: If onMouseUp fires when isDragging is already false, the function returns early without side effects, preventing redundant DOM updates.
     *
     * why: |
     *   Complements onMouseDown to implement a complete drag lifecycle. Early return when isDragging is false prevents unnecessary DOM manipulation and class removal when no drag is active.
     *   This pattern ensures clean state transitions and prevents visual glitches from cursor/selection style mismatches.
     *
     * guardrails:
     *   - DO NOT remove the isDragging check; it prevents errors if onMouseUp fires outside an active drag context
     *   - ALWAYS restore document.body.style.cursor and userSelect to empty string (not null) to revert to stylesheet defaults
     *   - NOTE: This function assumes handle element exists and has the 'dragging' class applied during drag; will silently fail if handle is null or class was never added
     *   - ASK USER: Confirm whether onMouseUp should be attached to document (for global drag termination) or only to the handle element before modifying event listener attachment
     * ---/agentspec
     */
    const onMouseUp = () => {
      if (!isDragging) return;
      isDragging = false;
      handle.classList.remove('dragging');
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
    };

    handle.addEventListener('mousedown', onMouseDown);
    document.addEventListener('mousemove', onMouseMove);
    document.addEventListener('mouseup', onMouseUp);
  }, [$]);

  // Day conversion helpers
  const wireDayConverters = useCallback(() => {
    /**
     * ---agentspec
     * what: |
     *   Recalculates input and output costs by dividing daily totals by a requests-per-day (RPD) rate.
     *   Reads three numeric values from DOM elements: 'cost-rpd' (divisor), 'cost-in-day' (daily input cost), 'cost-out-day' (daily output cost).
     *   Writes computed per-request costs back to 'cost-in' and 'cost-out' DOM elements using Math.floor for integer results.
     *   Handles zero/negative RPD by skipping calculation; handles zero/negative daily costs by skipping their respective updates.
     *   No return value; side effect is DOM mutation via setNum().
     *
     * why: |
     *   Normalizes daily cost totals into per-request metrics for cost analysis and comparison.
     *   Uses Math.floor to ensure integer cost values, avoiding fractional cent/token representations.
     *   Conditional checks prevent division by zero and unnecessary DOM updates when inputs are invalid or zero.
     *
     * guardrails:
     *   - DO NOT remove the rpd > 0 guard; division by zero or negative rates produces invalid cost metrics
     *   - ALWAYS use Math.floor for cost calculations to maintain integer precision and avoid floating-point artifacts
     *   - NOTE: This function assumes getNum() and setNum() are defined globally and correctly map DOM element IDs to numeric values
     *   - NOTE: Zero or negative daily costs are silently skipped; no warning or error is raised to the user
     *   - ASK USER: Confirm whether negative RPD values should trigger an error/warning or continue to be silently ignored
     * ---/agentspec
     */
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
      if (el) {
        el.addEventListener('input', recalc);
      }
    });

    recalc();
  }, [getNum, setNum]);

  // Toast notification helper
  const showToast = useCallback((message: string, type: 'success' | 'error' | 'info' = 'info') => {
    // Create toast element
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
  }, []);

  return {
    $,
    $$,
    getNum,
    setNum,
    attachCommaFormatting,
    bindCollapsibleSections,
    bindResizableSidepanel,
    wireDayConverters,
    showToast
  };
}
