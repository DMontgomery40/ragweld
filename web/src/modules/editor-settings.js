// Editor Settings Management Module - Unified synchronization between frontend and backend
// Handles persistent storage of editor configuration with server-side backing
;(function(){
  'use strict';

  const api = (window.CoreUtils && window.CoreUtils.api) ? window.CoreUtils.api : (p=>p);

  // In-memory cache of settings
  const settingsCache = {
    port: 4440,
    enabled: true,
    host: '127.0.0.1',
    lastFetch: null
  };

  /**
   * Load editor settings from server
   * @returns {Promise<Object>} Settings object with port, enabled, host
   */
  async function loadSettings() {
    try {
      const resp = await fetch(api('/api/editor/settings'));
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const data = await resp.json();

      if (data.ok) {
        // Update cache
        settingsCache.port = data.port || 4440;
        settingsCache.enabled = data.enabled !== false;
        settingsCache.host = data.host || '127.0.0.1';
        settingsCache.lastFetch = Date.now();
        console.log('[EditorSettings] Loaded from server:', settingsCache);
        return { ...settingsCache };
      }
    } catch (error) {
      console.warn('[EditorSettings] Failed to load from server, using cache:', error);
    }
    return { ...settingsCache };
  }

  /**
   * Save editor settings to server
   * @param {Object} updates - Partial settings to update {port?, enabled?, host?}
   * @returns {Promise<boolean>} Success status
   */
  async function saveSettings(updates) {
    try {
      // Update cache locally first for optimistic UI
      if ('port' in updates) settingsCache.port = updates.port;
      if ('enabled' in updates) settingsCache.enabled = updates.enabled;
      if ('host' in updates) settingsCache.host = updates.host;

      // Persist to server
      const resp = await fetch(api('/api/editor/settings'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(updates)
      });

      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const data = await resp.json();

      if (data.ok) {
        console.log('[EditorSettings] Saved to server:', updates);
        return true;
      } else {
        throw new Error(data.error || 'Save failed');
      }
    } catch (error) {
      console.error('[EditorSettings] Failed to save:', error);
      // Revert cache on error
      return false;
    }
  }

  /**
   * Get current settings from cache
   * @returns {Object} Current settings
   */
  /**
   * ---agentspec
   * what: |
   *   Returns shallow copy of settingsCache object. Checks if editor embedding is enabled via boolean flag.
   *
   * why: |
   *   Shallow copy prevents external mutation of cached settings; boolean check provides simple feature gate.
   *
   * guardrails:
   *   - NOTE: Shallow copy does not protect nested objects from mutation
   *   - ASK USER: Should embedding state be persisted or computed on-demand?
   * ---/agentspec
   */
  function getSettings() {
    return { ...settingsCache };
  }

  /**
   * Check if editor embedding is enabled
   * @returns {boolean} Whether embedding is enabled
   */
  /**
   * ---agentspec
   * what: |
   *   Checks if embedding is enabled by reading CI env var, then DOM checkbox. Returns boolean.
   *
   * why: |
   *   CI environments must disable embedding; fallback to user checkbox preference.
   *
   * guardrails:
   *   - DO NOT enable embedding in CI (CI=1/true/yes disables)
   *   - NOTE: DOM query returns undefined if field missing; treat as falsy
   * ---/agentspec
   */
  function isEmbeddingEnabled() {
    // Check environment variable first (from config)
    try {
      const ci = String(window.CoreUtils?.state?.config?.env?.CI ?? '').toLowerCase();
      if (ci === '1' || ci === 'true' || ci === 'yes') return false; // CI guard

      const fld = document.querySelector('[name="EDITOR_EMBED_ENABLED"]');
      if (fld && fld.type === 'checkbox') return fld.checked;

      const envVal = String(window.CoreUtils?.state?.config?.env?.EDITOR_EMBED_ENABLED ?? '1');
      return envVal === '1' || envVal.toLowerCase() === 'true';
    } catch {
      return settingsCache.enabled;
    }
  }

  /**
   * Update embedding checkbox when settings change
   * @param {boolean} enabled - Whether embedding should be enabled
   */
  /**
   * ---agentspec
   * what: |
   *   Updates checkbox UI element for embedding toggle. Sets checked state based on enabled boolean parameter.
   *
   * why: |
   *   Decouples UI state sync from business logic; single responsibility for DOM mutation.
   *
   * guardrails:
   *   - DO NOT assume checkbox exists; guard with null check already present
   *   - NOTE: Only updates UI; does not persist to server
   * ---/agentspec
   */
  function updateEmbeddingUI(enabled) {
    const checkbox = document.querySelector('[name="EDITOR_EMBED_ENABLED"]');
    if (checkbox && checkbox.type === 'checkbox') {
      checkbox.checked = enabled;
    }
  }

  /**
   * Initialize settings module - load from server on startup
   */
  async function init() {
    console.log('[EditorSettings] Initializing...');
    await loadSettings();
  }

  // Auto-initialize on DOM ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

  // Export public API
  window.EditorSettings = {
    loadSettings,
    saveSettings,
    getSettings,
    isEmbeddingEnabled,
    updateEmbeddingUI,
    init
  };

  console.log('[EditorSettings] Module loaded');
})();
