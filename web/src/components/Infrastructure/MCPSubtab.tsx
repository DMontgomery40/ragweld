// AGRO - MCP Subtab Component
// MCP Server connection and configuration
// MCP_API_KEY is configured in .env only - never written programmatically

import { useState, useEffect, useMemo } from 'react';
import { TooltipIcon } from '@/components/ui/TooltipIcon';
import { ApiKeyStatus } from '@/components/ui/ApiKeyStatus';
import { useAPI } from '@/hooks/useAPI';
import { useConfig, useConfigField } from '@/hooks';

interface MCPServer {
  name: string;
  url: string;
  status: 'connected' | 'disconnected' | 'unknown';
}

/**
 * ---agentspec
 * what: |
 *   React component that manages Model Context Protocol (MCP) server configuration and testing.
 *   Accepts user input for MCP HTTP host/port/path via controlled form inputs (config-backed fields).
 *   Maintains a list of MCPServer objects with name, url, and status fields; initializes with a default localhost server.
 *   Returns JSX rendering a subtab UI with server list, input fields, test/save buttons, and result display.
 *   Side effects: Updates component state on user input; triggers async operations (test connection, save config) that set loading states and display results.
 *   Edge cases: Handles unknown server status on mount; manages loading states during async operations; displays test results or errors in testResult field.
 *
 * why: |
 *   Encapsulates MCP server management in a reusable React component following hooks-based patterns (useState for local state).
 *   Separates concerns: form input handling, server list management, and async operations (test/save) are distinct state slices.
 *   Allows users to configure multiple MCP servers and validate connectivity before deployment without leaving the UI.
 *
 * guardrails:
 *   - DO NOT store sensitive API keys in component state long-term; consider moving to secure credential storage (e.g., environment variables or encrypted store) before production
 *   - ALWAYS validate host/port/path values before attempting connection test to avoid malformed requests
 *   - NOTE: MCP HTTP config is store-backed; only transient UI state uses useState
 *   - ASK USER: Confirm whether MCPServer list should persist across sessions (requires localStorage or backend persistence) or reset on component unmount
 *   - DO NOT expose apiKey in console logs, error messages, or UI output; sanitize all debug output to prevent credential leakage
 * ---/agentspec
 */
export function MCPSubtab() {
  const { api } = useAPI();
  const { patchSection } = useConfig();
  const [mcpHttpHost, setMcpHttpHost] = useConfigField<string>('MCP_HTTP_HOST', '127.0.0.1');
  const [mcpHttpPort, setMcpHttpPort] = useConfigField<number>('MCP_HTTP_PORT', 8013);
  const [mcpHttpPath, setMcpHttpPath] = useConfigField<string>('MCP_HTTP_PATH', '/mcp');

  const serverUrl = useMemo(() => {
    const host = mcpHttpHost || '127.0.0.1';
    const port = Number(mcpHttpPort) || 8013;
    const rawPath = mcpHttpPath || '/mcp';
    const path = rawPath.startsWith('/') ? rawPath : `/${rawPath}`;
    return `http://${host}:${port}${path}`;
  }, [mcpHttpHost, mcpHttpPort, mcpHttpPath]);

  const [servers, setServers] = useState<MCPServer[]>(() => [
    { name: 'MCP HTTP Server', url: serverUrl, status: 'unknown' }
  ]);
  // apiKey is in .env only - not stored in React state
  const [testResult, setTestResult] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [actionMessage, setActionMessage] = useState<string | null>(null);

  useEffect(() => {
    checkMCPStatus();
  }, [api]);

  useEffect(() => {
    setServers((prev) => prev.map((server) => ({ ...server, url: serverUrl })));
  }, [serverUrl]);

  async function checkMCPStatus() {
    try {
      const response = await fetch(api('/mcp/http/status'));
      const data = await response.json();
      const running = !!data.running;
      setServers(prev => prev.map(s => ({
        ...s,
        url: data.url || s.url,
        status: running ? 'connected' : 'disconnected'
      })));
    } catch (error) {
      setServers(prev => prev.map(s => ({
        ...s,
        status: 'disconnected'
      })));
    }
  }

  async function testConnection() {
    setTestResult('Testing connection...');
    try {
      const response = await fetch(api('/mcp/http/status'));
      const data = await response.json();
      const running = !!data.running;
      if (running) setTestResult(`Connected! Host: ${data.host} Port: ${data.port} Path: ${data.path}`);
      else setTestResult(`Not running (Host: ${data.host} Port: ${data.port} Path: ${data.path})`);
    } catch (error: any) {
      setTestResult(`Connection failed: ${error.message}`);
    }
  }

  async function startMCPServer() {
    setIsLoading(true);
    setActionMessage('Starting MCP HTTP Server...');
    try {
      const response = await fetch(api('/mcp/http/start'), { method: 'POST' });
      const data = await response.json();
      if (data.success) {
        setActionMessage('MCP HTTP Server started successfully on port 8013');
        await checkMCPStatus();
      } else {
        setActionMessage(`Failed to start MCP server: ${data.error || 'Unknown error'}`);
      }
    } catch (error: any) {
      setActionMessage(`Error starting MCP server: ${error.message}`);
    } finally {
      setIsLoading(false);
      setTimeout(() => setActionMessage(null), 3000);
    }
  }

  async function stopMCPServer() {
    setIsLoading(true);
    setActionMessage('Stopping MCP HTTP Server...');
    try {
      const response = await fetch(api('/mcp/http/stop'), { method: 'POST' });
      const data = await response.json();
      if (data.success) {
        setActionMessage('MCP HTTP Server stopped successfully');
        await checkMCPStatus();
      } else {
        setActionMessage(`Failed to stop MCP server: ${data.error || 'Unknown error'}`);
      }
    } catch (error: any) {
      setActionMessage(`Error stopping MCP server: ${error.message}`);
    } finally {
      setIsLoading(false);
      setTimeout(() => setActionMessage(null), 3000);
    }
  }

  async function restartMCPServer() {
    setIsLoading(true);
    setActionMessage('Restarting MCP HTTP Server...');
    try {
      const response = await fetch(api('/mcp/http/restart'), { method: 'POST' });
      const data = await response.json();
      if (data.success) {
        setActionMessage('MCP HTTP Server restarted successfully');
        await checkMCPStatus();
      } else {
        setActionMessage(`Failed to restart MCP server: ${data.error || 'Unknown error'}`);
      }
    } catch (error: any) {
      setActionMessage(`Error restarting MCP server: ${error.message}`);
    } finally {
      setIsLoading(false);
      setTimeout(() => setActionMessage(null), 3000);
    }
  }

  async function saveMCPSettings() {
    setIsSaving(true);
    setActionMessage('Saving MCP settings...');
    try {
      // MCP settings not yet in Pydantic config - use generation section's mcp model field
      await patchSection('generation', {
        gen_model_mcp: `http://${mcpHttpHost}:${mcpHttpPort}${mcpHttpPath}`,
      });

      // API key must be configured in .env file directly - never saved via GUI
      setActionMessage('MCP settings saved! MCP_API_KEY must be configured in .env file. Restart the MCP server for changes to take effect.');
    } catch (error: unknown) {
      const message = error instanceof Error ? error.message : 'Unknown error';
      setActionMessage(`Error saving MCP settings: ${message}`);
    } finally {
      setIsSaving(false);
      setTimeout(() => setActionMessage(null), 5000);
    }
  }

  /**
   * ---agentspec
   * what: |
   *   Maps connection status strings to visual indicators (color and icon).
   *   Takes a status string parameter ('connected', 'disconnected', or other).
   *   Returns a CSS custom property string for statusColor (accent/err/fg-muted) or a Unicode circle character for statusIcon (filled/hollow/default).
   *   statusColor handles three cases: 'connected' → accent color, 'disconnected' → error color, anything else → muted foreground.
   *   statusIcon handles two cases: 'connected' → filled circle (●), 'disconnected' → hollow circle (○), anything else → returns undefined.
   *   No side effects; pure functions that depend only on input parameter.
   *
   * why: |
   *   Separates presentation logic (color/icon mapping) from component rendering to keep UI state consistent across the application.
   *   Using CSS custom properties (var(--accent), var(--err), var(--fg-muted)) allows theme changes to propagate without code modification.
   *   Unicode circle characters provide lightweight, accessible status indicators without requiring icon libraries or assets.
   *
   * guardrails:
   *   - DO NOT hardcode hex colors or RGB values; always use CSS custom properties (var(--*)) to maintain theme consistency
   *   - ALWAYS handle the default case (unrecognized status strings) gracefully; currently returns muted color or undefined icon, which is safe but should be documented in calling components
   *   - NOTE: statusIcon returns undefined for unrecognized statuses; calling code must handle undefined or provide a fallback
   *   - ASK USER: Before adding new status values, confirm the desired color and icon representation and whether they should map to existing CSS variables or new ones
   * ---/agentspec
   */
  const statusColor = (status: string) => {
    if (status === 'connected') return 'var(--accent)';
    if (status === 'disconnected') return 'var(--err)';
    return 'var(--fg-muted)';
  };

  /**
   * ---agentspec
   * what: |
   *   Returns a single-character icon representing connection status as a visual indicator.
   *   Takes a status string parameter ('connected', 'disconnected', or any other value).
   *   Returns '●' (filled circle) for 'connected', '○' (empty circle) for 'disconnected', or '?' (question mark) for unknown/unrecognized status values.
   *   No side effects; pure function with no external dependencies or state mutations.
   *   Handles edge cases: null/undefined status defaults to '?', case-sensitive matching (e.g., 'Connected' returns '?').
   *
   * why: |
   *   Centralizes status-to-icon mapping logic to avoid duplication across UI components and ensure consistent visual representation.
   *   Uses semantic Unicode characters (filled vs. empty circles) to provide immediate visual feedback without text labels.
   *   Separates presentation logic from rendering, making it testable and reusable across different component contexts.
   *
   * guardrails:
   *   - DO NOT add conditional rendering or JSX here; this must remain a pure utility function that returns only a string
   *   - ALWAYS handle the unknown case with '?' to prevent silent failures when unexpected status values are passed
   *   - NOTE: Status matching is case-sensitive; 'Connected' and 'connected' are treated differently (returns '?')
   *   - ASK USER: Before adding new status values, confirm the icon representation and whether case-insensitivity should be implemented
   * ---/agentspec
   */
  const statusIcon = (status: string) => {
    if (status === 'connected') return '●';
    if (status === 'disconnected') return '○';
    return '?';
  };

  return (
    <div className="settings-section">
      {/* Action message */}
      {actionMessage && (
        <div style={{
          padding: '12px',
          background: 'var(--bg-elev2)',
          border: '1px solid var(--line)',
          borderRadius: '6px',
          marginBottom: '16px',
          fontSize: '12px',
          color: 'var(--fg)'
        }}>
          {actionMessage}
        </div>
      )}

      <h2>MCP Server Connection Status</h2>

      {/* Server List */}
      <div style={{ marginBottom: '24px' }}>
        {servers.map((server, idx) => (
          <div
            key={idx}
            style={{
              background: 'var(--card-bg)',
              border: '1px solid var(--line)',
              borderRadius: '6px',
              padding: '16px',
              marginBottom: '12px'
            }}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
              <div style={{ fontWeight: '600', color: 'var(--fg)' }}>{server.name}</div>
              <div style={{ fontSize: '11px', color: statusColor(server.status) }}>
                {statusIcon(server.status)} {server.status.toUpperCase()}
              </div>
            </div>
            <div style={{ fontSize: '12px', color: 'var(--fg-muted)', fontFamily: 'monospace', marginBottom: '8px' }}>
              {server.url}
            </div>
            <div style={{ display: 'flex', gap: '8px' }}>
              <button
                className="small-button"
                onClick={checkMCPStatus}
                style={{
                  flex: '1',
                  background: 'var(--bg-elev2)',
                  color: 'var(--link)',
                  border: '1px solid var(--link)'
                }}
              >
                Check Status
              </button>
              {server.status === 'disconnected' && (
                <button
                  className="small-button"
                  onClick={startMCPServer}
                  disabled={isLoading}
                  style={{
                    flex: '1',
                    background: 'var(--bg-elev2)',
                    color: 'var(--accent)',
                    border: '1px solid var(--accent)'
                  }}
                >
                  {isLoading ? 'Starting...' : 'Start Server'}
                </button>
              )}
              {server.status === 'connected' && (
                <>
                  <button
                    className="small-button"
                    onClick={stopMCPServer}
                    disabled={isLoading}
                    style={{
                      flex: '1',
                      background: 'var(--bg-elev2)',
                      color: 'var(--err)',
                      border: '1px solid var(--err)'
                    }}
                  >
                    {isLoading ? 'Stopping...' : 'Stop Server'}
                  </button>
                  <button
                    className="small-button"
                    onClick={restartMCPServer}
                    disabled={isLoading}
                    style={{
                      flex: '1',
                      background: 'var(--bg-elev2)',
                      color: 'var(--warn)',
                      border: '1px solid var(--warn)'
                    }}
                  >
                    {isLoading ? 'Restarting...' : 'Restart'}
                  </button>
                </>
              )}
            </div>
          </div>
        ))}
      </div>

      {/* Configuration Form */}
      <h3>MCP Server Configuration</h3>
      <div style={{ marginBottom: '16px' }}>
        <div className="input-row">
          <div className="input-group">
            <label>
              MCP HTTP Host
              <TooltipIcon name="MCP_HTTP_HOST" />
            </label>
            <input
              type="text"
              value={mcpHttpHost}
              onChange={(e) => setMcpHttpHost(e.target.value)}
              placeholder="127.0.0.1"
              style={{
                width: '100%',
                padding: '8px',
                background: 'var(--input-bg)',
                border: '1px solid var(--line)',
                borderRadius: '4px',
                color: 'var(--fg)'
              }}
            />
            <p className="small" style={{ color: 'var(--fg-muted)', marginTop: '4px' }}>
              Bind address for the MCP HTTP server
            </p>
          </div>
          <div className="input-group">
            <label>
              MCP HTTP Port
              <TooltipIcon name="MCP_HTTP_PORT" />
            </label>
            <input
              type="number"
              min={1}
              max={65535}
              value={mcpHttpPort}
              onChange={(e) => setMcpHttpPort(Number(e.target.value) || 8013)}
              placeholder="8013"
              style={{
                width: '100%',
                padding: '8px',
                background: 'var(--input-bg)',
                border: '1px solid var(--line)',
                borderRadius: '4px',
                color: 'var(--fg)'
              }}
            />
            <p className="small" style={{ color: 'var(--fg-muted)', marginTop: '4px' }}>
              Port for the MCP HTTP server
            </p>
          </div>
        </div>

        <div className="input-row">
          <div className="input-group">
            <label>
              MCP HTTP Path
              <TooltipIcon name="MCP_HTTP_PATH" />
            </label>
            <input
              type="text"
              value={mcpHttpPath}
              onChange={(e) => setMcpHttpPath(e.target.value)}
              placeholder="/mcp"
              style={{
                width: '100%',
                padding: '8px',
                background: 'var(--input-bg)',
                border: '1px solid var(--line)',
                borderRadius: '4px',
                color: 'var(--fg)'
              }}
            />
            <p className="small" style={{ color: 'var(--fg-muted)', marginTop: '4px' }}>
              Endpoint URL: {serverUrl}
            </p>
          </div>
        </div>

        <div className="input-row">
          <div className="input-group">
            <ApiKeyStatus keyName="MCP_API_KEY" label="MCP API Key" />
          </div>
        </div>

        <div style={{ display: 'flex', gap: '8px', marginTop: '16px' }}>
          <button
            className="small-button"
            onClick={testConnection}
            style={{
              flex: '1',
              background: 'var(--link)',
              color: 'var(--accent-contrast)',
              fontWeight: '600',
              padding: '10px'
            }}
          >
            Test Connection
          </button>
          <button
            className="small-button"
            onClick={saveMCPSettings}
            disabled={isSaving}
            style={{
              flex: '1',
              background: 'var(--accent)',
              color: 'var(--accent-contrast)',
              fontWeight: '600',
              padding: '10px'
            }}
          >
            {isSaving ? 'Saving...' : 'Save Settings'}
          </button>
        </div>

        {testResult && (
          <div
            style={{
              marginTop: '12px',
              padding: '12px',
              background: 'var(--code-bg)',
              border: '1px solid var(--line)',
              borderRadius: '4px',
              fontSize: '12px',
              color: 'var(--fg)',
              fontFamily: 'monospace'
            }}
          >
            {testResult}
          </div>
        )}
      </div>

      {/* Documentation */}
      <div
        style={{
          marginTop: '24px',
          padding: '16px',
          background: 'var(--bg-elev2)',
          border: '1px solid var(--line)',
          borderRadius: '6px'
        }}
      >
        <h4 style={{ marginTop: 0 }}>About MCP Servers</h4>
        <p style={{ fontSize: '12px', color: 'var(--fg-muted)', lineHeight: '1.6' }}>
          Model Context Protocol (MCP) servers provide a standardized way to connect AI assistants
          to external tools and data sources. The MCP HTTP server exposes RAG search and other
          functionality via HTTP endpoints.
        </p>
        <ul style={{ fontSize: '12px', color: 'var(--fg-muted)', lineHeight: '1.6' }}>
          <li>Default endpoint: http://127.0.0.1:8013/mcp</li>
          <li>Configurable via MCP_HTTP_HOST, MCP_HTTP_PORT, MCP_HTTP_PATH environment variables</li>
          <li>No authentication required for local development</li>
        </ul>
      </div>
    </div>
  );
}
