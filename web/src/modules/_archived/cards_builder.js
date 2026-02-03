// Cards Builder (Job + SSE) logic with PERMANENT VISIBLE PROGRESS. Exported via window.CardsBuilder
;(function(){
  'use strict';
  const api = (window.CoreUtils && window.CoreUtils.api) ? window.CoreUtils.api : (p=>p);
  const state = (window.CoreUtils && window.CoreUtils.state) ? window.CoreUtils.state : {};
  /**
   * ---agentspec
   * what: |
   *   Populates repo dropdown from /api/config endpoint. Fetches config, extracts repos, renders <option> elements in #cards-repo-select.
   *
   * why: |
   *   Centralizes repo list at API layer; UI stays in sync with backend config.
   *
   * guardrails:
   *   - DO NOT assume #cards-repo-select exists; check before populate
   *   - NOTE: Throws silently on fetch fail; add error handler if needed
   * ---/agentspec
   */
  const $ = (id) => document.getElementById(id);
  let cardsJob = { id: null, timer: null, sse: null };

  // Populate repo dropdown
  async function populateRepoSelect(){
    const sel = $('cards-repo-select');
    if (!sel) return;
    try {
      const r = await fetch(api('/api/config'));
      const config = await r.json();
      sel.innerHTML = '';
      (config.repos || []).forEach(repo => {
        const opt = document.createElement('option');
        opt.value = repo.name;
        opt.textContent = repo.name;
        sel.appendChild(opt);
      });
      sel.value = (config.env && config.env.REPO) || config.default_repo || 'auto';
    } catch(e){
      const msg = window.ErrorHelpers ? window.ErrorHelpers.createAlertError('Failed to load repositories', {
        message: e.message,
        causes: [
          'Backend configuration API service is unavailable',
          'Invalid JSON response from configuration endpoint',
          'Network connectivity issue or timeout',
          'Repository configuration file is missing or corrupted'
        ],
        fixes: [
          'Verify backend service is running in Infrastructure tab',
          'Check backend logs for configuration loading errors',
          'Verify network connectivity and check firewall rules',
          'Refresh the page and try loading repositories again'
        ],
        links: [
          ['Fetch API Documentation', 'https://developer.mozilla.org/en-US/docs/Web/API/Fetch_API'],
          ['JSON Parsing Guide', 'https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Global_Objects/JSON/parse']
        ]
      }) : `Failed to load repos: ${e.message}`;
      console.error('[cards_builder] Failed to load repos:', msg);
    }
  }

  /**
   * ---agentspec
   * what: |
   *   Shows/hides DOM element with id 'cards-progress-container' by toggling display style. showProgress() sets display='block'; hideProgress() sets display='none'.
   *
   * why: |
   *   Minimal DOM manipulation for progress UI visibility control without external dependencies.
   *
   * guardrails:
   *   - DO NOT assume element exists; both functions check null before style access
   *   - NOTE: Uses shorthand $() selector; ensure it's defined in scope
   * ---/agentspec
   */
  function showProgress(){
    const cont = $('cards-progress-container');
    if (cont) cont.style.display = 'block';
  }

  /**
   * ---agentspec
   * what: |
   *   Hides/shows progress container DOM element. hideProgress() sets display:none; showCompletionStatus() displays persistent status summary.
   *
   * why: |
   *   Decouples UI visibility logic from data flow; allows independent control of progress bar state.
   *
   * guardrails:
   *   - DO NOT assume 'cards-progress-container' exists; check null before style mutation
   *   - NOTE: showCompletionStatus() incomplete; data param unused, implementation cut off
   * ---/agentspec
   */
  function hideProgress(){
    const cont = $('cards-progress-container');
    if (cont) cont.style.display = 'none';
  }

  /**
   * ---agentspec
   * what: |
   *   Displays progress bar in DOM by selecting cards-progress-container, setting display:block and border style. Updates title text if present.
   *
   * why: |
   *   Centralizes UI feedback for async card-building operations into single persistent status element.
   *
   * guardrails:
   *   - DO NOT assume cont exists; null-check before style mutations
   *   - NOTE: Relies on external CSS var(--ok); fails silently if undefined
   *   - ASK USER: Should title update be conditional on data state?
   * ---/agentspec
   */
  function showCompletionStatus(data){
    // Show progress bar as a persistent status summary
    const cont = $('cards-progress-container');
    if (cont) {
      cont.style.display = 'block';
      cont.style.border = '2px solid var(--ok)';
    }
    const title = cont?.querySelector('div[style*="Building Cards"]');
    if (title) {
      title.textContent = '✓ Cards Build Complete';
      title.style.color = 'var(--ok)';
    }
    updateProgress(data);
    // Keep visible - don't auto-hide
  }

  /**
   * ---agentspec
   * what: |
   *   Displays error status by showing cards-progress-container, setting red border, and updating title to "✗ Cards Build Failed".
   *
   * why: |
   *   Centralizes error UI feedback into single function to avoid scattered DOM mutations.
   *
   * guardrails:
   *   - DO NOT assume cont exists; null checks prevent crashes
   *   - NOTE: Uses CSS variable --err; ensure defined in stylesheet
   * ---/agentspec
   */
  function showErrorStatus(error){
    const cont = $('cards-progress-container');
    if (cont) {
      cont.style.display = 'block';
      cont.style.border = '2px solid var(--err)';
    }
    const title = cont?.querySelector('div');
    if (title) {
      title.textContent = '✗ Cards Build Failed';
      title.style.color = 'var(--err)';
    }
    const tipEl = $('cards-progress-tip');
    if (tipEl) tipEl.textContent = `❌ ${error || 'Unknown error'}`;
  }

  /**
   * ---agentspec
   * what: |
   *   Highlights active pipeline stage by ID. Sets color, border, background CSS vars on matching DOM element; resets others to default.
   *
   * why: |
   *   Centralizes stage UI state to prevent inconsistent highlighting across pipeline steps.
   *
   * guardrails:
   *   - DO NOT assume element exists; add null check before style assignment
   *   - NOTE: Relies on predictable ID format 'cards-progress-stage-{stageName}'
   * ---/agentspec
   */
  function highlightStage(stage){
    const all = ['scan','chunk','summarize','sparse','write','finalize'];
    all.forEach(s => {
      const el = $('cards-progress-stage-'+s);
      if (el) {
        if (s === stage) {
          el.style.color = 'var(--fg)';
          el.style.borderColor = 'var(--ok)';
          el.style.background = 'var(--ok)';
          el.style.fontWeight = '600';
        } else {
          el.style.color = 'var(--fg-muted)';
          el.style.borderColor = 'var(--line)';
          el.style.background = 'transparent';
          el.style.fontWeight = '400';
        }
      }
    });
  }

  /**
   * ---agentspec
   * what: |
   *   Updates progress bar UI with completion percentage, stats (done/total), and metadata (model, stage, throughput, ETA, repo). Reads data object, writes to DOM elements #cards-progress-bar (width) and #cards-progress-stats (text).
   *
   * why: |
   *   Centralizes progress rendering logic; decouples data updates from DOM manipulation.
   *
   * guardrails:
   *   - DO NOT assume data keys exist; all destructured values default to falsy
   *   - NOTE: Silently skips DOM updates if elements missing (no error thrown)
   *   - ASK USER: Should missing elements throw or warn?
   * ---/agentspec
   */
  function updateProgress(data){
    try {
      const { pct, total, done, tip, model, stage, throughput, eta_s, repo } = data || {};
      
      const bar = $('cards-progress-bar');
      if (bar) bar.style.width = `${pct||0}%`;
      
      const stats = $('cards-progress-stats');
      if (stats) stats.textContent = `${done||0} / ${total||0} (${(pct||0).toFixed(1)}%)`;
      const statsModal = $('cards-progress-stats-modal');
      if (statsModal) statsModal.textContent = `${done||0} / ${total||0} (${(pct||0).toFixed(1)}%)`;
      
      const thr = $('cards-progress-throughput');
      if (thr) thr.textContent = throughput || '--';
      
      const eta = $('cards-progress-eta');
      if (eta) eta.textContent = `ETA: ${eta_s||0}s`;
      
      const tipEl = $('cards-progress-tip');
      if (tipEl && tip) tipEl.textContent = `💡 ${tip}`;
      
      const repoEl = $('cards-progress-repo');
      if (repoEl && repo) repoEl.textContent = repo;
      
      highlightStage(stage);
    } catch(e){ console.error('[cards_builder] Update progress failed:', e); }
  }

  /**
   * ---agentspec
   * what: |
   *   Stops active card streams (timer + SSE). Clears cardsJob state. Inputs: none. Outputs: cardsJob.timer and cardsJob.sse set to null.
   *
   * why: |
   *   Prevents resource leaks and duplicate streams before starting new build.
   *
   * guardrails:
   *   - DO NOT throw on close() failure; silent catch required
   *   - NOTE: startCardsBuild() incomplete; requires repo + enrich logic
   * ---/agentspec
   */
  function stopCardsStreams(){
    if (cardsJob.timer) { clearInterval(cardsJob.timer); cardsJob.timer = null; }
    if (cardsJob.sse) { try { cardsJob.sse.close(); } catch{} cardsJob.sse = null; }
  }

  async function startCardsBuild(){
    try{
      const repo = $('cards-repo-select')?.value || 'auto';
      const enrich = $('cards-enrich-gui')?.checked ? 1 : 0;
      const excludeDirs = $('cards-exclude-dirs')?.value || '';
      const excludePatterns = $('cards-exclude-patterns')?.value || '';
      const excludeKeywords = $('cards-exclude-keywords')?.value || '';
      
      const params = new URLSearchParams({
        repo,
        enrich,
        exclude_dirs: excludeDirs,
        exclude_patterns: excludePatterns,
        exclude_keywords: excludeKeywords
      });
      
      showProgress();
      // Reset styling for new build
      const cont = $('cards-progress-container');
      if (cont) cont.style.border = '2px solid var(--accent)';
      const title = cont?.querySelector('div');
      if (title) {
        title.textContent = '⚡ Building Cards...';
        title.style.color = 'var(--fg)';
      }
      updateProgress({ stage: 'scan', done: 0, total: 0, pct: 0, repo, tip: 'Starting cards build...' });
      
      const r = await fetch(api(`/api/cards/build/start?${params}`), { method: 'POST' });
      if (r.status === 409) {
        const d = await r.json();
        if (window.showStatus) window.showStatus(d.detail || 'Job already running', 'error');
        hideProgress();
        return;
      }
      const d = await r.json();
      cardsJob.id = d.job_id;
      if (window.showStatus) window.showStatus('Cards build started', 'loading');
      
      try {
        const es = new EventSource(api(`/api/cards/build/stream/${cardsJob.id}`));
        cardsJob.sse = es;
        es.addEventListener('progress', (ev) => { try { const data = JSON.parse(ev.data||'{}'); updateProgress(data); } catch(e){ console.error('[cards_builder] SSE parse error:', e); } });
        es.addEventListener('done', async (ev) => {
          stopCardsStreams();
          const finalData = JSON.parse(ev.data||'{}');
          showCompletionStatus(finalData);
          if (window.showStatus) window.showStatus('✓ Cards built successfully', 'success');
          window.dispatchEvent(new Event('tribrid:cards:refresh'));
        });
        es.addEventListener('error', (_ev) => { console.log('[cards_builder] SSE error, falling back to polling'); });
        es.addEventListener('cancelled', (_ev) => {
          stopCardsStreams();
          if (window.showStatus) window.showStatus('Cards build cancelled', 'warn');
          hideProgress();
        });
      } catch (_e) {
        // SSE not available; use polling
        cardsJob.timer = setInterval(async () => {
          try {
            const s = await (await fetch(api(`/api/cards/build/status/${cardsJob.id}`))).json();
            updateProgress(s);
            if ((s.status||'')==='done'){
              stopCardsStreams();
              showCompletionStatus(s);
              window.dispatchEvent(new Event('tribrid:cards:refresh'));
              if (window.showStatus) window.showStatus('✓ Cards built successfully', 'success');
            }
            if ((s.status||'')==='error'){
              stopCardsStreams();
              showErrorStatus(s.error||'Unknown error');
              if (window.showStatus) window.showStatus('✗ Cards build failed: '+(s.error||'Unknown error'), 'error');
            }
          } catch(e){ console.error('[cards_builder] Polling error:', e); }
        }, 1000);
      }
    }catch(e){
      const msg = window.ErrorHelpers ? window.ErrorHelpers.createAlertError('Failed to start cards build', {
        message: e.message,
        causes: [
          'Cards build API service is unavailable or not responding',
          'Job system (Celery/Redis) is not running or experiencing issues',
          'Invalid repository configuration or path is inaccessible',
          'Insufficient system resources (memory, disk space, CPU)'
        ],
        fixes: [
          'Verify backend service and job queue are running in Infrastructure tab',
          'Check that selected repository path exists and is accessible',
          'Verify Redis and Celery services are operational',
          'Check available system resources (memory, disk space)'
        ],
        links: [
          ['Fetch API Documentation', 'https://developer.mozilla.org/en-US/docs/Web/API/Fetch_API'],
          ['EventSource API Documentation', 'https://developer.mozilla.org/en-US/docs/Web/API/EventSource']
        ]
      }) : `Failed to start cards build: ${e.message}`;
      if (window.showStatus) window.showStatus(msg, 'error');
      hideProgress();
    }
  }

  async function cancelCardsBuild(){
    if (!cardsJob.id) return;
    try {
      await fetch(api('/api/cards/build/cancel/'+cardsJob.id), { method: 'POST' });
      stopCardsStreams();
      hideProgress();
      if (window.showStatus) window.showStatus('Cards build cancelled', 'warn');
    } catch (e) {
      const msg = window.ErrorHelpers ? window.ErrorHelpers.createAlertError('Failed to cancel cards build', {
        message: e.message,
        causes: [
          'Backend API service not responding during cancellation',
          'Job ID is no longer valid or has already completed',
          'Job system (Celery) is experiencing issues',
          'Network connectivity problem during cancel request'
        ],
        fixes: [
          'Verify backend service is running and responsive',
          'Wait a moment for the current job to finish naturally',
          'Check Infrastructure tab to verify Celery/Redis are running',
          'Try refreshing the page to sync job status'
        ],
        links: [
          ['Fetch API Documentation', 'https://developer.mozilla.org/en-US/docs/Web/API/Fetch_API']
        ]
      }) : `Cancel failed: ${e.message}`;
      if (window.showStatus) window.showStatus(msg, 'error');
    }
  }

  async function showLogs(){
    try {
      const r = await fetch(api('/api/cards/build/logs'));
      const d = await r.json();
      alert(d.content || 'No logs available');
    } catch(e){
      const msg = window.ErrorHelpers ? window.ErrorHelpers.createAlertError('Failed to load build logs', {
        message: e.message,
        causes: [
          'Log service API is not responding',
          'Build logs have not been generated yet',
          'Logs file is missing, corrupted, or not accessible',
          'Network connectivity issue retrieving logs'
        ],
        fixes: [
          'Ensure a cards build has been run previously',
          'Verify backend service is running in Infrastructure tab',
          'Check that log directory exists and permissions are correct',
          'Refresh the page and try loading logs again'
        ],
        links: [
          ['Fetch API Documentation', 'https://developer.mozilla.org/en-US/docs/Web/API/Fetch_API'],
          ['JSON Parsing Guide', 'https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Global_Objects/JSON/parse']
        ]
      }) : `Unable to load logs: ${e.message}`;
      alert(msg);
      console.error('[cards_builder] Failed to load logs:', msg);
    }
  }

  // Bind events on load
  document.addEventListener('DOMContentLoaded', () => {
    populateRepoSelect();
    const buildBtn = $('btn-cards-build');
    if (buildBtn) buildBtn.addEventListener('click', startCardsBuild);
    const cancelBtn = $('cards-progress-cancel');
    if (cancelBtn) cancelBtn.addEventListener('click', cancelCardsBuild);
    const logsBtn = $('cards-progress-logs');
    if (logsBtn) logsBtn.addEventListener('click', showLogs);
    const clearBtn = $('cards-progress-clear');
    if (clearBtn) clearBtn.addEventListener('click', hideProgress);
  });

  // Initialization function called by cards.js when rag-data-quality view mounts
  // Does NOT register view - cards.js handles that
  window.initCardsBuilder = function() {
    console.log('[cards_builder.js] Initializing cards builder for rag-data-quality view');
    populateRepoSelect();
  };

  window.CardsBuilder = { startCardsBuild, cancelCardsBuild, showLogs, updateProgress, populateRepoSelect };

  console.log('[cards_builder.js] Module loaded (coordination with cards.js for rag-data-quality view)');
})();
