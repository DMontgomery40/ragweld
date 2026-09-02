// TriBridRAG - MCP Subtab
// Status of the embedded MCP Streamable HTTP server, its registered tools, and
// a real search probe. Nothing here starts or stops a process: the transport is
// mounted inside the API (config.mcp.enabled / mount_path).

import { useState } from 'react';
import { TooltipIcon } from '@/components/ui/TooltipIcon';
import { StatusIndicator } from '@/components/ui/StatusIndicator';
import { useConfig } from '@/hooks/useConfig';
import { useMCPServer } from '@/hooks/useMCPServer';
import { useRepoStore } from '@/stores/useRepoStore';

export function MCPSubtab() {
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const [question, setQuestion] = useState('');
  const { status, probe, probeQuestion, loading, probing, error, refresh, probeSearch } = useMCPServer();
  const { config } = useConfig();
  const activeRepo = useRepoStore((s) => s.activeRepo);
  // The probe sends no mode or top_k, so it runs on the configured defaults. The card used to
  // name a literal top_k=5 while `mcp.default_top_k` was 20, which is the number the result line
  // then printed (S40).
  const defaultMode = config?.mcp?.default_mode ?? null;
  const defaultTopK = config?.mcp?.default_top_k ?? null;

  const refreshAndStamp = async () => {
    await refresh();
    setLastUpdated(new Date());
  };

  const http = status?.python_http || null;
  // The server owns this string. Assembling `http://{host}:{port}{path}` here advertised
  // plain HTTP on port 80 to operators of an HTTPS-only deployment, because host/port
  // describe the hop the status request arrived on rather than the address an MCP client
  // can reach (M-91). It now comes from `config.mcp.public_base_url`.
  const httpHref = http?.url || null;

  const canProbe = Boolean(activeRepo) && question.trim().length > 0 && !probing;

  const runProbe = async () => {
    if (!activeRepo || !question.trim()) return;
    try {
      await probeSearch(question.trim(), activeRepo);
    } catch {
      // error is surfaced through the hook state
    }
  };

  return (
    <div style={{ padding: '24px' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '14px' }}>
        <span style={{ color: 'var(--accent-text)', fontSize: '8px' }}>●</span>
        <h3 style={{ margin: 0, fontSize: '16px', color: 'var(--fg)', display: 'flex', alignItems: 'center', gap: '8px' }}>
          MCP Server <TooltipIcon name="SYS_STATUS_MCP_SERVERS" />
        </h3>
      </div>

      <p style={{ marginTop: 0, color: 'var(--fg-muted)', fontSize: '13px', lineHeight: '1.6' }}>
        ragweld exposes its retrieval as MCP tools over Streamable HTTP, mounted inside the API process at{' '}
        <span className="mono">config.mcp.mount_path</span>. Point an MCP client at the URL below; there is no separate daemon to
        start. The advertised URL is <span className="mono">config.mcp.public_base_url</span> plus that mount path — set it to
        this deployment&rsquo;s public origin so clients are not sent to an address only the proxy can reach.
      </p>

      {error && (
        <div
          role="alert"
          style={{
            background: 'rgba(255, 107, 107, 0.12)',
            border: '1px solid var(--err)',
            borderRadius: '8px',
            padding: '12px 14px',
            color: 'var(--err)',
            fontSize: '13px',
            marginBottom: '16px',
          }}
          data-testid="mcp-error"
        >
          {error}
        </div>
      )}

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: '12px', marginBottom: '16px' }}>
        <div style={{ background: 'var(--bg-elev1)', border: '1px solid var(--line)', borderRadius: '8px', padding: '14px' }} data-testid="mcp-http-card">
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '10px' }}>
            <div style={{ fontSize: '13px', fontWeight: 700, color: 'var(--fg)' }}>Streamable HTTP</div>
            <StatusIndicator status={loading ? 'loading' : http?.running ? 'online' : 'offline'} showLabel={false} size="sm" pulse />
          </div>
          <div style={{ marginTop: '8px', fontSize: '13px', color: 'var(--fg-muted)', lineHeight: 1.5 }}>
            {http && httpHref ? (
              <>
                <a href={httpHref} target="_blank" rel="noopener noreferrer" style={{ color: 'var(--link)', textDecoration: 'none' }} data-testid="mcp-http-url">
                  {httpHref}
                </a>
                {http.public_base_url_configured === false ? (
                  <div
                    role="alert"
                    data-testid="mcp-public-url-unconfigured"
                    style={{ marginTop: '8px', color: 'var(--err)', fontSize: '12px', lineHeight: 1.5 }}
                  >
                    Public URL not configured — this page reached the API from{' '}
                    <span className="mono">{http.request_host}</span>, but{' '}
                    <span className="mono">config.mcp.public_base_url</span> is still the
                    loopback default, so the URL above names an address no client on that
                    origin can reach. Set{' '}
                    <span className="mono">mcp.public_base_url</span> to{' '}
                    <span className="mono">https://{http.request_host}</span> and add{' '}
                    <span className="mono">{http.request_host}</span> to{' '}
                    <span className="mono">mcp.allowed_hosts</span>.
                  </div>
                ) : http.host_allowed === false ? (
                  <div
                    role="alert"
                    data-testid="mcp-host-not-allowed"
                    style={{ marginTop: '8px', color: 'var(--err)', fontSize: '12px', lineHeight: 1.5 }}
                  >
                    A client using this URL is answered 421: its host is not in{' '}
                    <span className="mono">config.mcp.allowed_hosts</span>, and DNS rebinding
                    protection is on. Add <span className="mono">{new URL(httpHref).host}</span>{' '}
                    there, or turn the protection off deliberately.
                  </div>
                ) : null}
              </>
            ) : (
              <span>disabled (config.mcp.enabled=false) or the Python MCP runtime is not installed</span>
            )}
          </div>
        </div>

        <div style={{ background: 'var(--bg-elev1)', border: '1px solid var(--line)', borderRadius: '8px', padding: '14px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '10px' }}>
            <div style={{ fontSize: '13px', fontWeight: 700, color: 'var(--fg)' }}>Python stdio</div>
            <StatusIndicator status={loading ? 'loading' : status?.python_stdio_available ? 'online' : 'offline'} showLabel={false} size="sm" pulse />
          </div>
          <div style={{ marginTop: '8px', fontSize: '13px', color: 'var(--fg-muted)', lineHeight: 1.5 }}>
            {status?.python_stdio_available ? 'runtime available (client-spawned)' : 'missing (Python MCP runtime not installed)'}
          </div>
        </div>
      </div>

      <div style={{ display: 'flex', gap: '10px', alignItems: 'center', marginBottom: '16px' }}>
        <button
          type="button"
          className="small-button"
          onClick={() => void refreshAndStamp()}
          disabled={loading}
          style={{ background: 'var(--accent)', color: 'var(--accent-contrast)', border: 'none', borderRadius: '6px', padding: '10px 14px', fontSize: '13px', fontWeight: 700, cursor: loading ? 'wait' : 'pointer' }}
        >
          {loading ? 'Refreshing…' : '↻ Refresh'}
        </button>
        <div style={{ fontSize: '12px', color: 'var(--fg-muted)' }}>{lastUpdated ? `Last updated: ${lastUpdated.toLocaleTimeString()}` : '—'}</div>
        <a href="https://modelcontextprotocol.io/specification" target="_blank" rel="noopener noreferrer" style={{ marginLeft: 'auto', fontSize: '12px', color: 'var(--link)', textDecoration: 'none' }}>
          MCP spec ↗
        </a>
      </div>

      <div style={{ background: 'var(--bg-elev1)', border: '1px solid var(--line)', borderRadius: '8px', padding: '14px', marginBottom: '16px' }} data-testid="mcp-tools">
        <div style={{ fontSize: '13px', fontWeight: 800, color: 'var(--fg)', marginBottom: '8px' }}>Registered tools</div>
        {status?.tools?.length ? (
          <ul style={{ margin: 0, paddingLeft: '18px', display: 'grid', gap: '6px' }}>
            {status.tools.map((tool) => (
              <li key={tool.name} style={{ fontSize: '13px', color: 'var(--fg)' }} data-testid={`mcp-tool-${tool.name}`}>
                <span className="mono" style={{ fontWeight: 700 }}>{tool.name}</span>
                {tool.description ? <span style={{ color: 'var(--fg-muted)' }}> — {tool.description}</span> : null}
              </li>
            ))}
          </ul>
        ) : (
          <div style={{ fontSize: '13px', color: 'var(--fg-muted)' }}>
            {loading ? 'Loading…' : 'No tools advertised (the HTTP transport is disabled).'}
          </div>
        )}
      </div>

      {status?.details && status.details.length > 0 && (
        <div style={{ background: 'var(--code-bg)', border: '1px solid var(--line)', borderRadius: '8px', padding: '14px', fontSize: '12.5px', color: 'var(--fg)', whiteSpace: 'pre-wrap', fontFamily: 'var(--font-mono)', marginBottom: '16px' }}>
          {status.details.map((d, idx) => `${idx + 1}. ${d}`).join('\n')}
        </div>
      )}

      <div style={{ background: 'var(--bg-elev1)', border: '1px solid var(--line)', borderRadius: '8px', padding: '14px' }} data-testid="mcp-probe">
        <div style={{ fontSize: '13px', fontWeight: 800, color: 'var(--fg)', marginBottom: '6px' }}>Probe the search tool</div>
        <div style={{ fontSize: '13px', color: 'var(--fg-muted)', marginBottom: '10px' }}>
          Calls the MCP <span className="mono">search</span> tool through a real client session on the mounted transport,
          on this deployment&rsquo;s defaults (
          <span className="mono">mode={defaultMode ?? 'mcp.default_mode'}</span>,{' '}
          <span className="mono">top_k={defaultTopK ?? 'mcp.default_top_k'}</span>), against the active corpus
          {activeRepo ? <> (<span className="mono">{activeRepo}</span>)</> : ' (select a corpus first)'}. Ask a real question about the
          corpus — every query is reranker training signal.
        </div>
        <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
          <input
            type="text"
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && canProbe) void runProbe();
            }}
            placeholder="e.g. How often is the salinity sensor calibrated?"
            aria-label="MCP search probe question"
            data-testid="mcp-probe-question"
            style={{ flex: 1, background: 'var(--input-bg)', border: '1px solid var(--line)', color: 'var(--fg)', padding: '10px 12px', borderRadius: '8px', fontSize: '13px' }}
          />
          <button
            type="button"
            className="small-button"
            onClick={() => void runProbe()}
            disabled={!canProbe}
            data-testid="mcp-probe-run"
            style={{ background: 'var(--link)', color: 'var(--accent-contrast)', fontWeight: 700, padding: '10px 14px' }}
          >
            {probing ? 'Searching…' : 'Run search'}
          </button>
        </div>
        {probe ? (
          <div style={{ marginTop: '12px' }} data-testid="mcp-probe-results">
            <div style={{ fontSize: '12.5px', color: 'var(--fg-muted)', marginBottom: '6px' }}>
              {probe.results?.length ?? 0} result{(probe.results?.length ?? 0) === 1 ? '' : 's'} for “{probeQuestion}” via the
              in-process transport <span className="mono">{probe.transport_url}</span> (the address an MCP client dials is
              above) · tool <span className="mono">{probe.tool}</span> · mode{' '}
              <span className="mono">{probe.mode}</span> · top_k {probe.top_k}
            </div>
            {probe.results?.length ? (
              <ol style={{ margin: 0, paddingLeft: '18px', display: 'grid', gap: '4px' }}>
                {probe.results.map((r, idx) => (
                  <li key={`${r.chunk_id}:${idx}`} style={{ fontSize: '13px', color: 'var(--fg)', fontFamily: 'var(--font-mono)' }}>
                    {r.file_path}:{r.start_line}-{r.end_line}
                    <span style={{ color: 'var(--fg-muted)' }}>
                      {' '}· {r.source} · score {r.score.toFixed(3)}
                    </span>
                  </li>
                ))}
              </ol>
            ) : (
              <div style={{ fontSize: '13px', color: 'var(--fg-muted)' }}>The tool returned no chunks for this question.</div>
            )}
          </div>
        ) : null}
      </div>
    </div>
  );
}
