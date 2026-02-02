// Indexing status and controls. Exported via window.IndexStatus
;(function(){
  'use strict';
  const api = (window.CoreUtils && window.CoreUtils.api) ? window.CoreUtils.api : (p=>p);
  let indexPoll = null;
  let backgroundPoll = null;  // Persistent background poll for index display

  /**
   * ---agentspec
   * what: |
   *   Detects React dashboard DOM elements and formats byte sizes. Returns boolean for containment check; returns formatted string (e.g., "1.5 MB") for byte input.
   *
   * why: |
   *   Centralizes dashboard element detection and human-readable storage formatting.
   *
   * guardrails:
   *   - DO NOT rely on window.__TRIBRID_REACT_DASHBOARD__ as primary source; prioritize data-react-dashboard attribute
   *   - NOTE: formatBytes silently returns '0 B' for null/undefined/0; add explicit validation if strict type-checking required
   *   - ASK USER: Should formatBytes throw on negative bytes or non-numeric input?
   * ---/agentspec
   */
  const getReactDashboardRoot = () => document.querySelector('[data-react-dashboard="true"]');
  /**
   * ---agentspec
   * what: |
   *   isReactDashboardElement checks if a DOM node belongs to React dashboard root. formatBytes converts byte count to human-readable string (B, KB, MB, GB).
   *
   * why: |
   *   Utility pair for dashboard DOM validation and memory/file size display.
   *
   * guardrails:
   *   - DO NOT call getReactDashboardRoot() repeatedly; cache result
   *   - NOTE: formatBytes returns '0 B' for null/undefined/0; handles edge cases
   *   - NOTE: isReactDashboardElement requires window.__TRIBRID_REACT_DASHBOARD__ or root to exist
   * ---/agentspec
   */
  const isReactDashboardElement = (node) => {
    const root = getReactDashboardRoot();
    return Boolean((window.__TRIBRID_REACT_DASHBOARD__ || root) && node && root && root.contains(node));
  };

  /**
   * ---agentspec
   * what: |
   *   Formats byte counts to human-readable units (B, KB, MB, GB). Accepts bytes integer, returns string with value + unit.
   *
   * why: |
   *   Standardizes file size display across UI without external dependencies.
   *
   * guardrails:
   *   - DO NOT use for network throughput; bytes-per-second requires different formatting
   *   - NOTE: Returns '0 B' for null/undefined/0 input
   * ---/agentspec
   */
  function formatBytes(bytes){
    if (!bytes || bytes === 0) return '0 B';
    const k = 1024; const sizes = ['B','KB','MB','GB'];
    const i = Math.floor(Math.log(bytes)/Math.log(k));
    return Math.round((bytes / Math.pow(k,i))*100)/100 + ' ' + sizes[i];
  }

  /**
   * ---agentspec
   * what: |
   *   Formats index status UI. Takes lines array + optional metadata; returns HTML div with styled status text or metadata display.
   *
   * why: |
   *   Centralizes status rendering logic to avoid duplication across index UI components.
   *
   * guardrails:
   *   - DO NOT inject unsanitized user input into HTML; escape metadata values
   *   - NOTE: Falls back to "Ready to index..." if no lines/metadata provided
   * ---/agentspec
   */
  function formatIndexStatus(lines, metadata){
    if (!metadata){
      if (!lines || !lines.length) return '<div style="color:var(--fg-muted);font-size:13px;">Ready to index...</div>';
      return `<div style="color:var(--fg-muted);font-size:12px;">${(lines||[]).join('<br>')}</div>`;
    }
    const html = [];
    html.push(`
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;padding-bottom:12px;border-bottom:1px solid var(--line);">
        <div style="display:flex;align-items:center;gap:12px;">
          <div style="width:6px;height:6px;border-radius:50%;background:var(--accent);box-shadow:0 0 8px var(--accent);"></div>
          <div>
            <div style="font-size:16px;font-weight:600;color: var(--fg);letter-spacing:-0.3px;">${metadata.current_repo}</div>
            <div style="font-size:11px;color:var(--fg-muted);text-transform:uppercase;letter-spacing:0.5px;margin-top:2px;">Branch: <span style="color:var(--link);">${metadata.current_branch}</span></div>
          </div>
        </div>
        <div style="text-align:right;font-size:10px;color:var(--fg-muted);">${new Date(metadata.timestamp).toLocaleString()}</div>
      </div>
    `);
    html.push(`
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:16px;">
        <div style="background:var(--card-bg);padding:12px;border-radius:6px;border:1px solid var(--line);">
          <div style="font-size:10px;color:var(--fg-muted);text-transform:uppercase;letter-spacing:0.5px;margin-bottom:6px;">Embedding Model</div>
          <div style="font-size:14px;font-weight:600;color:var(--link);font-family:'SF Mono',monospace;">${metadata.embedding_model}</div>
        </div>
        <div style="background:var(--card-bg);padding:12px;border-radius:6px;border:1px solid var(--line);">
          <div style="font-size:10px;color:var(--fg-muted);text-transform:uppercase;letter-spacing:0.5px;margin-bottom:6px;">Keywords</div>
          <div style="font-size:14px;font-weight:600;color:var(--warn);font-family:'SF Mono',monospace;">${metadata.keywords_count.toLocaleString()}</div>
        </div>
      </div>
    `);
    if (metadata.repos && metadata.repos.length>0){
      html.push(`<div style="margin-bottom:12px;"><div style="font-size:11px;font-weight:600;color:var(--accent);text-transform:uppercase;letter-spacing:0.5px;margin-bottom:10px;">Index Profiles</div>`);
      metadata.repos.forEach(repo => {
        const totalSize = (repo.sizes.chunks||0) + (repo.sizes.bm25||0) + (repo.sizes.cards||0);
        html.push(`
          <div style="background:var(--code-bg);border:1px solid ${repo.has_cards?'var(--ok)':'var(--line)'};border-radius:6px;padding:12px;margin-bottom:8px;">
            <div style="display:flex;justify-content:space-between;align-items:start;margin-bottom:10px;">
              <div>
                <div style="font-size:13px;font-weight:600;color: var(--fg);margin-bottom:4px;">${repo.name} <span style="font-size:10px;color:var(--fg-muted);font-weight:400;">/ ${repo.profile}</span></div>
                <div style="font-size:11px;color:var(--fg-muted);">${repo.chunk_count.toLocaleString()} chunks ${repo.has_cards ? ' • <span style="color:var(--accent);">✓ Cards</span>' : ' • <span style="color:var(--fg-muted);">No cards</span>'}</div>
              </div>
              <div style="text-align:right;">
                <div style="font-size:14px;font-weight:600;color:var(--accent);font-family:'SF Mono',monospace;">${formatBytes(totalSize)}</div>
              </div>
            </div>
          </div>
        `);
      });
      html.push(`</div>`);
    }
    html.push(`
      <div style="display:flex;justify-content:space-between;align-items:center;padding-top:12px;border-top:1px solid var(--line);">
        <div style="font-size:12px;color:var(--fg-muted);text-transform:uppercase;letter-spacing:0.5px;">Total Index Storage</div>
        <div style="font-size:18px;font-weight:700;color:var(--accent);font-family:'SF Mono',monospace;">${formatBytes(metadata.total_storage)}</div>
      </div>
    `);
    return html.join('');
  }

  async function pollIndexStatus(){
    try{
      const r = await fetch(api('/api/index/status'));
      const d = await r.json();
      const box1 = document.getElementById('index-status');
      const bar1 = document.getElementById('index-bar');
      const box2 = document.getElementById('dash-index-status');
      const bar2 = document.getElementById('dash-index-bar');
      const lastIndexedDisplay = document.getElementById('last-indexed-display');
      const formatted = (typeof window.formatIndexStatusDisplay === 'function') ? window.formatIndexStatusDisplay(d.lines, d.metadata) : formatIndexStatus(d.lines, d.metadata);
      const pct = d.running ? 50 : (d.metadata ? 100 : 0);
      if (box1) box1.innerHTML = formatted;
      if (bar1) bar1.style.width = pct + '%';
      if (box2 && !isReactDashboardElement(box2)) box2.innerHTML = formatted;
      if (bar2 && !isReactDashboardElement(bar2)) bar2.style.width = pct + '%';
      if (lastIndexedDisplay && d.metadata && d.metadata.timestamp){ lastIndexedDisplay.textContent = new Date(d.metadata.timestamp).toLocaleString(); }
      if (!d.running && indexPoll){
        clearInterval(indexPoll);
        indexPoll = null;
        if (bar2 && !isReactDashboardElement(bar2)){
          setTimeout(()=>{bar2.style.width='0%';}, 2000);
        }
      }
    }catch(_e){}
  }

  async function startIndexing(){
    try{
      if (window.showStatus) window.showStatus('Starting indexer...', 'loading');
      await fetch(api('/api/index/start'), { method:'POST' });
      if (indexPoll) clearInterval(indexPoll);
      indexPoll = setInterval(pollIndexStatus, 2000); // poll every 2 seconds during indexing
      await pollIndexStatus();
    }catch(e){ if (window.showStatus) window.showStatus('Failed to start indexer: ' + e.message, 'error'); throw e; }
  }

  // Start persistent background poll to keep index display updated
  // This runs every 30 seconds and ensures the display is always populated
  /**
   * ---agentspec
   * what: |
   *   Starts a recurring 30-second poll of index status. Calls pollIndexStatus() immediately, then every 30s. Returns early if poll already running.
   *
   * why: |
   *   Keeps dashboard display fresh without manual refresh; guards against duplicate intervals.
   *
   * guardrails:
   *   - DO NOT poll if target elements missing; add visibility check before setInterval
   *   - NOTE: backgroundPoll must be cleared on unmount/logout to prevent memory leak
   * ---/agentspec
   */
  function startBackgroundPoll() {
    if (backgroundPoll) return; // Already running

    // Initial poll
    pollIndexStatus();

    // Poll every 30 seconds to keep display fresh
    backgroundPoll = setInterval(() => {
      // Only poll if target elements exist (Dashboard is visible)
      const box1 = document.getElementById('index-status');
      const box2 = document.getElementById('dash-index-status');
      if (box1 || box2) {
        pollIndexStatus();
      }
    }, 30000);
  }

  // Watch for DOM changes to detect when dashboard elements appear
  // This ensures the display is populated when navigating back to dashboard
  /**
   * ---agentspec
   * what: |
   *   Observes DOM mutations for target elements (#dash-index-status, #index-status). Triggers callback on element addition.
   *
   * why: |
   *   MutationObserver detects dynamic DOM changes without polling; efficient for async-rendered content.
   *
   * guardrails:
   *   - DO NOT observe entire document without subtree limit; scope to parent container
   *   - NOTE: nodeType === Node.ELEMENT_NODE filters text/comment nodes; querySelector may be null on non-Element nodes
   *   - ASK USER: Define callback action; observer setup incomplete without handler
   * ---/agentspec
   */
  function setupDOMWatcher() {
    const observer = new MutationObserver((mutations) => {
      for (const mutation of mutations) {
        for (const node of mutation.addedNodes) {
          if (node.nodeType === Node.ELEMENT_NODE) {
            // Check if the added node is or contains our target elements
            const hasTarget = node.id === 'dash-index-status' ||
                            node.id === 'index-status' ||
                            (node.querySelector && (node.querySelector('#dash-index-status') || node.querySelector('#index-status')));
            if (hasTarget) {
              // Element appeared - trigger poll to populate it
              setTimeout(pollIndexStatus, 100);
              return;
            }
          }
        }
      }
    });

    observer.observe(document.body, { childList: true, subtree: true });
  }

  // Initialize on DOMContentLoaded
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => {
      startBackgroundPoll();
      setupDOMWatcher();
    });
  } else {
    // DOM already ready
    startBackgroundPoll();
    setupDOMWatcher();
  }

  window.IndexStatus = { formatIndexStatus, pollIndexStatus, startIndexing, startBackgroundPoll };
})();
