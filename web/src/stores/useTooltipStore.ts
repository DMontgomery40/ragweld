import { create } from 'zustand';
import { tooltipMap, type TooltipMap as RegistryTooltipMap } from '../tooltips/registry';

export type TooltipMap = RegistryTooltipMap;

interface TooltipStore {
  tooltips: TooltipMap;
  loading: boolean;
  initialized: boolean;

  // Actions
  initialize: () => void;
  getTooltip: (key: string) => string;
}

/**
 * Build tooltip HTML (matches L() function from tooltips.js)
 * Kept here as a utility for fallback generation
 */
/**
 * ---agentspec
 * what: |
 *   Constructs an HTML string for a tooltip component with label, body text, optional links, and optional badges.
 *   Takes four parameters: label (string, required), body (string, required), links (optional array of [text, href] tuples), badges (optional array of [label, value] tuples).
 *   Returns a single HTML string ready for DOM insertion.
 *   Currently only processes links into anchor tags; badges parameter is accepted but not rendered in the returned HTML.
 *   Applies security attributes (target="_blank" rel="noopener") to all generated links to prevent window.opener access.
 *
 * why: |
 *   Centralizes tooltip HTML generation to ensure consistent markup and security practices across the application.
 *   The rel="noopener" attribute prevents security vulnerabilities when opening external links in new tabs.
 *   Accepts optional links and badges to support flexible tooltip content without requiring conditional logic at call sites.
 *
 * guardrails:
 *   - DO NOT remove rel="noopener" from link generation; it prevents window.opener exploitation attacks
 *   - ALWAYS escape href and link text values to prevent XSS injection before rendering
 *   - NOTE: badges parameter is accepted but currently unused; returned HTML does not include badge markup
 *   - ASK USER: Confirm the intended behavior for badges before implementing badge rendering, as current implementation silently ignores this parameter
 *   - DO NOT use innerHTML to insert this output without sanitization; treat as potentially unsafe HTML
 * ---/agentspec
 */
function buildTooltipHTML(
  label: string,
  body: string,
  links?: Array<[string, string]>,
  badges?: Array<[string, string]>
): string {
  const linkHtml = (links || [])
    .map(([txt, href]) => `<a href="${href}" target="_blank" rel="noopener">${txt}</a>`)
    .join(' ');

  const badgeHtml = (badges || [])
    .map(([txt, cls]) => `<span class="tt-badge ${cls || ''}">${txt}</span>`)
    .join(' ');

  const badgesBlock = badgeHtml ? `<div class="tt-badges">${badgeHtml}</div>` : '';
  const linksBlock = links && links.length ? `<div class="tt-links">${linkHtml}</div>` : '';

  return `<span class="tt-title">${label}</span>${badgesBlock}<div>${body}</div>${linksBlock}`;
}

/**
 * Zustand store for tooltips - SINGLE SOURCE OF TRUTH
 *
 * All tooltip definitions live in web/src/modules/tooltips.js
 * This store loads from the centralized tooltip registry (Wave 1A)
 */
export const useTooltipStore = create<TooltipStore>((set, get) => ({
  tooltips: tooltipMap,
  loading: false,
  initialized: true,

  initialize: () => {
    // Wave 1A: store is pre-loaded from `web/src/tooltips/registry.ts`.
    // Keep initialize() for backward compatibility with existing hook call sites.
    if (get().initialized) return;
    set({
      tooltips: tooltipMap,
      loading: false,
      initialized: true
    });
  },

  getTooltip: (settingKey: string): string => {
    const { tooltips } = get();

    // Handle repo-specific dynamic keys
    let key = settingKey;
    if (settingKey.startsWith('repo_')) {
      const type = settingKey.split('_')[1];
      key = 'repo_' + type;
    }

    const tooltip = tooltips[key];
    if (tooltip) {
      return tooltip;
    }

    // Default fallback tooltip
    return buildTooltipHTML(
      settingKey,
      'No detailed tooltip available yet. See our docs for related settings.',
      [
        ['Main README', '/files/README.md'],
        ['Docs Index', '/docs/README.md']
      ]
    );
  }
}));
