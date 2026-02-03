// Health Check - System health monitoring
// Handles health status checking and display
;(function() {
  'use strict';

  // Get shared utilities
  const api = window.CoreUtils?.api || ((p) => `/api${p}`);
  const $ = window.CoreUtils?.$ || ((s) => document.querySelector(s));

  // Check system health
  async function checkHealth() {
    try {
      const r = await fetch(api('/health'));
      const d = await r.json();
      const healthEl = $('#health-status');
      if (healthEl) {
        healthEl.textContent = d.ok || d.status === 'healthy'
          ? `OK @ ${d.ts ? new Date(d.ts).toLocaleString() : new Date().toLocaleString()}`
          : 'Not OK';
      }
    } catch (e) {
      const healthEl = $('#health-status');
      if (healthEl) {
        healthEl.textContent = 'Error';
      }
      console.error('[Health] Check failed:', e);
    }
  }

  // Export public API
  window.Health = {
    checkHealth
  };

  console.log('[Health] Loaded');
})();
