import React, { useState, useEffect, useCallback } from 'react';
import type { CardsBuildOptions, CardsBuildStatus } from '@web/types/cards';
import { useAPI } from '@/hooks/useAPI';

interface BuilderProps {
  onBuildComplete?: () => void;
  repos?: string[];
  defaultRepo?: string;
}

export function Builder({ onBuildComplete, repos = ['agro'], defaultRepo = 'agro' }: BuilderProps) {
  const { api } = useAPI();
  const [repo, setRepo] = useState(defaultRepo);
  const [enrich, setEnrich] = useState(true);
  const [excludeDirs, setExcludeDirs] = useState('');
  const [excludePatterns, setExcludePatterns] = useState('');
  const [excludeKeywords, setExcludeKeywords] = useState('');
  const [isBuilding, setIsBuilding] = useState(false);
  const [jobId, setJobId] = useState<string | null>(null);
  const [progress, setProgress] = useState<CardsBuildStatus | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const loadDefaults = async () => {
      try {
        const response = await fetch(api('config'));
        if (!response.ok) {
          console.warn('[Cards.Builder] Config fetch returned', response.status);
          return;
        }
        const data = await response.json();
        const env = data.env || {};
        setExcludeDirs(env.CARDS_EXCLUDE_DIRS || '');
        setExcludePatterns(env.CARDS_EXCLUDE_PATTERNS || '');
        setExcludeKeywords(env.CARDS_EXCLUDE_KEYWORDS || '');
      } catch (err) {
        console.warn('[Cards.Builder] Failed to load defaults:', err);
      }
    };
    loadDefaults();
  }, [api]);

  const startBuild = useCallback(async () => {
    try {
      setIsBuilding(true);
      setError(null);
      setProgress({
        status: 'running',
        stage: 'scan',
        total: 0,
        done: 0,
        pct: 0,
        tip: 'Starting cards build...',
        repo
      });

      const params = new URLSearchParams({
        repo,
        enrich: enrich ? '1' : '0',
        exclude_dirs: excludeDirs,
        exclude_patterns: excludePatterns,
        exclude_keywords: excludeKeywords
      });

      const response = await fetch(api(`/api/cards/build/start?${params}`), {
        method: 'POST'
      });

      if (response.status === 409) {
        const data = await response.json();
        throw new Error(data.detail || 'Job already running');
      }

      if (!response.ok) {
        throw new Error(`Failed to start build: ${response.status}`);
      }

      const data = await response.json();
      setJobId(data.job_id);

      // Start progress monitoring
      monitorProgress(data.job_id);
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Unknown error';
      setError(message);
      setIsBuilding(false);
      console.error('[Builder] Start build error:', err);
    }
  }, [api, repo, enrich, excludeDirs, excludePatterns, excludeKeywords]);

  const monitorProgress = useCallback(async (id: string) => {
    try {
      const eventSource = new EventSource(api(`/api/cards/build/stream/${id}`));

      eventSource.addEventListener('progress', (event) => {
        try {
          const data: CardsBuildStatus = JSON.parse(event.data || '{}');
          setProgress(data);
        } catch (err) {
          console.error('[Builder] Progress parse error:', err);
        }
      });

      eventSource.addEventListener('done', (event) => {
        try {
          const data: CardsBuildStatus = JSON.parse(event.data || '{}');
          setProgress({ ...data, status: 'done' });
          setIsBuilding(false);
          eventSource.close();
          if (onBuildComplete) {
            onBuildComplete();
          }
        } catch (err) {
          console.error('[Builder] Done event error:', err);
        }
      });

      eventSource.addEventListener('error', () => {
        console.log('[Builder] SSE error, falling back to polling');
        eventSource.close();
        pollProgress(id);
      });

      eventSource.addEventListener('cancelled', () => {
        setIsBuilding(false);
        setProgress({ status: 'cancelled', stage: 'scan', total: 0, done: 0, pct: 0 });
        eventSource.close();
      });
    } catch (err) {
      console.error('[Builder] Monitor error:', err);
      pollProgress(id);
    }
  }, [api, onBuildComplete]);

  const pollProgress = useCallback(async (id: string) => {
    const interval = setInterval(async () => {
      try {
        const response = await fetch(api(`/api/cards/build/status/${id}`));
        const data: CardsBuildStatus = await response.json();
        setProgress(data);

        if (data.status === 'done') {
          setIsBuilding(false);
          clearInterval(interval);
          if (onBuildComplete) {
            onBuildComplete();
          }
        }

        if (data.status === 'error') {
          setIsBuilding(false);
          setError(data.error || 'Build failed');
          clearInterval(interval);
        }
      } catch (err) {
        console.error('[Builder] Poll error:', err);
      }
    }, 1000);

    return () => clearInterval(interval);
  }, [api, onBuildComplete]);

  const cancelBuild = useCallback(async () => {
    if (!jobId) return;

    try {
      await fetch(api(`/api/cards/build/cancel/${jobId}`), {
        method: 'POST'
      });
      setIsBuilding(false);
      setProgress(null);
    } catch (err) {
      console.error('[Builder] Cancel error:', err);
    }
  }, [api, jobId]);

  return (
    <div style={{ padding: '16px' }}>
      <div style={{ marginBottom: '24px' }}>
        <h3 style={{ margin: '0 0 16px 0', fontSize: '18px', fontWeight: 600 }}>
          Build Cards
        </h3>

        <div style={{ display: 'grid', gap: '12px', maxWidth: '600px' }}>
          <div>
            <label style={{ display: 'block', marginBottom: '4px', fontSize: '13px', fontWeight: 500 }}>
              Repository
            </label>
            <select
              value={repo}
              onChange={(e) => setRepo(e.target.value)}
              disabled={isBuilding}
              style={{
                width: '100%',
                padding: '8px',
                borderRadius: '4px',
                border: '1px solid var(--line)',
                background: 'var(--bg-elev1)',
                color: 'var(--fg)'
              }}
            >
              {repos.map((r) => (
                <option key={r} value={r}>{r}</option>
              ))}
            </select>
          </div>

          <div>
            <label style={{ display: 'flex', alignItems: 'center', fontSize: '13px', cursor: 'pointer' }}>
              <input
                type="checkbox"
                checked={enrich}
                onChange={(e) => setEnrich(e.target.checked)}
                disabled={isBuilding}
                style={{ marginRight: '8px' }}
              />
              Enrich with AI summaries
            </label>
          </div>

          <div>
            <label style={{ display: 'block', marginBottom: '4px', fontSize: '13px', fontWeight: 500 }}>
              Exclude Directories (comma-separated)
            </label>
            <input
              type="text"
              value={excludeDirs}
              onChange={(e) => setExcludeDirs(e.target.value)}
              disabled={isBuilding}
              placeholder="node_modules,dist,build"
              style={{
                width: '100%',
                padding: '8px',
                borderRadius: '4px',
                border: '1px solid var(--line)',
                background: 'var(--bg-elev1)',
                color: 'var(--fg)'
              }}
            />
          </div>

          <div>
            <label style={{ display: 'block', marginBottom: '4px', fontSize: '13px', fontWeight: 500 }}>
              Exclude Patterns (comma-separated)
            </label>
            <input
              type="text"
              value={excludePatterns}
              onChange={(e) => setExcludePatterns(e.target.value)}
              disabled={isBuilding}
              placeholder="*.test.js,*.spec.ts"
              style={{
                width: '100%',
                padding: '8px',
                borderRadius: '4px',
                border: '1px solid var(--line)',
                background: 'var(--bg-elev1)',
                color: 'var(--fg)'
              }}
            />
          </div>

          <div style={{ display: 'flex', gap: '8px', marginTop: '8px' }}>
            <button
              onClick={startBuild}
              disabled={isBuilding}
              style={{
                padding: '10px 20px',
                borderRadius: '6px',
                border: 'none',
                background: isBuilding ? 'var(--fg-muted)' : 'var(--accent)',
                color: 'white',
                fontWeight: 600,
                cursor: isBuilding ? 'not-allowed' : 'pointer',
                fontSize: '14px'
              }}
            >
              {isBuilding ? 'Building...' : '⚡ Build Cards'}
            </button>

            {isBuilding && (
              <button
                onClick={cancelBuild}
                style={{
                  padding: '10px 20px',
                  borderRadius: '6px',
                  border: '1px solid var(--line)',
                  background: 'var(--bg-elev1)',
                  color: 'var(--fg)',
                  fontWeight: 600,
                  cursor: 'pointer',
                  fontSize: '14px'
                }}
              >
                Cancel
              </button>
            )}
          </div>
        </div>
      </div>

      {error && (
        <div style={{
          padding: '12px',
          borderRadius: '6px',
          background: 'var(--err-bg)',
          border: '1px solid var(--err)',
          color: 'var(--err)',
          fontSize: '13px',
          marginBottom: '16px'
        }}>
          ❌ {error}
        </div>
      )}

      {progress && isBuilding && (
        <BuildProgress progress={progress} />
      )}
    </div>
  );
}

interface BuildProgressProps {
  progress: CardsBuildStatus;
}

function BuildProgress({ progress }: BuildProgressProps) {
  const stages = ['scan', 'chunk', 'summarize', 'sparse', 'write', 'finalize'];

  return (
    <div style={{
      padding: '16px',
      borderRadius: '8px',
      border: '2px solid var(--accent)',
      background: 'var(--bg-elev1)'
    }}>
      <div style={{ marginBottom: '12px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '8px' }}>
          <span style={{ fontSize: '14px', fontWeight: 600 }}>⚡ Building Cards...</span>
          <span style={{ fontSize: '13px', color: 'var(--fg-muted)' }}>
            {progress.done} / {progress.total} ({progress.pct.toFixed(1)}%)
          </span>
        </div>

        <div style={{
          width: '100%',
          height: '8px',
          background: 'var(--bg-elev2)',
          borderRadius: '4px',
          overflow: 'hidden'
        }}>
          <div style={{
            width: `${progress.pct}%`,
            height: '100%',
            background: 'var(--accent)',
            transition: 'width 0.3s ease'
          }} />
        </div>
      </div>

      <div style={{ display: 'flex', gap: '8px', marginBottom: '12px', flexWrap: 'wrap' }}>
        {stages.map((stage) => (
          <div
            key={stage}
            style={{
              padding: '4px 12px',
              borderRadius: '4px',
              fontSize: '11px',
              fontWeight: progress.stage === stage ? 600 : 400,
              border: `1px solid ${progress.stage === stage ? 'var(--ok)' : 'var(--line)'}`,
              background: progress.stage === stage ? 'var(--ok)' : 'transparent',
              color: progress.stage === stage ? 'var(--fg)' : 'var(--fg-muted)'
            }}
          >
            {stage}
          </div>
        ))}
      </div>

      {progress.tip && (
        <div style={{ fontSize: '12px', color: 'var(--fg-muted)', marginTop: '8px' }}>
          💡 {progress.tip}
        </div>
      )}

      {progress.throughput && (
        <div style={{ fontSize: '12px', color: 'var(--fg-muted)', marginTop: '4px' }}>
          Throughput: {progress.throughput}
        </div>
      )}

      {progress.eta_s !== undefined && progress.eta_s > 0 && (
        <div style={{ fontSize: '12px', color: 'var(--fg-muted)', marginTop: '4px' }}>
          ETA: {progress.eta_s}s
        </div>
      )}
    </div>
  );
}
