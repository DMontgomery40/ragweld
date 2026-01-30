// Commit Metadata (Agent/Session Signing)
// Exposes UI helpers to load/save commit metadata and configure git
;(function() {
  'use strict';

  const api = window.CoreUtils?.api || ((p) => `/api${p}`);
  const $ = window.CoreUtils?.$ || ((s) => document.querySelector(s));

  async function loadCommitMeta() {
    try {
      const d = await (await fetch(api('/api/git/commit-meta'))).json();
      const m = d.meta || {};
      const user = d.git_user || {};

      const setVal = (id, v) => { const el = $(id); if (el) el.value = v ?? ''; };
      const setChk = (id, v) => { const el = $(id); if (el) el.checked = !!v; };

      setVal('#git-agent-name', m.agent_name || user.name || '');
      setVal('#git-agent-email', m.agent_email || user.email || '');
      setVal('#git-chat-session', m.chat_session_id || '');
      setVal('#git-trailer-key', m.trailer_key || 'Chat-Session');
      setChk('#git-set-user', m.set_git_user ?? false);
      setChk('#git-append-trailer', m.append_trailer ?? true);
      setChk('#git-enable-template', m.enable_template ?? false);
      setChk('#git-install-hook', m.install_hook ?? true);

      const status = $('#git-commit-meta-status');
      if (status) status.textContent = 'Loaded';
    } catch (e) {
      const status = $('#git-commit-meta-status');
      if (status) status.textContent = 'Error loading';
      console.error('[CommitMeta] load error:', e);
    }
  }

  async function saveCommitMeta() {
    try {
      const body = {
        agent_name: $('#git-agent-name')?.value || '',
        agent_email: $('#git-agent-email')?.value || '',
        chat_session_id: $('#git-chat-session')?.value || '',
        trailer_key: $('#git-trailer-key')?.value || 'Chat-Session',
        set_git_user: $('#git-set-user')?.checked || false,
        append_trailer: $('#git-append-trailer')?.checked || true,
        enable_template: $('#git-enable-template')?.checked || false,
        install_hook: $('#git-install-hook')?.checked || true,
      };
      const r = await fetch(api('/api/git/commit-meta'), {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body)
      });
      const d = await r.json();
      if (!r.ok || d.error) throw new Error(d.error || 'Failed to save');
      const status = $('#git-commit-meta-status'); if (status) status.textContent = 'Saved';
      alert('Commit metadata saved. New commits will include the session trailer if enabled.');
    } catch (e) {
      const status = $('#git-commit-meta-status'); if (status) status.textContent = 'Save failed';
      alert('Failed to save commit metadata: ' + e.message);
    }
  }

  window.CommitMeta = {
    load: loadCommitMeta,
    save: saveCommitMeta,
  };

  console.log('[CommitMeta] Loaded');
})();

