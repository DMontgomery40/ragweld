// AGRO - Git Integration Subtab Component
// Git hooks and commit metadata configuration

import { useState, useEffect } from 'react';
import { useAPI } from '@/hooks';

export function GitIntegrationSubtab() {
  const { api } = useAPI();
  const [agentName, setAgentName] = useState('');
  const [agentEmail, setAgentEmail] = useState('');
  const [chatSession, setChatSession] = useState('');
  const [trailerKey, setTrailerKey] = useState('Chat-Session');
  const [setGitUser, setSetGitUser] = useState(false);
  const [appendTrailer, setAppendTrailer] = useState(true);
  const [enableTemplate, setEnableTemplate] = useState(false);
  const [installHook, setInstallHook] = useState(true);
  const [hooksStatus, setHooksStatus] = useState('Not checked');


  useEffect(() => {
    loadStatus();
    loadMeta();
  }, []);

  async function loadStatus() {
    try {
      const res = await fetch(api('/git/hooks/status'));
      if (res.ok) {
        const data = await res.json();
        if (data.post_commit && data.post_checkout) {
            setHooksStatus('Installed');
        } else {
            setHooksStatus('Not Installed');
        }
      }
    } catch (e) { console.error(e); }
  }

  async function loadMeta() {
    try {
      const res = await fetch(api('/git/commit-meta'));
      if (res.ok) {
        const data = await res.json();
        if (data.meta) {
            setAgentName(data.meta.agent_name || '');
            setAgentEmail(data.meta.agent_email || '');
            setChatSession(data.meta.chat_session_id || '');
            setTrailerKey(data.meta.trailer_key || 'Chat-Session');
            setSetGitUser(data.meta.set_git_user || false);
            setAppendTrailer(data.meta.append_trailer !== false);
            setEnableTemplate(data.meta.enable_template || false);
            setInstallHook(data.meta.install_hook !== false);
        }
      }
    } catch (e) { console.error(e); }
  }

  async function installGitHooks() {
    try {
        const res = await fetch(api('/git/hooks/install'), { method: 'POST' });
        if (res.ok) {
            setHooksStatus('Installed successfully');
            alert('Git hooks installed successfully');
        } else {
            alert('Failed to install hooks');
        }
    } catch (e) {
        alert('Error installing hooks: ' + e);
    }
  }

  async function saveCommitMetadata() {
    const config = {
      agent_name: agentName,
      agent_email: agentEmail,
      chat_session_id: chatSession,
      trailer_key: trailerKey,
      set_git_user: setGitUser,
      append_trailer: appendTrailer,
      enable_template: enableTemplate,
      install_hook: installHook
    };

    try {
        const res = await fetch(api('/git/commit-meta'), {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(config)
        });
        if (res.ok) {
            alert('Commit metadata saved!');
        } else {
            alert('Failed to save metadata');
        }
    } catch (e) {
        alert('Error saving metadata: ' + e);
    }
  }


  return (
    <div className="settings-section">
      <h2>Git Integration</h2>

      {/* Git Hooks */}
      <div
        style={{
          background: 'var(--bg-elev2)',
          border: '1px solid var(--line)',
          borderRadius: '6px',
          padding: '20px',
          marginBottom: '20px'
        }}
      >
        <h3 style={{ marginTop: 0 }}>Git Hooks (Auto-Index)</h3>
        <p className="small" style={{ marginBottom: '16px' }}>
          Install local git hooks to auto-run BM25 indexing on branch changes and commits.
          Enable it with AUTO_INDEX=1.
        </p>

        <div className="input-row">
          <div className="input-group">
            <label>Status</label>
            <div
              style={{
                padding: '8px',
                background: 'var(--code-bg)',
                border: '1px solid var(--line)',
                borderRadius: '4px',
                fontFamily: 'monospace',
                fontSize: '12px'
              }}
            >
              {hooksStatus}
            </div>
          </div>
          <div className="input-group">
            <label>Install Hooks</label>
            <button
              className="small-button"
              onClick={installGitHooks}
              style={{
                background: 'var(--accent)',
                color: 'var(--accent-contrast)',
                fontWeight: '600'
              }}
            >
              Install
            </button>
          </div>
        </div>

        <div className="input-row">
          <div className="input-group">
            <label>Enable Auto-Index</label>
            <input
              type="text"
              readOnly
              value="export AUTO_INDEX=1"
              onClick={(e) => {
                (e.target as HTMLInputElement).select();
                navigator.clipboard.writeText('export AUTO_INDEX=1');
                alert('Copied to clipboard!');
              }}
              style={{
                width: '100%',
                padding: '8px',
                background: 'var(--code-bg)',
                border: '1px solid var(--line)',
                borderRadius: '4px',
                color: 'var(--fg)',
                fontFamily: 'monospace',
                cursor: 'pointer'
              }}
            />
            <p className="small" style={{ color: 'var(--fg-muted)', marginTop: '4px' }}>
              Click to copy command to clipboard
            </p>
          </div>
        </div>
      </div>

      {/* Commit Metadata */}
      <div
        style={{
          background: 'var(--bg-elev2)',
          border: '1px solid var(--line)',
          borderRadius: '6px',
          padding: '20px',
          marginBottom: '20px'
        }}
      >
        <h3 style={{ marginTop: 0 }}>Commit Metadata (Agent/Session Signing)</h3>
        <p className="small" style={{ marginBottom: '16px' }}>
          Append a Chat Session trailer to every commit and optionally set git user info.
          This helps trace changes to a local chat session ID.
        </p>

        <div className="input-row">
          <div className="input-group">
            <label>Agent Name</label>
            <input
              type="text"
              value={agentName}
              onChange={(e) => setAgentName(e.target.value)}
              placeholder="Codex Agent"
              style={{
                width: '100%',
                padding: '8px',
                background: 'var(--input-bg)',
                border: '1px solid var(--line)',
                borderRadius: '4px',
                color: 'var(--fg)'
              }}
            />
          </div>
          <div className="input-group">
            <label>Agent Email</label>
            <input
              type="email"
              value={agentEmail}
              onChange={(e) => setAgentEmail(e.target.value)}
              placeholder="agent@example.com"
              style={{
                width: '100%',
                padding: '8px',
                background: 'var(--input-bg)',
                border: '1px solid var(--line)',
                borderRadius: '4px',
                color: 'var(--fg)'
              }}
            />
          </div>
        </div>

        <div className="input-row">
          <div className="input-group">
            <label>Chat Session ID</label>
            <input
              type="text"
              value={chatSession}
              onChange={(e) => setChatSession(e.target.value)}
              placeholder="paste your local chat session id"
              style={{
                width: '100%',
                padding: '8px',
                background: 'var(--input-bg)',
                border: '1px solid var(--line)',
                borderRadius: '4px',
                color: 'var(--fg)'
              }}
            />
          </div>
          <div className="input-group">
            <label>Trailer Key</label>
            <input
              type="text"
              value={trailerKey}
              onChange={(e) => setTrailerKey(e.target.value)}
              placeholder="Chat-Session"
              style={{
                width: '100%',
                padding: '8px',
                background: 'var(--input-bg)',
                border: '1px solid var(--line)',
                borderRadius: '4px',
                color: 'var(--fg)'
              }}
            />
          </div>
        </div>

        <div className="input-row">
          <div className="input-group">
            <label style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <input
                type="checkbox"
                checked={setGitUser}
                onChange={(e) => setSetGitUser(e.target.checked)}
              />
              <span>Set git user.name/email</span>
            </label>
          </div>
          <div className="input-group">
            <label style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <input
                type="checkbox"
                checked={appendTrailer}
                onChange={(e) => setAppendTrailer(e.target.checked)}
              />
              <span>Append session trailer via hook</span>
            </label>
          </div>
        </div>

        <div className="input-row">
          <div className="input-group">
            <label style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <input
                type="checkbox"
                checked={enableTemplate}
                onChange={(e) => setEnableTemplate(e.target.checked)}
              />
              <span>Use commit template</span>
            </label>
          </div>
          <div className="input-group">
            <label style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <input
                type="checkbox"
                checked={installHook}
                onChange={(e) => setInstallHook(e.target.checked)}
              />
              <span>Install/refresh prepare-commit-msg hook</span>
            </label>
          </div>
        </div>

        <button
          className="small-button"
          onClick={saveCommitMetadata}
          style={{
            width: '100%',
            background: 'var(--accent)',
            color: 'var(--accent-contrast)',
            fontWeight: '600',
            marginTop: '12px'
          }}
        >
          Save Commit Metadata
        </button>
      </div>
    </div>
  );
}
