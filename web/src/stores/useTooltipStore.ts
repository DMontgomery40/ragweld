import { create } from 'zustand';

export type TooltipMap = Record<string, string>;

type GlossaryLink = { text: string; href: string };
type GlossaryBadge = { text: string; class: string };
export type GlossaryTerm = {
  term: string;
  key: string;
  definition: string; // HTML body (no wrapper div)
  category: string;
  related: string[];
  links?: GlossaryLink[];
  badges?: GlossaryBadge[];
};
type GlossaryJson = {
  version: string;
  generated_from?: string | null;
  terms: GlossaryTerm[];
};

let glossaryCache: GlossaryJson | null = null;
let glossaryInFlight: Promise<GlossaryJson> | null = null;

function escapeHtml(text: string): string {
  return String(text)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

function buildTooltipHtmlFromGlossaryTerm(term: GlossaryTerm): string {
  const title = escapeHtml(term.term || term.key);
  const body = term.definition || '';

  const badges = Array.isArray(term.badges) ? term.badges : [];
  const badgeHtml = badges
    .map((b) => {
      const cls = (b?.class || '').trim();
      const text = escapeHtml(b?.text || '');
      if (!text) return '';
      return `<span class="tt-badge ${escapeHtml(cls)}">${text}</span>`;
    })
    .filter(Boolean)
    .join(' ');
  const badgesBlock = badgeHtml ? `<div class="tt-badges">${badgeHtml}</div>` : '';

  const links = Array.isArray(term.links) ? term.links : [];
  const linkHtml = links
    .map((l) => {
      const href = String(l?.href || '').trim();
      if (!href) return '';
      const txt = escapeHtml(l?.text || href);
      return `<a href="${escapeHtml(href)}" target="_blank" rel="noopener">${txt}</a>`;
    })
    .filter(Boolean)
    .join(' ');
  const linksBlock = linkHtml ? `<div class="tt-links">${linkHtml}</div>` : '';

  return `<span class="tt-title">${title}</span>${badgesBlock}<div>${body}</div>${linksBlock}`;
}

async function fetchGlossaryJson(): Promise<GlossaryJson> {
  if (glossaryCache) return glossaryCache;
  if (glossaryInFlight) return glossaryInFlight;

  const baseUrl = import.meta.env.BASE_URL || '/';
  const glossaryUrl = `${baseUrl}glossary.json`.replace(/\/+/g, '/');

  glossaryInFlight = fetch(glossaryUrl, { cache: 'no-store' })
    .then(async (res) => {
      if (!res.ok) throw new Error(`Failed to load glossary.json: ${res.status}`);
      return (await res.json()) as GlossaryJson;
    })
    .then((data) => {
      glossaryCache = data;
      return data;
    })
    .finally(() => {
      glossaryInFlight = null;
    });

  return glossaryInFlight;
}

interface TooltipStore {
  tooltips: TooltipMap;
  /**
   * The glossary as it is written, not as it renders.
   *
   * The Glossary tab used to re-derive a term's category by keyword-matching its key
   * against a hardcoded six-bucket table, defaulting everything unmatched to "Advanced" --
   * so the file's own `category` field, which every term carries, was thrown away and one
   * chip held most of the glossary (M-133). Surfaces that need the structured record read
   * it here; `tooltips` stays the rendered-HTML map the hover bubbles use.
   */
  terms: GlossaryTerm[];
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
 * All tooltip definitions live in data/glossary.json (and are served via web/public/glossary.json).
 * This store loads from glossary.json on first use.
 */
export const useTooltipStore = create<TooltipStore>((set, get) => ({
  tooltips: {},
  terms: [],
  loading: false,
  initialized: false,

  initialize: () => {
    if (get().initialized || get().loading) return;

    set({ loading: true });
    void fetchGlossaryJson()
      .then((glossary) => {
        const tooltips: TooltipMap = {};
        const terms: GlossaryTerm[] = [];
        for (const t of glossary?.terms || []) {
          if (!t || typeof t.key !== 'string' || !t.key.trim()) continue;
          tooltips[t.key] = buildTooltipHtmlFromGlossaryTerm(t);
          terms.push(t);
        }
        set({ tooltips, terms, loading: false, initialized: true });
      })
      .catch((e) => {
        console.error('[useTooltipStore] Failed to load glossary tooltips:', e);
        set({ loading: false, initialized: true });
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
    return buildTooltipHTML(settingKey, 'No detailed tooltip available yet.');
  }
}));
