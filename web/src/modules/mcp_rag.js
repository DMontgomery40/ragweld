// MCP RAG search debug binder. Exported via window.McpRag
;(function(){
  'use strict';
  const api = (window.CoreUtils && window.CoreUtils.api) ? window.CoreUtils.api : (p=>p);
  const state = (window.CoreUtils && window.CoreUtils.state) ? window.CoreUtils.state : {};

  /**
   * ---agentspec
   * what: |
   *   Binds click handler to MCP RAG button. Reads query, repo, topk, local from DOM; triggers async RAG pipeline.
   *
   * why: |
   *   Centralizes event binding to prevent duplicate listeners and ensure single entry point for RAG execution.
   *
   * guardrails:
   *   - DO NOT rebind if already bound (check dataset.bound flag)
   *   - NOTE: Assumes all DOM elements exist; add null checks before access
   *   - ASK USER: What happens on missing elements? Should fail gracefully or throw?
   * ---/agentspec
   */
  function bind(){
    const btn = document.getElementById('btn-mcp-rag-run');
    if (!btn || btn.dataset.bound) return;
    btn.dataset.bound = '1';
    btn.addEventListener('click', async () => {
      const qEl = document.getElementById('mcp-rag-q');
      const repoEl = document.getElementById('mcp-rag-repo');
      const topkEl = document.getElementById('mcp-rag-topk');
      const localEl = document.getElementById('mcp-rag-local');
      const out = document.getElementById('mcp-rag-results');
      if (!qEl || !out) return;
      const q = (qEl.value || '').trim();
      if (!q) { out.textContent = 'Please enter a question.'; return; }
      const repo = (repoEl && repoEl.value) ? repoEl.value.trim() : ((state.config && state.config.env && state.config.env.REPO) ? state.config.env.REPO : 'auto');
      const top_k = parseInt((topkEl && topkEl.value) ? String(topkEl.value) : '10', 10) || 10;
      const force_local = (localEl && String(localEl.value) === 'true') ? 'true' : 'false';
      try {
        out.textContent = 'Running rag_search...';
        const qs = new URLSearchParams({ q, top_k: String(top_k), force_local });
        if (repo) qs.set('repo', repo);
        const r = await fetch(api(`/api/mcp/rag_search?${qs.toString()}`));
        const d = await r.json();
        if (d && Array.isArray(d.results)) {
          const lines = d.results.map(x => `${x.file_path}:${x.start_line}-${x.end_line}  score=${Number(x.rerank_score||0).toFixed(3)}`);
          out.textContent = lines.join('\n');
        } else if (d && d.error) {
          out.textContent = `Error: ${d.error}`;
        } else {
          out.textContent = JSON.stringify(d, null, 2);
        }
      } catch (e) {
        out.textContent = `Request failed: ${e.message}`;
      }
    });
    // Pre-fill repo field from env on load
    try {
      const repoEl = document.getElementById('mcp-rag-repo');
      if (repoEl && state.config && state.config.env && state.config.env.REPO) {
        repoEl.value = state.config.env.REPO;
      }
    } catch {}
  }

  window.McpRag = { bind };
})();

