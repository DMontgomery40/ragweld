import { useVSCodeEmbed } from '@/hooks/useVSCodeEmbed';
import { VSCodeSubtabs } from '../VSCode/VSCodeSubtabs';
import { VSCodeSettingsPanel } from '../VSCode/VSCodeSettingsPanel';
import { useUIStore } from '@/stores/useUIStore';

/**
 * VS Code editor tab - embeds VS Code server in iframe
 */
export default function VSCodeTab() {
  const activeSubtab = useUIStore((state) => state.activeSubtab['vscode'] || 'editor');
  const setActiveSubtab = useUIStore((state) => state.setActiveSubtab);
  
  const {
    isHealthy,
    isEnabled,
    iframeUrl,
    statusMessage,
    statusColor,
    copyButtonText,
    isRestarting,
    checkHealth,
    openInWindow,
    copyUrl,
    restart
  } = useVSCodeEmbed();

  const getBadgeStyle = () => {
    return {
      padding: '4px 10px',
      borderRadius: '12px',
      fontSize: '11px',
      fontWeight: 600,
      background: statusColor,
      color: isHealthy ? 'var(--accent-contrast)' : 'var(--fg)'
    };
  };

  const getStatusIcon = () => {
    if (isHealthy) return '●';
    if (!isEnabled) return '○';
    return '●';
  };

  const getBannerMessage = () => {
    if (!isEnabled) {
      return 'Editor is disabled. Enable it in the Misc tab and restart.';
    }
    return `${statusMessage}. Retrying...`;
  };

  const handleSubtabChange = (subtab: string) => {
    if (subtab === 'editor' || subtab === 'editor-settings') {
      setActiveSubtab('vscode', subtab);
    }
  };

  return (
    <div id="tab-vscode" className="tab-content" style={{ padding: 0 }}>
      <VSCodeSubtabs activeSubtab={activeSubtab} onSubtabChange={handleSubtabChange} />
      
      {/* Editor Subtab */}
      <div
        id="tab-vscode-editor"
        className={`section-subtab ${activeSubtab === 'editor' ? 'active' : ''}`}
        style={{ padding: '12px 0' }}
      >
        <div className="settings-section">
          {/* Header */}
          <div
            style={{
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
              marginBottom: '16px'
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
              <h3 style={{ margin: 0 }}>Embedded Code Editor</h3>
              <div id="editor-health-badge" style={getBadgeStyle()}>
                <span id="editor-health-text">{getStatusIcon()} {statusMessage}</span>
              </div>
            </div>
            <div style={{ display: 'flex', gap: '8px' }}>
              <button
                onClick={openInWindow}
                className="small-button"
                style={{
                  background: 'var(--bg-elev2)',
                  color: 'var(--link)',
                  border: '1px solid var(--link)'
                }}
              >
                🗗 Open in Window
              </button>
              <button
                onClick={copyUrl}
                className="small-button"
                style={{
                  background: 'var(--bg-elev2)',
                  color: 'var(--accent)',
                  border: '1px solid var(--accent)'
                }}
              >
                {copyButtonText}
              </button>
              <button
                onClick={restart}
                disabled={isRestarting}
                className="small-button"
                style={{
                  background: 'var(--bg-elev2)',
                  color: 'var(--warn)',
                  border: '1px solid var(--warn)',
                  cursor: isRestarting ? 'not-allowed' : 'pointer',
                  opacity: isRestarting ? 0.6 : 1
                }}
              >
                {isRestarting ? 'Restarting...' : 'Restart'}
              </button>
            </div>
          </div>

          {/* Status Banner (shown when editor is not healthy) */}
          {!isHealthy && (
            <div
              style={{
                display: 'block',
                background: 'var(--bg-elev2)',
                border: '1px solid var(--warn)',
                borderRadius: '6px',
                padding: '16px',
                marginBottom: '16px'
              }}
            >
              <div style={{ display: 'flex', alignItems: 'start', gap: '12px' }}>
                <span style={{ fontSize: '24px' }}>⚠️</span>
                <div style={{ flex: 1 }}>
                  <div style={{ fontWeight: 600, marginBottom: '4px' }}>Editor Unavailable</div>
                  <div style={{ fontSize: '12px', color: 'var(--fg-muted)', marginBottom: '8px' }}>
                    {getBannerMessage()}
                  </div>

                  {/* Troubleshooting steps */}
                  {!isEnabled && (
                    <div style={{ fontSize: '12px', marginTop: '8px' }}>
                      <div style={{ fontWeight: 600, marginBottom: '4px' }}>To enable:</div>
                      <ol style={{ margin: '4px 0', paddingLeft: '20px' }}>
                        <li>Go to the Misc tab</li>
                        <li>Enable the editor setting</li>
                        <li>Click the Restart button above</li>
                      </ol>
                    </div>
                  )}

                  {isEnabled && (
                    <div style={{ fontSize: '12px', marginTop: '8px' }}>
                      <div style={{ fontWeight: 600, marginBottom: '4px' }}>Troubleshooting:</div>
                      <ul style={{ margin: '4px 0 8px 0', paddingLeft: '20px' }}>
                        <li>Try clicking the Restart button above</li>
                        <li>Check if Docker is running</li>
                        <li>Wait a few moments for the service to start</li>
                        <li>Check browser console for detailed error messages</li>
                      </ul>
                      <button
                        onClick={checkHealth}
                        className="small-button"
                        style={{
                          background: 'var(--accent)',
                          color: 'var(--accent-contrast)',
                          border: 'none',
                          padding: '4px 12px',
                          fontSize: '11px'
                        }}
                      >
                        Check Status Now
                      </button>
                    </div>
                  )}
                </div>
              </div>
            </div>
          )}

          {/* Editor Iframe */}
          <div
            id="editor-iframe-container"
            style={{
              position: 'relative',
              width: '100%',
              height: 'calc(100vh - 200px)',
              minHeight: '600px',
              background: 'var(--card-bg)',
              border: '1px solid var(--line)',
              borderRadius: '6px',
              overflow: 'hidden',
              display: iframeUrl ? 'block' : 'none'
            }}
          >
            <iframe
              id="editor-iframe"
              src={iframeUrl || 'about:blank'}
              style={{
                width: '100%',
                height: '100%',
                border: 'none'
              }}
              sandbox="allow-same-origin allow-scripts allow-forms allow-downloads allow-modals allow-popups allow-top-navigation-by-user-activation"
              title="VS Code Editor"
            />
          </div>

          {/* Description */}
          <p className="small" style={{ color: 'var(--fg-muted)', marginTop: '12px' }}>
            Full VS Code experience running in your browser. Changes are saved to the workspace automatically.
          </p>
        </div>
      </div>

      {/* Settings Subtab */}
      <div
        id="tab-vscode-settings"
        className={`section-subtab ${activeSubtab === 'editor-settings' ? 'active' : ''}`}
        style={{ padding: '12px 0' }}
      >
        <VSCodeSettingsPanel />
      </div>
    </div>
  );
}
