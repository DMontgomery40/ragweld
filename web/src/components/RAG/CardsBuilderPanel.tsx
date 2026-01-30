import { useCallback, useEffect, useMemo, useState } from 'react';

type CardsBuilderPanelProps = {
  api: (path: string) => string;
  repos: string[];
  selectedRepo: string;
  onSelectRepo: (repo: string) => void;
  excludeDirs: string;
  onChangeExcludeDirs: (value: string) => void;
  excludePatterns: string;
  onChangeExcludePatterns: (value: string) => void;
  excludeKeywords: string;
  onChangeExcludeKeywords: (value: string) => void;
  cardsMax: number;
  onChangeCardsMax: (value: number) => void;
  enrichEnabled: boolean | string;
  onChangeEnrich: (value: boolean | string) => void;
  onUpdateConfig?: (key: string, value: any) => Promise<void>;
  onError: (message: string) => void;
};

type ProgressPayload = {
  pct?: number;
  total?: number;
  done?: number;
  stage?: string;
  throughput?: string;
  eta_s?: number;
  tip?: string;
  repo?: string;
  models?: {
    embed?: string;
    enrich?: string;
    rerank?: string;
  };
};

type Stage =
  | 'scan'
  | 'chunk'
  | 'summarize'
  | 'sparse'
  | 'write'
  | 'finalize';

const STAGES: Stage[] = ['scan', 'chunk', 'summarize', 'sparse', 'write', 'finalize'];

export function CardsBuilderPanel({
  api,
  repos,
  selectedRepo,
  onSelectRepo,
  excludeDirs,
  onChangeExcludeDirs,
  excludePatterns,
  onChangeExcludePatterns,
  excludeKeywords,
  onChangeExcludeKeywords,
  cardsMax,
  onChangeCardsMax,
  enrichEnabled,
  onChangeEnrich,
  onUpdateConfig,
  onError,
}: CardsBuilderPanelProps) {
  const [modelsInfo, setModelsInfo] = useState<Record<string, string>>({});
  const [jobId, setJobId] = useState<string | null>(null);
  const [eventSource, setEventSource] = useState<EventSource | null>(null);
  const [pollTimer, setPollTimer] = useState<number | null>(null);
  const [progressVisible, setProgressVisible] = useState(false);
  const [progressStatus, setProgressStatus] = useState<'idle' | 'running' | 'success' | 'error'>(
    'idle'
  );
  const [progressData, setProgressData] = useState<ProgressPayload>({ repo: selectedRepo });
  const [statusMessage, setStatusMessage] = useState<string>('');
  const [loading, setLoading] = useState(false);
  const [logsLoading, setLogsLoading] = useState(false);

  const progressPct = progressData.pct ?? 0;
  const progressStage = (progressData.stage || '') as Stage;

  const statsLabel = useMemo(() => {
    const done = progressData.done ?? 0;
    const total = progressData.total ?? 0;
    if (done > 0 || total > 0) {
      return `${done} / ${total} (${progressPct.toFixed(1)}%)`;
    }
    return `${progressPct.toFixed(1)}%`;
  }, [progressData.done, progressData.total, progressPct]);

  const throughputLabel = progressData.throughput ?? '';
  const etaLabel =
    typeof progressData.eta_s === 'number' && progressData.eta_s > 0
      ? `ETA: ${Math.ceil(progressData.eta_s)}s`
      : '';
  const tipLabel = progressData.tip ? `💡 ${progressData.tip}` : '';
  const progressModels = progressData.models ?? modelsInfo;

  const cleanupStreams = useCallback(() => {
    if (eventSource) {
      try {
        eventSource.close();
      } catch {
        // ignore
      }
    }
    if (pollTimer) {
      clearInterval(pollTimer);
    }
    setEventSource(null);
    setPollTimer(null);
  }, [eventSource, pollTimer]);

  useEffect(() => {
    return () => {
      cleanupStreams();
    };
  }, [cleanupStreams]);

  const updateProgress = useCallback((payload: ProgressPayload) => {
    setProgressData((prev) => ({
      ...prev,
      ...payload,
    }));
    if (payload.models) {
      setModelsInfo((prev) => ({
        ...prev,
        ...payload.models,
      }));
    }
  }, []);

  const handleProgressEvent = useCallback(
    (data: ProgressPayload) => {
      updateProgress(data);
    },
    [updateProgress]
  );

  const pollStatus = useCallback(
    (job: string) => {
      const timer = window.setInterval(async () => {
        try {
          const response = await fetch(api(`cards/build/status/${job}`));
          if (!response.ok) return;
          const payload: ProgressPayload & { status?: string; error?: string } =
            await response.json();
          handleProgressEvent(payload);
          if ((payload as any).status === 'done') {
            cleanupStreams();
            setProgressStatus('success');
            setStatusMessage('Cards built successfully');
            window.dispatchEvent(new Event('agro:cards:refresh'));
          } else if ((payload as any).status === 'error') {
            cleanupStreams();
            setProgressStatus('error');
            const message = payload.error || 'Cards build failed';
            setStatusMessage(message);
            onError(message);
          }
        } catch (err) {
          console.error('[CardsBuilderPanel] Polling error:', err);
        }
      }, 1000);
      setPollTimer(timer);
    },
    [api, cleanupStreams, handleProgressEvent, onError]
  );

  const listenToStream = useCallback(
    (job: string) => {
      try {
        const source = new EventSource(api(`cards/build/stream/${job}`));
        source.addEventListener('progress', (event) => {
          try {
            const data = JSON.parse(event.data || '{}');
            handleProgressEvent(data);
          } catch (err) {
            console.error('[CardsBuilderPanel] SSE progress parse error:', err);
          }
        });
        source.addEventListener('done', (event) => {
          cleanupStreams();
          try {
            const data = JSON.parse(event.data || '{}');
            handleProgressEvent(data);
          } catch {
            // ignore
          }
          setProgressStatus('success');
          setStatusMessage('Cards built successfully');
          window.dispatchEvent(new Event('agro:cards:refresh'));
        });
        source.addEventListener('cancelled', () => {
          cleanupStreams();
          setProgressStatus('idle');
          setStatusMessage('Cards build cancelled');
        });
        source.addEventListener('error', () => {
          console.warn('[CardsBuilderPanel] SSE error; falling back to polling');
          cleanupStreams();
          pollStatus(job);
        });
        setEventSource(source);
      } catch (err) {
        console.error('[CardsBuilderPanel] SSE init failed:', err);
        pollStatus(job);
      }
    },
    [api, cleanupStreams, handleProgressEvent, pollStatus]
  );

  const startCardsBuild = useCallback(async () => {
    if (!selectedRepo) {
      onError('Please select a repository first');
      return;
    }
    try {
      setLoading(true);
      setProgressVisible(true);
      setProgressStatus('running');
      setStatusMessage('');
      updateProgress({
        pct: 0,
        done: 0,
        total: 0,
        stage: 'scan',
        repo: selectedRepo,
        tip: 'Starting cards build...',
      });

      const params = new URLSearchParams({
        repo: selectedRepo,
        enrich: enrichEnabled ? '1' : '0',
        exclude_dirs: excludeDirs,
        exclude_patterns: excludePatterns,
        exclude_keywords: excludeKeywords,
        max: String(cardsMax),
      });

      const response = await fetch(api(`cards/build/start?${params.toString()}`), {
        method: 'POST',
      });

      if (response.status === 409) {
        const payload = await response.json();
        const message = payload.detail || 'A cards build is already running.';
        setProgressStatus('error');
        setStatusMessage(message);
        onError(message);
        setProgressVisible(false);
        return;
      }

      if (!response.ok) {
        throw new Error(`Failed to start cards build (${response.status})`);
      }

      const payload = await response.json();
      const newJobId = payload.job_id;
      setJobId(newJobId);
      listenToStream(newJobId);
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to start cards build';
      setProgressStatus('error');
      setStatusMessage(message);
      onError(message);
      setProgressVisible(false);
    } finally {
      setLoading(false);
    }
  }, [
    api,
    cardsMax,
    enrichEnabled,
    excludeDirs,
    excludeKeywords,
    excludePatterns,
    listenToStream,
    onError,
    selectedRepo,
    updateProgress,
  ]);

  const cancelCardsBuild = useCallback(async () => {
    if (!jobId) return;
    try {
      await fetch(api(`cards/build/cancel/${jobId}`), { method: 'POST' });
      cleanupStreams();
      setProgressStatus('idle');
      setStatusMessage('Cards build cancelled');
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to cancel cards build';
      onError(message);
    }
  }, [api, cleanupStreams, jobId, onError]);

  const showBuildLogs = useCallback(async () => {
    try {
      setLogsLoading(true);
      const response = await fetch(api('cards/build/logs'));
      if (!response.ok) {
        throw new Error(`Failed to load logs (${response.status})`);
      }
      const data = await response.json();
      alert(data.content || 'No logs available');
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Unable to load logs';
      onError(message);
    } finally {
      setLogsLoading(false);
    }
  }, [api, onError]);

  const clearProgress = () => {
    cleanupStreams();
    setProgressVisible(false);
    setProgressStatus('idle');
    setStatusMessage('');
    setJobId(null);
    setProgressData({ repo: selectedRepo });
  };

  const highlightClass = (stage: Stage) => {
    const active = progressStage === stage && progressStatus === 'running';
    return {
      color: active ? 'var(--bg)' : 'var(--fg-muted)',
      borderColor: active ? 'var(--ok)' : 'var(--line)',
      background: active ? 'var(--ok)' : 'transparent',
      fontWeight: active ? 600 : 400,
    };
  };

  const borderColor = useMemo(() => {
    if (progressStatus === 'success') return '2px solid var(--ok)';
    if (progressStatus === 'error') return '2px solid var(--err)';
    if (progressStatus === 'running') return '2px solid var(--accent)';
    return '2px solid var(--line)';
  }, [progressStatus]);

  const statusColor = useMemo(() => {
    if (progressStatus === 'success') return 'var(--ok)';
    if (progressStatus === 'error') return 'var(--err)';
    if (progressStatus === 'running') return 'var(--fg)';
    return 'var(--fg-muted)';
  }, [progressStatus]);

  return (
    <>
      {/* Repository Selection */}
      <div className="input-row" style={{ marginBottom: '12px' }}>
        <div className="input-group">
          <label>Repository to Build Cards For</label>
          <select
            id="cards-repo-select"
            value={selectedRepo}
            onChange={(e) => onSelectRepo(e.target.value)}
            style={{ width: '100%' }}
          >
            {repos.length === 0 && <option value="">Loading...</option>}
            {repos.map((repo) => (
              <option key={repo} value={repo}>
                {repo}
              </option>
            ))}
          </select>
        </div>
      </div>

      {/* Filters */}
      <div className="input-row" style={{ marginBottom: '12px' }}>
        <div className="input-group">
          <label>
            Exclude Directories (comma-separated)
            <span className="help-icon" data-tooltip="CARDS_EXCLUDE_DIRS">
              ?
            </span>
          </label>
          <input
            type="text"
            id="cards-exclude-dirs"
            name="CARDS_EXCLUDE_DIRS"
            placeholder="e.g., node_modules, vendor, dist"
            value={excludeDirs}
            onChange={(e) => onChangeExcludeDirs(e.target.value)}
            onBlur={() => onUpdateConfig?.('CARDS_EXCLUDE_DIRS', excludeDirs)}
            style={{ width: '100%' }}
          />
          <p className="small" style={{ color: 'var(--fg-muted)' }}>
            Directories skipped during cards builds. Stored in agro_config.json (CARDS_EXCLUDE_DIRS).
          </p>
        </div>
      </div>

      <div className="input-row" style={{ marginBottom: '12px' }}>
        <div className="input-group">
          <label>
            Exclude Patterns (comma-separated)
            <span className="help-icon" data-tooltip="CARDS_EXCLUDE_PATTERNS">
              ?
            </span>
          </label>
          <input
            type="text"
            id="cards-exclude-patterns"
            name="CARDS_EXCLUDE_PATTERNS"
            placeholder="e.g., .test.js, .spec.ts, .min.js"
            value={excludePatterns}
            onChange={(e) => onChangeExcludePatterns(e.target.value)}
            onBlur={() => onUpdateConfig?.('CARDS_EXCLUDE_PATTERNS', excludePatterns)}
            style={{ width: '100%' }}
          />
          <p className="small" style={{ color: 'var(--fg-muted)' }}>
            File patterns to skip (CARDS_EXCLUDE_PATTERNS).
          </p>
        </div>
      </div>

      <div className="input-row" style={{ marginBottom: '16px' }}>
        <div className="input-group">
          <label>
            Exclude Keywords (comma-separated)
            <span className="help-icon" data-tooltip="CARDS_EXCLUDE_KEYWORDS">
              ?
            </span>
          </label>
          <input
            type="text"
            id="cards-exclude-keywords"
            name="CARDS_EXCLUDE_KEYWORDS"
            placeholder="e.g., deprecated, legacy, TODO"
            value={excludeKeywords}
            onChange={(e) => onChangeExcludeKeywords(e.target.value)}
            onBlur={() => onUpdateConfig?.('CARDS_EXCLUDE_KEYWORDS', excludeKeywords)}
            style={{ width: '100%' }}
          />
          <p className="small" style={{ color: 'var(--fg-muted)' }}>
            Skip chunks containing these keywords (CARDS_EXCLUDE_KEYWORDS).
          </p>
        </div>
      </div>

      {/* Options */}
      <div className="input-row" style={{ marginBottom: '16px', alignItems: 'flex-end' }}>
        <div className="input-group">
          <label>Cards Max</label>
          <input
            type="number"
            id="cards-max"
            name="CARDS_MAX"
            value={cardsMax}
            onChange={(e) => {
              const val = Math.max(10, Number(e.target.value));
              onChangeCardsMax(val);
            }}
            onBlur={() => onUpdateConfig?.('CARDS_MAX', cardsMax)}
            min="10"
            step="10"
            style={{ maxWidth: '160px' }}
          />
          <p className="small" style={{ color: 'var(--fg-muted)' }}>
            Max chunks to process (min: 10, default: 100)
          </p>
        </div>
        <div className="input-group">
          <label>
            <input
              type="checkbox"
              id="cards-enrich-gui"
              name="CARDS_ENRICH"
              checked={enrichEnabled === true || enrichEnabled === '1'}
              onChange={(e) => onChangeEnrich(e.target.checked ? '1' : '0')}
            />{' '}
            Enrich with AI
          </label>
          <p className="small" style={{ color: 'var(--fg-muted)' }}>
            Use LLM for rich semantic cards
          </p>
        </div>
      </div>

      {/* Progress Container */}
      {progressVisible && (
        <div
          id="cards-progress-container"
          style={{
            background: 'var(--card-bg)',
            border: borderColor,
            borderRadius: '8px',
            padding: '16px',
            marginBottom: '16px',
          }}
        >
          <div
            style={{
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
              marginBottom: '12px',
              color: statusColor,
            }}
          >
            <div style={{ fontWeight: 700, fontSize: '16px' }}>
              {progressStatus === 'success'
                ? '✅ Cards Built Successfully'
                : progressStatus === 'error'
                ? '❌ Build Failed'
                : progressStatus === 'running'
                ? '🔄 Building Cards...'
                : 'Ready to Build'}
            </div>
            <button
              onClick={() => setProgressVisible(false)}
              style={{
                background: 'transparent',
                border: 'none',
                color: 'var(--fg-muted)',
                cursor: 'pointer',
                fontSize: '18px',
                padding: '4px',
              }}
            >
              ✕
            </button>
          </div>

          {/* Progress Bar */}
          <div
            style={{
              background: 'var(--bg-elev2)',
              borderRadius: '4px',
              overflow: 'hidden',
              height: '8px',
              marginBottom: '8px',
            }}
          >
            <div
              style={{
                width: `${progressPct}%`,
                background: statusColor,
                height: '100%',
                transition: 'width 0.3s ease',
              }}
            />
          </div>

          {/* Progress Details */}
          <div style={{ display: 'flex', gap: '16px', flexWrap: 'wrap', fontSize: '12px', color: 'var(--fg-muted)' }}>
            <span>{statsLabel}</span>
            {progressStage && <span>Stage: {progressStage}</span>}
            {throughputLabel && <span>{throughputLabel}</span>}
            {etaLabel && <span>{etaLabel}</span>}
          </div>

          {/* Tip if available */}
          {tipLabel && (
            <div style={{ marginTop: '8px', fontSize: '11px', color: 'var(--fg-muted)', fontStyle: 'italic' }}>
              {tipLabel}
            </div>
          )}

          {/* Model info if available */}
          {progressModels && Object.keys(progressModels).length > 0 && (
            <div style={{ marginTop: '8px', fontSize: '10px', color: 'var(--fg-muted)' }}>
              {progressModels.embed && <span style={{ marginRight: '12px' }}>Embed: {progressModels.embed}</span>}
              {progressModels.enrich && <span style={{ marginRight: '12px' }}>Enrich: {progressModels.enrich}</span>}
              {progressModels.rerank && <span>Rerank: {progressModels.rerank}</span>}
            </div>
          )}
        </div>
      )}

      {/* Stage Indicator */}
      {progressVisible && progressStatus === 'running' && (
        <div style={{ display: 'flex', gap: '4px', marginBottom: '16px' }}>
          {STAGES.map((stage) => (
            <div
              key={stage}
              style={{
                flex: 1,
                padding: '8px 4px',
                textAlign: 'center',
                fontSize: '10px',
                fontWeight: 500,
                borderRadius: '4px',
                ...highlightClass(stage),
              }}
            >
              {stage.toUpperCase()}
            </div>
          ))}
        </div>
      )}
    </>
  );
}

