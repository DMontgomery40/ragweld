// Global Search - Search functionality across GUI
// Handles text highlighting and live search with autocomplete
;(function() {
  'use strict';

  // Get shared utilities
  const $ = window.CoreUtils?.$ || ((s) => document.querySelector(s));
  const $$ = window.CoreUtils?.$$ || ((s) => Array.from(document.querySelectorAll(s)));

  // ---------------- Search Helpers ----------------

  /**
   * ---agentspec
   * what: |
   *   Clears all highlight spans (.hl) by replacing them with plain text nodes. Removes visual highlighting from DOM.
   *
   * why: |
   *   Direct DOM manipulation avoids re-rendering; textContent preserves text while stripping markup.
   *
   * guardrails:
   *   - DO NOT call on large DOMs without batching; forEach + replaceWith is O(n)
   *   - NOTE: highlightMatches() incomplete; guardrail assumes it re-applies highlights
   * ---/agentspec
   */
  function clearHighlights() {
    $$('.hl').forEach(m => {
      const t = document.createTextNode(m.textContent);
      m.replaceWith(t);
    });
  }

  /**
   * ---agentspec
   * what: |
   *   Highlights text matches in DOM. Takes root element and query string; wraps matches in <mark> tags via TreeWalker.
   *
   * why: |
   *   TreeWalker efficiently traverses text nodes while skipping script/style/iframe content.
   *
   * guardrails:
   *   - DO NOT highlight inside SCRIPT, STYLE, IFRAME; causes injection risk
   *   - NOTE: Regex escaping required; unescaped queries break matching
   *   - ASK USER: Store hits array for external use or discard?
   * ---/agentspec
   */
  function highlightMatches(root, q) {
    if (!q) return;
    const rx = new RegExp(q.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'ig');
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, null);
    const hits = [];
    while (walker.nextNode()) {
      const n = walker.currentNode;
      if (!n.nodeValue || !n.parentElement) continue;
      if (/SCRIPT|STYLE|IFRAME/.test(n.parentElement.tagName)) continue;
      const m = n.nodeValue.match(rx);
      if (!m) continue;
      const span = document.createElement('mark');
      span.className = 'hl';
      span.textContent = n.nodeValue;
      const html = n.nodeValue.replace(rx, s => `<mark class="hl">${s}</mark>`);
      const frag = document.createElement('span');
      frag.innerHTML = html;
      n.parentElement.replaceChild(frag, n);
      hits.push(frag.querySelector('mark.hl'));
    }
    return hits;
  }

  // ---------------- Basic Global Search ----------------

  /**
   * ---agentspec
   * what: |
   *   Binds global search box to highlight matching text in .content. Clears highlights on empty query; jumps to first match if flag set.
   *
   * why: |
   *   Centralizes search UI binding to prevent duplicate event handlers and ensure consistent highlight lifecycle.
   *
   * guardrails:
   *   - DO NOT search if box element missing; early return prevents errors
   *   - NOTE: highlightMatches() must return array-like; jump only fires if hits.length > 0
   * ---/agentspec
   */
  function bindGlobalSearch() {
    const box = $('#global-search');
    if (!box) return;

    /**
     * ---agentspec
     * what: |
     *   Clears highlights, searches .content for query string q, highlights matches, optionally scrolls to first hit.
     *
     * why: |
     *   Centralizes search + highlight + scroll logic to avoid duplication across UI.
     *
     * guardrails:
     *   - DO NOT highlight if q is empty; early return prevents DOM thrashing
     *   - NOTE: scrollIntoView only fires if jump=true AND hits exist
     * ---/agentspec
     */
    function run(q, jump = false) {
      clearHighlights();
      if (!q) return;
      const hits = highlightMatches($('.content'), q);
      if (jump && hits && hits.length) {
        hits[0].scrollIntoView({ behavior: 'smooth', block: 'center' });
      }
    }

    box.addEventListener('keydown', (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        box.focus();
        box.select();
      }
    });
    box.addEventListener('input', () => run(box.value.trim()));
    box.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') run(box.value.trim(), true);
    });
  }

  // ---------------- Live Search with Autocomplete ----------------

  /**
   * ---agentspec
   * what: |
   *   Binds live search UI to global search box. Indexes items, handles cursor navigation, populates results dropdown on keystroke.
   *
   * why: |
   *   Centralizes search interaction logic; decouples index building from DOM updates.
   *
   * guardrails:
   *   - DO NOT assume #global-search or #search-results exist; check before binding
   *   - NOTE: cursor=-1 means no selection; validate bounds before access
   *   - ASK USER: What triggers index rebuild? (keystroke, load, manual?)
   * ---/agentspec
   */
  function bindGlobalSearchLive() {
    const box = $('#global-search');
    if (!box) return;
    const pop = $('#search-results');
    let index = [];
    let items = [];
    let cursor = -1;

    /**
     * ---agentspec
     * what: |
     *   Builds searchable index of DOM settings sections. Scans .settings-section elements for h3 titles and .input-group labels/inputs. Returns cached array or populates on first call.
     *
     * why: |
     *   Lazy initialization with memoization avoids repeated DOM traversals.
     *
     * guardrails:
     *   - DO NOT call before DOM ready; will index empty tree
     *   - NOTE: Mutates global `index` array; not thread-safe
     *   - DO NOT rely on label text for form submission; use input name/id
     * ---/agentspec
     */
    function ensureIndex() {
      if (index.length) return index;
      const idx = [];
      $$('.settings-section').forEach(sec => {
        const title = (sec.querySelector('h3')?.textContent || '').toLowerCase();
        sec.querySelectorAll('.input-group').forEach(g => {
          const label = (g.querySelector('label')?.textContent || '').trim();
          const input = g.querySelector('input,select,textarea');
          if (!input) return;
          const name = input.name || input.id || '';
          const ph = input.getAttribute('placeholder') || '';
          const content = (title + ' ' + label + ' ' + name + ' ' + ph).toLowerCase();
          idx.push({
            label: label || name,
            title: title,
            name: name,
            placeholder: ph,
            el: input,
            content
          });
        });
      });
      index = idx;
      return idx;
    }

    /**
     * ---agentspec
     * what: |
     *   Maps legacy tab IDs to current Navigation tab IDs. Input: DOM element. Output: normalized tab section string ('start' if no tab found).
     *
     * why: |
     *   Maintains backward compatibility as tab structure evolved; centralizes ID mapping logic.
     *
     * guardrails:
     *   - DO NOT hardcode tab IDs in callers; use this function
     *   - NOTE: Returns 'start' as fallback; verify map completeness before deploy
     * ---/agentspec
     */
    function sectionGroupFor(el) {
      const tc = el.closest('.tab-content');
      if (!tc) return 'start';
      const id = tc.id.replace('tab-', '');

      // Map old tab IDs to new Navigation tab IDs
      const map = {
        // Old config tabs -> new tabs
        generation: 'rag-generation',
        embeddings: 'rag-embeddings',
        reranking: 'rag-reranking',
        retrieval: 'rag-retrieval',
        confidence: 'rag-retrieval',
        repos: 'rag-repos',
        indexing: 'rag-indexing',

        // Old devtools tabs -> new tabs
        infra: 'infrastructure',
        calculator: 'profiles',
        eval: 'evaluation',
        misc: 'experiments',

        // Dashboard/start
        dashboard: 'start',

        // Pass through new tab IDs unchanged
        'rag-generation': 'rag-generation',
        'rag-embeddings': 'rag-embeddings',
        'rag-reranking': 'rag-reranking',
        'rag-retrieval': 'rag-retrieval',
        'rag-repos': 'rag-repos',
        'rag-indexing': 'rag-indexing',
        'infrastructure': 'infrastructure',
        'profiles': 'profiles',
        'evaluation': 'evaluation',
        'experiments': 'experiments',
        'admin': 'admin',
        'start': 'start',
        'chat': 'chat'
      };

      return map[id] || id;
    }

    /**
     * ---agentspec
     * what: |
     *   Navigates to item's section tab, highlights element, scrolls into view. Calls global switchTab if available.
     *
     * why: |
     *   Centralizes search result navigation logic with visual feedback.
     *
     * guardrails:
     *   - NOTE: Depends on global window.switchTab; fails silently if undefined
     *   - DO NOT remove setTimeout cleanup; prevents persistent highlight state
     * ---/agentspec
     */
    function go(item) {
      const tab = sectionGroupFor(item.el);
      // Call global switchTab if available
      if (typeof window.switchTab === 'function') {
        window.switchTab(tab);
      }
      item.el.classList.add('search-hit');
      item.el.scrollIntoView({ behavior: 'smooth', block: 'center' });
      setTimeout(() => item.el.classList.remove('search-hit'), 1200);
      if (pop) pop.style.display = 'none';
    }

    /**
     * ---agentspec
     * what: |
     *   Highlights search query matches in text. Escapes regex special chars, returns HTML with <span class="search-highlight"> wrapped matches.
     *
     * why: |
     *   Regex escaping prevents injection; case-insensitive global matching ensures all occurrences highlighted.
     *
     * guardrails:
     *   - DO NOT skip regex escape; user input can break pattern
     *   - NOTE: Returns HTML string; caller must inject safely (innerHTML risk)
     * ---/agentspec
     */
    function highlightText(text, query) {
      if (!query) return text;
      const regex = new RegExp(`(${query.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')})`, 'gi');
      return text.replace(regex, '<span class="search-highlight">$1</span>');
    }

    /**
     * ---agentspec
     * what: |
     *   Renders autocomplete dropdown. Clears popup, hides if empty, displays max 15 items with index.
     *
     * why: |
     *   Limits DOM mutations and visible results for performance.
     *
     * guardrails:
     *   - DO NOT render beyond 15 items; truncate with slice(0, 15)
     *   - NOTE: Hides popup when items.length === 0
     * ---/agentspec
     */
    function render(query = '') {
      if (!pop) return;
      pop.innerHTML = '';
      if (!items.length) {
        pop.style.display = 'none';
        return;
      }

      items.slice(0, 15).forEach((r, i) => {
        const div = document.createElement('div');
        div.className = 'item' + (i === cursor ? ' active' : '');

        const labelSpan = document.createElement('span');
        labelSpan.className = 'item-label';
        labelSpan.innerHTML = highlightText(r.label || r.name, query);

        const contextSpan = document.createElement('span');
        contextSpan.className = 'item-context';
        const contextParts = [];
        if (r.title) contextParts.push(highlightText(r.title, query));
        if (r.name && r.name !== r.label) contextParts.push(highlightText(r.name, query));
        contextSpan.innerHTML = contextParts.join(' • ');

        div.appendChild(labelSpan);
        if (contextParts.length > 0) div.appendChild(contextSpan);
        div.addEventListener('click', () => go(r));
        pop.appendChild(div);
      });
      pop.style.display = 'block';
    }

    /**
     * ---agentspec
     * what: |
     *   Filters indexed items by lowercase query string. Returns matching items array; renders empty if query blank.
     *
     * why: |
     *   Client-side search with lazy index build avoids server calls for simple substring matching.
     *
     * guardrails:
     *   - DO NOT index on every search; ensureIndex() guards against rebuilds
     *   - NOTE: Case-insensitive substring only; no fuzzy/ranking
     *   - ASK USER: Add debounce if search called frequently
     * ---/agentspec
     */
    function search(q) {
      const s = q.trim().toLowerCase();
      if (!s) {
        items = [];
        render();
        return;
      }
      ensureIndex();
      items = index.filter(x => x.content.includes(s));
      cursor = 0;
      render(s);
    }

    document.addEventListener('click', (e) => {
      if (pop && !pop.contains(e.target) && e.target !== box) {
        pop.style.display = 'none';
      }
    });

    box.addEventListener('keydown', (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        box.focus();
        box.select();
      }
    });

    box.addEventListener('input', () => search(box.value));
    box.addEventListener('keydown', (e) => {
      if (!pop || pop.style.display !== 'block') return;
      if (e.key === 'ArrowDown') {
        e.preventDefault();
        cursor = Math.min(cursor + 1, items.length - 1);
        render();
      } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        cursor = Math.max(cursor - 1, 0);
        render();
      } else if (e.key === 'Enter') {
        e.preventDefault();
        if (items[cursor]) go(items[cursor]);
      }
    });
  }

  // Export public API
  window.Search = {
    clearHighlights,
    highlightMatches,
    bindGlobalSearch,
    bindGlobalSearchLive
  };

  console.log('[Search] Loaded');
})();
