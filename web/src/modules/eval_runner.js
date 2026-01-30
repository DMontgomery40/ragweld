// Evaluation Runner
// Handles running full evaluation suite and displaying results

let evalResults = null;
let evalPollingInterval = null;

// Defaults for settings
const DEFAULT_GOLDEN = 'data/golden.json';
const DEFAULT_BASELINE = 'data/evals/eval_baseline.json';

async function loadEvalSettings() {
    try {
        const r = await fetch('/api/config');
        const cfg = await r.json();
        const env = (cfg && cfg.env) || {};
        const golden = env.GOLDEN_PATH || DEFAULT_GOLDEN;
        const baseline = env.BASELINE_PATH || DEFAULT_BASELINE;
        const gp = document.getElementById('eval-golden-path');
        const bp = document.getElementById('eval-baseline-path');
        if (gp) gp.value = golden;
        if (bp) bp.value = baseline;
    } catch (e) {
        console.warn('[eval_runner] loadEvalSettings failed', e);
        const gp = document.getElementById('eval-golden-path');
        const bp = document.getElementById('eval-baseline-path');
        if (gp && !gp.value) gp.value = DEFAULT_GOLDEN;
        if (bp && !bp.value) bp.value = DEFAULT_BASELINE;
    }
}

async function saveEvalSettings() {
    const btn = document.getElementById('btn-eval-save-settings');
    if (btn) { btn.disabled = true; btn.textContent = 'Saving...'; }
    try {
        const gp = document.getElementById('eval-golden-path')?.value?.trim() || DEFAULT_GOLDEN;
        const bp = document.getElementById('eval-baseline-path')?.value?.trim() || DEFAULT_BASELINE;
        const payload = { env: { GOLDEN_PATH: gp, BASELINE_PATH: bp }, repos: [] };
        const r = await fetch('/api/config', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
        if (!r.ok) throw new Error('Config update failed');
        await fetch('/api/env/reload', { method: 'POST' }).catch(() => {});
        showToast('✓ Eval settings saved', 'success');
    } catch (e) {
        console.error('Failed to save eval settings:', e);
        showToast('Failed to save eval settings', 'error');
    } finally {
        if (btn) { btn.disabled = false; btn.textContent = 'Save Eval Settings'; }
    }
}

// Run full evaluation
async function runEvaluation() {
    const useMulti = document.getElementById('eval-use-multi').value === '1';
    const finalK = parseInt(document.getElementById('eval-final-k').value) || 5;

    const btn = document.getElementById('btn-eval-run');
    btn.disabled = true;
    btn.textContent = 'Starting...';

    try {
        const response = await fetch('/api/eval/run', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ use_multi: useMulti, final_k: finalK })
        });

        const data = await response.json();

        if (data.ok) {
            showEvalProgress();
            startPolling();
        } else {
            throw new Error(data.error || 'Failed to start evaluation');
        }
    } catch (error) {
        console.error('Failed to start evaluation:', error);
        const msg = window.ErrorHelpers ? window.ErrorHelpers.createAlertError('Failed to start evaluation', {
            message: error.message,
            causes: [
                'No test dataset available to evaluate',
                'Backend evaluation service not running',
                'Insufficient API quota (LLM provider)',
                'RAG database or indexes are missing',
                'LLM model not configured properly'
            ],
            fixes: [
                'Create a test dataset in Data > Test Sets first',
                'Check Infrastructure tab - verify backend is running',
                'Verify API credentials and quota in Settings',
                'Run Data > Indexing to build vector indexes',
                'Configure LLM model in Settings > API Configuration'
            ],
            links: [
                ['Qdrant Vector Database', 'https://qdrant.tech/documentation/concepts/collections/']
            ]
        }) : ('Failed to start evaluation: ' + error.message);
        alert(msg);
        btn.disabled = false;
        btn.textContent = 'Run Full Evaluation';
    }
}

// Show progress UI
/**
 * ---agentspec
 * what: |
 *   Displays evaluation progress UI. Shows progress bar, hides results/comparison panels, sets status text to "Initializing..." and width to 0%.
 *
 * why: |
 *   Centralizes UI state transitions for eval workflow; prevents inconsistent visibility states.
 *
 * guardrails:
 *   - DO NOT call before eval starts; assumes DOM elements exist
 *   - NOTE: Depends on window.UXFeedback; incomplete initialization check
 * ---/agentspec
 */
function showEvalProgress() {
    document.getElementById('eval-progress').style.display = 'block';
    document.getElementById('eval-results').style.display = 'none';
    document.getElementById('eval-comparison').style.display = 'none';
    document.getElementById('eval-status').textContent = 'Initializing...';
    document.getElementById('eval-progress-bar').style.width = '0%';

    // Initialize UXFeedback progress bar
    if (window.UXFeedback) {
        window.UXFeedback.progress.show('evaluation', {
            message: 'Initializing evaluation...',
            initialPercent: 0,
            container: '#eval-progress'
        });
    }
}

// Start polling for status
/**
 * ---agentspec
 * what: |
 *   Polls /api/eval/status endpoint at fixed interval. Clears prior interval, fetches JSON status, checks running flag.
 *
 * why: |
 *   Interval-based polling for simple state synchronization without WebSocket overhead.
 *
 * guardrails:
 *   - DO NOT poll without clearing prior interval; prevents interval stack-up
 *   - NOTE: No backoff on failure; will retry indefinitely
 *   - ASK USER: Should failed polls trigger exponential backoff or circuit breaker?
 * ---/agentspec
 */
function startPolling() {
    if (evalPollingInterval) clearInterval(evalPollingInterval);

    evalPollingInterval = setInterval(async () => {
        try {
            const response = await fetch('/api/eval/status');
            const status = await response.json();

            if (status.running) {
                const progress = status.total > 0 ? (status.progress / status.total * 100) : 10;
                document.getElementById('eval-progress-bar').style.width = progress + '%';
                document.getElementById('eval-status').textContent =
                    `Running... ${status.progress}/${status.total} questions`;

                // Update UXFeedback progress bar
                if (window.UXFeedback) {
                    const remaining = status.total - status.progress;
                    const eta = remaining > 0 ? `~${remaining} questions remaining` : null;
                    window.UXFeedback.progress.update('evaluation', {
                        percent: progress,
                        message: `Evaluating ${status.progress}/${status.total} questions`,
                        eta: eta
                    });
                }
            } else {
                // Evaluation finished
                clearInterval(evalPollingInterval);
                evalPollingInterval = null;

                // Complete UXFeedback progress bar
                if (window.UXFeedback) {
                    window.UXFeedback.progress.update('evaluation', {
                        percent: 100,
                        message: 'Evaluation complete!'
                    });
                    setTimeout(() => {
                        window.UXFeedback.progress.hide('evaluation');
                    }, 1500);
                }

                await loadEvalResults();
            }
        } catch (error) {
            console.error('Failed to poll status:', error);

            // Hide progress bar on error
            if (window.UXFeedback) {
                window.UXFeedback.progress.hide('evaluation');
            }
        }
    }, 2000); // poll every 2 seconds during evaluation
}

// Load evaluation results
async function loadEvalResults() {
    try {
        const response = await fetch('/api/eval/results');
        const data = await response.json();

        if (data.error) {
            throw new Error(data.error);
        }

        evalResults = data;
        renderEvalResults();

        // Re-enable button
        const btn = document.getElementById('btn-eval-run');
        btn.disabled = false;
        btn.textContent = 'Run Full Evaluation';

        // Hide progress
        document.getElementById('eval-progress').style.display = 'none';

        // Hide UXFeedback progress bar
        if (window.UXFeedback) {
            window.UXFeedback.progress.hide('evaluation');
        }
    } catch (error) {
        console.error('Failed to load results:', error);
        document.getElementById('eval-status').textContent = 'Error: ' + error.message;
        document.getElementById('eval-status').style.color = 'var(--err)';
        const btn = document.getElementById('btn-eval-run');
        btn.disabled = false;
        btn.textContent = 'Run Full Evaluation';

        // Hide UXFeedback progress bar on error
        if (window.UXFeedback) {
            window.UXFeedback.progress.hide('evaluation');
        }
    }
}

// Render evaluation results
/**
 * ---agentspec
 * what: |
 *   Renders evaluation metrics (top-1 and top-k accuracy) to DOM. Converts decimal accuracies to percentages, displays results section.
 *
 * why: |
 *   Centralizes metric formatting and visibility toggle for consistent UI updates.
 *
 * guardrails:
 *   - DO NOT assume evalResults is populated; check exists before access
 *   - NOTE: Mutates DOM directly; consider event-driven updates for testability
 * ---/agentspec
 */
function renderEvalResults() {
    if (!evalResults) return;

    // Show results section
    document.getElementById('eval-results').style.display = 'block';

    // Overall metrics
    const top1Pct = (evalResults.top1_accuracy * 100).toFixed(1) + '%';
    const topkPct = (evalResults.topk_accuracy * 100).toFixed(1) + '%';
    const duration = evalResults.duration_secs + 's';

    document.getElementById('eval-top1-acc').textContent = top1Pct;
    document.getElementById('eval-topk-acc').textContent = topkPct;
    document.getElementById('eval-duration').textContent = duration;

    // Per-question details
    const detailsContainer = document.getElementById('eval-details');
    const results = evalResults.results || [];
    const failures = results.filter(r => !r.topk_hit);
    const passes = results.filter(r => r.topk_hit);

    let html = `
        <div style="margin-bottom: 12px;">
            <div style="font-size: 12px; color: var(--fg-muted); margin-bottom: 8px;">
                <span style="color: var(--ok);">✓ ${passes.length} passed</span>
                <span style="margin-left: 16px; color: var(--err);">✗ ${failures.length} failed</span>
            </div>
        </div>
    `;

    // Show failures first
    if (failures.length > 0) {
        html += '<div style="margin-bottom: 16px;"><div style="font-size: 12px; font-weight: 600; color: var(--err); margin-bottom: 8px;">FAILURES</div>';
        failures.forEach((r, i) => {
            html += renderQuestionResult(r, true);
        });
        html += '</div>';
    }

    // Show passes (collapsed by default)
    if (passes.length > 0) {
        html += `
            <details style="margin-top: 12px;">
                <summary style="font-size: 12px; font-weight: 600; color: var(--accent); margin-bottom: 8px; cursor: pointer;">
                    PASSES (${passes.length})
                </summary>
                <div style="margin-top: 8px;">
        `;
        passes.forEach((r, i) => {
            html += renderQuestionResult(r, false);
        });
        html += '</div></details>';
    }

    detailsContainer.innerHTML = html;
}

// Render individual question result
/**
 * ---agentspec
 * what: |
 *   Renders retrieval evaluation result (question + top-1/top-k hits). Returns HTML card with color-coded pass/fail border and metrics.
 *
 * why: |
 *   Centralizes result formatting; consistent styling via CSS variables.
 *
 * guardrails:
 *   - DO NOT trust r.top1_hit/r.topk_hit without validation; sanitize input
 *   - NOTE: escapeHtml() required to prevent XSS on r.question
 *   - DO NOT assume isFailure maps 1:1 to hit status; document mapping
 * ---/agentspec
 */
function renderQuestionResult(r, isFailure) {
    const top1Color = r.top1_hit ? 'var(--ok)' : 'var(--err)';
    const topkColor = r.topk_hit ? 'var(--ok)' : 'var(--warn)';

    return `
        <div style="background: var(--card-bg); border-left: 3px solid ${isFailure ? 'var(--err)' : 'var(--ok)'}; padding: 10px; margin-bottom: 8px; border-radius: 4px;">
            <div style="display: flex; justify-content: space-between; align-items: start; margin-bottom: 6px;">
                <div style="flex: 1; font-size: 12px; color: var(--fg); font-weight: 500;">${escapeHtml(r.question)}</div>
                <div style="font-size: 11px; margin-left: 12px;">
                    <span style="background: var(--bg-elev2); padding: 2px 6px; border-radius: 3px;">${r.repo}</span>
                </div>
            </div>
            <div style="font-size: 11px; color: var(--fg-muted); margin-bottom: 4px;">
                <strong>Expected:</strong> ${(r.expect_paths || []).join(', ')}
            </div>
            <div style="font-size: 11px;">
                <span style="color: ${top1Color}; font-weight: 600;">${r.top1_hit ? '✓' : '✗'} Top-1</span>
                <span style="margin-left: 12px; color: ${topkColor}; font-weight: 600;">${r.topk_hit ? '✓' : '✗'} Top-K</span>
            </div>
            <div style="margin-top: 6px; font-size: 10px; font-family: 'SF Mono', monospace; color: var(--fg-muted);">
                ${(r.top_paths || []).slice(0, 3).map((p, i) => {
                    const match = (r.expect_paths || []).some(exp => p.includes(exp));
                    const color = match ? 'var(--ok)' : 'var(--fg-muted)';
                    return `<div style="color: ${color};">${i + 1}. ${escapeHtml(p)}</div>`;
                }).join('')}
            </div>
        </div>
    `;
}

// Save baseline
async function saveBaseline() {
    if (!evalResults) {
        alert('No evaluation results to save');
        return;
    }

    try {
        const response = await fetch('/api/eval/baseline/save', {
            method: 'POST'
        });

        const data = await response.json();
        if (data.ok) {
            showToast('Baseline saved successfully', 'success');
        } else {
            throw new Error('Failed to save baseline');
        }
    } catch (error) {
        console.error('Failed to save baseline:', error);
        const msg = window.ErrorHelpers ? window.ErrorHelpers.createAlertError('Failed to save baseline', {
            message: error.message,
            causes: [
                'Backend API service not responding',
                'Baseline storage database not initialized',
                'Insufficient permissions to save',
                'Disk space or storage quota exceeded'
            ],
            fixes: [
                'Check Infrastructure tab - verify backend is running',
                'Check available disk space',
                'Verify user account has baseline save permissions',
                'Try again in a few moments'
            ],
            links: [
                ['Qdrant Vector Database', 'https://qdrant.tech/documentation/concepts/collections/']
            ]
        }) : ('Failed to save baseline: ' + error.message);
        alert(msg);
    }
}

// Compare with baseline
async function compareWithBaseline() {
    if (!evalResults) {
        alert('No current evaluation results');
        return;
    }

    try {
        const response = await fetch('/api/eval/baseline/compare');
        const data = await response.json();

        if (!data.ok) {
            throw new Error(data.message || 'No baseline found');
        }

        renderComparison(data);
    } catch (error) {
        console.error('Failed to compare:', error);
        alert(error.message);
    }
}

// Render comparison results
/**
 * ---agentspec
 * what: |
 *   Renders evaluation comparison UI. Takes delta object (top1, topk metrics), calculates percentage deltas, displays in #eval-comparison container.
 *
 * why: |
 *   Centralizes metric formatting and DOM rendering to avoid scattered percentage calculations.
 *
 * guardrails:
 *   - DO NOT assume data.delta exists; validate before access
 *   - NOTE: Assumes #eval-comparison element present in DOM
 * ---/agentspec
 */
function renderComparison(data) {
    const container = document.getElementById('eval-comparison');
    container.style.display = 'block';

    const deltaTop1 = data.delta.top1;
    const deltaTopk = data.delta.topk;
    const deltaTop1Pct = (deltaTop1 * 100).toFixed(1) + '%';
    const deltaTopkPct = (deltaTopk * 100).toFixed(1) + '%';

    const top1Icon = deltaTop1 >= 0 ? '✓' : '✗';
    const topkIcon = deltaTopk >= 0 ? '✓' : '✗';
    const top1Color = deltaTop1 >= 0 ? 'var(--ok)' : 'var(--err)';
    const topkColor = deltaTopk >= 0 ? 'var(--ok)' : 'var(--err)';

    let html = `
        <div style="background: var(--code-bg); border: 1px solid var(--line); border-radius: 6px; padding: 16px;">
            <h4 style="font-size: 14px; color: var(--link); margin-bottom: 12px; text-transform: uppercase; letter-spacing: 0.5px;">
                Baseline Comparison
            </h4>
            <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-bottom: 16px;">
                <div style="background: var(--card-bg); border: 1px solid var(--line); border-radius: 4px; padding: 12px;">
                    <div style="font-size: 11px; color: var(--fg-muted); text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 4px;">Top-1 Accuracy</div>
                    <div style="font-size: 14px; color: var(--fg-muted); margin-bottom: 4px;">
                        Baseline: ${(data.baseline.top1_accuracy * 100).toFixed(1)}%
                    </div>
                    <div style="font-size: 14px; color: var(--fg); margin-bottom: 4px;">
                        Current: ${(data.current.top1_accuracy * 100).toFixed(1)}%
                    </div>
                    <div style="font-size: 16px; color: ${top1Color}; font-weight: 700;">
                        ${top1Icon} ${deltaTop1 >= 0 ? '+' : ''}${deltaTop1Pct}
                    </div>
                </div>
                <div style="background: var(--card-bg); border: 1px solid var(--line); border-radius: 4px; padding: 12px;">
                    <div style="font-size: 11px; color: var(--fg-muted); text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 4px;">Top-K Accuracy</div>
                    <div style="font-size: 14px; color: var(--fg-muted); margin-bottom: 4px;">
                        Baseline: ${(data.baseline.topk_accuracy * 100).toFixed(1)}%
                    </div>
                    <div style="font-size: 14px; color: var(--fg); margin-bottom: 4px;">
                        Current: ${(data.current.topk_accuracy * 100).toFixed(1)}%
                    </div>
                    <div style="font-size: 16px; color: ${topkColor}; font-weight: 700;">
                        ${topkIcon} ${deltaTopk >= 0 ? '+' : ''}${deltaTopkPct}
                    </div>
                </div>
            </div>
    `;

    if (data.regressions && data.regressions.length > 0) {
        html += `
            <div style="background: color-mix(in oklch, var(--err) 8%, var(--bg)); border: 1px solid var(--err); border-radius: 4px; padding: 12px; margin-bottom: 12px;">
                <div style="font-size: 12px; font-weight: 600; color: var(--err); margin-bottom: 8px;">
                    ⚠ REGRESSIONS (${data.regressions.length})
                </div>
                ${data.regressions.map(r => `
                    <div style="font-size: 11px; color: var(--err); opacity: .85; margin-bottom: 4px;">
                        <span style="background: var(--bg-elev2); padding: 2px 6px; border-radius: 2px; margin-right: 6px;">${r.repo}</span>
                        ${escapeHtml(r.question)}
                    </div>
                `).join('')}
            </div>
        `;
    }

    if (data.improvements && data.improvements.length > 0) {
        html += `
            <div style="background: color-mix(in oklch, var(--ok) 8%, var(--bg)); border: 1px solid var(--ok); border-radius: 4px; padding: 12px;">
                <div style="font-size: 12px; font-weight: 600; color: var(--ok); margin-bottom: 8px;">
                    ✓ IMPROVEMENTS (${data.improvements.length})
                </div>
                ${data.improvements.map(r => `
                    <div style="font-size: 11px; color: var(--ok); opacity:.85; margin-bottom: 4px;">
                        <span style="background: var(--bg-elev2); padding: 2px 6px; border-radius: 2px; margin-right: 6px;">${r.repo}</span>
                        ${escapeHtml(r.question)}
                    </div>
                `).join('')}
            </div>
        `;
    }

    if (!data.has_regressions) {
        html += `
            <div style="background: color-mix(in oklch, var(--ok) 8%, var(--bg)); border: 1px solid var(--ok); border-radius: 4px; padding: 12px; text-align: center; color: var(--ok); font-weight: 600;">
                ✓ No significant regressions detected
            </div>
        `;
    }

    html += '</div>';
    container.innerHTML = html;
}

// Export results
/**
 * ---agentspec
 * what: |
 *   Exports evalResults object to JSON file. Creates blob, generates download URL, triggers browser download.
 *
 * why: |
 *   Standard client-side export pattern for structured data persistence.
 *
 * guardrails:
 *   - DO NOT export if evalResults is null/undefined; alert user first
 *   - NOTE: Uses URL.createObjectURL; clean up with revokeObjectURL if memory-critical
 * ---/agentspec
 */
function exportEvalResults() {
    if (!evalResults) {
        alert('No results to export');
        return;
    }

    const dataStr = JSON.stringify(evalResults, null, 2);
    const blob = new Blob([dataStr], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    const timestamp = new Date().toLocaleString().replace(/[\/\s:,]/g, '-').replace(/--+/g, '-');
    a.download = `eval_results_${timestamp}.json`;
    a.click();
    URL.revokeObjectURL(url);
    showToast('Results exported', 'success');
}

// Helper functions
/**
 * ---agentspec
 * what: |
 *   Escapes HTML special chars via textContent/innerHTML. Shows dismissible toast notifications with color-coded type (success/error/info).
 *
 * why: |
 *   textContent prevents XSS; toast provides non-blocking user feedback.
 *
 * guardrails:
 *   - DO NOT use innerHTML directly on user input; textContent sanitizes first
 *   - NOTE: Toast color depends on CSS vars (--ok, --err, --link); verify defined
 *   - ASK USER: Add toast auto-dismiss timeout?
 * ---/agentspec
 */
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

/**
 * ---agentspec
 * what: |
 *   Creates and displays a toast notification. Accepts message string and type ('info'|'success'|'error'). Renders fixed-position div with color mapped to type.
 *
 * why: |
 *   Centralizes toast UI logic; reusable across app for consistent notifications.
 *
 * guardrails:
 *   - DO NOT call without message; toast will be empty
 *   - NOTE: Uses CSS custom properties (--ok, --err, --link, --panel); ensure defined in root scope
 * ---/agentspec
 */
function showToast(message, type = 'info') {
    const color = type === 'success' ? 'var(--ok)' : type === 'error' ? 'var(--err)' : 'var(--link)';
    const toast = document.createElement('div');
    toast.style.cssText = `
        position: fixed;
        top: 80px;
        right: 24px;
        background: var(--panel);
        color: ${color};
        border: 1px solid ${color};
        padding: 12px 20px;
        border-radius: 6px;
        font-size: 13px;
        z-index: 10000;
        box-shadow: 0 4px 12px rgba(0,0,0,0.5);
    `;
    toast.textContent = message;
    document.body.appendChild(toast);
    setTimeout(() => toast.remove(), 3000);
}

// Initialize
if (typeof window !== 'undefined') {
    // Initialization function called by golden_questions.js when rag-evaluate view mounts
    // Does NOT register view - golden_questions.js handles that
    window.initEvalRunner = function() {
        console.log('[eval_runner.js] Initializing eval runner for rag-evaluate view');
        const btnRun = document.getElementById('btn-eval-run');
        const btnSaveBaseline = document.getElementById('btn-eval-save-baseline');
        const btnCompare = document.getElementById('btn-eval-compare');
        const btnExport = document.getElementById('btn-eval-export');
        const btnSaveSettings = document.getElementById('btn-eval-save-settings');

        if (btnRun) btnRun.addEventListener('click', runEvaluation);
        if (btnSaveBaseline) btnSaveBaseline.addEventListener('click', saveBaseline);
        if (btnCompare) btnCompare.addEventListener('click', compareWithBaseline);
        if (btnExport) btnExport.addEventListener('click', exportEvalResults);
        if (btnSaveSettings) btnSaveSettings.addEventListener('click', saveEvalSettings);
        loadEvalSettings();
    };

    // Legacy mode support
    window.addEventListener('DOMContentLoaded', () => {
        const btnRun = document.getElementById('btn-eval-run');
        const btnSaveBaseline = document.getElementById('btn-eval-save-baseline');
        const btnCompare = document.getElementById('btn-eval-compare');
        const btnExport = document.getElementById('btn-eval-export');
        const btnSaveSettings = document.getElementById('btn-eval-save-settings');

        if (btnRun) btnRun.addEventListener('click', runEvaluation);
        if (btnSaveBaseline) btnSaveBaseline.addEventListener('click', saveBaseline);
        if (btnCompare) btnCompare.addEventListener('click', compareWithBaseline);
        if (btnExport) btnExport.addEventListener('click', exportEvalResults);
        if (btnSaveSettings) btnSaveSettings.addEventListener('click', saveEvalSettings);
        loadEvalSettings();
    });

    console.log('[eval_runner.js] Module loaded (coordination with golden_questions.js for rag-evaluate view)');
}
