// Git Hooks - Git hooks installation and status
// Handles git hooks management for the repository
;(function() {
  'use strict';

  // Get shared utilities
  const api = window.CoreUtils?.api || ((p) => `/api${p}`);
  const $ = window.CoreUtils?.$ || ((s) => document.querySelector(s));

  // Refresh hooks installation status
  async function refreshHooksStatus() {
    try {
      const d = await (await fetch(api('/api/git/hooks/status'))).json();
      const el = $('#hooks-status');
      if (el) {
        el.textContent = (d.post_checkout && d.post_commit)
          ? `Installed @ ${d.dir}`
          : 'Not installed';
      }
    } catch {
      const el = $('#hooks-status');
      if (el) el.textContent = 'Status unavailable';
    }
  }

  // Install git hooks
  async function installHooks() {
    try {
      const r = await fetch(api('/api/git/hooks/install'), { method: 'POST' });
      const d = await r.json();
      alert(d.message || 'Hooks installed');
      await refreshHooksStatus();
    } catch (e) {
      alert('Failed to install hooks: ' + e.message);
    }
  }

  // Initialization function called by secrets.js when admin view mounts
  // Does NOT register view - secrets.js handles that
  window.initGitHooks = function() {
    console.log('[git-hooks.js] Initializing git hooks for admin view');
    refreshHooksStatus();
  };

  // Export public API
  window.GitHooks = {
    refreshHooksStatus,
    installHooks
  };

  console.log('[git-hooks.js] Module loaded (coordination with secrets.js for admin view)');
})();
