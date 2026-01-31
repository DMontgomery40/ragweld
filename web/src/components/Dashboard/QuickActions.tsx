// AGRO - Dashboard Quick Actions Component
// 6 action buttons for common operations

import { useState, useEffect } from 'react';
import { QuickActionButton } from './QuickActionButton';
import { LiveTerminalPanel } from './LiveTerminalPanel';
import { TerminalService } from '../../services/TerminalService';
import { RepoSwitcherModal } from '../ui/RepoSwitcherModal';
import { useRepoStore } from '@/stores/useRepoStore';
import * as DashAPI from '@/api/dashboard';

const FALLBACK_EVAL_OPTIONS: DashAPI.RerankerOption[] = [
  {
    id: 'baseline-eval',
    backend: 'default',
    label: 'Baseline Eval (current config)',
    description: 'Run evaluation using the active agro_config settings.'
  },
  {
    id: 'multi-query-eval',
    backend: 'multi',
    label: 'Multi‑Query Eval (stress test)',
    description: 'Enable multi-query rewrites with a higher final_k for recall tuning.'
  }
];

const FALLBACK_EVAL_PARAMS: Record<string, { use_multi?: boolean; final_k?: number; sample_limit?: number }> = {
  'baseline-eval': { use_multi: false, final_k: 5, sample_limit: 10 },
  'multi-query-eval': { use_multi: true, final_k: 15, sample_limit: 20 }
};

export function QuickActions() {
  const [terminalVisible, setTerminalVisible] = useState(false);
  const [statusMessage, setStatusMessage] = useState('Ready');
  const [progress, setProgress] = useState(0);
  const [showRepoSwitcher, setShowRepoSwitcher] = useState(false);
  const [showEvalDropdown, setShowEvalDropdown] = useState(false);
  const [evalOptions, setEvalOptions] = useState<DashAPI.RerankerOption[]>([]);
  const [evalLoading, setEvalLoading] = useState(false);
  const [evalError, setEvalError] = useState<string | null>(null);
  
  // Use centralized repo store
  const { activeRepo, switching, loadRepos, initialized, getRepoByName } = useRepoStore();

  // Load repos once on mount if not yet initialized
  useEffect(() => {
    if (!initialized) {
      loadRepos();
    }
  }, [initialized, loadRepos]);

  useEffect(() => {
    if (!showEvalDropdown) {
      return;
    }
    const handleClickOutside = (event: MouseEvent) => {
      const trigger = document.getElementById('dash-eval-trigger');
      const dropdown = document.getElementById('dash-eval-dropdown');
      if (trigger && dropdown && !trigger.contains(event.target as Node) && !dropdown.contains(event.target as Node)) {
        setShowEvalDropdown(false);
      }
    };
    document.addEventListener('click', handleClickOutside);
    return () => {
      document.removeEventListener('click', handleClickOutside);
    };
  }, [showEvalDropdown]);

  const handleGenerateKeywords = async () => {
    setTerminalVisible(true);
    setStatusMessage('Generating keywords...');
    setProgress(0);

    const terminal = (window as any)._dashboardTerminal;
    if (terminal) {
      terminal.setTitle('Generate Keywords');
      terminal.updateProgress(0, 'Initializing...');
      terminal.appendLine('🔄 Generating keywords from indexed content...\n');
    }

    try {
      // Get current repo from URL params or default to agro
      const params = new URLSearchParams(window.location.search);
      const corpusId =
        params.get('corpus') ||
        params.get('repo') ||
        activeRepo ||
        localStorage.getItem('tribrid_active_corpus') ||
        localStorage.getItem('tribrid_active_repo') ||
        'tribrid';

      const response = await fetch('/api/keywords/generate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ corpus_id: corpusId })
      });
      const data = await response.json();
      
      if (response.ok) {
        // Support both new format (count/keywords) and legacy format (total_count)
        const total = data.count ?? data.total_count ?? 0;
        setStatusMessage(`✓ Loaded ${total} keywords from repos.json`);
        setProgress(100);
        if (terminal) {
          terminal.appendLine(`✓ Loaded ${total} keywords from repos.json\n`);
          terminal.updateProgress(100, 'Complete');
        }
      } else {
        setStatusMessage(`✗ Error: ${data.error || 'Unknown'}`);
        if (terminal) {
          terminal.appendLine(`✗ Error: ${data.error}\n`);
        }
      }
    } catch (e) {
      setStatusMessage(`✗ Failed: ${e}`);
      if (terminal) {
        terminal.appendLine(`✗ Error: ${e}\n`);
      }
    }
  };

  const handleChangeRepo = () => {
    // Open the repo switcher modal - proper dropdown UI instead of prompt()
    setShowRepoSwitcher(true);
  };

  const handleRunIndexer = () => {
    runIndexer();
  };

  const runIndexer = async () => {
    setTerminalVisible(true);
    setStatusMessage('Starting indexer...');
    setProgress(0);

    const terminal = (window as any)._dashboardTerminal;
    if (terminal) {
      terminal.setTitle('Run Indexer');
      terminal.clear();
      terminal.appendLine('🚀 Starting indexer...');
    }

    try {
      const corpus = getRepoByName(activeRepo);
      const repoPath = corpus?.path || '';
      if (!activeRepo || !repoPath) {
        throw new Error('Select a corpus with a valid path before indexing');
      }

      const response = await fetch('/api/index/start', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ repo_id: activeRepo, repo_path: repoPath })
      });

      if (!response.ok) {
        const error = await response.text();
        setStatusMessage(`✗ Error: ${error}`);
        if (terminal) {
          terminal.appendLine(`\x1b[31m✗ Failed to start indexer: ${error}\x1b[0m`);
        }
        return;
      }

      setStatusMessage('✓ Indexer started');
      if (terminal) {
        terminal.appendLine('✓ Indexer started, connecting to log stream...');
      }

      // Connect to SSE stream for real logs
      TerminalService.streamOperation('dashboard_indexer', 'index', {
        repo: activeRepo,
        onLine: (line) => {
          if (terminal) {
            terminal.appendLine(line);
          }
        },
        onProgress: (percent, message) => {
          setProgress(percent);
          setStatusMessage(message || `Indexing: ${Math.round(percent)}%`);
          if (terminal) {
            terminal.updateProgress(percent, message);
          }
        },
        onError: (error) => {
          setStatusMessage(`✗ Error: ${error}`);
          if (terminal) {
            terminal.appendLine(`\x1b[31m✗ Error: ${error}\x1b[0m`);
          }
        },
        onComplete: () => {
          setProgress(100);
          setStatusMessage('✓ Indexing complete');
          if (terminal) {
            terminal.updateProgress(100, 'Complete');
            terminal.appendLine('\x1b[32m✓ Indexing complete\x1b[0m');
          }
        }
      });
    } catch (e) {
      setStatusMessage(`✗ Failed: ${e}`);
      if (terminal) {
        terminal.appendLine(`\x1b[31m✗ Error: ${e}\x1b[0m`);
      }
    }
  };

  const handleReloadConfig = async () => {
    setTerminalVisible(true);
    setStatusMessage('Reloading configuration...');

    const terminal = (window as any)._dashboardTerminal;
    if (terminal) {
      terminal.setTitle('Reload Config');
      terminal.appendLine('🔄 Reloading configuration...\n');
    }

    try {
      const response = await fetch('/api/config/reload', { method: 'POST' });
      if (response.ok) {
        setStatusMessage('✓ Config reloaded');
        if (terminal) {
          terminal.appendLine('✓ Configuration reloaded successfully\n');
        }
      }
    } catch (e) {
      setStatusMessage(`✗ Failed: ${e}`);
      if (terminal) {
        terminal.appendLine(`✗ Error: ${e}\n`);
      }
    }
  };

  const handleRunEval = async () => {
    if (showEvalDropdown) {
      setShowEvalDropdown(false);
      return;
    }
    setShowEvalDropdown(true);
    if (evalOptions.length === 0) {
      setEvalOptions(FALLBACK_EVAL_OPTIONS);
    }
    setEvalLoading(true);
    setEvalError(null);
    try {
      const options = await DashAPI.getRerankerOptions();
      if (options.length > 0) {
        setEvalOptions(options);
      } else {
        setEvalOptions(FALLBACK_EVAL_OPTIONS);
      }
    } catch (err) {
      setEvalOptions(FALLBACK_EVAL_OPTIONS);
      setEvalError(
        err instanceof Error
          ? `${err.message} (showing default presets)`
          : 'Failed to load evaluation presets (showing defaults)'
      );
    } finally {
      setEvalLoading(false);
    }
  };

  const handleEvalOptionSelect = async (option: DashAPI.RerankerOption) => {
    setShowEvalDropdown(false);
    setTerminalVisible(true);
    setStatusMessage(`Running eval with ${option.label}`);
    setProgress(0);

    const params = new URLSearchParams(window.location.search);
    const corpusId =
      params.get('corpus') ||
      params.get('repo') ||
      activeRepo ||
      localStorage.getItem('tribrid_active_corpus') ||
      localStorage.getItem('tribrid_active_repo') ||
      'tribrid';

    const terminal = (window as any)._dashboardTerminal;
    if (terminal) {
      terminal.setTitle(`Evaluate (${option.label})`);
      terminal.clear();
      terminal.appendLine(`🔬 Starting evaluation for corpus: ${corpusId}`);
    }

    // Kick off eval run to ensure backend starts processing (non-stream acknowledgement)
    try {
      await fetch('/api/eval/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ corpus_id: corpusId, dataset_id: null, sample_size: null })
      });
    } catch (error) {
      console.warn('Eval run kickoff failed (continuing with stream):', error);
    }

    const preset = FALLBACK_EVAL_PARAMS[option.id] || {};

    TerminalService.streamEvalRun('dashboard_eval', {
      corpus_id: corpusId,
      use_multi: preset.use_multi,
      final_k: preset.final_k,
      sample_limit: preset.sample_limit,
      onLine: (line) => {
        if (terminal) {
          terminal.appendLine(line);
        }
      },
      onProgress: (percent, message) => {
        setProgress(percent);
        setStatusMessage(message || `Eval: ${Math.round(percent)}%`);
        if (terminal) {
          terminal.updateProgress(percent, message || `Eval ${Math.round(percent)}%`);
        }
      },
      onError: (error) => {
        setStatusMessage(`✗ Eval error: ${error}`);
        if (terminal) {
          terminal.appendLine(`\x1b[31m✗ Eval error: ${error}\x1b[0m`);
        }
      },
      onComplete: () => {
        setProgress(100);
        setStatusMessage('✓ Eval complete');
        if (terminal) {
          terminal.updateProgress(100, 'Complete');
          terminal.appendLine('\x1b[32m✓ Evaluation complete\x1b[0m');
        }
      }
    });
  };

  const handleRefreshStatus = () => {
    setStatusMessage('Refreshing status...');
    // Trigger reload of all dashboard data
    window.dispatchEvent(new CustomEvent('dashboard-refresh'));
    setTimeout(() => setStatusMessage('✓ Status refreshed'), 500);
  };

  return (
    <div>
      <h3
        style={{
          fontSize: '14px',
          marginBottom: '16px',
          color: 'var(--warn)',
          display: 'flex',
          alignItems: 'center',
          gap: '8px',
        }}
      >
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"></polygon>
        </svg>
        Quick Actions
      </h3>

      {/* Action Buttons Grid */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '12px', marginBottom: '16px' }}>
        <QuickActionButton
          id="btn-generate-keywords"
          icon="⭐"
          label="Generate Keywords"
          onClick={handleGenerateKeywords}
          dataAction="generate-keywords"
        />
        <QuickActionButton
          id="dash-change-repo"
          icon="📁"
          label={activeRepo ? `Corpus: ${getRepoByName(activeRepo)?.name || activeRepo}` : 'Change Corpus'}
          onClick={handleChangeRepo}
          dataAction="change-repo"
          disabled={switching}
        />
        <QuickActionButton
          id="dash-index-start"
          icon="🔄"
          label="Run Indexer"
          onClick={handleRunIndexer}
          dataAction="index"
        />
        <QuickActionButton
          id="dash-reload-config"
          icon="⚙️"
          label="Reload Config"
          onClick={handleReloadConfig}
          dataAction="reload"
        />

        <QuickActionButton
          id="dash-eval-trigger"
          icon="🧪"
          label="Run Eval"
          onClick={handleRunEval}
          dataAction="eval"
        />

        <QuickActionButton
          id="dash-refresh-status"
          icon="🔄"
          label="Refresh Status"
          onClick={handleRefreshStatus}
          dataAction="refresh"
        />
      </div>

      {showEvalDropdown && (
        <div
          id="dash-eval-dropdown"
          style={{
            background: 'var(--bg-elev2)',
            border: '1px solid var(--line)',
            borderRadius: '8px',
            padding: '12px',
            marginBottom: '16px',
            boxShadow: '0 8px 24px rgba(0, 0, 0, 0.3)'
          }}
        >
          <div style={{ fontSize: '12px', color: 'var(--fg-muted)', marginBottom: '8px' }}>
            Select an evaluation preset to run instantly.
          </div>
          {evalLoading && (
            <div style={{ color: 'var(--fg-muted)', marginBottom: '8px' }}>Loading evaluation presets…</div>
          )}
          {evalError && (
            <div style={{ color: 'var(--err)', marginBottom: '8px' }}>{evalError}</div>
          )}
          {evalOptions.length === 0 ? (
            <div style={{ color: 'var(--fg-muted)' }}>No evaluation presets available.</div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
              {evalOptions.map(option => (
                <button
                  key={option.id}
                  onClick={() => handleEvalOptionSelect(option)}
                  style={{
                    display: 'flex',
                    flexDirection: 'column',
                    alignItems: 'flex-start',
                    padding: '10px 12px',
                    background: 'var(--bg-elev1)',
                    border: '1px solid var(--line)',
                    borderRadius: '6px',
                    cursor: 'pointer',
                    textAlign: 'left'
                  }}
                >
                  <span style={{ fontWeight: 600, color: 'var(--accent)' }}>{option.label}</span>
                  <span style={{ fontSize: '11px', color: 'var(--fg-muted)' }}>{option.description}</span>
                </button>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Status Display */}
      <div
        id="dash-index-status"
        style={{
          background: 'var(--code-bg)',
          border: '1px solid var(--line)',
          borderRadius: '6px',
          padding: '12px',
          fontFamily: "'SF Mono', monospace",
          fontSize: '12px',
          lineHeight: 1.6,
          color: 'var(--fg-muted)',
          minHeight: '48px',
        }}
      >
        {statusMessage}
      </div>

      {/* Progress Bar with Shimmer */}
      <div
        style={{
          marginTop: '12px',
          background: 'var(--card-bg)',
          border: '1px solid var(--line)',
          borderRadius: '4px',
          height: '8px',
          overflow: 'hidden',
          position: 'relative',
        }}
      >
        <div
          id="dash-index-bar"
          style={{
            height: '100%',
            width: `${progress}%`,
            background: 'linear-gradient(90deg, var(--warn) 0%, var(--accent) 100%)',
            transition: 'width 0.3s cubic-bezier(0.4, 0, 0.2, 1), opacity 0.3s ease',
            position: 'relative',
          }}
        >
          {progress > 0 && progress < 100 && (
            <div
              style={{
                position: 'absolute',
                top: 0,
                left: 0,
                height: '100%',
                width: '30%',
                background: 'linear-gradient(90deg, transparent, rgba(255, 255, 255, 0.3), transparent)',
                animation: 'shine 2s infinite',
              }}
            />
          )}
        </div>

        <style>{`
          @keyframes shine {
            0% {
              transform: translateX(-100%);
            }
            100% {
              transform: translateX(400%);
            }
          }
        `}</style>
      </div>

      {/* Live Terminal */}
      <LiveTerminalPanel containerId="dash-operations-terminal" isVisible={terminalVisible} />
      
      {/* Repository Switcher Modal */}
      <RepoSwitcherModal 
        isOpen={showRepoSwitcher}
        onClose={() => setShowRepoSwitcher(false)}
      />
    </div>
  );
}
