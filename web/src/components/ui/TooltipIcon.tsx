import React, { useCallback, useEffect, useId, useLayoutEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { useTooltips } from '@/hooks/useTooltips';

type TooltipIconProps = {
  name: string;
};

const TOOLTIP_GAP_PX = 8;
const VIEWPORT_MARGIN_PX = 8;
const TOOLTIP_MAX_WIDTH_PX = 460;

type TooltipPlacement = 'top' | 'bottom';

/**
 * TooltipIcon - Renders a help icon with tooltip bubble
 * 
 * Uses glossary-driven tooltips (data/glossary.json → /web/glossary.json) via useTooltips hook.
 * Renders proper DOM structure for tooltip display with hover/click behavior.
 */
export function TooltipIcon({ name }: TooltipIconProps) {
  const { getTooltip } = useTooltips();
  const [visible, setVisible] = useState(false);
  const [placement, setPlacement] = useState<TooltipPlacement>('bottom');
  const [position, setPosition] = useState({ top: -9999, left: -9999 });
  const wrapRef = useRef<HTMLSpanElement>(null);
  const bubbleRef = useRef<HTMLDivElement>(null);
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pinnedRef = useRef(false);
  const suppressFocusRef = useRef(false);
  const tooltipId = useId();

  // Get tooltip HTML content
  const content = getTooltip(name) || `<span class="tt-title">${name}</span><div>No tooltip available.</div>`;

  // Render tooltip content safely (no dangerouslySetInnerHTML)
  const renderNodes = (nodes: NodeListOf<ChildNode>): React.ReactNode[] => {
    const out: React.ReactNode[] = [];
    nodes.forEach((n, idx) => {
      if (n.nodeType === Node.TEXT_NODE) {
        out.push(n.textContent);
        return;
      }
      if (n.nodeType === Node.ELEMENT_NODE) {
        const el = n as HTMLElement;
        const children = renderNodes(el.childNodes as NodeListOf<ChildNode>);
        const key = `${el.tagName}-${idx}`;
        const tag = el.tagName.toLowerCase();
        const commonProps = { key, className: el.className || undefined };
        switch (tag) {
          case 'a': {
            const href = el.getAttribute('href') || '#';
            return out.push(
              <a {...commonProps} href={href} target="_blank" rel="noopener noreferrer">
                {children}
              </a>
            );
          }
          case 'div':
          case 'span':
            return out.push(React.createElement(tag, commonProps, children));
          case 'br':
            return out.push(<br key={key} />);
          default:
            return;
        }
      }
    });
    return out;
  };

  const renderContent = (): React.ReactNode => {
    if (typeof window === 'undefined' || typeof DOMParser === 'undefined') {
      console.warn('[TooltipIcon] DOMParser not available, returning raw content');
      return content;
    }
    try {
      const parser = new DOMParser();
      const doc = parser.parseFromString(content, 'text/html');
      const nodes = renderNodes(doc.body.childNodes as NodeListOf<ChildNode>);
      // If renderNodes returns empty array, something went wrong
      if (Array.isArray(nodes) && nodes.length === 0 && content.length > 0) {
        console.warn('[TooltipIcon] renderNodes returned empty for non-empty content:', name);
      }
      return nodes;
    } catch (e) {
      console.error('[TooltipIcon] Error parsing tooltip HTML:', e, 'for key:', name);
      return content;
    }
  };

  const clearHideTimeout = () => {
    if (timeoutRef.current) {
      clearTimeout(timeoutRef.current);
      timeoutRef.current = null;
    }
  };

  const updatePosition = useCallback(() => {
    const anchor = wrapRef.current;
    const bubble = bubbleRef.current;
    if (!anchor || !bubble) return;

    const anchorRect = anchor.getBoundingClientRect();
    const bubbleRect = bubble.getBoundingClientRect();
    const viewportWidth = window.innerWidth;
    const viewportHeight = window.innerHeight;

    const maxWidth = Math.min(TOOLTIP_MAX_WIDTH_PX, viewportWidth - VIEWPORT_MARGIN_PX * 2);
    const bubbleWidth = Math.min(bubbleRect.width || maxWidth, maxWidth);

    let left = anchorRect.left;
    if (left + bubbleWidth + VIEWPORT_MARGIN_PX > viewportWidth) {
      left = viewportWidth - bubbleWidth - VIEWPORT_MARGIN_PX;
    }
    left = Math.max(VIEWPORT_MARGIN_PX, left);

    const preferBelowTop = anchorRect.bottom + TOOLTIP_GAP_PX;
    const preferAboveTop = anchorRect.top - bubbleRect.height - TOOLTIP_GAP_PX;

    let nextTop = preferBelowTop;
    let nextPlacement: TooltipPlacement = 'bottom';

    const wouldOverflowBelow = preferBelowTop + bubbleRect.height + VIEWPORT_MARGIN_PX > viewportHeight;
    const canFitAbove = preferAboveTop >= VIEWPORT_MARGIN_PX;
    if (wouldOverflowBelow && canFitAbove) {
      nextTop = preferAboveTop;
      nextPlacement = 'top';
    } else {
      const maxTop = Math.max(VIEWPORT_MARGIN_PX, viewportHeight - bubbleRect.height - VIEWPORT_MARGIN_PX);
      nextTop = Math.min(Math.max(preferBelowTop, VIEWPORT_MARGIN_PX), maxTop);
    }

    setPlacement(nextPlacement);
    setPosition({
      top: Math.round(nextTop),
      left: Math.round(left),
    });
  }, []);

  // Handle click outside to close.
  useEffect(() => {
    const handlePointerDown = (e: PointerEvent) => {
      const target = e.target as Node | null;
      if (!target) return;

      const clickedTrigger = !!wrapRef.current?.contains(target);
      const clickedBubble = !!bubbleRef.current?.contains(target);
      if (!clickedTrigger && !clickedBubble) {
        pinnedRef.current = false;
        setVisible(false);
      }
    };

    const handleEsc = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        pinnedRef.current = false;
        if (bubbleRef.current?.contains(document.activeElement)) {
          suppressFocusRef.current = true;
          wrapRef.current?.querySelector<HTMLElement>('.help-icon')?.focus();
        }
        setVisible(false);
      }
    };

    if (visible) {
      document.addEventListener('pointerdown', handlePointerDown, true);
      document.addEventListener('keydown', handleEsc);
    }
    return () => {
      document.removeEventListener('pointerdown', handlePointerDown, true);
      document.removeEventListener('keydown', handleEsc);
    };
  }, [visible]);

  useLayoutEffect(() => {
    if (!visible) return;

    updatePosition();
    const rafId = window.requestAnimationFrame(updatePosition);

    const handleReflow = () => updatePosition();
    window.addEventListener('resize', handleReflow);
    window.addEventListener('scroll', handleReflow, true);

    let resizeObserver: ResizeObserver | null = null;
    if (typeof ResizeObserver !== 'undefined') {
      resizeObserver = new ResizeObserver(handleReflow);
      if (wrapRef.current) resizeObserver.observe(wrapRef.current);
      if (bubbleRef.current) resizeObserver.observe(bubbleRef.current);
    }

    return () => {
      window.cancelAnimationFrame(rafId);
      window.removeEventListener('resize', handleReflow);
      window.removeEventListener('scroll', handleReflow, true);
      resizeObserver?.disconnect();
    };
  }, [visible, updatePosition]);

  useEffect(() => {
    return () => clearHideTimeout();
  }, []);

  const show = () => {
    clearHideTimeout();
    setVisible(true);
  };

  const hide = () => {
    clearHideTimeout();
    timeoutRef.current = setTimeout(() => {
      if (!pinnedRef.current && !bubbleRef.current?.contains(document.activeElement)
          && !wrapRef.current?.contains(document.activeElement)) setVisible(false);
    }, 150);
  };

  const handleBlur = (e: React.FocusEvent) => {
    const next = e.relatedTarget as Node | null;
    if (next && (wrapRef.current?.contains(next) || bubbleRef.current?.contains(next))) return;
    pinnedRef.current = false;
    hide();
  };

  const toggle = (e: React.MouseEvent) => {
    // Help is often inside a setting label; opening it must not toggle that field.
    e.preventDefault();
    e.stopPropagation();
    clearHideTimeout();
    pinnedRef.current = !pinnedRef.current;
    setVisible(pinnedRef.current);
  };

  const tooltipBubble = visible && typeof document !== 'undefined'
    ? createPortal(
        <div
          ref={bubbleRef}
          id={tooltipId}
          className={`tooltip-bubble tooltip-visible tooltip-bubble--floating tooltip-bubble--${placement}`}
          onMouseEnter={show}
          onMouseLeave={hide}
          onFocusCapture={show}
          onBlurCapture={handleBlur}
          onKeyDown={e => {
            if (e.key === 'Tab' && e.shiftKey && e.target === bubbleRef.current?.querySelector('a')) {
              e.preventDefault();
              wrapRef.current?.querySelector<HTMLElement>('.help-icon')?.focus();
            }
          }}
          role="tooltip"
          aria-label={`Tooltip for ${name}`}
          style={{
            position: 'fixed',
            top: `${position.top}px`,
            left: `${position.left}px`,
            maxWidth: `min(${TOOLTIP_MAX_WIDTH_PX}px, calc(100vw - ${VIEWPORT_MARGIN_PX * 2}px))`,
            minWidth: `min(260px, calc(100vw - ${VIEWPORT_MARGIN_PX * 2}px))`,
            boxSizing: 'border-box',
            zIndex: 30000,
          }}
        >
          {renderContent()}
        </div>,
        document.body,
      )
    : null;

  return (
    <>
      <span
        ref={wrapRef}
        className="tooltip-wrap"
        style={{ position: 'relative', display: 'inline-block' }}
      >
        <span
          className="help-icon"
          tabIndex={0}
          role="button"
          aria-label={`Help: ${name}`}
          aria-expanded={visible}
          aria-controls={visible ? tooltipId : undefined}
          onClick={toggle}
          onMouseEnter={show}
          onMouseLeave={hide}
          onFocus={() => {
            if (suppressFocusRef.current) suppressFocusRef.current = false;
            else show();
          }}
          onBlur={handleBlur}
          onKeyDown={e => {
            if (e.key === 'Enter' || e.key === ' ') {
              e.preventDefault();
              e.stopPropagation();
              pinnedRef.current = true;
              show();
            } else if (e.key === 'Tab' && !e.shiftKey && visible) {
              const firstLink = bubbleRef.current?.querySelector<HTMLAnchorElement>('a');
              if (firstLink) {
                e.preventDefault();
                firstLink.focus();
              }
            }
          }}
          style={{ cursor: 'help' }}
        >
          ?
        </span>
      </span>
      {tooltipBubble}
    </>
  );
}
