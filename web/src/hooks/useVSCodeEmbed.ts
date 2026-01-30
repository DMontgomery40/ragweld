import { useState, useEffect, useCallback } from 'react';
import { useAPI } from './useAPI';

interface EditorSettings {
  port: number;
  host: string;
  enabled: boolean;
  embed_enabled: boolean;
  bind?: string;
  image?: string;
  url?: string;
}

const DEFAULT_SETTINGS: EditorSettings = {
  port: 4440,
  host: '127.0.0.1',
  enabled: true,
  embed_enabled: true
};

/**
 * ---agentspec
 * what: |
 *   Custom React hook that manages VS Code embedded editor lifecycle, health checks, and configuration.
 *   Accepts no parameters; uses useAPI() and useState hooks internally.
 *   Returns object with: settings (EditorSettings), iframeUrl (string), isHealthy (boolean), isEnabled (boolean), statusMessage (string), statusColor (string), copyButtonText (string).
 *   Initializes editor with DEFAULT_SETTINGS, performs health checks to set isHealthy state, manages iframe URL generation, and tracks UI feedback states (status messages, button text).
 *   Side effects: calls api.healthCheck() or similar during mount/dependency changes; updates multiple state variables asynchronously.
 *
 * why: |
 *   Encapsulates all VS Code embed state management in a single reusable hook to avoid prop drilling and reduce component complexity.
 *   Separates concerns: settings management, health monitoring, iframe URL handling, and UI feedback are all coordinated in one place.
 *   Allows multiple components to consume editor state without duplicating logic or creating tight coupling to the API layer.
 *
 * guardrails:
 *   - DO NOT expose raw api object to consuming components; always wrap API calls within this hook to maintain abstraction
 *   - ALWAYS initialize all state variables (settings, iframeUrl, isHealthy, isEnabled, statusMessage, statusColor, copyButtonText) before returning to prevent undefined reference errors
 *   - NOTE: Health check logic is not visible in this hook signature; ASK USER whether health checks run on mount, on demand, or on interval to document side effects accurately
 *   - ASK USER: Confirm the dependency array for any useEffect that drives health checks, iframe URL updates, or settings changes; missing dependencies can cause stale state bugs
 *   - ASK USER: Clarify whether statusColor and copyButtonText are derived from isHealthy/isEnabled state or managed independently; if derived, consider computing them instead of storing separately
 * ---/agentspec
 */
export function useVSCodeEmbed() {
  const { api } = useAPI();
  const [settings, setSettings] = useState<EditorSettings>(DEFAULT_SETTINGS);
  const [iframeUrl, setIframeUrl] = useState<string>('');
  const [isHealthy, setIsHealthy] = useState(false);
  const [isEnabled, setIsEnabled] = useState(true);
  const [statusMessage, setStatusMessage] = useState('Checking...');
  const [statusColor, setStatusColor] = useState('var(--fg-muted)');
  const [copyButtonText, setCopyButtonText] = useState('📋 Copy URL');
  const [isRestarting, setIsRestarting] = useState(false);
  const [directUrl, setDirectUrl] = useState<string>('');
  const [probeUrl, setProbeUrl] = useState<string>('');

  const buildProxyUrl = useCallback((s: EditorSettings) => {
    if (s.url && s.url.startsWith('/')) return s.url;
    return '/editor/';
  }, []);

  const loadSettings = useCallback(async () => {
    try {
      const resp = await fetch(api('/api/editor/settings'));
      if (resp.ok) {
        const data = await resp.json();
        const merged: EditorSettings = {
          port: Number(data.port ?? DEFAULT_SETTINGS.port),
          host: String(data.host ?? DEFAULT_SETTINGS.host),
          enabled: data.enabled !== false,
          embed_enabled: data.embed_enabled !== false,
          bind: data.bind,
          image: data.image,
          url: data.url,
        };
        setSettings(merged);
        setIsEnabled(merged.enabled && merged.embed_enabled !== false);
        setIframeUrl(buildProxyUrl(merged));
        return merged;
      }
    } catch (e) {
      console.warn('[useVSCodeEmbed] Failed to load editor settings', e);
    }
    setIsEnabled(false);
    return DEFAULT_SETTINGS;
  }, [api, buildProxyUrl]);

  const checkHealth = useCallback(async () => {
    const s = await loadSettings();
    try {
      const resp = await fetch(api('/health/editor'));
      if (!resp.ok) {
        setIsHealthy(false);
        setStatusMessage('Editor unavailable');
        setStatusColor('var(--warn)');
        return;
      }
      const data = await resp.json();
      const enabled = data.enabled !== undefined ? Boolean(data.enabled) : s.enabled;
      const ok = Boolean(data.ok) && enabled;
      const proxy = data.proxy_url || data.url || buildProxyUrl(s);
      const direct = data.direct_url || directUrl || `http://${s.host || '127.0.0.1'}:${s.port || 4440}/`;
      const best = proxy.startsWith('/editor') ? proxy : direct;

      setIsEnabled(enabled && s.embed_enabled !== false);
      setIsHealthy(ok && s.embed_enabled !== false);
      setIframeUrl(best);
      setDirectUrl(direct);
      setProbeUrl(proxy);
      setStatusMessage(ok ? 'Editor ready' : 'Editor starting');
      setStatusColor(ok ? 'var(--success)' : 'var(--warn)');
    } catch (e) {
      setIsHealthy(false);
      setStatusMessage('Editor check failed');
      setStatusColor('var(--warn)');
    }
  }, [api, buildProxyUrl, loadSettings, directUrl]);

  useEffect(() => {
    void checkHealth();
    const id = setInterval(() => void checkHealth(), 30000);
    return () => clearInterval(id);
  }, [checkHealth]);

  const openInWindow = useCallback(() => {
    const url = directUrl || iframeUrl;
    if (!url) return;
    window.open(url, '_blank', 'noopener,noreferrer');
  }, [iframeUrl, directUrl]);

  const copyUrl = useCallback(async () => {
    try {
      if (iframeUrl) {
        await navigator.clipboard.writeText(directUrl || iframeUrl || probeUrl);
        setCopyButtonText('✓ Copied');
        setTimeout(() => setCopyButtonText('📋 Copy URL'), 1200);
      }
    } catch (e) {
      console.error('[useVSCodeEmbed] Failed to copy URL', e);
      setCopyButtonText('Copy failed');
      setTimeout(() => setCopyButtonText('📋 Copy URL'), 1500);
    }
  }, [iframeUrl, directUrl]);

  const restart = useCallback(async () => {
    setIsRestarting(true);
    try {
      const resp = await fetch(api('/api/editor/restart'), { method: 'POST' });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      setStatusMessage('Restart requested');
    } catch (e) {
      setStatusMessage('Restart failed');
    } finally {
      setIsRestarting(false);
      setTimeout(() => void checkHealth(), 3000);
    }
  }, [api, checkHealth]);

  return {
    isHealthy,
    isEnabled,
    iframeUrl,
    directUrl,
    statusMessage,
    statusColor,
    copyButtonText,
    isRestarting,
    checkHealth,
    openInWindow,
    copyUrl,
    restart,
  };
}
