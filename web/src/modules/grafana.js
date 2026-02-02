// TriBridRAG GUI - Grafana Embed Module
// Builds iframe URL from GUI-controlled env and provides show/hide controls
(function() {
  'use strict';

  const { api, $, state } = window.CoreUtils || {};

  /**
   * ---agentspec
   * what: |
   *   Retrieves config value from env, falls back to DOM. Returns string or fallback default.
   *
   * why: |
   *   Env-first lookup ensures runtime config overrides DOM defaults.
   *
   * guardrails:
   *   - DO NOT treat empty string as missing; only null/undefined trigger fallback
   *   - NOTE: Returns String type; coerce if numeric needed
   * ---/agentspec
   */
  function env(k, d) {
    try { return (state.config && state.config.env && (state.config.env[k] ?? d)) ?? d; } catch { return d; }
  }

  /**
   * ---agentspec
   * what: |
   *   Retrieves config value from environment or DOM. Checks env first, falls back to DOM element by name attribute. Returns string or fallback.
   *
   * why: |
   *   Environment variables take precedence; DOM is secondary source for browser-based config.
   *
   * guardrails:
   *   - DO NOT treat empty string as missing; env('') is falsy but valid
   *   - NOTE: Checkbox returns '1'/'0', not boolean
   *   - NOTE: Returns string; caller must parse if number/bool needed
   * ---/agentspec
   */
  function vFromDom(name, fallback) {
    // Always prefer env value first, then fallback to DOM
    const envVal = env(name, null);
    if (envVal !== null && envVal !== undefined && envVal !== '') return String(envVal);

    const el = document.querySelector(`[name="${name}"]`);
    if (!el) return fallback;
    if (el.type === 'checkbox') return el.checked ? '1' : '0';
    return el.value || fallback;
  }

  /**
   * ---agentspec
   * what: |
   *   Builds Grafana dashboard URL from DOM config vars. Reads base URL, dashboard UID/slug, org ID, refresh rate, kiosk mode, auth mode, and token. Returns constructed URL string.
   *
   * why: |
   *   Centralizes URL construction logic; allows runtime config override via DOM without hardcoding.
   *
   * guardrails:
   *   - DO NOT expose GRAFANA_AUTH_TOKEN in logs or client-side; token leaks auth
   *   - NOTE: Falls back to 'anonymous' auth if token absent; verify Grafana permits this mode
   *   - DO NOT assume vFromDom() sanitizes values; validate URL before use
   * ---/agentspec
   */
  function buildUrl() {
    const base = String(vFromDom('GRAFANA_BASE_URL', 'http://127.0.0.1:3000')).replace(/\/$/, '');
    const uid = String(vFromDom('GRAFANA_DASHBOARD_UID', 'tribrid-overview'));
    const slug = String(vFromDom('GRAFANA_DASHBOARD_SLUG', 'tribrid-overview'));
    const orgId = String(vFromDom('GRAFANA_ORG_ID', '1'));
    const refresh = String(vFromDom('GRAFANA_REFRESH', '10s'));
    const kiosk = String(vFromDom('GRAFANA_KIOSK', 'tv'));
    const authMode = String(vFromDom('GRAFANA_AUTH_MODE', 'anonymous'));
    const token = String(vFromDom('GRAFANA_AUTH_TOKEN', '') || '');

    const params = new URLSearchParams();
    if (orgId) params.set('orgId', orgId);
    if (refresh) params.set('refresh', refresh);
    if (kiosk) params.set('kiosk', kiosk);
    if (authMode === 'token' && token) params.set('auth_token', token);

    return `${base}/d/${encodeURIComponent(uid)}/${encodeURIComponent(slug)}?${params.toString()}`;
  }

  /**
   * ---agentspec
   * what: |
   *   Toggles Grafana embed visibility based on GRAFANA_EMBED_ENABLED env var and CI detection. Shows embed block only when enabled AND not in CI environment.
   *
   * why: |
   *   Prevents iframe load overhead in CI pipelines while respecting explicit disable flag.
   *
   * guardrails:
   *   - DO NOT load iframe in CI; wastes resources and may fail auth
   *   - NOTE: Defaults to 'true' if GRAFANA_EMBED_ENABLED unset
   *   - NOTE: vFromDom() and env() must handle missing keys gracefully
   * ---/agentspec
   */
  function applyEmbedVisibility() {
    const enabled = String(vFromDom('GRAFANA_EMBED_ENABLED', 'true')).toLowerCase();
    /**
     * ---agentspec
     * what: |
     *   Conditionally displays Grafana embed iframe. Checks CI environment; shows embed only in non-CI contexts. Auto-loads iframe src on first display.
     *
     * why: |
     *   Prevents iframe load overhead in CI pipelines while enabling live dashboards in dev/prod browsers.
     *
     * guardrails:
     *   - DO NOT load iframe.src in CI; wastes resources and may fail auth
     *   - NOTE: Requires #grafana-embed and #grafana-iframe DOM elements present
     *   - ASK USER: Confirm buildUrl() handles auth tokens securely
     * ---/agentspec
     */
    const isCI = (() => { try { return /^(1|true|yes)$/i.test(String(env('CI',''))); } catch { return false; } })();
    const show = !isCI && (enabled === 'true' || enabled === '1');
    const wrap = document.getElementById('grafana-embed');
    if (wrap) wrap.style.display = show ? 'block' : 'none';
    // Auto-load iframe only when not in CI
    if (show) {
      const iframe = document.getElementById('grafana-iframe');
      if (iframe && !iframe.src) iframe.src = buildUrl();
    }
  }

  /**
   * ---agentspec
   * what: |
   *   Displays Grafana dashboard in iframe (preview) or opens in new window (openExternal). Calls buildUrl() to construct dashboard URL.
   *
   * why: |
   *   Separates embed vs. external-link logic; reuses URL builder.
   *
   * guardrails:
   *   - DO NOT call preview/openExternal without buildUrl() defined
   *   - NOTE: iframe must exist with id='grafana-iframe'; wrap div id='grafana-embed'
   *   - ASK USER: Validate buildUrl() returns valid Grafana URL before deploy
   * ---/agentspec
   */
  function preview() {
    const iframe = document.getElementById('grafana-iframe');
    const wrap = document.getElementById('grafana-embed');
    if (wrap) wrap.style.display = 'block';
    if (iframe) iframe.src = buildUrl();
  }

  /**
   * ```
   * ---agentspec
   * what: |
   *   Opens external URL in new browser tab. Builds URL, calls window.open with '_blank' target, silently catches errors.
   *
   * why: |
   *   Graceful fallback for environments where window.open may be blocked or unavailable.
   *
   * guardrails:
   *   - DO NOT rely on return value; window.open may return null if blocked
   *   - NOTE: '_blank' target always used; no option to open in same tab
   *   - DO NOT assume popup will succeed; user may have blocked popups
   * ---/agentspec
   * ```
   */
  function openExternal() {
    const url = buildUrl();
    try { window.open(url, '_blank'); } catch { /* no-op */ }
  }

  /**
   * ---agentspec
   * what: |
   *   Initializes UI on config load. Applies embed visibility, attaches click handlers to preview/open buttons.
   *
   * why: |
   *   Centralizes setup logic to ensure DOM listeners and visibility state sync on config changes.
   *
   * guardrails:
   *   - DO NOT call init() before DOM ready; attach to DOMContentLoaded
   *   - NOTE: Assumes grafana-preview and grafana-open elements exist; fails silently if missing
   * ---/agentspec
   */
  function init() {
    // When config loads (or reloads), set default values and visibility (no iframe load)
    applyEmbedVisibility();

    const prevBtn = document.getElementById('grafana-preview');
    if (prevBtn) prevBtn.addEventListener('click', (e) => { e.preventDefault(); preview(); });
    const openBtn = document.getElementById('grafana-open');
    if (openBtn) openBtn.addEventListener('click', (e) => { e.preventDefault(); openExternal(); });
  }

  /**
   * ---agentspec
   * what: |
   *   Toggles Grafana dashboard visibility. showDashboard() calls preview(); hideDashboard() sets display:none on #grafana-embed.
   *
   * why: |
   *   Simple DOM control for conditional dashboard rendering.
   *
   * guardrails:
   *   - DO NOT assume #grafana-embed exists; hideDashboard() silently fails if missing
   *   - NOTE: preview() function undefined; will throw if showDashboard() called
   * ---/agentspec
   */
  function showDashboard() {
    preview();
  }

  /**
   * ---agentspec
   * what: |
   *   Toggles visibility of Grafana dashboard embed. hideDashboard() hides element; isVisible() returns boolean state.
   *
   * why: |
   *   DOM manipulation for conditional dashboard display without page reload.
   *
   * guardrails:
   *   - DO NOT assume element exists; isVisible() safely checks before access
   *   - NOTE: Relies on 'grafana-embed' ID; will fail silently if missing
   * ---/agentspec
   */
  function hideDashboard() {
    const wrap = document.getElementById('grafana-embed');
    if (wrap) wrap.style.display = 'none';
  }

  /**
   * ---agentspec
   * what: |
   *   Checks Grafana embed visibility and retrieves config (baseUrl, dashboardUid) from DOM or defaults.
   *
   * why: |
   *   Centralizes embed state + config lookup to avoid repeated DOM queries.
   *
   * guardrails:
   *   - DO NOT assume vFromDom() exists; define or import it
   *   - NOTE: Defaults to localhost:3000; override via DOM attributes
   * ---/agentspec
   */
  function isVisible() {
    const wrap = document.getElementById('grafana-embed');
    return wrap && wrap.style.display !== 'none';
  }

  /**
   * ---agentspec
   * what: |
   *   Reads Grafana config from DOM data attributes. Returns object with baseUrl, dashboardUid, embedEnabled. Defaults: http://127.0.0.1:3000, 'tribrid-overview', 'true'.
   *
   * why: |
   *   Centralizes config retrieval; enables environment-specific overrides via DOM without code changes.
   *
   * guardrails:
   *   - DO NOT hardcode URLs; always read from DOM first
   *   - NOTE: String values ('true'/'false') returned as-is; caller must parse booleans
   *   - ASK USER: Validate baseUrl format before use in HTTP requests
   * ---/agentspec
   */
  function getConfig() {
    return {
      baseUrl: vFromDom('GRAFANA_BASE_URL', 'http://127.0.0.1:3000'),
      dashboardUid: vFromDom('GRAFANA_DASHBOARD_UID', 'tribrid-overview'),
      embedEnabled: vFromDom('GRAFANA_EMBED_ENABLED', 'true')
    };
  }

  // Register with Navigation API
  /**
   * ---agentspec
   * what: |
   *   Registers 'grafana' view with Navigation API. On mount, initializes Grafana and applies embed visibility rules.
   *
   * why: |
   *   Decouples view registration from initialization; allows lazy mounting when view becomes active.
   *
   * guardrails:
   *   - DO NOT call init() outside mount callback; breaks lazy loading
   *   - NOTE: Requires window.Navigation.registerView to exist; fails silently if missing
   *   - ASK USER: What triggers applyEmbedVisibility()? Clarify visibility logic.
   * ---/agentspec
   */
  function registerGrafanaView() {
    if (window.Navigation && typeof window.Navigation.registerView === 'function') {
      window.Navigation.registerView({
        id: 'grafana',
        title: 'Grafana',
        mount: () => {
          console.log('[grafana.js] Mounted');
          init();
          applyEmbedVisibility();
        },
        unmount: () => {
          console.log('[grafana.js] Unmounted');
          // No cleanup needed currently
        }
      });
    }
  }

  // Expose minimal API
  window.Grafana = {
    buildUrl,
    preview,
    openExternal,
    showDashboard,
    hideDashboard,
    isVisible,
    getConfig
  };

  // Initialize after DOM + after Config first load
  document.addEventListener('DOMContentLoaded', () => {
    // If Config is already loaded, init now, else hook into loadConfig completion
    setTimeout(init, 0);
    // Register with Navigation API
    registerGrafanaView();
  });
})();
