// gui/js/reranker.js - Learning Reranker UI Module
// Handles feedback collection, triplet mining, training, evaluation, and all reranker features

// ============ LIVE TERMINAL ============
let _rerankerTerminal = null;
let _lastOutputLineCount = 0;

/**
 * ---agentspec
 * what: |
 *   Initializes LiveTerminal instance for reranker output. Checks window.LiveTerminal availability; creates singleton _rerankerTerminal if missing.
 *
 * why: |
 *   Deferred initialization prevents errors when LiveTerminal script loads asynchronously.
 *
 * guardrails:
 *   - DO NOT reinitialize if _rerankerTerminal already exists; check singleton first
 *   - NOTE: Logs warning if LiveTerminal unavailable; caller must retry
 * ---/agentspec
 */
function initRerankerTerminal() {
    if (!window.LiveTerminal) {
        console.warn('[reranker] LiveTerminal not loaded yet, will initialize later');
        return;
    }

    if (!_rerankerTerminal) {
        _rerankerTerminal = new window.LiveTerminal('reranker-terminal-container');
        console.log('[reranker] Live terminal initialized');
    }
}

// ============ FEEDBACK SYSTEM ============

// Track file link clicks
window.trackFileClick = async function(eventId, docId) {
    if (!eventId || !docId) return;
    
    try {
        await fetch('/api/reranker/click', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ event_id: eventId, doc_id: docId })
        });
    } catch (error) {
        console.error('[reranker] Failed to track click:', error);
        // Silent failure - click tracking is non-critical for UX
        // Check /api/reranker/click endpoint if debugging user feedback loop
    }
};

// Add feedback buttons to a chat message (thumbs + stars + note)
window.addFeedbackButtons = function addFeedbackButtons(messageElement, eventId) {
    if (!eventId) return;
    
    const feedbackDiv = document.createElement('div');
    feedbackDiv.style.cssText = 'margin-top:12px; padding:12px; background:var(--card-bg); border-radius:6px; border-left:3px solid var(--link);';
    feedbackDiv.innerHTML = `
        <div style="display:flex; gap:12px; align-items:center; margin-bottom:8px;">
            <button class="feedback-btn" data-event-id="${eventId}" data-signal="thumbsup" 
                style="background:var(--accent); color:var(--accent-contrast); border:none; padding:6px 14px; border-radius:4px; cursor:pointer; font-size:11px; font-weight:600;">
                👍 Helpful
            </button>
            <button class="feedback-btn" data-event-id="${eventId}" data-signal="thumbsdown"
                style="background:var(--err); color:var(--accent-contrast); border:none; padding:6px 14px; border-radius:4px; cursor:pointer; font-size:11px; font-weight:600;">
                👎 Not Helpful
            </button>
            <span style="color:var(--fg-muted);font-size:11px;">or rate:</span>
            ${[1,2,3,4,5].map(n => `<button class="star-btn" data-event-id="${eventId}" data-rating="${n}" 
                style="background:transparent; color:var(--warn); border:1px solid var(--line); padding:4px 10px; border-radius:4px; cursor:pointer; font-size:13px;">
                ${'⭐'.repeat(n)}
            </button>`).join('')}
        </div>
        <details style="margin-top:8px;">
            <summary style="cursor:pointer; font-size:11px; color:var(--fg-muted);">What was missing? (optional)</summary>
            <textarea class="feedback-note" data-event-id="${eventId}" 
                placeholder="Help us improve: What information were you looking for?" 
                style="width:100%; margin-top:8px; padding:8px; background: var(--code-bg); color: var(--fg); border:1px solid var(--bg-elev2); border-radius:4px; font-size:11px; font-family:'SF Mono',monospace; resize:vertical; min-height:50px;"></textarea>
            <button class="submit-note-btn" data-event-id="${eventId}"
                style="margin-top:8px; background:var(--link); color: var(--fg); border:none; padding:4px 12px; border-radius:4px; cursor:pointer; font-size:11px;">
                Submit Note
            </button>
        </details>
        <div class="feedback-status" style="font-size:11px; color:var(--fg-muted); margin-top:8px;"></div>
        <div style="font-size:10px; color:var(--fg-muted); margin-top:8px; font-style:italic;">
            💡 This helps train search quality (only the reranker, not the chat model)
        </div>
    `;
    
    messageElement.appendChild(feedbackDiv);
    
    // Bind thumbs buttons
    feedbackDiv.querySelectorAll('.feedback-btn').forEach(btn => {
        btn.addEventListener('click', async (e) => {
            await submitFeedback(e.currentTarget.dataset.eventId, e.currentTarget.dataset.signal, null, feedbackDiv);
        });
    });
    
    // Bind star buttons
    feedbackDiv.querySelectorAll('.star-btn').forEach(btn => {
        btn.addEventListener('click', async (e) => {
            const rating = e.currentTarget.dataset.rating;
            await submitFeedback(e.currentTarget.dataset.eventId, `star${rating}`, null, feedbackDiv);
        });
    });
    
    // Bind note submit
    const submitNoteBtn = feedbackDiv.querySelector('.submit-note-btn');
    if (submitNoteBtn) {
        submitNoteBtn.addEventListener('click', async (e) => {
            const note = feedbackDiv.querySelector('.feedback-note').value.trim();
            if (note) {
                await submitFeedback(e.currentTarget.dataset.eventId, 'note', note, feedbackDiv);
            }
        });
    }
};

async function submitFeedback(eventId, signal, note, feedbackDiv) {
    const statusSpan = feedbackDiv.querySelector('.feedback-status');
    
    try {
        const response = await fetch('/api/feedback', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ 
                event_id: eventId, 
                signal: signal,
                note: note
            })
        });
        
        if (response.ok) {
            const label = signal.startsWith('star') ? `${signal.replace('star', '')} stars` : signal;
            statusSpan.textContent = `✓ Feedback recorded: ${label}`;
            statusSpan.style.color = 'var(--accent)';
            // Disable buttons after feedback
            feedbackDiv.querySelectorAll('.feedback-btn, .star-btn').forEach(b => b.disabled = true);
        } else {
            statusSpan.innerHTML = `
                ✗ Failed to save feedback
                <a href="/docs/RERANKER.md#feedback" target="_blank" rel="noopener" style="color: var(--link); margin-left: 8px; text-decoration: underline;">Troubleshoot</a>
            `;
            statusSpan.style.color = 'var(--err)';
        }
    } catch (error) {
        statusSpan.innerHTML = `
            ✗ Error: ${error.message}
            <a href="/docs/RERANKER.md#feedback" target="_blank" rel="noopener" style="color: var(--link); margin-left: 8px; text-decoration: underline;">Help</a>
            <a href="https://developer.mozilla.org/en-US/docs/Web/API/Fetch_API/Using_Fetch#checking_that_the_fetch_was_successful" target="_blank" rel="noopener" style="color: var(--link); margin-left: 8px; text-decoration: underline;">Fetch API</a>
        `;
        statusSpan.style.color = 'var(--err)';
    }
}

// ============ TRAINING WORKFLOW ============

async function mineTriplets() {
    const resultDiv = document.getElementById('reranker-mine-result');
    try {
        const response = await fetch('/api/reranker/mine', { method: 'POST' });
        const data = await response.json();
        if (resultDiv) resultDiv.textContent = 'Mining started...';
        startStatusPolling();
        return data;
    } catch (error) {
        if (resultDiv) {
            resultDiv.innerHTML = window.ErrorHelpers ? window.ErrorHelpers.createHelpfulError({
                title: 'Failed to start triplet mining',
                message: error.message,
                causes: [
                    'Backend server is not running (check Infrastructure tab)',
                    'Insufficient training data (need at least 50 logged queries with feedback)',
                    'Network connectivity issues',
                    'Mining process already running'
                ],
                fixes: [
                    'Check server status in Infrastructure > Services',
                    'Verify query logs exist (need feedback data)',
                    'Wait for any running mining tasks to complete',
                    'Check browser console for detailed errors'
                ],
                links: [
                    ['📖 Learning Reranker Docs', '/docs/RERANKER.md#mining'],
                    ['Triplet Loss Explained', 'https://en.wikipedia.org/wiki/Triplet_loss'],
                    ['Backend API', '/docs/API.md#reranker-endpoints']
                ]
            }) : `✗ ${error.message}`;
        }
        throw error;
    }
}

async function trainReranker(options = {}) {
    const resultDiv = document.getElementById('reranker-train-result');
    try {
        const response = await fetch('/api/reranker/train', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(options)
        });
        const data = await response.json();
        if (resultDiv) resultDiv.textContent = 'Training started...';
        startStatusPolling();
        return data;
    } catch (error) {
        if (resultDiv) {
            resultDiv.innerHTML = window.ErrorHelpers ? window.ErrorHelpers.createHelpfulError({
                title: 'Failed to start model training',
                message: error.message,
                causes: [
                    'No training triplets available (run "Mine Triplets" first)',
                    'Insufficient GPU/CPU resources',
                    'Model files are locked or corrupted',
                    'Training already in progress',
                    'Python dependencies missing (sentence-transformers, torch)'
                ],
                fixes: [
                    'Mine triplets first using the "Mine Triplets" button',
                    'Check system resources (RAM, GPU availability)',
                    'Verify Python environment has required packages',
                    'Wait for any running training jobs to complete',
                    'Check logs for detailed error messages'
                ],
                links: [
                    ['📖 Training Guide', '/docs/RERANKER.md#training'],
                    ['Cross-Encoder Model Info', '/models/cross-encoder-agro.baseline/README.md'],
                    ['Sentence-Transformers Docs', 'https://www.sbert.net/docs/cross_encoder/training/usage.html'],
                    ['PyTorch Installation', 'https://pytorch.org/get-started/locally/']
                ]
            }) : `✗ ${error.message}`;
        }
        throw error;
    }
}

async function evaluateReranker() {
    const resultDiv = document.getElementById('reranker-eval-result');
    try {
        const response = await fetch('/api/reranker/evaluate', { method: 'POST' });
        const data = await response.json();
        if (resultDiv) resultDiv.textContent = 'Evaluating...';
        startStatusPolling();
        return data;
    } catch (error) {
        if (resultDiv) {
            resultDiv.innerHTML = window.ErrorHelpers ? window.ErrorHelpers.createHelpfulError({
                title: 'Failed to evaluate model',
                message: error.message,
                causes: [
                    'No trained model available (train a model first)',
                    'Golden questions file missing or invalid (GOLDEN_PATH)',
                    'Evaluation dataset is empty',
                    'Backend server not responding'
                ],
                fixes: [
                    'Train a model first using the "Train Model" button',
                    'Verify golden questions file exists at GOLDEN_PATH setting',
                    'Check that golden.json has valid query/answer pairs',
                    'Ensure backend server is running (Infrastructure tab)'
                ],
                links: [
                    ['📖 Evaluation Guide', '/docs/RERANKER.md#evaluation'],
                    ['Golden Questions Format', '/docs/EVALUATION.md#golden-questions'],
                    ['MRR & Hit@K Metrics', 'https://en.wikipedia.org/wiki/Mean_reciprocal_rank'],
                    ['Cross-Encoder Evaluation', 'https://www.sbert.net/docs/cross_encoder/usage/usage.html']
                ]
            }) : `✗ ${error.message}`;
        }
        throw error;
    }
}

async function getRerankerStatus() {
    try {
        const response = await fetch('/api/reranker/status');
        const data = await response.json();
        return data;
    } catch (error) {
        return { running: false, progress: 0, task: '', message: '', result: null };
    }
}

// ============ UI UPDATES ============

let statusPollInterval = null;

/**
 * ---agentspec
 * what: |
 *   Starts polling loop for status updates. Initializes terminal UI if needed, then displays it. Guards against duplicate polling with interval check.
 *
 * why: |
 *   Prevents multiple concurrent poll loops; centralizes terminal setup.
 *
 * guardrails:
 *   - DO NOT call repeatedly without checking statusPollInterval; causes duplicate timers
 *   - NOTE: initRerankerTerminal() must be idempotent
 *   - ASK USER: What triggers polling stop? (missing stopStatusPolling call)
 * ---/agentspec
 */
function startStatusPolling() {
    if (statusPollInterval) return;

    // Initialize terminal if not already done
    initRerankerTerminal();

    // Show and configure terminal
    if (_rerankerTerminal) {
        _rerankerTerminal.show();
        _rerankerTerminal.clear();
        _lastOutputLineCount = 0;
    }

    statusPollInterval = setInterval(async () => {
        const status = await getRerankerStatus();
        updateRerankerStatusUI(status);

        // Update terminal with new output lines
        if (_rerankerTerminal && status.live_output && Array.isArray(status.live_output)) {
            const newLines = status.live_output.slice(_lastOutputLineCount);
            if (newLines.length > 0) {
                _rerankerTerminal.appendLines(newLines);
                _lastOutputLineCount = status.live_output.length;
            }
        }

        // Update progress bar
        if (_rerankerTerminal && status.running && status.progress > 0) {
            const taskName = {
                'mining': 'Mining Triplets',
                'training': 'Training Model',
                'evaluating': 'Evaluating Model'
            }[status.task] || status.task;

            _rerankerTerminal.updateProgress(status.progress, taskName);
            _rerankerTerminal.setTitle(`${taskName} - Live Output`);
        }

        // Stop polling when task completes
        if (!status.running && statusPollInterval) {
            clearInterval(statusPollInterval);
            statusPollInterval = null;

            // Hide progress bar
            if (_rerankerTerminal) {
                _rerankerTerminal.hideProgress();
                _rerankerTerminal.setTitle('Live Output - Complete');
            }

            // Update results display
            if (status.result) {
                updateTaskResults(status);
            }
        }
    }, 2000); // poll every 2 seconds during reranker training
}

/**
 * ---agentspec
 * what: |
 *   Updates DOM element #reranker-status with task progress or result. Sets text content and color based on running/result state.
 *
 * why: |
 *   Centralizes UI state updates for reranker operations; decouples status logic from DOM manipulation.
 *
 * guardrails:
 *   - DO NOT assume #reranker-status exists; early return prevents crashes
 *   - NOTE: Color uses CSS variable --accent; verify it's defined in stylesheet
 *   - ASK USER: Should failed results (status.result.ok === false) display error color?
 * ---/agentspec
 */
function updateRerankerStatusUI(status) {
    const statusEl = document.getElementById('reranker-status');
    if (!statusEl) return;
    
    if (status.running) {
        statusEl.textContent = status.message || `Running ${status.task}...`;
        statusEl.style.color = 'var(--accent)';
    } else if (status.result) {
        if (status.result.ok) {
            statusEl.textContent = status.message || 'Task complete';
            statusEl.style.color = 'var(--accent)';
        } else {
            // Include message fallback so users see server-side details
            statusEl.textContent = status.result.error || status.message || 'Task failed';
            statusEl.style.color = 'var(--err)';
        }
    } else {
        statusEl.textContent = 'Ready';
        statusEl.style.color = 'var(--fg-muted)';
    }
}

/**
 * ---agentspec
 * what: |
 *   Updates DOM element with mining task results. Parses result.output for triplet/event counts via regex, writes to #reranker-mine-result div.
 *
 * why: |
 *   Centralizes result rendering logic; regex extraction decouples parsing from display.
 *
 * guardrails:
 *   - DO NOT assume result.output format; add fallback if regex fails to match
 *   - NOTE: Silent fail if mineDiv missing; consider console.warn for debugging
 * ---/agentspec
 */
function updateTaskResults(status) {
    const task = status.task;
    const result = status.result;
    
    if (task === 'mining' && result?.output) {
        const mineDiv = document.getElementById('reranker-mine-result');
        if (mineDiv) {
            // Parse "mined X triplets from Y query events"
            const match = result.output.match(/mined (\d+) triplets from (\d+) query events/);
            if (match) {
                mineDiv.innerHTML = `✓ Mined <strong>${match[1]}</strong> triplets from ${match[2]} queries`;
                mineDiv.style.color = 'var(--accent)';
                updateTripletCount(match[1]);
            } else {
                mineDiv.textContent = '✓ ' + result.output;
                mineDiv.style.color = 'var(--accent)';
            }
        }
    } else if (task === 'training' && result?.output) {
        const trainDiv = document.getElementById('reranker-train-result');
        if (trainDiv) {
            // Parse "dev pairwise accuracy: 0.XXXX"
            const match = result.output.match(/dev pairwise accuracy: ([\d\.]+)/);
            if (match) {
                const acc = (parseFloat(match[1]) * 100).toFixed(1);
                trainDiv.innerHTML = `✓ Training complete! Dev accuracy: <strong>${acc}%</strong>`;
                trainDiv.style.color = 'var(--accent)';
            } else {
                trainDiv.textContent = '✓ Training complete';
                trainDiv.style.color = 'var(--accent)';
            }
        }
    } else if (task === 'evaluating' && result?.output) {
        const evalDiv = document.getElementById('reranker-eval-result');
        if (evalDiv) {
            evalDiv.textContent = '✓ Evaluation complete';
            evalDiv.style.color = 'var(--accent)';
        }
        // Parse and display metrics
        parseAndDisplayMetrics(result.output);
    }
}

/**
 * ---agentspec
 * what: |
 *   Parses reranker metrics (MRR@all, Hit@K) from output string via regex. Displays results in DOM element #reranker-metrics-display.
 *
 * why: |
 *   Decouples metric extraction from display logic; regex patterns isolate numeric values from formatted output.
 *
 * guardrails:
 *   - DO NOT assume output format is stable; add fallback parsing if format changes
 *   - NOTE: Silent fail if metricsDiv missing or output null; consider logging
 *   - ASK USER: Should invalid/missing metrics trigger error vs silent skip?
 * ---/agentspec
 */
function parseAndDisplayMetrics(output) {
    const metricsDiv = document.getElementById('reranker-metrics-display');
    if (!metricsDiv || !output) return;
    
    // Parse lines like "MRR@all: 0.XXXX" and "Hit@K: 0.XXXX"
    const mrrMatch = output.match(/MRR@all:\s*([\d\.]+)/);
    const hit1Match = output.match(/Hit@1:\s*([\d\.]+)/);
    const hit3Match = output.match(/Hit@3:\s*([\d\.]+)/);
    const hit5Match = output.match(/Hit@5:\s*([\d\.]+)/);
    const hit10Match = output.match(/Hit@10:\s*([\d\.]+)/);
    const evalMatch = output.match(/Evaluated on (\d+) items/);
    
    if (mrrMatch) {
        const mrr = (parseFloat(mrrMatch[1]) * 100).toFixed(1);
        const hit1 = hit1Match ? (parseFloat(hit1Match[1]) * 100).toFixed(1) : 'N/A';
        const hit3 = hit3Match ? (parseFloat(hit3Match[1]) * 100).toFixed(1) : 'N/A';
        const hit5 = hit5Match ? (parseFloat(hit5Match[1]) * 100).toFixed(1) : 'N/A';
        const hit10 = hit10Match ? (parseFloat(hit10Match[1]) * 100).toFixed(1) : 'N/A';
        const n = evalMatch ? evalMatch[1] : '?';
        
        metricsDiv.innerHTML = `
            <div style="display: grid; grid-template-columns: repeat(2, 1fr); gap: 16px;">
                <div>
                    <div style="font-size:11px; color:var(--fg-muted); margin-bottom:4px;">MRR (Mean Reciprocal Rank)</div>
                    <div style="font-size:32px; color:var(--accent); font-weight:700;">${mrr}%</div>
                    <div style="font-size:10px; color:var(--fg-muted);">Evaluated on ${n} items</div>
                </div>
                <div style="display:grid; grid-template-columns:repeat(2,1fr); gap:8px;">
                    <div>
                        <div style="font-size:10px; color:var(--fg-muted);">Hit@1</div>
                        <div style="font-size:20px; color:var(--link); font-weight:600;">${hit1}%</div>
                    </div>
                    <div>
                        <div style="font-size:10px; color:var(--fg-muted);">Hit@3</div>
                        <div style="font-size:20px; color:var(--link); font-weight:600;">${hit3}%</div>
                    </div>
                    <div>
                        <div style="font-size:10px; color:var(--fg-muted);">Hit@5</div>
                        <div style="font-size:20px; color:var(--link); font-weight:600;">${hit5}%</div>
                    </div>
                    <div>
                        <div style="font-size:10px; color:var(--fg-muted);">Hit@10</div>
                        <div style="font-size:20px; color:var(--link); font-weight:600;">${hit10}%</div>
                    </div>
                </div>
            </div>
        `;
    }
}

/**
 * ---agentspec
 * what: |
 *   Updates DOM element #reranker-triplet-count with triplet count and accent color. Reads count param, writes textContent and inline style.
 *
 * why: |
 *   Centralizes UI state updates for reranker triplet display; prevents scattered DOM mutations.
 *
 * guardrails:
 *   - DO NOT assume element exists; guard with null check already present
 *   - NOTE: Uses inline style; consider CSS class for maintainability at scale
 * ---/agentspec
 */
function updateTripletCount(count) {
    const countDiv = document.getElementById('reranker-triplet-count');
    if (countDiv) {
        countDiv.textContent = count + ' triplets';
        countDiv.style.color = 'var(--accent)';
    }
}

// ============ STATUS & STATS ============

async function updateRerankerStats() {
    // Check if reranker is enabled
    const statusDiv = document.getElementById('reranker-enabled-status');
    if (statusDiv) {
        const config = await fetch('/api/config').then(r => r.json()).catch(() => ({env:{}}));
        const enabled = config.env?.AGRO_RERANKER_ENABLED === '1';
        statusDiv.textContent = enabled ? '✓ Enabled' : '✗ Disabled';
        statusDiv.style.color = enabled ? 'var(--accent)' : 'var(--err)';
    }
    
    // Count logged queries
    const queryCountDiv = document.getElementById('reranker-query-count');
    if (queryCountDiv) {
        try {
            const logsResp = await fetch('/api/reranker/logs/count');
            const data = await logsResp.json();
            queryCountDiv.textContent = (data.count || 0) + ' queries';
            queryCountDiv.style.color = 'var(--accent)';
        } catch {
            queryCountDiv.textContent = 'N/A';
        }
    }
    
    // Count triplets
    const tripletCountDiv = document.getElementById('reranker-triplet-count');
    if (tripletCountDiv) {
        try {
            const tripletsResp = await fetch('/api/reranker/triplets/count');
            const data = await tripletsResp.json();
            tripletCountDiv.textContent = (data.count || 0) + ' triplets';
            tripletCountDiv.style.color = 'var(--accent)';
        } catch {
            tripletCountDiv.textContent = 'N/A';
        }
    }
    
    // Load cost stats
    try {
        const costsResp = await fetch('/api/reranker/costs');
        const data = await costsResp.json();
        const cost24h = document.getElementById('reranker-cost-24h');
        const costAvg = document.getElementById('reranker-cost-avg');
        if (cost24h) {
            cost24h.textContent = '$' + (data.total_24h || 0).toFixed(4);
        }
        if (costAvg) {
            costAvg.textContent = '$' + (data.avg_per_query || 0).toFixed(6);
        }
    } catch {}

    // Load server reranker info (model, device, params)
    try {
        const infoResp = await fetch('/api/reranker/info');
        if (infoResp.ok) {
            const info = await infoResp.json();
            const on = !!info.enabled;
            const apply = (suffix = '') => {
                const enabledEl = document.getElementById(`reranker-info-enabled${suffix}`);
                const pathEl = document.getElementById(`reranker-info-path${suffix}`);
                const devEl = document.getElementById(`reranker-info-device${suffix}`);
                const alphaEl = document.getElementById(`reranker-info-alpha${suffix}`);
                const topnEl = document.getElementById(`reranker-info-topn${suffix}`);
                const batchEl = document.getElementById(`reranker-info-batch${suffix}`);
                const maxlenEl = document.getElementById(`reranker-info-maxlen${suffix}`);
                if (enabledEl) {
                    enabledEl.textContent = on ? 'ON' : 'OFF';
                    enabledEl.style.color = on ? 'var(--accent)' : 'var(--err)';
                }
                if (pathEl) pathEl.textContent = info.resolved_path || info.path || '—';
                if (devEl) devEl.textContent = info.device || 'cpu';
                if (alphaEl) alphaEl.textContent = String(info.alpha ?? '—');
                if (topnEl) topnEl.textContent = String(info.topn ?? '—');
                if (batchEl) batchEl.textContent = String(info.batch ?? '—');
                if (maxlenEl) maxlenEl.textContent = String(info.maxlen ?? '—');
            };
            // Update both panels: external-rerankers (-ext) and learning-ranker (no suffix)
            apply('-ext');
            apply('');
        } else {
            const panel = document.getElementById('reranker-info-panel');
            if (panel) panel.innerHTML = '<div style="color:var(--err);">Failed to read /api/reranker/info</div>';
        }
    } catch (e) {
        const panel = document.getElementById('reranker-info-panel');
        if (panel) panel.innerHTML = `<div style=\"color:var(--err);\">Error: ${e.message}</div>`;
    }

    // Load no-hit queries
    try {
        const nohitsResp = await fetch('/api/reranker/nohits');
        const data = await nohitsResp.json();
        const nohitsList = document.getElementById('reranker-nohits-list');
        if (nohitsList) {
            if (data.queries && data.queries.length > 0) {
                nohitsList.innerHTML = data.queries.map(q =>
                    `<div style="padding:6px; border-bottom:1px solid var(--line);">
                        <div style="color: var(--fg);">${q.query}</div>
                        <div style="font-size:10px; color:var(--fg-muted);">${q.ts}</div>
                    </div>`
                ).join('');
            } else {
                nohitsList.innerHTML = '<div style="color: var(--fg-muted); text-align: center; padding: 20px;">No no-hit queries tracked yet.</div>';
            }
        }
    } catch (error) {
        const nohitsList = document.getElementById('reranker-nohits-list');
        if (nohitsList) {
            nohitsList.innerHTML = '<div style="color: var(--err); text-align: center; padding: 20px;">Failed to load no-hit queries</div>';
        }
    }
}

// ============ LOG VIEWER ============

async function viewLogs() {
    const viewer = document.getElementById('reranker-logs-viewer');
    if (!viewer) return;
    
    try {
        const response = await fetch('/api/reranker/logs');
        const data = await response.json();
        
        if (data.logs && data.logs.length > 0) {
            viewer.innerHTML = data.logs.slice(-50).map(log => {
                const color = log.type === 'query' ? 'var(--link)' : 'var(--warn)';
                return `<div style="margin-bottom:8px; padding:8px; background: var(--code-bg); border-left:2px solid ${color};">
                    <div style="color:${color}; font-size:10px;">${log.ts} - ${log.type}</div>
                    <div style="color: var(--fg);">${log.query_raw || JSON.stringify(log).slice(0, 100)}</div>
                </div>`;
            }).join('');
            viewer.style.display = 'block';
        } else {
            viewer.innerHTML = '<div style="color:var(--fg-muted); text-align:center; padding:20px;">No logs found</div>';
            viewer.style.display = 'block';
        }
    } catch (error) {
        viewer.innerHTML = window.ErrorHelpers ? window.ErrorHelpers.createHelpfulError({
            title: 'Error loading query logs',
            message: error.message,
            causes: [
                'Backend server is not running or not accessible',
                'Query logging is disabled (AGRO_RERANKER_ENABLED not set)',
                'Log file is corrupted or inaccessible',
                'Insufficient permissions to read log files'
            ],
            fixes: [
                'Check that backend server is running (Infrastructure > Services)',
                'Verify AGRO_RERANKER_ENABLED=1 in environment',
                'Check file permissions on data/queries/ directory',
                'Look for errors in server logs'
            ],
            links: [
                ['📖 Logging Setup', '/docs/RERANKER.md#logging'],
                ['Environment Variables', '/docs/CONFIGURATION.md#reranker-settings'],
                ['Backend API Reference', '/docs/API.md#reranker-logs']
            ]
        }) : `<div style="color:var(--err);">Error loading logs: ${error.message}</div>`;
        viewer.style.display = 'block';
    }
}

async function downloadLogs() {
    try {
        const response = await fetch('/api/reranker/logs/download');
        const blob = await response.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `queries-${new Date().toISOString().split('T')[0]}.jsonl`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
    } catch (error) {
        const msg = window.ErrorHelpers ? window.ErrorHelpers.createAlertError('Failed to download query logs', {
            message: error.message,
            causes: [
                'Backend server endpoint /api/reranker/logs/download not accessible',
                'No query logs available to download',
                'Browser blocked the download (check popup/download permissions)',
                'File size too large for browser to handle'
            ],
            fixes: [
                'Check server status in Infrastructure tab',
                'Verify logs exist by using "View Logs" button first',
                'Allow downloads in browser settings',
                'Try downloading a smaller date range if available'
            ],
            links: [
                ['Query Log Format', '/docs/RERANKER.md#log-format'],
                ['Browser Download Permissions', 'https://support.google.com/chrome/answer/95759']
            ]
        }) : `Failed to download logs: ${error.message}`;
        alert(msg);
    }
}

async function clearLogs() {
    if (!confirm('Clear all query logs? This will delete training data. Continue?')) return;
    try {
        await fetch('/api/reranker/logs/clear', { method: 'POST' });
        alert('✓ Logs cleared successfully. All query history and feedback data has been removed.');
        updateRerankerStats();
    } catch (error) {
        const msg = window.ErrorHelpers ? window.ErrorHelpers.createAlertError('Failed to clear query logs', {
            message: error.message,
            causes: [
                'Backend server is not responding',
                'Insufficient permissions to delete log files',
                'Log files are locked by another process',
                'API endpoint /api/reranker/logs/clear not available'
            ],
            fixes: [
                'Check server status (Infrastructure > Services)',
                'Verify file permissions on data/queries/ directory',
                'Stop any running training/mining processes',
                'Manually delete files in data/queries/ if necessary'
            ],
            links: [
                ['Log Management', '/docs/RERANKER.md#log-management'],
                ['File Permissions Guide', 'https://en.wikipedia.org/wiki/File-system_permissions']
            ]
        }) : `Failed to clear logs: ${error.message}`;
        alert(msg);
    }
}

// ============ AUTOMATION ============

async function setupNightlyJob() {
    const timeInput = document.getElementById('reranker-cron-time');
    const statusDiv = document.getElementById('reranker-cron-status');
    const time = timeInput?.value || '02:15';
    
    try {
        const response = await fetch('/api/reranker/cron/setup', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ time: time })
        });
        const data = await response.json();
        if (statusDiv) {
            if (data.ok) {
                statusDiv.textContent = `✓ Nightly job scheduled for ${time}`;
                statusDiv.style.color = 'var(--accent)';
            } else {
                statusDiv.innerHTML = `
                    ✗ ${data.error || 'Failed to schedule job'}
                    <a href="/docs/RERANKER.md#automation" target="_blank" rel="noopener" style="color: var(--link); margin-left: 8px; text-decoration: underline;">Troubleshoot</a>
                `;
                statusDiv.style.color = 'var(--err)';
            }
        }
    } catch (error) {
        if (statusDiv) {
            statusDiv.innerHTML = `
                ✗ ${error.message}
                <a href="/docs/RERANKER.md#automation" target="_blank" rel="noopener" style="color: var(--link); margin-left: 8px; text-decoration: underline;">Cron Setup Guide</a>
                <a href="https://crontab.guru/" target="_blank" rel="noopener" style="color: var(--link); margin-left: 8px; text-decoration: underline;">Cron Syntax</a>
            `;
            statusDiv.style.color = 'var(--err)';
        }
    }
}

async function removeNightlyJob() {
    const statusDiv = document.getElementById('reranker-cron-status');
    try {
        const response = await fetch('/api/reranker/cron/remove', { method: 'POST' });
        const data = await response.json();
        if (statusDiv) {
            if (data.ok) {
                statusDiv.textContent = '✓ Nightly job removed';
                statusDiv.style.color = 'var(--accent)';
            } else {
                statusDiv.innerHTML = `
                    ✗ ${data.error || 'Failed to remove job'}
                    <a href="/docs/RERANKER.md#automation" target="_blank" rel="noopener" style="color: var(--link); margin-left: 8px; text-decoration: underline;">Troubleshoot</a>
                `;
                statusDiv.style.color = 'var(--err)';
            }
        }
    } catch (error) {
        if (statusDiv) {
            statusDiv.innerHTML = `
                ✗ ${error.message}
                <a href="/docs/RERANKER.md#automation" target="_blank" rel="noopener" style="color: var(--link); margin-left: 8px; text-decoration: underline;">Help</a>
            `;
            statusDiv.style.color = 'var(--err)';
        }
    }
}

// ============ BASELINES ============

async function saveBaseline() {
    try {
        const response = await fetch('/api/reranker/baseline/save', { method: 'POST' });
        const data = await response.json();
        if (data.ok) {
            alert('✓ Baseline saved!\n\nYour current model has been backed up to models/cross-encoder-agro.baseline/\n\nUse this baseline to compare future training runs and prevent regressions.');
        } else {
            const msg = window.ErrorHelpers ? window.ErrorHelpers.createAlertError('Failed to save baseline', {
                message: data.error || 'Unknown error',
                causes: [
                    'No trained model exists to save as baseline',
                    'Insufficient permissions to write to models/ directory',
                    'Baseline directory already exists and is locked',
                    'Disk space full'
                ],
                fixes: [
                    'Train a model first before saving a baseline',
                    'Check file permissions on models/cross-encoder-agro.baseline/',
                    'Ensure sufficient disk space is available',
                    'Manually back up model files if necessary'
                ],
                links: [
                    ['Baseline Management', '/docs/RERANKER.md#baselines'],
                    ['Model Files Location', '/models/cross-encoder-agro.baseline/']
                ]
            }) : `Failed: ${data.error || 'Unknown'}`;
            alert(msg);
        }
    } catch (error) {
        const msg = window.ErrorHelpers ? window.ErrorHelpers.createAlertError('Error saving baseline', {
            message: error.message,
            causes: ['Backend server not responding', 'Network connectivity issues', 'API endpoint unavailable'],
            fixes: ['Check server status in Infrastructure tab', 'Verify network connection', 'Check browser console for details'],
            links: [['Backend Health', '/api/health']]
        }) : `Error: ${error.message}`;
        alert(msg);
    }
}

async function compareBaseline() {
    try {
        const response = await fetch('/api/reranker/baseline/compare');
        const data = await response.json();
        if (data.ok) {
            const delta = data.delta || {};
            const mrrDelta = (delta.mrr * 100).toFixed(1);
            const hit1Delta = (delta.hit1 * 100).toFixed(1);

            let message = `📊 Comparison vs Baseline:\n\n`;
            message += `MRR: ${delta.mrr > 0 ? '+' : ''}${mrrDelta}%\n`;
            message += `Hit@1: ${delta.hit1 > 0 ? '+' : ''}${hit1Delta}%\n\n`;

            // Promotion gating
            if (delta.mrr < -0.02 || delta.hit1 < -0.05) {
                message += '⚠️ WARNING: Metrics WORSE than baseline!\nConsider rolling back or retraining.\n\n';
                message += 'Learn more:\n• MRR Explanation: https://en.wikipedia.org/wiki/Mean_reciprocal_rank\n• Rollback Guide: /docs/RERANKER.md#rollback';
            } else if (delta.mrr > 0.02 || delta.hit1 > 0.05) {
                message += '✓ IMPROVEMENT detected!\nSafe to enable in production.\n\n';
                message += 'Next steps:\n• Save this as new baseline\n• Update AGRO_RERANKER_ENABLED=1 to enable';
            } else {
                message += '→ Marginal change. Consider more training data.\n\n';
                message += 'Tips:\n• Collect more user feedback\n• Add more golden questions\n• Increase training epochs';
            }

            alert(message);
        } else {
            const msg = window.ErrorHelpers ? window.ErrorHelpers.createAlertError('Baseline comparison failed', {
                message: 'No baseline found or comparison failed',
                causes: [
                    'No baseline model saved (use "Save Baseline" first)',
                    'Baseline evaluation data missing or corrupted',
                    'No current model to compare against baseline'
                ],
                fixes: [
                    'Save a baseline first using "Save Baseline" button',
                    'Train or load a model to compare',
                    'Verify both baseline and current model directories exist'
                ],
                links: [
                    ['Baseline Workflow', '/docs/RERANKER.md#baseline-workflow'],
                    ['Model Directory', '/models/cross-encoder-agro.baseline/']
                ]
            }) : 'No baseline found or comparison failed';
            alert(msg);
        }
    } catch (error) {
        const msg = window.ErrorHelpers ? window.ErrorHelpers.createAlertError('Error comparing baseline', {
            message: error.message,
            causes: ['Backend server not responding', 'Evaluation metrics unavailable', 'Network error'],
            fixes: ['Check server status', 'Ensure model is trained and evaluated', 'Check browser console'],
            links: [['Evaluation Guide', '/docs/RERANKER.md#evaluation']]
        }) : `Error: ${error.message}`;
        alert(msg);
    }
}

async function rollbackModel() {
    if (!confirm('Rollback to previous model?\n\nThis will restore models/cross-encoder-agro.baseline/ to the active model.\n\nIMPORTANT: You must restart the server after rollback for changes to take effect.\n\nContinue?')) return;
    try {
        const response = await fetch('/api/reranker/rollback', { method: 'POST' });
        const data = await response.json();
        if (data.ok) {
            alert('✓ Model rolled back successfully!\n\nNext steps:\n1. Restart the backend server (Infrastructure tab)\n2. Verify model version with a smoke test\n3. Consider saving a new baseline after verification\n\nThe baseline model is now your active model.');
        } else {
            const msg = window.ErrorHelpers ? window.ErrorHelpers.createAlertError('Rollback failed', {
                message: data.error || 'Failed to rollback model',
                causes: [
                    'No baseline model exists to rollback to',
                    'Insufficient permissions to modify model files',
                    'Model files are locked by running process',
                    'Baseline model is corrupted or incomplete'
                ],
                fixes: [
                    'Ensure a baseline exists (check models/cross-encoder-agro.baseline/)',
                    'Stop all training/evaluation processes',
                    'Check file permissions on models/ directory',
                    'Manually restore model files if necessary'
                ],
                links: [
                    ['Rollback Guide', '/docs/RERANKER.md#rollback'],
                    ['Model Management', '/docs/RERANKER.md#model-management']
                ]
            }) : `✗ ${data.error || 'Failed'}`;
            alert(msg);
        }
    } catch (error) {
        const msg = window.ErrorHelpers ? window.ErrorHelpers.createAlertError('Error during rollback', {
            message: error.message,
            causes: ['Backend server not responding', 'Network connectivity issues', 'API endpoint unavailable'],
            fixes: ['Check server status', 'Verify network connection', 'Check browser console for details'],
            links: [['Backend Health', '/api/health']]
        }) : `Error: ${error.message}`;
        alert(msg);
    }
}

// ============ SMOKE TEST ============

async function runSmokeTest() {
    const queryInput = document.getElementById('reranker-test-query');
    const resultDiv = document.getElementById('reranker-smoke-result');
    const query = queryInput?.value?.trim();
    
    if (!query) {
        alert('Enter a test query');
        return;
    }
    
    if (resultDiv) resultDiv.style.display = 'block';
    if (resultDiv) resultDiv.textContent = 'Running smoke test...';
    
    try {
        const response = await fetch('/api/reranker/smoketest', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ query: query })
        });
        const data = await response.json();
        
        if (resultDiv && data.ok) {
            resultDiv.innerHTML = `
                <div style="color:var(--accent); margin-bottom:8px;">✓ Smoke test passed!</div>
                <div>Query logged: ${data.logged ? '✓' : '✗'}</div>
                <div>Results retrieved: ${data.results_count || 0}</div>
                <div>Reranker applied: ${data.reranked ? '✓' : '✗'}</div>
                <div>Event ID: <code>${data.event_id || 'N/A'}</code></div>
                <div style="margin-top:8px; color:var(--fg-muted);">Full log entry created successfully.</div>
            `;
        } else if (resultDiv) {
            resultDiv.innerHTML = window.ErrorHelpers ? window.ErrorHelpers.createHelpfulError({
                title: 'Smoke test failed',
                message: data.error || 'Unknown error',
                causes: [
                    'Reranker is disabled (AGRO_RERANKER_ENABLED not set)',
                    'Model files are missing or corrupted',
                    'Insufficient resources to run reranker',
                    'Backend API endpoint not accessible'
                ],
                fixes: [
                    'Enable reranker with AGRO_RERANKER_ENABLED=1',
                    'Train or download a reranker model',
                    'Check server logs for detailed error messages',
                    'Verify backend server is running (Infrastructure tab)'
                ],
                links: [
                    ['Reranker Setup', '/docs/RERANKER.md#setup'],
                    ['Environment Variables', '/docs/CONFIGURATION.md#reranker'],
                    ['Troubleshooting', '/docs/RERANKER.md#troubleshooting']
                ]
            }) : `<div style="color:var(--err);">✗ Test failed: ${data.error || 'Unknown'}</div>`;
        }
    } catch (error) {
        if (resultDiv) {
            resultDiv.innerHTML = window.ErrorHelpers ? window.ErrorHelpers.createHelpfulError({
                title: 'Error running smoke test',
                message: error.message,
                causes: [
                    'Backend server is not running or not accessible',
                    'Network connectivity issues',
                    'Smoke test endpoint /api/reranker/smoketest unavailable',
                    'Request timeout (model loading can take time)'
                ],
                fixes: [
                    'Check server status in Infrastructure > Services tab',
                    'Verify network connection',
                    'Wait a moment and try again (first test may be slow)',
                    'Check browser console and server logs for details'
                ],
                links: [
                    ['Backend Health Check', '/api/health'],
                    ['Reranker API Docs', '/docs/API.md#reranker-smoketest'],
                    ['Server Logs', '/docs/DEBUGGING.md#server-logs']
                ]
            }) : `<div style="color:var(--err);">✗ Error: ${error.message}</div>`;
        }
    }
}

// ============ INITIALIZE ============

/**
 * ---agentspec
 * what: |
 *   Initializes reranker UI. Attaches click handler to mine button; disables button, updates text to "Mining...", then calls mineTriplets().
 *
 * why: |
 *   Centralizes UI event binding and state management for mining workflow.
 *
 * guardrails:
 *   - DO NOT re-enable button if mineTriplets() fails; add error handler
 *   - NOTE: Assumes reranker-mine-btn exists; will silently skip if missing
 * ---/agentspec
 */
function initRerankerUI() {
    // Mine button
    const mineBtn = document.getElementById('reranker-mine-btn');
    if (mineBtn) {
        mineBtn.addEventListener('click', async () => {
            mineBtn.disabled = true;
            mineBtn.textContent = 'Mining...';
            try {
                await mineTriplets();
            } catch (error) {
                alert(error.message);
            } finally {
                setTimeout(() => {
                    mineBtn.disabled = false;
                    mineBtn.textContent = 'Mine Triplets';
                }, 2000);
            }
        });
    }

    // Train button
    const trainBtn = document.getElementById('reranker-train-btn');
    if (trainBtn) {
        trainBtn.addEventListener('click', async () => {
            const epochs = parseInt(document.getElementById('reranker-epochs')?.value || '2');
            const batchSize = parseInt(document.getElementById('reranker-batch')?.value || '16');

            trainBtn.disabled = true;
            trainBtn.textContent = 'Training...';
            try {
                await trainReranker({ epochs, batch_size: batchSize });
            } catch (error) {
                alert(error.message);
            } finally {
                setTimeout(() => {
                    trainBtn.disabled = false;
                    trainBtn.textContent = 'Train Model';
                }, 2000);
            }
        });
    }

    // Eval button
    const evalBtn = document.getElementById('reranker-eval-btn');
    if (evalBtn) {
        evalBtn.addEventListener('click', async () => {
            evalBtn.disabled = true;
            evalBtn.textContent = 'Evaluating...';
            try {
                await evaluateReranker();
            } catch (error) {
                alert(error.message);
            } finally {
                setTimeout(() => {
                    evalBtn.disabled = false;
                    evalBtn.textContent = 'Evaluate';
                }, 2000);
            }
        });
    }

    // Log viewer buttons
    const viewLogsBtn = document.getElementById('reranker-view-logs');
    if (viewLogsBtn) viewLogsBtn.addEventListener('click', viewLogs);

    const downloadLogsBtn = document.getElementById('reranker-download-logs');
    if (downloadLogsBtn) downloadLogsBtn.addEventListener('click', downloadLogs);

    const clearLogsBtn = document.getElementById('reranker-clear-logs');
    if (clearLogsBtn) clearLogsBtn.addEventListener('click', clearLogs);

    // Automation buttons
    const setupCronBtn = document.getElementById('reranker-setup-cron');
    if (setupCronBtn) setupCronBtn.addEventListener('click', setupNightlyJob);

    const removeCronBtn = document.getElementById('reranker-remove-cron');
    if (removeCronBtn) removeCronBtn.addEventListener('click', removeNightlyJob);

    // Baseline buttons
    const saveBaselineBtn = document.getElementById('reranker-save-baseline');
    if (saveBaselineBtn) saveBaselineBtn.addEventListener('click', saveBaseline);

    const compareBaselineBtn = document.getElementById('reranker-compare-baseline');
    if (compareBaselineBtn) compareBaselineBtn.addEventListener('click', compareBaseline);

    const rollbackBtn = document.getElementById('reranker-rollback');
    if (rollbackBtn) rollbackBtn.addEventListener('click', rollbackModel);

    // Smoke test button
    const smokeTestBtn = document.getElementById('reranker-smoke-test');
    if (smokeTestBtn) smokeTestBtn.addEventListener('click', runSmokeTest);

    // Initialize terminal (lazy init, will be created when first needed)
    setTimeout(() => {
        initRerankerTerminal();
    }, 500);

    // Load initial stats
    setTimeout(updateRerankerStats, 100);
}

// Register with Navigation API
/**
 * ---agentspec
 * what: |
 *   Registers a reranker view with Navigation API. Mounts UI on callback, logs mount event.
 *
 * why: |
 *   Decouples view registration from initialization; allows Navigation to control lifecycle.
 *
 * guardrails:
 *   - DO NOT assume window.Navigation exists; guard with typeof check
 *   - NOTE: initRerankerUI() must be defined before mount() is called
 * ---/agentspec
 */
function registerRerankerView() {
    if (window.Navigation && typeof window.Navigation.registerView === 'function') {
        window.Navigation.registerView({
            id: 'rag-learning-ranker',
            title: 'Learning Ranker',
            mount: () => {
                console.log('[reranker.js] Mounted as rag-learning-ranker');
                initRerankerUI();
            },
            unmount: () => {
                console.log('[reranker.js] Unmounted');
                // No cleanup needed currently
            }
        });
    }
}

if (typeof window !== 'undefined') {
    window.addEventListener('DOMContentLoaded', () => {
        initRerankerUI();
        registerRerankerView();
    });
    // React bridge: initialize when RAG learning-ranker subtab becomes visible
    window.addEventListener('agro:reranker:mount', () => {
        try { initRerankerUI(); } catch (e) { console.warn('[reranker] init failed on mount event:', e); }
    });
    // Expose manual init for React components/tests
    window.RerankerUI = Object.assign({}, window.RerankerUI || {}, { init: initRerankerUI });
}

console.log('✓ Reranker module loaded');
