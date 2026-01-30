// Keywords - Discriminative keywords management
// Handles loading and generating keywords catalog
;(function() {
  'use strict';

  // Get shared utilities
  const api = window.CoreUtils?.api || ((p) => `/api${p}`);
  const $ = window.CoreUtils?.$ || ((s) => document.querySelector(s));
  const $$ = window.CoreUtils?.$$ || ((s) => Array.from(document.querySelectorAll(s)));
  const state = window.CoreUtils?.state || {};

  // Load keywords catalog
  async function loadKeywords() {
    try {
      const r = await fetch(api('/api/keywords'));
      const d = await r.json();
      state.keywordsCatalog = d;

      const list = $('#keywords-list');
      if (list) {
        list.innerHTML = '';
        (d.keywords || []).forEach(k => {
          const opt = document.createElement('option');
          opt.value = k;
          list.appendChild(opt);
        });
      }

      const kc = $('#keywords-count');
      if (kc) kc.textContent = String((d.keywords || []).length);

      // Repaint per-repo managers if present
      ($$('#repos-section > div') || []).forEach(div => {
        const srcSel = div.querySelector('[id^="kw-src-"]');
        const filter = div.querySelector('[id^="kw-filter-"]');
        const allSel = div.querySelector('[id^="kw-all-"]');
        const fld = div.querySelector('[name^="repo_keywords_"]');

        if (srcSel && filter && allSel && fld) {
          const cat = (srcSel.value || 'all');
          const catMap = d;
          let base = cat === 'all' ? (d.keywords || []) : (d[cat] || []);
          const f = (filter.value || '').toLowerCase();
          const inRepo = new Set((fld.value || '').split(',').map(s => s.trim()).filter(Boolean));

          allSel.innerHTML = '';
          base
            .filter(k => !inRepo.has(k) && (!f || k.toLowerCase().includes(f)))
            .slice(0, 500)
            .forEach(k => {
              const o = document.createElement('option');
              o.value = k;
              o.textContent = k;
              allSel.appendChild(o);
            });
        }
      });
    } catch (e) {
      console.warn('[Keywords] Load failed:', e);
    }
  }

  // Initialization function called by cards.js when rag-data-quality view mounts
  // Does NOT register view - cards.js handles that
  window.initKeywords = function() {
    console.log('[keywords.js] Initializing keywords for rag-data-quality view');
    loadKeywords();
  };

  // Export public API
  window.Keywords = {
    loadKeywords
  };

  console.log('[keywords.js] Module loaded (coordination with cards.js for rag-data-quality view)');
})();
