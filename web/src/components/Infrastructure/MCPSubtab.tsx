// TriBridRAG - MCP Subtab
// Status + guidance for inbound MCP transports (stdio now; HTTP later).

import { useMemo, useState } from 'react';
import { TooltipIcon } from '@/components/ui/TooltipIcon';
import { StatusIndicator } from '@/components/ui/StatusIndicator';
import type { MCPHTTPTransportStatus } from '@/types/generated';
import { useMCPServer } from '@/hooks/useMCPServer';

type TransportRow = {
  key: string;
  label: string;
  status: 'online' | 'offline' | 'loading' | 'idle';
  summary: string;
  href?: string;
};

function buildHttpSummary(t: MCPHTTPTransportStatus): { summary: string; href: string } {
  const rawPath = String(t.path || '').trim();
  const path = !rawPath ? '' : rawPath.startsWith('/') ? rawPath : `/${rawPath}`;
  const href = `http://${t.host}:${t.port}${path}`;
  const summary = `${t.running ? 'running' : 'stopped'} • ${t.host}:${t.port}${path || ''}`;
  return { summary, href };
}

export function MCPSubtab() {
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const { status, httpStatus, stdioTestResult, loading, error, refresh, startHttp, stopHttp, restartHttp, testStdio } = useMCPServer();
 
  // Keep a human timestamp in this component for UX
  const refreshAndStamp = async () => {
    await refresh();
    setLastUpdated(new Date());
  };

  const rows: TransportRow[] = useMemo(() => {
    const out: TransportRow[] = [];

    const stdioAvail = Boolean(status?.python_stdio_available);
    out.push({
      key: 'py-stdio',
      label: 'Python stdio',
      status: loading ? 'loading' : stdioAvail ? 'online' : 'offline',
      summary: stdioAvail ? 'available (client-spawned)' : 'missing (Python MCP runtime not installed)',
    });

    const pyHttp = status?.python_http || null;
    if (pyHttp) {
      const { summary, href } = buildHttpSummary(pyHttp);
      out.push({
        key: 'py-http',
        label: 'Python HTTP',
        status: loading ? 'loading' : pyHttp.running ? 'online' : 'offline',
        summary,
        href,
      });
    } else {
      out.push({
        key: 'py-http',
        label: 'Python HTTP',
        status: loading ? 'loading' : 'idle',
        summary: 'not implemented',
      });
    }

    const nodeHttp = status?.node_http || null;
    if (nodeHttp) {
      const { summary, href } = buildHttpSummary(nodeHttp);
      out.push({
        key: 'node-http',
        label: 'Node HTTP',
        status: loading ? 'loading' : nodeHttp.running ? 'online' : 'offline',
        summary,
        href,
      });
    } else {
      out.push({
        key: 'node-http',
        label: 'Node HTTP',
        status: loading ? 'loading' : 'idle',
        summary: 'not implemented',
      });
    }

    return out;
  }, [status, loading]);

  return (
    <div style={{ padding: '24px' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '14px' }}>
        <span style={{ color: 'var(--accent)', fontSize: '8px' }}>●</span>
        <h3
          style={{
            margin: 0,
            fontSize: '16px',
            color: 'var(--fg)',
            display: 'flex',
            alignItems: 'center',
            gap: '8px',
          }}
        >
          MCP Servers <TooltipIcon name="SYS_STATUS_MCP_SERVERS" />
        </h3>
      </div>

      <p style={{ marginTop: 0, color: 'var(--fg-muted)', fontSize: '12px', lineHeight: '1.6' }}>
        TriBridRAG exposes MCP (Model Context Protocol) functionality via inbound transports. In this build, the expected
        default is <span className="mono">py-stdio</span> (stdio, client-spawned). HTTP transports will appear here when
        implemented.
      </p>

      {error && (
        <div
          style={{
            background: 'rgba(255, 107, 107, 0.12)',
            border: '1px solid var(--err)',
            borderRadius: '8px',
            padding: '12px 14px',
            color: 'var(--err)',
            fontSize: '12px',
            marginBottom: '16px',
          }}
        >
          Failed to load MCP status: {error}
        </div>
      )}

      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))',
          gap: '12px',
          marginBottom: '16px',
        }}
      >
        {rows.map((row) => (
          <div
            key={row.key}
            style={{
              background: 'var(--bg-elev1)',
              border: '1px solid var(--line)',
              borderRadius: '8px',
              padding: '14px',
            }}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '10px' }}>
              <div style={{ fontSize: '13px', fontWeight: 700, color: 'var(--fg)' }}>{row.label}</div>
              <StatusIndicator status={row.status} showLabel={false} size="sm" pulse />
            </div>
            <div style={{ marginTop: '8px', fontSize: '12px', color: 'var(--fg-muted)', lineHeight: 1.5 }}>
              {row.href ? (
                <a href={row.href} target="_blank" rel="noopener noreferrer" style={{ color: 'var(--link)', textDecoration: 'none' }}>
                  {row.summary}
                </a>
              ) : (
                <span>{row.summary}</span>
              )}
            </div>
          </div>
        ))}
      </div>

      <div style={{ display: 'flex', gap: '10px', alignItems: 'center', marginBottom: '16px' }}>
        <button
          type="button"
          className="small-button"
          onClick={() => void refreshAndStamp()}
          disabled={loading}
          style={{
            background: 'var(--accent)',
            color: 'var(--accent-contrast)',
            border: 'none',
            borderRadius: '6px',
            padding: '10px 14px',
            fontSize: '12px',
            fontWeight: 700,
            cursor: loading ? 'wait' : 'pointer',
          }}
        >
          {loading ? 'Refreshing…' : '↻ Refresh'}
        </button>
        <div style={{ fontSize: '11px', color: 'var(--fg-muted)' }}>
          {lastUpdated ? `Last updated: ${lastUpdated.toLocaleTimeString()}` : '—'}
        </div>
        <a
          href="https://github.com/modelcontextprotocol/specification"
          target="_blank"
          rel="noopener noreferrer"
          style={{ marginLeft: 'auto', fontSize: '11px', color: 'var(--link)', textDecoration: 'none' }}
        >
          MCP spec ↗
        </a>
      </div>

      {status?.details && status.details.length > 0 && (
        <div
          style={{
            background: 'var(--code-bg)',
            border: '1px solid var(--line)',
            borderRadius: '8px',
            padding: '14px',
            fontSize: '12px',
            color: 'var(--fg)',
            whiteSpace: 'pre-wrap',
            fontFamily: 'var(--font-mono)',
          }}
        >
          {status.details.map((d, idx) => `${idx + 1}. ${d}`).join('\n')}
        </div>
      )}

      <div style={{ marginTop: '22px', display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
        <div
          style={{
            background: 'var(--bg-elev1)',
            border: '1px solid var(--line)',
            borderRadius: '8px',
            padding: '14px',
          }}
        >
          <div style={{ fontSize: '13px', fontWeight: 800, color: 'var(--fg)', marginBottom: '8px' }}>
            MCP HTTP server controls
          </div>
          <div style={{ fontSize: '12px', color: 'var(--fg-muted)', marginBottom: '10px' }}>
            Start/stop the embedded Streamable HTTP transport (if compiled in).
          </div>
          <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
            <button className="small-button" onClick={() => void startHttp()} disabled={loading} style={{ background: 'var(--accent)', color: 'var(--accent-contrast)', fontWeight: 700 }}>
              Start
            </button>
            <button className="small-button" onClick={() => void stopHttp()} disabled={loading} style={{ background: 'transparent', border: '1px solid var(--err)', color: 'var(--err)', fontWeight: 700 }}>
              Stop
            </button>
            <button className="small-button" onClick={() => void restartHttp()} disabled={loading} style={{ background: 'var(--bg-elev2)', border: '1px solid var(--line)', color: 'var(--fg)', fontWeight: 700 }}>
              Restart
            </button>
            <button className="small-button" onClick={() => void refreshAndStamp()} disabled={loading} style={{ background: 'transparent', border: '1px solid var(--line)', color: 'var(--fg-muted)', fontWeight: 700 }}>
              Check
            </button>
          </div>
          <div style={{ marginTop: '10px', fontSize: '12px', color: 'var(--fg-muted)', fontFamily: 'var(--font-mono)', whiteSpace: 'pre-wrap' }}>
            {httpStatus
              ? `${httpStatus.running ? '✓ running' : '✗ stopped'} • ${String(httpStatus.host || '0.0.0.0')}:${String(httpStatus.port || '—')}${String(httpStatus.path || '')}`
              : 'HTTP status unavailable'}
          </div>
        </div>

        <div
          style={{
            background: 'var(--bg-elev1)',
            border: '1px solid var(--line)',
            borderRadius: '8px',
            padding: '14px',
          }}
        >
          <div style={{ fontSize: '13px', fontWeight: 800, color: 'var(--fg)', marginBottom: '8px' }}>
            stdio MCP test
          </div>
          <div style={{ fontSize: '12px', color: 'var(--fg-muted)', marginBottom: '10px' }}>
            Verifies the stdio runtime can spawn and list tools.
          </div>
          <button className="small-button" onClick={() => void testStdio()} disabled={loading} style={{ background: 'var(--link)', color: 'var(--accent-contrast)', fontWeight: 700 }}>
            {loading ? 'Testing…' : 'Run test'}
          </button>
          <pre
            style={{
              marginTop: '10px',
              background: 'var(--code-bg)',
              border: '1px solid var(--line)',
              borderRadius: '8px',
              padding: '12px',
              fontSize: '11px',
              color: 'var(--fg)',
              whiteSpace: 'pre-wrap',
              minHeight: '74px',
            }}
          >
            {stdioTestResult ? JSON.stringify(stdioTestResult, null, 2) : '—'}
          </pre>
        </div>
      </div>
    </div>
  );
}
