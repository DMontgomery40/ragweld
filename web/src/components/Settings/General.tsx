import { useState, useEffect } from 'react';
import { useConfigStore } from '@/stores';
import { ApiKeyStatus } from '@/components/ui/ApiKeyStatus';

export function General() {
  const { config, loadConfig, saveEnv, saving } = useConfigStore();

  // Form state
  const [themeMode, setThemeMode] = useState<'auto' | 'dark' | 'light'>('dark');
  const [edition, setEdition] = useState('enterprise');
  const [threadId, setThreadId] = useState('');
  const [serveHost, setServeHost] = useState('127.0.0.1');
  const [servePort, setServePort] = useState('8012');
  const [openBrowserOnStart, setOpenBrowserOnStart] = useState('On');
  const [autoStartColima, setAutoStartColima] = useState('On');
  const [colimaProfile, setColimaProfile] = useState('default');
  const [agroPath, setAgroPath] = useState('');
  const [langchainTracingV2, setLangchainTracingV2] = useState('On');
  const [langchainProject, setLangchainProject] = useState('agro');
  const [langsmithEndpoint, setLangsmithEndpoint] = useState('https://api.smith.langchain.com');
  const [netlifyDomains, setNetlifyDomains] = useState('');
  const [enableEmbeddedEditor, setEnableEmbeddedEditor] = useState(false);
  const [editorPort, setEditorPort] = useState('4440');
  const [bindMode, setBindMode] = useState('Public (0.0.0.0)');

  const [hasChanges, setHasChanges] = useState(false);

  // Load config values
  useEffect(() => {
    if (!config) {
      loadConfig();
    }
  }, [config, loadConfig]);

  useEffect(() => {
    if (config?.env) {
      setThemeMode((config.env.THEME_MODE as any) || 'dark');
      setEdition(String(config.env.AGRO_EDITION || 'enterprise'));
      setThreadId(String(config.env.THREAD_ID || ''));
      setServeHost(String(config.env.SERVE_HOST || '127.0.0.1'));
      setServePort(String(config.env.SERVE_PORT || '8012'));
      setOpenBrowserOnStart(config.env.OPEN_BROWSER_ON_START ? 'On' : 'Off');
      setAutoStartColima(config.env.AUTO_START_COLIMA ? 'On' : 'Off');
      setColimaProfile(String(config.env.COLIMA_PROFILE || 'default'));
      setAgroPath(String(config.env.AGRO_PATH || ''));
      setLangchainTracingV2(config.env.LANGCHAIN_TRACING_V2 ? 'On' : 'Off');
      setLangchainProject(String(config.env.LANGCHAIN_PROJECT || 'agro'));
      setLangsmithEndpoint(String(config.env.LANGSMITH_ENDPOINT || 'https://api.smith.langchain.com'));
      setNetlifyDomains(String(config.env.NETLIFY_DOMAINS || ''));
      setEnableEmbeddedEditor(Boolean(config.env.ENABLE_EMBEDDED_EDITOR));
      setEditorPort(String(config.env.EDITOR_PORT || '4440'));
      setBindMode(config.env.BIND_MODE === '0.0.0.0' ? 'Public (0.0.0.0)' : 'Local = secure; Public = accessible from network');
    }
  }, [config]);

  const handleSaveSettings = async () => {
    const envUpdates = {
      THEME_MODE: themeMode,
      AGRO_EDITION: edition,
      THREAD_ID: threadId,
      SERVE_HOST: serveHost,
      SERVE_PORT: parseInt(servePort, 10),
      OPEN_BROWSER_ON_START: openBrowserOnStart === 'On',
      AUTO_START_COLIMA: autoStartColima === 'On',
      COLIMA_PROFILE: colimaProfile,
      AGRO_PATH: agroPath,
      LANGCHAIN_TRACING_V2: langchainTracingV2 === 'On',
      LANGCHAIN_PROJECT: langchainProject,
      LANGSMITH_ENDPOINT: langsmithEndpoint,
      NETLIFY_DOMAINS: netlifyDomains,
      ENABLE_EMBEDDED_EDITOR: enableEmbeddedEditor,
      EDITOR_PORT: parseInt(editorPort, 10),
      BIND_MODE: bindMode === 'Public (0.0.0.0)' ? '0.0.0.0' : '127.0.0.1',
    };

    await saveEnv(envUpdates);
    setHasChanges(false);
    alert('Settings saved successfully. Some changes may require a restart.');
  };

  const handleResetToDefaults = () => {
    if (!confirm('Are you sure you want to reset all settings to defaults?')) return;

    setThemeMode('dark');
    setEdition('enterprise');
    setThreadId('');
    setServeHost('127.0.0.1');
    setServePort('8012');
    setOpenBrowserOnStart('On');
    setAutoStartColima('On');
    setColimaProfile('default');
    setAgroPath('');
    setLangchainTracingV2('On');
    setLangchainProject('agro');
    setLangsmithEndpoint('https://api.smith.langchain.com');
    setNetlifyDomains('');
    setEnableEmbeddedEditor(false);
    setEditorPort('4440');
    setBindMode('Public (0.0.0.0)');
    setHasChanges(true);
  };

  const markChanged = () => setHasChanges(true);

  if (!config) {
    return (
      <div style={{ padding: '24px', color: 'var(--fg-muted)' }}>
        Loading configuration...
      </div>
    );
  }

  return (
    <div style={{ padding: '24px' }}>
      {/* Miscellaneous Section */}
      <div
        style={{
          background: 'var(--bg-elev1)',
          border: '1px solid var(--line)',
          borderRadius: '6px',
          padding: '16px',
          marginBottom: '24px',
        }}
      >
        <h3 style={{ margin: '0 0 16px 0', fontSize: '16px', color: 'var(--fg)' }}>
          Miscellaneous
        </h3>

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px' }}>
          <div>
            <label htmlFor="theme-mode" style={{ display: 'block', fontSize: '13px', color: 'var(--fg-muted)', marginBottom: '6px' }}>
              THEME MODE
            </label>
            <select
              id="theme-mode"
              value={themeMode}
              onChange={(e) => { setThemeMode(e.target.value as any); markChanged(); }}
              style={{
                width: '100%',
                background: 'var(--bg-elev2)',
                border: '1px solid var(--line)',
                color: 'var(--fg)',
                padding: '8px 12px',
                borderRadius: '4px',
                fontSize: '14px',
              }}
            >
              <option value="dark">Dark</option>
              <option value="light">Light</option>
              <option value="auto">Auto</option>
            </select>
            <div style={{ fontSize: '11px', color: 'var(--fg-muted)', marginTop: '4px' }}>
              Controls light/dark theme globally. Top bar selector changes it live.
            </div>
          </div>

          <div>
            <label htmlFor="thread-id" style={{ display: 'block', fontSize: '13px', color: 'var(--fg-muted)', marginBottom: '6px' }}>
              THREAD ID
            </label>
            <input
              id="thread-id"
              type="text"
              value={threadId}
              onChange={(e) => { setThreadId(e.target.value); markChanged(); }}
              placeholder="http or cli-chat"
              style={{
                width: '100%',
                background: 'var(--bg-elev2)',
                border: '1px solid var(--line)',
                color: 'var(--fg)',
                padding: '8px 12px',
                borderRadius: '4px',
                fontSize: '14px',
              }}
            />
          </div>

          <div>
            <label htmlFor="edition" style={{ display: 'block', fontSize: '13px', color: 'var(--fg-muted)', marginBottom: '6px' }}>
              EDITION (AGRO_EDITION)
            </label>
            <input
              id="edition"
              type="text"
              value={edition}
              onChange={(e) => { setEdition(e.target.value); markChanged(); }}
              style={{
                width: '100%',
                background: 'var(--bg-elev2)',
                border: '1px solid var(--line)',
                color: 'var(--fg)',
                padding: '8px 12px',
                borderRadius: '4px',
                fontSize: '14px',
              }}
            />
          </div>

          <div>
            <label htmlFor="serve-host" style={{ display: 'block', fontSize: '13px', color: 'var(--fg-muted)', marginBottom: '6px' }}>
              SERVE HOST
            </label>
            <input
              id="serve-host"
              type="text"
              value={serveHost}
              onChange={(e) => { setServeHost(e.target.value); markChanged(); }}
              style={{
                width: '100%',
                background: 'var(--bg-elev2)',
                border: '1px solid var(--line)',
                color: 'var(--fg)',
                padding: '8px 12px',
                borderRadius: '4px',
                fontSize: '14px',
              }}
            />
          </div>

          <div>
            <label htmlFor="serve-port" style={{ display: 'block', fontSize: '13px', color: 'var(--fg-muted)', marginBottom: '6px' }}>
              SERVE PORT
            </label>
            <input
              id="serve-port"
              type="number"
              value={servePort}
              onChange={(e) => { setServePort(e.target.value); markChanged(); }}
              style={{
                width: '100%',
                background: 'var(--bg-elev2)',
                border: '1px solid var(--line)',
                color: 'var(--fg)',
                padding: '8px 12px',
                borderRadius: '4px',
                fontSize: '14px',
              }}
            />
          </div>

          <div>
            <label htmlFor="open-browser" style={{ display: 'block', fontSize: '13px', color: 'var(--fg-muted)', marginBottom: '6px' }}>
              OPEN BROWSER ON START
            </label>
            <select
              id="open-browser"
              value={openBrowserOnStart}
              onChange={(e) => { setOpenBrowserOnStart(e.target.value); markChanged(); }}
              style={{
                width: '100%',
                background: 'var(--bg-elev2)',
                border: '1px solid var(--line)',
                color: 'var(--fg)',
                padding: '8px 12px',
                borderRadius: '4px',
                fontSize: '14px',
              }}
            >
              <option value="On">On</option>
              <option value="Off">Off</option>
            </select>
          </div>

          <div>
            <label htmlFor="auto-start-colima" style={{ display: 'block', fontSize: '13px', color: 'var(--fg-muted)', marginBottom: '6px' }}>
              AUTO-START COLIMA (DOCKER)
            </label>
            <select
              id="auto-start-colima"
              value={autoStartColima}
              onChange={(e) => { setAutoStartColima(e.target.value); markChanged(); }}
              style={{
                width: '100%',
                background: 'var(--bg-elev2)',
                border: '1px solid var(--line)',
                color: 'var(--fg)',
                padding: '8px 12px',
                borderRadius: '4px',
                fontSize: '14px',
              }}
            >
              <option value="On">On</option>
              <option value="Off">Off</option>
            </select>
            <div style={{ fontSize: '11px', color: 'var(--fg-muted)', marginTop: '4px' }}>
              Automatically start Colima Docker runtime on macOS
            </div>
          </div>

          <div>
            <label htmlFor="colima-profile" style={{ display: 'block', fontSize: '13px', color: 'var(--fg-muted)', marginBottom: '6px' }}>
              COLIMA PROFILE
            </label>
            <input
              id="colima-profile"
              type="text"
              value={colimaProfile}
              onChange={(e) => { setColimaProfile(e.target.value); markChanged(); }}
              style={{
                width: '100%',
                background: 'var(--bg-elev2)',
                border: '1px solid var(--line)',
                color: 'var(--fg)',
                padding: '8px 12px',
                borderRadius: '4px',
                fontSize: '14px',
              }}
            />
            <div style={{ fontSize: '11px', color: 'var(--fg-muted)', marginTop: '4px' }}>
              Colima profile name (leave empty for default)
            </div>
          </div>

          <div>
            <label htmlFor="agro-path" style={{ display: 'block', fontSize: '13px', color: 'var(--fg-muted)', marginBottom: '6px' }}>
              AGRO PATH
            </label>
            <input
              id="agro-path"
              type="text"
              value={agroPath}
              onChange={(e) => { setAgroPath(e.target.value); markChanged(); }}
              style={{
                width: '100%',
                background: 'var(--bg-elev2)',
                border: '1px solid var(--line)',
                color: 'var(--fg)',
                padding: '8px 12px',
                borderRadius: '4px',
                fontSize: '14px',
              }}
            />
          </div>

          <div>
            <label htmlFor="langchain-tracing" style={{ display: 'block', fontSize: '13px', color: 'var(--fg-muted)', marginBottom: '6px' }}>
              LANGCHAIN TRACING V2
            </label>
            <select
              id="langchain-tracing"
              value={langchainTracingV2}
              onChange={(e) => { setLangchainTracingV2(e.target.value); markChanged(); }}
              style={{
                width: '100%',
                background: 'var(--bg-elev2)',
                border: '1px solid var(--line)',
                color: 'var(--fg)',
                padding: '8px 12px',
                borderRadius: '4px',
                fontSize: '14px',
              }}
            >
              <option value="On">On</option>
              <option value="Off">Off</option>
            </select>
          </div>

          <div>
            <label htmlFor="langchain-project" style={{ display: 'block', fontSize: '13px', color: 'var(--fg-muted)', marginBottom: '6px' }}>
              LANGCHAIN PROJECT
            </label>
            <input
              id="langchain-project"
              type="text"
              value={langchainProject}
              onChange={(e) => { setLangchainProject(e.target.value); markChanged(); }}
              style={{
                width: '100%',
                background: 'var(--bg-elev2)',
                border: '1px solid var(--line)',
                color: 'var(--fg)',
                padding: '8px 12px',
                borderRadius: '4px',
                fontSize: '14px',
              }}
            />
          </div>

          <div>
            <label htmlFor="langsmith-endpoint" style={{ display: 'block', fontSize: '13px', color: 'var(--fg-muted)', marginBottom: '6px' }}>
              LANGSMITH ENDPOINT
            </label>
            <input
              id="langsmith-endpoint"
              type="text"
              value={langsmithEndpoint}
              onChange={(e) => { setLangsmithEndpoint(e.target.value); markChanged(); }}
              style={{
                width: '100%',
                background: 'var(--bg-elev2)',
                border: '1px solid var(--line)',
                color: 'var(--fg)',
                padding: '8px 12px',
                borderRadius: '4px',
                fontSize: '14px',
              }}
            />
          </div>

          <div>
            <ApiKeyStatus keyName="LANGSMITH_API_KEY" label="LangSmith API Key" />
          </div>

          <div>
            <ApiKeyStatus keyName="LANGSMITH_API_KEY_ALIAS" label="LangSmith API Key (Alias)" />
          </div>

          <div>
            <ApiKeyStatus keyName="NETLIFY_API_KEY" label="Netlify API Key" />
          </div>

          <div>
            <label htmlFor="netlify-domains" style={{ display: 'block', fontSize: '13px', color: 'var(--fg-muted)', marginBottom: '6px' }}>
              NETLIFY DOMAINS
            </label>
            <input
              id="netlify-domains"
              type="text"
              value={netlifyDomains}
              onChange={(e) => { setNetlifyDomains(e.target.value); markChanged(); }}
              style={{
                width: '100%',
                background: 'var(--bg-elev2)',
                border: '1px solid var(--line)',
                color: 'var(--fg)',
                padding: '8px 12px',
                borderRadius: '4px',
                fontSize: '14px',
              }}
            />
          </div>
        </div>
      </div>

      {/* Embedded Editor Section */}
      <div
        style={{
          background: 'var(--bg-elev1)',
          border: '1px solid var(--line)',
          borderRadius: '6px',
          padding: '16px',
          marginBottom: '24px',
        }}
      >
        <h3 style={{ margin: '0 0 16px 0', fontSize: '16px', color: 'var(--fg)' }}>
          Embedded Editor
        </h3>

        <div>
          <label style={{ display: 'flex', alignItems: 'center', marginBottom: '16px', cursor: 'pointer' }}>
            <input
              type="checkbox"
              checked={enableEmbeddedEditor}
              onChange={(e) => { setEnableEmbeddedEditor(e.target.checked); markChanged(); }}
              style={{ marginRight: '8px' }}
            />
            <span style={{ fontSize: '14px', color: 'var(--fg)' }}>
              ENABLE EMBEDDED EDITOR
            </span>
          </label>
          <div style={{ fontSize: '12px', color: 'var(--fg-muted)', marginBottom: '16px' }}>
            Start OpenVSCode Server container on up.sh
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px' }}>
            <div>
              <label htmlFor="editor-port" style={{ display: 'block', fontSize: '13px', color: 'var(--fg-muted)', marginBottom: '6px' }}>
                EDITOR PORT
              </label>
              <input
                id="editor-port"
                type="number"
                value={editorPort}
                onChange={(e) => { setEditorPort(e.target.value); markChanged(); }}
                style={{
                  width: '100%',
                  background: 'var(--bg-elev2)',
                  border: '1px solid var(--line)',
                  color: 'var(--fg)',
                  padding: '8px 12px',
                  borderRadius: '4px',
                  fontSize: '14px',
                }}
              />
              <div style={{ fontSize: '11px', color: 'var(--fg-muted)', marginTop: '4px' }}>
                Preferred port (auto-increments if busy)
              </div>
            </div>

            <div>
              <label htmlFor="bind-mode" style={{ display: 'block', fontSize: '13px', color: 'var(--fg-muted)', marginBottom: '6px' }}>
                BIND MODE
              </label>
              <select
                id="bind-mode"
                value={bindMode}
                onChange={(e) => { setBindMode(e.target.value); markChanged(); }}
                style={{
                  width: '100%',
                  background: 'var(--bg-elev2)',
                  border: '1px solid var(--line)',
                  color: 'var(--fg)',
                  padding: '8px 12px',
                  borderRadius: '4px',
                  fontSize: '14px',
                }}
              >
                <option value="Public (0.0.0.0)">Public (0.0.0.0)</option>
                <option value="Local">Local (127.0.0.1)</option>
              </select>
              <div style={{ fontSize: '11px', color: 'var(--fg-muted)', marginTop: '4px' }}>
                Local = secure; Public = accessible from network
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Action Buttons */}
      <div style={{ display: 'flex', gap: '12px', justifyContent: 'flex-end' }}>
        <button
          onClick={handleResetToDefaults}
          style={{
            background: 'var(--bg-elev2)',
            color: 'var(--fg)',
            border: '1px solid var(--line)',
            padding: '10px 20px',
            borderRadius: '4px',
            fontSize: '14px',
            cursor: 'pointer',
            fontWeight: 500,
          }}
        >
          Reset to Defaults
        </button>

        <button
          onClick={handleSaveSettings}
          disabled={!hasChanges || saving}
          style={{
            background: !hasChanges || saving ? 'var(--bg-elev2)' : 'var(--accent)',
            color: !hasChanges || saving ? 'var(--fg-muted)' : 'var(--accent-contrast)',
            border: 'none',
            padding: '10px 32px',
            borderRadius: '4px',
            fontSize: '14px',
            fontWeight: 600,
            cursor: !hasChanges || saving ? 'not-allowed' : 'pointer',
          }}
        >
          {saving ? 'Saving...' : 'Save Settings'}
        </button>
      </div>
    </div>
  );
}
