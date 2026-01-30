;(function(){
  /**
   * ---agentspec
   * what: |
   *   Resolves API base URL from query param, window origin, or localhost fallback. Returns string.
   *
   * why: |
   *   Centralizes URL resolution for environment-agnostic API client initialization.
   *
   * guardrails:
   *   - DO NOT use hardcoded URLs; always call apiBase() at runtime
   *   - NOTE: Query param 'api' takes precedence; strips trailing slash
   *   - NOTE: Falls back to 127.0.0.1:8012 if URL parsing fails
   * ---/agentspec
   */
  function apiBase(){
    try{
      const u = new URL(window.location.href);
      const q = new URLSearchParams(u.search);
      const override = q.get('api');
      if (override) return override.replace(/\/$/, '');
      if (u.protocol.startsWith('http')) return u.origin;
      return 'http://127.0.0.1:8012';
    }catch{ return 'http://127.0.0.1:8012'; }
  }
  /**
   * ---agentspec
   * what: |
   *   Reads UI form state (mode, budget override, providers). Returns parsed config object with mode string, numeric budget, provider array.
   *
   * why: |
   *   Centralizes form input extraction to prevent scattered DOM queries and type coercion bugs.
   *
   * guardrails:
   *   - DO NOT assume budget input is valid number; parseFloat returns NaN on invalid input
   *   - NOTE: Provider array built from DOM elements; order depends on DOM traversal
   *   - ASK USER: Should invalid budget override silently default to 0 or reject form submission?
   * ---/agentspec
   */
  function api(path){ return apiBase() + path; }
  async function getConfig(){
    try{ const r = await fetch(api('/api/config')); return await r.json(); }catch{ return { env:{}, repos:[] }; }
  }
  /**
   * ---agentspec
   * what: |
   *   Reads UI form state (mode, budget, providers, regions, compliance, heuristics). Returns object with parsed values: mode string, budget number, prov array, regions array, compliance array, heur boolean.
   *
   * why: |
   *   Centralizes form extraction logic; handles CSV parsing and null/empty defaults consistently.
   *
   * guardrails:
   *   - DO NOT assume form elements exist; use optional chaining (?.) to prevent crashes
   *   - NOTE: csvToList trims whitespace and filters empty strings; regions/compliance may be empty arrays
   *   - ASK USER: Validate budget override range before use; no bounds checking here
   * ---/agentspec
   */
  function csvToList(s){ return (String(s||'').split(',').map(x=>x.trim()).filter(Boolean)); }
  /**
   * ---agentspec
   * what: |
   *   Reads UI form inputs (mode, budget, providers, regions, compliance, heuristics). Returns object with parsed values: mode string, budgetOverride number, prov array, regions array, compliance array, heur boolean.
   *
   * why: |
   *   Centralizes form state extraction to decouple UI from business logic.
   *
   * guardrails:
   *   - DO NOT assume form elements exist; use optional chaining (?.) to prevent crashes
   *   - NOTE: csvToList() must handle empty/null strings gracefully
   *   - DO NOT validate values here; validation belongs in caller
   * ---/agentspec
   */
  function readAdvanced(){
    const mode = document.getElementById('apv2-mode')?.value || 'balanced';
    const budgetOverride = parseFloat(document.getElementById('apv2-budget')?.value || '');
    const prov = Array.from(document.querySelectorAll('.apv2-prov'))
      .filter(cb => cb.checked).map(cb => cb.value);
    const regions = csvToList(document.getElementById('apv2-regions')?.value||'');
    const compliance = csvToList(document.getElementById('apv2-compliance')?.value||'');
    const heur = !!document.getElementById('apv2-heuristics')?.checked;
    const wl = {
      requests_per_day: parseInt(document.getElementById('apv2-rpd')?.value||'')||undefined,
      tokens_in_per_req: parseInt(document.getElementById('apv2-tin')?.value||'')||undefined,
      tokens_out_per_req: parseInt(document.getElementById('apv2-tout')?.value||'')||undefined,
      mq_rewrites: parseInt(document.getElementById('apv2-mq')?.value||'')||undefined,
      embed_tokens_per_req: parseInt(document.getElementById('apv2-embt')?.value||'')||undefined,
      rerank_tokens_per_req: parseInt(document.getElementById('apv2-rrt')?.value||'')||undefined,
    };
    const slo = {
      latency_target_ms: parseInt(document.getElementById('apv2-latency')?.value||'')||undefined,
      min_qps: parseFloat(document.getElementById('apv2-minqps')?.value||'')||undefined,
    };
    return { mode, budgetOverride, prov, regions, compliance, heur, workload: wl, slo };
  }
  /**
   * ---agentspec
   * what: |
   *   Displays loading spinner in profile placeholder. Sets innerHTML with animated border and status text. Inputs: DOM element IDs. Outputs: Visual loading state.
   *
   * why: |
   *   Provides immediate UX feedback during async profile selection with v2 engine.
   *
   * guardrails:
   *   - DO NOT inject untrusted content; innerHTML used only for controlled markup
   *   - NOTE: Requires CSS vars (--line, --accent) and @keyframes spin defined globally
   *   - NOTE: Assumes profile-placeholder element exists; no null check
   * ---/agentspec
   */
  function setPlaceholderLoading(){
    const placeholder = document.getElementById('profile-placeholder');
    const results = document.getElementById('profile-results-content');
    if (placeholder) {
      placeholder.style.display='flex';
      placeholder.innerHTML = `
        <div style="display:flex;flex-direction:column;align-items:center;justify-content:center;">
          <div style=\"width:48px;height:48px;border:3px solid var(--line);border-top-color:var(--accent);border-radius:50%;animation:spin 1s linear infinite;margin-bottom:16px;\"></div>
          <p id=\"apv2-phase\" style=\"font-size:14px;color:var(--fg-muted);\">Selecting profile with v2 engine...</p>
        </div>
        <style>@keyframes spin { to { transform: rotate(360deg); } }</style>`;
    }
    if (results) results.style.display='none';
  }
  /**
   * ---agentspec
   * what: |
   *   Wraps fetch() with configurable timeout. Returns Promise<Response>. Rejects on timeout or network error.
   *
   * why: |
   *   Prevents hanging requests; fetch() lacks native timeout support.
   *
   * guardrails:
   *   - DO NOT set timeout < 1000ms; network latency will cause false failures
   *   - NOTE: Clears timeout on both success and error paths
   *   - ASK USER: Confirm timeout value (default 12000ms) fits your SLA
   * ---/agentspec
   */
  function setPhase(msg){ try{ const el=document.getElementById('apv2-phase'); if (el) el.textContent=msg; }catch{}
  }
  /**
   * ---agentspec
   * what: |
   *   fetchWithTimeout wraps fetch() with configurable timeout (default 12s). Returns Promise<Response> or rejects on timeout/network error.
   *   renderResult updates DOM element #profile-results-content with scan results. Inputs: env, reason, scan, budget.
   *
   * why: |
   *   Timeout wrapper prevents hung requests; renderResult centralizes result display logic.
   *
   * guardrails:
   *   - DO NOT set timeout < 5000ms; network latency risk
   *   - NOTE: clearTimeout must fire on both success and error paths to prevent memory leaks
   *   - ASK USER: What should renderResult do if #profile-results-content missing?
   * ---/agentspec
   */
  function fetchWithTimeout(resource, opts){
    const { timeout=12000, ...rest } = (opts||{});
    return new Promise((resolve, reject)=>{
      const id = setTimeout(()=> reject(new Error('request timeout')), timeout);
      fetch(resource, rest).then((res)=>{ clearTimeout(id); resolve(res); }, (err)=>{ clearTimeout(id); reject(err); });
    });
  }
  /**
   * ---agentspec
   * what: |
   *   Renders profile scan results to DOM. Takes env, reason, scan, budget; outputs HTML to #profile-results-content. Binds tooltips if available.
   *
   * why: |
   *   Centralizes result rendering logic and defers tooltip binding to ProfileRenderer module for separation of concerns.
   *
   * guardrails:
   *   - DO NOT render if ProfileRenderer unavailable; silent fail acceptable
   *   - NOTE: Assumes #profile-results-content exists; no fallback if missing
   *   - ASK USER: What should happen if bindTooltips fails?
   * ---/agentspec
   */
  function renderResult(env, reason, scan, budget){
    const results = document.getElementById('profile-results-content');
    const placeholder = document.getElementById('profile-placeholder');
    if (window.ProfileRenderer && results) {
      try{
        const html = window.ProfileRenderer.renderProfileResults(env, scan, budget);
        results.innerHTML = html;
        if (window.ProfileRenderer.bindTooltips) window.ProfileRenderer.bindTooltips(results);
        // Append diagnostics accordion
        try{
          const details = document.createElement('details');
          details.style.marginTop = '12px';
          const sum = document.createElement('summary');
          sum.textContent = 'Diagnostics';
          sum.style.cursor = 'pointer';
          sum.style.color = 'var(--fg-muted)';
          const pre = document.createElement('pre');
          pre.style.color = 'var(--fg-muted)'; pre.style.whiteSpace = 'pre-wrap'; pre.style.fontSize = '12px'; pre.style.padding = '10px'; pre.style.border = '1px solid var(--line)'; pre.style.borderRadius = '6px'; pre.style.background = 'var(--card-bg)';
          pre.textContent = JSON.stringify({ objective: reason?.objective, budget: reason?.budget, weights: reason?.weights, candidates_total: reason?.candidates_total, policy_relaxed: reason?.policy_relaxed, diag: reason?.diag }, null, 2);
          details.appendChild(sum); details.appendChild(pre);
          results.appendChild(details);
        }catch{}
        if (placeholder) placeholder.style.display='none';
        results.style.display='block';
      }catch(err){
        results.innerHTML = '<pre style="color:var(--err);padding:20px;">'+(err?.message||String(err))+'</pre>';
        results.style.display='block';
        if (placeholder) placeholder.style.display='none';
      }
    }
  }
  async function ensureScan(){
    try {
      const out = document.getElementById('scan-out');
      if (out && out.dataset.scanData){ return JSON.parse(out.dataset.scanData); }
    }catch{}
    try{ const r = await fetch(api('/api/scan-hw'), { method:'POST' }); return await r.json(); }catch{ return null; }
  }

  async function run(){
    setPlaceholderLoading();
    setPhase('Loading configuration...');
    const cfg = await getConfig();
    const env = (cfg && cfg.env) || {};
    setPhase('Scanning hardware...');
    const scan = await ensureScan();
    const budget = parseFloat(document.getElementById('budget')?.value||'0');
    const adv = readAdvanced();

    // Fallbacks from cost panel when Advanced fields are blank
    /**
     * ---agentspec
     * what: |
     *   Parses numeric cost/workload inputs from DOM elements. Coerces to finite numbers or undefined. Populates adv.workload object if keys missing.
     *
     * why: |
     *   Centralizes input validation and fallback logic to prevent NaN propagation in cost calculations.
     *
     * guardrails:
     *   - DO NOT overwrite existing adv.workload keys; only fill undefined slots
     *   - NOTE: numOrUndef returns undefined for non-finite values (NaN, Infinity)
     * ---/agentspec
     */
    function numOrUndef(v){ const n = Number(v); return Number.isFinite(n) ? n : undefined; }
    const costIn   = numOrUndef(document.getElementById('cost-in')?.value);
    const costOut  = numOrUndef(document.getElementById('cost-out')?.value);
    const costEmb  = numOrUndef(document.getElementById('cost-embeds')?.value);
    const costRR   = numOrUndef(document.getElementById('cost-rerank')?.value);
    const costRPD  = numOrUndef(document.getElementById('cost-rpd')?.value);
    if (adv.workload.requests_per_day === undefined && costRPD !== undefined) adv.workload.requests_per_day = costRPD;
    if (adv.workload.tokens_in_per_req === undefined && costIn !== undefined) adv.workload.tokens_in_per_req = costIn;
    if (adv.workload.tokens_out_per_req === undefined && costOut !== undefined) adv.workload.tokens_out_per_req = costOut;
    if (adv.workload.embed_tokens_per_req === undefined && costEmb !== undefined) adv.workload.embed_tokens_per_req = costEmb;
    if (adv.workload.rerank_tokens_per_req === undefined && costRR !== undefined) adv.workload.rerank_tokens_per_req = costRR;
    // MQ default from current env if not provided
    if (adv.workload.mq_rewrites === undefined) {
      const mq = parseInt(env.MAX_QUERY_REWRITES || '');
      adv.workload.mq_rewrites = Number.isFinite(mq) && mq>0 ? mq : undefined; // leave undefined so server can recommend
    }
    const payload = {
      hardware: { runtimes: (scan && scan.runtimes) || {}, meta: (scan && scan.info) || {} },
      policy: { providers_allowed: adv.prov.length? adv.prov : undefined, regions_allowed: adv.regions.length? adv.regions: undefined, compliance: adv.compliance.length? adv.compliance: undefined },
      workload: Object.fromEntries(Object.entries(adv.workload).filter(([_,v])=> v!==undefined)),
      objective: {
        mode: adv.mode,
        monthly_budget_usd: isNaN(adv.budgetOverride)? budget : adv.budgetOverride,
        latency_target_ms: adv.slo.latency_target_ms,
        min_qps: adv.slo.min_qps,
      },
      tuning: { use_heuristic_quality: !!adv.heur },
      defaults: { gen_model: env.GEN_MODEL || '' }
    };
    try{
      setPhase('Calling selector...');
      const r = await fetchWithTimeout(api('/api/profile/autoselect'), { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(payload), timeout: 15000 });
      if (!r.ok){ const txt = await r.text(); throw new Error(txt || 'autoselect failed'); }
      setPhase('Rendering result...');
      const data = await r.json();
      renderResult(data.env, data.reason, scan, payload.objective.monthly_budget_usd || budget);

      // Optional: show an estimated cost banner using current cost panel inputs and selected providers
      try{
        const genProvider = (data.env.GEN_MODEL && data.env.GEN_MODEL.includes(':')) ? 'local' : 'openai';
        const genModel = data.env.GEN_MODEL || 'gpt-4o-mini';
        const cp = {
          gen_provider: genProvider,
          gen_model: genModel,
          tokens_in: (costIn || 0),
          tokens_out: (costOut || 0),
          embeds: (costEmb || 0),
          reranks: (costRR || 0),
          requests_per_day: (costRPD || 0),
          embed_provider: data.env.EMBEDDING_TYPE || undefined,
          rerank_provider: data.env.RERANK_BACKEND || undefined,
          rerank_model: data.env.COHERE_RERANK_MODEL || undefined,
        };
        const er = await fetchWithTimeout(api('/api/cost/estimate'), { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(cp), timeout: 10000 });
        if (er.ok){
          const est = await er.json();
          const results = document.getElementById('profile-results-content');
          if (results){
            const div = document.createElement('div');
            div.style.cssText = 'margin-top:10px;padding:10px;border:1px solid var(--line);border-radius:6px;background:var(--card-bg);color:var(--fg-muted);font-size:12px;';
            div.innerHTML = `<strong style="color:var(--accent);">Estimated Cost</strong> — Daily: $${Number(est.daily||0).toFixed(4)} • Monthly: $${Number(est.monthly||0).toFixed(2)}`;
            results.prepend(div);
          }
        }
      }catch{}
    }catch(err){
      const results = document.getElementById('profile-results-content');
      const placeholder = document.getElementById('profile-placeholder');
      const payloadStr = JSON.stringify(payload, null, 2);
      if (results){ results.innerHTML = '<div style="padding:20px;">'+
        '<div style="color:var(--err); font-weight:600; margin-bottom:8px;">Auto‑Profile v2 error</div>'+
        '<pre style="color:var(--fg-muted); white-space:pre-wrap;">'+(err?.message||String(err))+'</pre>'+
        '<details style="margin-top:12px;"><summary style="cursor:pointer; color:var(--fg-muted);">Payload</summary><pre style="color:var(--fg-muted); white-space:pre-wrap;">'+payloadStr+'</pre></details>'+
        '</div>'; results.style.display='block'; }
      if (placeholder) placeholder.style.display='none';
    }
  }

  // Initialization function called by config.js when profiles view mounts
  // Does NOT register view - config.js handles that
  window.initAutoProfile = function() {
    console.log('[autoprofile_v2.js] Initializing AutoProfile v2 for profiles view');
    // Initialize autoprofile state here if needed
    // Currently stateless, so nothing to do
  };

  window.AutoProfileV2 = { run };

  console.log('[autoprofile_v2.js] Module loaded (coordination with config.js for profiles view)');
})();
