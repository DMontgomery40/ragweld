// Evaluation Run History Management
// Tracks and displays BM25-only vs cross-encoder performance across runs

const EVAL_HISTORY_KEY = 'tribrid_eval_history';
const MAX_HISTORY_ENTRIES = 20;

// Initialize eval history on page load
document.addEventListener('DOMContentLoaded', () => {
    // Seed initial data if history is empty
    if (getEvalHistory().length === 0) {
        seedEvalHistory();
    }

    loadEvalHistory();

    // Refresh button
    document.getElementById('btn-eval-history-refresh')?.addEventListener('click', () => {
        loadEvalHistory();
    });

    // Clear history button
    document.getElementById('btn-eval-history-clear')?.addEventListener('click', () => {
        if (confirm('Clear all evaluation history? This cannot be undone.')) {
            localStorage.removeItem(EVAL_HISTORY_KEY);
            loadEvalHistory();
        }
    });
});

// Add eval run to history (called from eval_runner.js)
/**
 * ---agentspec
 * what: |
 *   Appends eval run entry (timestamp, config, rerank_backend, top1, topk metrics) to in-memory eval history. Returns updated history array.
 *
 * why: |
 *   Centralizes eval result tracking for comparison across retrieval + reranking configurations.
 *
 * guardrails:
 *   - DO NOT persist to disk here; caller owns storage strategy
 *   - NOTE: Mutates history array; no rollback on failure
 *   - ASK USER: Should history be capped (max entries) to prevent unbounded growth?
 * ---/agentspec
 */
function addEvalRunToHistory(config, results) {
    const history = getEvalHistory();

    const entry = {
        timestamp: new Date().toISOString(),
        config: config, // 'BM25-only', 'BM25 + Cross-Encoder', etc.
        rerank_backend: results.rerank_backend || 'none',
        top1: results.top1 || 0,
        topk: results.topk || 0,
        total: results.total || 52,
        secs: results.secs || 0,
        final_k: results.final_k || 5,
        use_multi: results.use_multi || false
    };

    history.unshift(entry); // Add to front

    // Keep only MAX_HISTORY_ENTRIES
    if (history.length > MAX_HISTORY_ENTRIES) {
        history.splice(MAX_HISTORY_ENTRIES);
    }

    localStorage.setItem(EVAL_HISTORY_KEY, JSON.stringify(history));
    loadEvalHistory();
}

// Get eval history from localStorage
/**
 * ---agentspec
 * what: |
 *   Retrieves evaluation history from localStorage. Returns parsed array or empty array on parse failure.
 *
 * why: |
 *   Wraps localStorage access with error handling to prevent crashes on corrupted data.
 *
 * guardrails:
 *   - DO NOT assume localStorage is always available; some browsers/contexts block it
 *   - NOTE: Silent fallback to [] masks data loss; consider logging severity level
 * ---/agentspec
 */
function getEvalHistory() {
    try {
        const stored = localStorage.getItem(EVAL_HISTORY_KEY);
        return stored ? JSON.parse(stored) : [];
    } catch (e) {
        console.error('Failed to load eval history:', e);
        return [];
    }
}

// Load and display eval history
/**
 * ---agentspec
 * what: |
 *   Loads evaluation history from storage and populates HTML table body. Reads from getEvalHistory(), renders rows into #eval-history-tbody. Returns early if tbody missing or history empty.
 *
 * why: |
 *   Centralizes history retrieval and DOM rendering to avoid duplication across UI refresh cycles.
 *
 * guardrails:
 *   - DO NOT assume tbody exists; guard with early return
 *   - NOTE: Empty history renders placeholder row; verify getEvalHistory() returns array
 * ---/agentspec
 */
function loadEvalHistory() {
    const history = getEvalHistory();
    const tbody = document.getElementById('eval-history-tbody');

    if (!tbody) return;

    if (history.length === 0) {
        tbody.innerHTML = `
            <tr>
                <td colspan="6" style="padding: 20px; text-align: center; color: var(--fg-muted);">
                    No evaluation history yet. Run evaluations to see comparisons.
                </td>
            </tr>
        `;
        return;
    }

    // Build table rows
    let html = '';
    history.forEach((entry, index) => {
        const timestamp = new Date(entry.timestamp);
        const timeStr = timestamp.toLocaleString();
        const dateStr = timestamp.toLocaleDateString();
        const clockStr = timestamp.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

        // Calculate accuracy percentages
        const top1Pct = ((entry.top1 / entry.total) * 100).toFixed(1);
        const top5Pct = ((entry.topk / entry.total) * 100).toFixed(1);

        // Calculate delta vs previous run (same config)
        let delta = null;
        let deltaColor = 'var(--fg-muted)';
        let deltaSymbol = '';

        // Find previous run with same config
        for (let i = index + 1; i < history.length; i++) {
            if (history[i].config === entry.config) {
                const prevTop5Pct = (history[i].topk / history[i].total) * 100;
                delta = top5Pct - prevTop5Pct;

                if (delta > 0) {
                    deltaColor = 'var(--accent-green)';
                    deltaSymbol = '+';
                } else if (delta < 0) {
                    deltaColor = 'var(--warn)';
                    deltaSymbol = '';
                } else {
                    deltaColor = 'var(--fg-muted)';
                    deltaSymbol = '';
                }
                break;
            }
        }

        // Determine config display and color
        let configDisplay = entry.config;
        let configColor = 'var(--fg)';
        let configBg = 'transparent';

        if (entry.rerank_backend === 'local') {
            configDisplay = 'BM25 + Trained CE';
            configColor = 'var(--accent)';
            configBg = 'rgba(var(--accent-rgb), 0.1)';
        } else if (entry.rerank_backend === 'cohere') {
            configDisplay = 'BM25 + Cohere CE';
            configColor = 'var(--link)';
            configBg = 'rgba(var(--link-rgb), 0.1)';
        } else {
            configDisplay = 'BM25-only';
            configColor = 'var(--fg-muted)';
        }

        // Top-5 color based on performance
        let top5Color = 'var(--fg)';
        if (top5Pct >= 95) top5Color = 'var(--accent-green)';
        else if (top5Pct >= 90) top5Color = 'var(--accent)';
        else if (top5Pct >= 80) top5Color = 'var(--link)';
        else if (top5Pct < 70) top5Color = 'var(--warn)';

        html += `
            <tr style="border-bottom: 1px solid var(--line);">
                <td style="padding: 10px; font-family: monospace; font-size: 11px; color: var(--fg-muted);" title="${timeStr}">
                    ${dateStr}<br>
                    <span style="color: var(--fg-muted);">${clockStr}</span>
                </td>
                <td style="padding: 10px;">
                    <span style="display: inline-block; padding: 4px 8px; border-radius: 4px; background: ${configBg}; color: ${configColor}; font-weight: 600; font-size: 11px;">
                        ${configDisplay}
                    </span>
                </td>
                <td style="padding: 10px; text-align: center; font-family: monospace; font-weight: 600;">
                    <div style="color: var(--fg);">${entry.top1}/${entry.total}</div>
                    <div style="font-size: 10px; color: var(--fg-muted);">${top1Pct}%</div>
                </td>
                <td style="padding: 10px; text-align: center; font-family: monospace; font-weight: 700;">
                    <div style="color: ${top5Color}; font-size: 14px;">${entry.topk}/${entry.total}</div>
                    <div style="font-size: 10px; color: var(--fg-muted);">${top5Pct}%</div>
                </td>
                <td style="padding: 10px; text-align: center; font-family: monospace; color: var(--fg-muted);">
                    ${entry.secs.toFixed(0)}s
                </td>
                <td style="padding: 10px; text-align: center; font-family: monospace; font-weight: 600;">
                    ${delta !== null ? `<span style="color: ${deltaColor};">${deltaSymbol}${delta.toFixed(1)}%</span>` : '<span style="color: var(--fg-muted);">—</span>'}
                </td>
            </tr>
        `;
    });

    tbody.innerHTML = html;
}

// Seed eval history with tonight's results
/**
 * ---agentspec
 * what: |
 *   Seeds evaluation history with BM25 + Trained CE retrieval config. Records timestamp, rerank backend (local), and retrieval metrics (top1=28, topk=48, total=52).
 *
 * why: |
 *   Establishes baseline retrieval performance snapshot for comparative eval tracking.
 *
 * guardrails:
 *   - DO NOT modify timestamp; use UTC ISO 8601 only
 *   - NOTE: top1 + topk must be ≤ total; validate before insert
 *   - ASK USER: Confirm rerank_backend='local' is correct for your setup
 * ---/agentspec
 */
function seedEvalHistory() {
    const history = [
        {
            timestamp: '2025-10-19T09:14:00.000Z',
            config: 'BM25 + Trained CE',
            rerank_backend: 'local',
            top1: 28,
            topk: 48,
            total: 52,
            secs: 609,
            final_k: 5,
            use_multi: true
        },
        {
            timestamp: '2025-10-19T09:06:00.000Z',
            config: 'BM25-only (after test exclusions)',
            rerank_backend: 'none',
            top1: 32,
            topk: 45,
            total: 52,
            secs: 343,
            final_k: 5,
            use_multi: true
        },
        {
            timestamp: '2025-10-19T08:45:00.000Z',
            config: 'BM25 + Dense (no rerank)',
            rerank_backend: 'none',
            top1: 29,
            topk: 42,
            total: 52,
            secs: 356,
            final_k: 5,
            use_multi: true
        },
        {
            timestamp: '2025-10-19T08:39:00.000Z',
            config: 'BM25 + Dense + Cohere',
            rerank_backend: 'cohere',
            top1: 29,
            topk: 43,
            total: 52,
            secs: 357,
            final_k: 5,
            use_multi: true
        }
    ];

    localStorage.setItem(EVAL_HISTORY_KEY, JSON.stringify(history));
    loadEvalHistory();
}

// Auto-seeded on first load (see DOMContentLoaded above)
