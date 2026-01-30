import React, { useState, useRef, useEffect } from 'react';
import { useTooltips } from '@/hooks/useTooltips';

interface TooltipIconProps {
  name: string;
}

/**
 * TooltipIcon - Renders a help icon with tooltip bubble
 * 
 * Uses the global tooltip system from tooltips.js via useTooltips hook.
 * Renders proper DOM structure for tooltip display with hover/click behavior.
 */
export function TooltipIcon({ name }: TooltipIconProps) {
  const { tooltips } = useTooltips();
  const [visible, setVisible] = useState(false);
  const wrapRef = useRef<HTMLSpanElement>(null);
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Get tooltip HTML content
  const content = tooltips[name] || `<span class="tt-title">${name}</span><div>No tooltip available.</div>`;

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

  // Handle click outside to close
  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) {
        setVisible(false);
      }
    }
    if (visible) {
      document.addEventListener('click', handleClickOutside);
    }
    return () => document.removeEventListener('click', handleClickOutside);
  }, [visible]);

  const show = () => {
    if (timeoutRef.current) clearTimeout(timeoutRef.current);
    setVisible(true);
  };

  const hide = () => {
    timeoutRef.current = setTimeout(() => setVisible(false), 150);
  };

  const toggle = (e: React.MouseEvent) => {
    e.stopPropagation();
    setVisible(v => !v);
  };

  return (
    <span 
      ref={wrapRef}
      className="tooltip-wrap" 
      style={{ position: 'relative', display: 'inline-block' }}
    >
      <span
        className="help-icon"
        tabIndex={0}
        aria-label={`Help: ${name}`}
        onClick={toggle}
        onMouseEnter={show}
        onMouseLeave={hide}
        onFocus={show}
        onBlur={hide}
        style={{ cursor: 'help' }}
      >
        ?
      </span>
      <div
        className={`tooltip-bubble ${visible ? 'tooltip-visible' : ''}`}
        onMouseEnter={show}
        onMouseLeave={hide}
        role="tooltip"
        aria-label={`Tooltip for ${name}`}
      >
        {renderContent()}
      </div>
    </span>
  );
}
