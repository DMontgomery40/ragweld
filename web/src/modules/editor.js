// Embedded Editor panel logic. Exported via window.Editor
;(function(){
  'use strict';

  const api = (window.CoreUtils && window.CoreUtils.api) ? window.CoreUtils.api : (p=>p);
  let editorHealthInterval = null;
  let lastHealthResponse = null;
  let iframeLoadAttempts = 0;
  const MAX_IFRAME_LOAD_ATTEMPTS = 3;

  /**
   * ---agentspec
   * what: |
   *   Checks if editor embedding is enabled. Returns boolean via checkbox field or env var EDITOR_EMBED_ENABLED. Defaults to true unless CI=1.
   *
   * why: |
   *   Centralizes embed-enabled logic with CI guard to prevent embedding in automated environments.
   *
   * guardrails:
   *   - DO NOT embed if CI env var is '1', 'true', or 'yes'; CI takes precedence
   *   - NOTE: Checkbox field takes priority over env var; env var is fallback
   *   - ASK USER: Clarify intended precedence if both checkbox and env var present
   * ---/agentspec
   */
  function _env(name, dflt){
    try { return (window.CoreUtils?.state?.config?.env?.[name]) ?? dflt; } catch { return dflt; }
  }
  /**
   * ---agentspec
   * what: |
   *   Checks if editor embedding is enabled. Returns boolean. Reads CI env var, then checkbox field, then EDITOR_EMBED_ENABLED env var (default true).
   *
   * why: |
   *   Layered fallback ensures CI pipelines disable embeds while respecting user UI toggles and env overrides.
   *
   * guardrails:
   *   - DO NOT embed in CI environments; CI guard must run first
   *   - NOTE: Checkbox field presence is optional; env var is fallback
   *   - NOTE: Default is true if no field or env var found
   * ---/agentspec
   */
  function _embedEnabled(){
    const ci = String(_env('CI','')).toLowerCase();
    if (ci === '1' || ci === 'true' || ci === 'yes') return false; // CI guard
    const fld = document.querySelector('[name="EDITOR_EMBED_ENABLED"]');
    if (fld && fld.type === 'checkbox') return fld.checked;
    const envVal = String(_env('EDITOR_EMBED_ENABLED','1'));
    return envVal === '1' || envVal.toLowerCase() === 'true';
  }

  async function checkEditorHealth() {
    try {
      const resp = await fetch(api('/health/editor'));
      const data = await resp.json();
      lastHealthResponse = data;

      const badge = document.getElementById('editor-health-badge');
      const badgeText = document.getElementById('editor-health-text');
      const banner = document.getElementById('editor-status-banner');
      const bannerMsg = document.getElementById('editor-status-message');
      const iframe = document.getElementById('editor-iframe');
      const wrap = document.getElementById('editor-iframe-container');

      if (!badge || !badgeText || !banner || !bannerMsg || !iframe || !wrap) return;

      const canEmbed = _embedEnabled();

      if (data.ok) {
        badge.style.background = 'var(--accent)';
        badge.style.color = 'var(--accent-contrast)';
        badgeText.textContent = '● Healthy';
        banner.style.display = 'none';
        if (canEmbed) {
          wrap.style.display = 'block';
          if (!iframe.src || iframe.src === 'about:blank') {
            // Only load if server confirms ready to avoid race conditions
            if (data.readiness_stage === 'ready') {
              // Use direct URL for WebSocket support (bypasses proxy)
              // The proxy can't handle WebSocket upgrades properly
              iframe.src = data.url || '/editor/';
              iframeLoadAttempts = 0;
            }
          }
        } else {
          wrap.style.display = 'none';
          iframe.src = '';
        }
      } else {
        const isDisabled = !data.enabled;
        badge.style.background = isDisabled ? 'var(--fg-muted)' : 'var(--err)';
        badge.style.color = 'var(--fg)';
        badgeText.textContent = isDisabled ? '○ Disabled' : '● Error';
        banner.style.display = 'block';

        // Provide more detailed status messages based on readiness stage
        let reason = data.reason || data.error || 'Unknown error';
        if (data.readiness_stage === 'startup_delay') {
          reason = `Service initializing (${data.uptime_seconds}s uptime)...`;
        } else if (data.readiness_stage === 'timeout') {
          reason = 'Service timeout - may still be starting up';
        } else if (data.readiness_stage === 'connection_failed') {
          reason = 'Cannot connect to service';
        }

        bannerMsg.textContent = isDisabled
          ? `Editor is disabled. Enable it in the Misc tab and restart.`
          : `${reason}. ${isDisabled ? '' : 'Retrying...'}`;
        wrap.style.display = 'none';
        iframe.src = '';
      }
    } catch (error) {
      console.error('[Editor] Failed to check health:', error);
      const badge = document.getElementById('editor-health-badge');
      const badgeText = document.getElementById('editor-health-text');
      if (badge && badgeText) {
        badge.style.background = 'var(--err)';
        badge.style.color = 'var(--fg)';
        badgeText.textContent = '● Error';
      }
    }
  }

  async function openEditorWindow() {
    try {
      const resp = await fetch(api('/health/editor'));
      const data = await resp.json();
      if (data.url) {
        window.open(data.url, '_blank');
      } else {
        alert('Editor URL not available');
      }
    } catch (error) {
      console.error('[Editor] Failed to open editor window:', error);
    }
  }

  async function copyEditorUrl() {
    try {
      const resp = await fetch(api('/health/editor'));
      const data = await resp.json();
      if (data.url) {
        await navigator.clipboard.writeText(data.url);
        const btn = document.getElementById('btn-editor-copy-url');
        if (btn) {
          const orig = btn.innerHTML;
          btn.innerHTML = '✓ Copied!';
          setTimeout(() => { btn.innerHTML = orig; }, 2000);
        }
      } else {
        alert('Editor URL not available');
      }
    } catch (error) {
      console.error('[Editor] Failed to copy URL:', error);
    }
  }

  async function restartEditor() {
    try {
      const btn = document.getElementById('btn-editor-restart');
      if (btn) {
        btn.disabled = true;
        btn.textContent = 'Restarting...';
      }
      const resp = await fetch(api('/api/editor/restart'), { method: 'POST' });
      const data = await resp.json();
      if (data.ok) {
        setTimeout(() => {
          const iframe = document.getElementById('editor-iframe');
          if (iframe) iframe.src = '';
          checkEditorHealth();
        }, 3000);
      } else {
        console.error('[Editor] Restart failed:', data.error || data.stderr);
        alert('Restart failed: ' + (data.error || 'Unknown error'));
      }
    } catch (error) {
      console.error('[Editor] Failed to restart editor:', error);
      alert('Restart failed: ' + error.message);
    } finally {
      const btn = document.getElementById('btn-editor-restart');
      if (btn) {
        btn.disabled = false;
        btn.innerHTML = '↻ Restart';
      }
    }
  }

  /**
   * ---agentspec
   * what: |
   *   Initializes periodic editor health checks every 10s. Calls checkEditorHealth() immediately, then sets interval. Stops via stopEditorHealthCheck().
   *
   * why: |
   *   Prevents duplicate intervals; single guard ensures one active check loop.
   *
   * guardrails:
   *   - DO NOT call initEditorHealthCheck() multiple times without stopEditorHealthCheck(); creates interval leaks
   *   - NOTE: Runs in CI with embed disabled; badge updates but iframe not reloaded
   *   - ASK USER: What triggers stopEditorHealthCheck()? Cleanup on unmount required.
   * ---/agentspec
   */
  function initEditorHealthCheck() {
    // In CI or when embed is disabled, we still update the badge but avoid loading the iframe repeatedly
    if (!editorHealthInterval) {
      checkEditorHealth();
      editorHealthInterval = setInterval(checkEditorHealth, 30000);
    }
  }

  /**
   * ---agentspec
   * what: |
   *   Clears the editor health check interval. Stops periodic monitoring by nullifying the interval handle.
   *
   * why: |
   *   Prevents memory leaks and redundant polling when health checks are no longer needed.
   *
   * guardrails:
   *   - NOTE: Assumes editorHealthInterval is a valid interval ID or null
   *   - DO NOT call without prior setInterval assignment; will silently no-op
   * ---/agentspec
   */
  function stopEditorHealthCheck() {
    if (editorHealthInterval) {
      clearInterval(editorHealthInterval);
      editorHealthInterval = null;
    }
  }

  /**
   * ---agentspec
   * what: |
   *   Binds click handlers to three editor control buttons (open window, copy URL, restart). Uses dataset.bound flag to prevent duplicate listener attachment.
   *
   * why: |
   *   Idempotent binding prevents memory leaks and multiple handler fires on repeated calls.
   *
   * guardrails:
   *   - DO NOT bind without checking dataset.bound; causes duplicate listeners
   *   - NOTE: Assumes button IDs exist; silently skips if missing
   * ---/agentspec
   */
  function bindControls(){
    const btnOpenWindow = document.getElementById('btn-editor-open-window');
    const btnCopyUrl = document.getElementById('btn-editor-copy-url');
    const btnRestart = document.getElementById('btn-editor-restart');
    if (btnOpenWindow && !btnOpenWindow.dataset.bound){ btnOpenWindow.dataset.bound='1'; btnOpenWindow.addEventListener('click', openEditorWindow); }
    if (btnCopyUrl && !btnCopyUrl.dataset.bound){ btnCopyUrl.dataset.bound='1'; btnCopyUrl.addEventListener('click', copyEditorUrl); }
    if (btnRestart && !btnRestart.dataset.bound){ btnRestart.dataset.bound='1'; btnRestart.addEventListener('click', restartEditor); }
  }

  // Auto-bind on load
  if (document.readyState === 'loading') {
    window.addEventListener('DOMContentLoaded', bindControls);
  } else {
    bindControls();
  }

  // Register with Navigation API
  /**
   * ---agentspec
   * what: |
   *   Registers VS Code editor view with Navigation API. Mounts controls and health check on activation.
   *
   * why: |
   *   Centralizes editor initialization and ensures Navigation framework recognizes the view.
   *
   * guardrails:
   *   - DO NOT call if window.Navigation unavailable; check exists first
   *   - NOTE: bindControls() and initEditorHealthCheck() must be defined before registerEditorView() runs
   * ---/agentspec
   */
  function registerEditorView() {
    if (window.Navigation && typeof window.Navigation.registerView === 'function') {
      window.Navigation.registerView({
        id: 'vscode',
        title: 'VS Code',
        mount: () => {
          console.log('[editor.js] Mounted as vscode');
          bindControls();
          initEditorHealthCheck();
        },
        unmount: () => {
          console.log('[editor.js] Unmounted');
          stopEditorHealthCheck();
        }
      });
    }
  }

  // Register when Navigation is ready
  if (document.readyState === 'loading') {
    window.addEventListener('DOMContentLoaded', registerEditorView);
  } else {
    registerEditorView();
  }

  window.Editor = { checkEditorHealth, openEditorWindow, copyEditorUrl, restartEditor, initEditorHealthCheck, stopEditorHealthCheck, bindControls };
})();
