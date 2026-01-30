import { useState, useEffect } from 'react';
import { useDockerStore } from '@/stores';

export function InfrastructureServices() {
  const { startInfrastructure, stopInfrastructure, pingRedis, loading } = useDockerStore();
  const [qdrantStatus, setQdrantStatus] = useState<'running' | 'stopped' | 'unknown'>('unknown');
  const [redisStatus, setRedisStatus] = useState<'running' | 'stopped' | 'unknown'>('unknown');
  const [prometheusStatus, setPrometheusStatus] = useState<'running' | 'stopped' | 'unknown'>('unknown');
  const [grafanaStatus, setGrafanaStatus] = useState<'running' | 'stopped' | 'unknown'>('unknown');

  useEffect(() => {
    checkInfraStatus();
    const interval = setInterval(checkInfraStatus, 30000);
    return () => clearInterval(interval);
  }, []);

  const checkInfraStatus = async () => {
    // Check Qdrant
    try {
      await fetch('http://127.0.0.1:6333/collections', { mode: 'no-cors' });
      setQdrantStatus('running');
    } catch {
      setQdrantStatus('stopped');
    }

    // Check Redis
    try {
      const result = await pingRedis();
      setRedisStatus(result.success ? 'running' : 'stopped');
    } catch {
      setRedisStatus('stopped');
    }

    // Check Prometheus
    try {
      await fetch('http://127.0.0.1:9090/-/ready', { mode: 'no-cors' });
      setPrometheusStatus('running');
    } catch {
      setPrometheusStatus('stopped');
    }

    // Check Grafana
    try {
      await fetch('http://127.0.0.1:3000/api/health', { mode: 'no-cors' });
      setGrafanaStatus('running');
    } catch {
      setGrafanaStatus('stopped');
    }
  };

  const handleStartInfra = async () => {
    await startInfrastructure();
    setTimeout(checkInfraStatus, 2000);
  };

  const handleStopInfra = async () => {
    await stopInfrastructure();
    setTimeout(checkInfraStatus, 2000);
  };

  const statusColor = (status: string) => {
    if (status === 'running') return 'var(--accent)';
    if (status === 'stopped') return 'var(--err)';
    return 'var(--fg-muted)';
  };

  const statusIcon = (status: string) => {
    if (status === 'running') return '✓';
    if (status === 'stopped') return '✗';
    return '○';
  };

  return (
    <div className="settings-section" style={{ background: 'var(--panel)', borderLeft: '3px solid var(--link)' }}>
      <h3 style={{
        fontSize: '14px',
        marginBottom: '16px',
        color: 'var(--link)',
        display: 'flex',
        alignItems: 'center',
        gap: '8px'
      }}>
        <span style={{
          width: '8px',
          height: '8px',
          borderRadius: '50%',
          background: 'var(--link)',
          boxShadow: '0 0 8px var(--link)'
        }}></span>
        Infrastructure Services
      </h3>

      <div style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))',
        gap: '12px',
        marginBottom: '16px'
      }}>
        <div style={{
          background: 'var(--card-bg)',
          border: `1px solid ${statusColor(qdrantStatus)}`,
          borderRadius: '6px',
          padding: '16px'
        }}>
          <div style={{
            color: 'var(--fg-muted)',
            fontSize: '11px',
            textTransform: 'uppercase',
            marginBottom: '8px'
          }}>
            Qdrant
          </div>
          <div style={{ color: statusColor(qdrantStatus), fontSize: '16px', fontWeight: 600 }}>
            {statusIcon(qdrantStatus)} {qdrantStatus === 'running' ? 'Running' : 'Not Running'}
          </div>
          {qdrantStatus === 'running' && (
            <button
              onClick={() => window.open('http://127.0.0.1:6333/dashboard', '_blank')}
              style={{
                marginTop: '8px',
                fontSize: '10px',
                padding: '4px 8px',
                background: 'var(--bg-elev1)',
                border: '1px solid var(--link)',
                color: 'var(--link)'
              }}
            >
              Open Dashboard
            </button>
          )}
        </div>

        <div style={{
          background: 'var(--card-bg)',
          border: `1px solid ${statusColor(redisStatus)}`,
          borderRadius: '6px',
          padding: '16px'
        }}>
          <div style={{
            color: 'var(--fg-muted)',
            fontSize: '11px',
            textTransform: 'uppercase',
            marginBottom: '8px'
          }}>
            Redis
          </div>
          <div style={{ color: statusColor(redisStatus), fontSize: '16px', fontWeight: 600 }}>
            {statusIcon(redisStatus)} {redisStatus === 'running' ? 'Running' : 'Not Running'}
          </div>
          {redisStatus === 'running' && (
            <button
              onClick={async () => {
                const result = await pingRedis();
                alert(result.success ? '✓ Redis PONG!' : '✗ Redis not responding');
              }}
              style={{
                marginTop: '8px',
                fontSize: '10px',
                padding: '4px 8px',
                background: 'var(--bg-elev1)',
                border: '1px solid var(--link)',
                color: 'var(--link)'
              }}
            >
              Ping Redis
            </button>
          )}
        </div>

        <div style={{
          background: 'var(--card-bg)',
          border: `1px solid ${statusColor(prometheusStatus)}`,
          borderRadius: '6px',
          padding: '16px'
        }}>
          <div style={{
            color: 'var(--fg-muted)',
            fontSize: '11px',
            textTransform: 'uppercase',
            marginBottom: '8px'
          }}>
            Prometheus
          </div>
          <div style={{ color: statusColor(prometheusStatus), fontSize: '16px', fontWeight: 600 }}>
            {statusIcon(prometheusStatus)} {prometheusStatus === 'running' ? 'Running' : 'Not Running'}
          </div>
          {prometheusStatus === 'running' && (
            <button
              onClick={() => window.open('http://127.0.0.1:9090', '_blank')}
              style={{
                marginTop: '8px',
                fontSize: '10px',
                padding: '4px 8px',
                background: 'var(--bg-elev1)',
                border: '1px solid var(--link)',
                color: 'var(--link)'
              }}
            >
              Open UI
            </button>
          )}
        </div>

        <div style={{
          background: 'var(--card-bg)',
          border: `1px solid ${statusColor(grafanaStatus)}`,
          borderRadius: '6px',
          padding: '16px'
        }}>
          <div style={{
            color: 'var(--fg-muted)',
            fontSize: '11px',
            textTransform: 'uppercase',
            marginBottom: '8px'
          }}>
            Grafana
          </div>
          <div style={{ color: statusColor(grafanaStatus), fontSize: '16px', fontWeight: 600 }}>
            {statusIcon(grafanaStatus)} {grafanaStatus === 'running' ? 'Running' : 'Not Running'}
          </div>
          {grafanaStatus === 'running' && (
            <button
              onClick={() => window.open('http://127.0.0.1:3000', '_blank')}
              style={{
                marginTop: '8px',
                fontSize: '10px',
                padding: '4px 8px',
                background: 'var(--bg-elev1)',
                border: '1px solid var(--link)',
                color: 'var(--link)'
              }}
            >
              Open UI
            </button>
          )}
        </div>
      </div>

      <div style={{ display: 'flex', gap: '12px' }}>
        <button
          onClick={handleStartInfra}
          disabled={loading}
          style={{
            flex: 1,
            background: 'var(--accent)',
            color: 'var(--accent-contrast)',
            border: 'none',
            padding: '12px 20px',
            fontSize: '14px',
            fontWeight: 600,
            opacity: loading ? 0.5 : 1
          }}
        >
          {loading ? '⏳ Starting...' : '▶ Start Infrastructure'}
        </button>
        <button
          onClick={handleStopInfra}
          disabled={loading}
          style={{
            flex: 1,
            background: 'var(--err)',
            color: 'white',
            border: 'none',
            padding: '12px 20px',
            fontSize: '14px',
            fontWeight: 600,
            opacity: loading ? 0.5 : 1
          }}
        >
          {loading ? '⏳ Stopping...' : '■ Stop Infrastructure'}
        </button>
      </div>
    </div>
  );
}
