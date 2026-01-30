// Golden Questions Manager
// Handles CRUD operations for golden questions used in RAG evaluation

let goldenQuestions = [];

// Recommended questions (baseline for this repo)
const RECOMMENDED_GOLDEN = [
  { q: 'Where is hybrid retrieval implemented?', repo: 'agro', expect_paths: ['retrieval/hybrid_search.py'] },
  { q: 'Where is keyword generation handled server-side?', repo: 'agro', expect_paths: ['server/app.py','keywords/generate'] },
  { q: 'Where is the metadata enrichment logic for code/keywords?', repo: 'agro', expect_paths: ['metadata_enricher.py'] },
  { q: 'Where is the indexing pipeline (BM25 and dense) implemented?', repo: 'agro', expect_paths: ['indexer/index_repo.py'] },
  { q: 'Where is comprehensive index status computed?', repo: 'agro', expect_paths: ['server/app.py','server/index_stats.py','index/status'] },
  { q: 'Where are semantic cards built or listed?', repo: 'agro', expect_paths: ['server/app.py','api/cards','indexer/build_cards.py'] },
  { q: 'Where are golden questions API routes defined?', repo: 'agro', expect_paths: ['server/app.py','api/golden'] },
  { q: 'Where is the endpoint to test a single golden question?', repo: 'agro', expect_paths: ['server/app.py','api/golden/test'] },
  { q: 'Where are GUI assets mounted and served?', repo: 'agro', expect_paths: ['server/app.py','/gui','gui/index.html'] },
  { q: 'Where is repository configuration (repos.json) loaded?', repo: 'agro', expect_paths: ['config_loader.py'] },
  { q: 'Where are MCP stdio tools implemented (rag_answer, rag_search)?', repo: 'agro', expect_paths: ['server/mcp/server.py'] },
  { q: 'Where can I list or fetch latest LangGraph traces?', repo: 'agro', expect_paths: ['server/app.py','api/traces'] }
];

// Load all golden questions
async function loadGoldenQuestions() {
    try {
        const response = await fetch('/api/golden');
        const data = await response.json();
        goldenQuestions = data.questions || [];
        renderGoldenQuestions();
    } catch (error) {
        console.error('Failed to load golden questions:', error);
        document.getElementById('golden-questions-content').innerHTML =
            `<div style="color: var(--err);">Error loading questions: ${error.message}</div>`;
    }
}

// Render questions list
/**
 * ---agentspec
 * what: |
 *   Renders golden questions list to DOM. If empty, displays centered empty state with icon and muted text.
 *
 * why: |
 *   Conditional rendering prevents blank containers; empty state provides visual feedback.
 *
 * guardrails:
 *   - DO NOT mutate goldenQuestions array; read-only check
 *   - NOTE: Assumes container ID 'golden-questions-content' exists in DOM
 * ---/agentspec
 */
function renderGoldenQuestions() {
    const container = document.getElementById('golden-questions-content');

    if (goldenQuestions.length === 0) {
        container.innerHTML = `
            <div style="text-align: center; padding: 24px; color: var(--fg-muted);">
                <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" style="opacity: 0.3; margin-bottom: 12px;">
                    <circle cx="12" cy="12" r="10"></circle>
                    <line x1="12" y1="16" x2="12" y2="12"></line>
                    <line x1="12" y1="8" x2="12.01" y2="8"></line>
                </svg>
                <div>No golden questions yet. Add one above!</div>
            </div>
        `;
        return;
    }

    const html = goldenQuestions.map((q, index) => `
        <div class="golden-question-item" data-index="${index}" style="background: var(--card-bg); border: 1px solid var(--line); border-radius: 4px; padding: 12px; margin-bottom: 10px;">
            <div style="display: flex; justify-content: space-between; align-items: start; margin-bottom: 8px;">
                <div style="flex: 1;">
                    <div style="font-weight: 600; color: var(--fg); margin-bottom: 4px; word-break: break-word;">${escapeHtml(q.q)}</div>
                    <div style="font-size: 11px; color: var(--fg-muted);">
                        <span style="background: var(--bg-elev2); padding: 2px 6px; border-radius: 3px; margin-right: 6px;">${q.repo}</span>
                        ${(q.expect_paths || []).map(p => `<span style="color: var(--accent);">${escapeHtml(p)}</span>`).join(', ')}
                    </div>
                </div>
                <div style="display: flex; gap: 6px; margin-left: 12px;">
                    <button class="btn-test-question" data-index="${index}" style="background: var(--bg-elev2); color: var(--link); border: 1px solid var(--link); padding: 4px 8px; border-radius: 3px; font-size: 11px; cursor: pointer; white-space: nowrap;" title="Test this question">Test</button>
                    <button class="btn-edit-question" data-index="${index}" style="background: var(--bg-elev2); color: var(--warn); border: 1px solid var(--warn); padding: 4px 8px; border-radius: 3px; font-size: 11px; cursor: pointer;" title="Edit">Edit</button>
                    <button class="btn-delete-question" data-index="${index}" style="background: var(--bg-elev2); color: var(--err); border: 1px solid var(--err); padding: 4px 8px; border-radius: 3px; font-size: 11px; cursor: pointer;" title="Delete">✗</button>
                </div>
            </div>
            <div class="question-test-results" id="test-results-${index}" style="display: none; margin-top: 8px; padding-top: 8px; border-top: 1px solid var(--line);"></div>
        </div>
    `).join('');

    container.innerHTML = html;

    // Attach event listeners
    document.querySelectorAll('.btn-test-question').forEach(btn => {
        btn.addEventListener('click', (e) => testQuestion(parseInt(e.target.dataset.index)));
    });
    document.querySelectorAll('.btn-edit-question').forEach(btn => {
        btn.addEventListener('click', (e) => editQuestion(parseInt(e.target.dataset.index)));
    });
    document.querySelectorAll('.btn-delete-question').forEach(btn => {
        btn.addEventListener('click', (e) => deleteQuestion(parseInt(e.target.dataset.index)));
    });
}

// Add new question
async function addGoldenQuestion() {
    const q = document.getElementById('golden-new-q').value.trim();
    const repo = document.getElementById('golden-new-repo').value;
    const pathsStr = document.getElementById('golden-new-paths').value.trim();

    if (!q) {
        alert('Please enter a question');
        return;
    }

    const expect_paths = pathsStr ? pathsStr.split(',').map(p => p.trim()).filter(p => p) : [];

    try {
        const response = await fetch('/api/golden', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ q, repo, expect_paths })
        });

        const data = await response.json();
        if (data.ok) {
            // Clear form
            document.getElementById('golden-new-q').value = '';
            document.getElementById('golden-new-paths').value = '';

            // Reload questions
            await loadGoldenQuestions();

            showToast('Question added successfully', 'success');
        } else {
            throw new Error(data.error || 'Failed to add question');
        }
    } catch (error) {
        console.error('Failed to add question:', error);
        alert('Failed to add question: ' + error.message);
    }
}

// Test a single question
async function testQuestion(index) {
    const q = goldenQuestions[index];
    const resultsDiv = document.getElementById(`test-results-${index}`);
    resultsDiv.style.display = 'block';
    resultsDiv.innerHTML = '<div style="color: var(--fg-muted); font-size: 12px;">Testing...</div>';

    try {
        const response = await fetch('/api/golden/test', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                q: q.q,
                repo: q.repo,
                expect_paths: q.expect_paths,
                final_k: 5,
                use_multi: true
            })
        });

        const data = await response.json();

        const top1Color = data.top1_hit ? 'var(--accent)' : 'var(--err)';
        const topkColor = data.topk_hit ? 'var(--accent)' : 'var(--warn)';

        let html = `
            <div style="font-size: 12px;">
                <div style="margin-bottom: 8px;">
                    <span style="color: ${top1Color}; font-weight: 600;">${data.top1_hit ? '✓' : '✗'} Top-1</span>
                    <span style="margin-left: 12px; color: ${topkColor}; font-weight: 600;">${data.topk_hit ? '✓' : '✗'} Top-K</span>
                </div>
                <div style="font-size: 11px; color: var(--fg-muted);">
                    <div style="margin-bottom: 4px;"><strong>Expected:</strong> ${q.expect_paths.join(', ')}</div>
                    <div style="margin-bottom: 4px;"><strong>Top Result:</strong></div>
        `;

        if (data.all_results && data.all_results.length > 0) {
            data.all_results.slice(0, 3).forEach((r, i) => {
                const color = i === 0 && data.top1_hit ? 'var(--accent)' : 'var(--fg-muted)';
                html += `
                    <div style="color: ${color}; font-family: 'SF Mono', monospace; font-size: 10px; margin-left: 8px; margin-top: 2px;">
                        ${r.file_path}:${r.start_line} (score: ${r.rerank_score.toFixed(3)})
                    </div>
                `;
            });
        } else {
            html += '<div style="margin-left: 8px; color: var(--err);">No results found</div>';
        }

        html += `
                </div>
            </div>
        `;

        resultsDiv.innerHTML = html;
    } catch (error) {
        console.error('Test failed:', error);
        resultsDiv.innerHTML = `<div style="color: var(--err); font-size: 12px;">Error: ${error.message}</div>`;
    }
}

// Edit question (inline)
/**
 * ---agentspec
 * what: |
 *   Replaces question list item with inline edit form. Inputs: index. Outputs: DOM mutation (innerHTML swap).
 *
 * why: |
 *   Inline editing avoids modal overhead; direct DOM replacement keeps state in goldenQuestions array.
 *
 * guardrails:
 *   - DO NOT use innerHTML with unsanitized user input; XSS risk
 *   - NOTE: Form submission must sync back to goldenQuestions[index] before re-render
 *   - ASK USER: Confirm undo/cancel behavior on form close
 * ---/agentspec
 */
function editQuestion(index) {
    const q = goldenQuestions[index];
    const item = document.querySelector(`[data-index="${index}"]`);

    // Replace with edit form
    item.innerHTML = `
        <div style="background: var(--panel); padding: 12px; border-radius: 4px;">
            <div style="margin-bottom: 8px;">
                <label style="font-size: 11px; color: var(--fg-muted); display: block; margin-bottom: 4px;">Question</label>
                <textarea id="edit-q-${index}" style="width: 100%; background: var(--card-bg); border: 1px solid var(--line); color: var(--fg); padding: 8px; border-radius: 3px; font-size: 13px; min-height: 60px;">${escapeHtml(q.q)}</textarea>
            </div>
            <div style="display: grid; grid-template-columns: 1fr 2fr; gap: 8px; margin-bottom: 8px;">
                <div>
                    <label style="font-size: 11px; color: var(--fg-muted); display: block; margin-bottom: 4px;">Repo</label>
                    <select id="edit-repo-${index}" style="width: 100%; background: var(--card-bg); border: 1px solid var(--line); color: var(--fg); padding: 6px; border-radius: 3px;">
                        <option value="agro" ${q.repo === 'agro' ? 'selected' : ''}>agro</option>
                    </select>
                </div>
                <div>
                    <label style="font-size: 11px; color: var(--fg-muted); display: block; margin-bottom: 4px;">Expected Paths (comma-separated)</label>
                    <input type="text" id="edit-paths-${index}" value="${(q.expect_paths || []).join(', ')}" style="width: 100%; background: var(--card-bg); border: 1px solid var(--line); color: var(--fg); padding: 6px; border-radius: 3px; font-size: 12px;">
                </div>
            </div>
            <div style="display: flex; gap: 6px;">
                <button onclick="saveEditQuestion(${index})" style="flex: 1; background: var(--accent); color: var(--accent-contrast); border: none; padding: 8px; border-radius: 3px; font-size: 12px; font-weight: 600; cursor: pointer;">Save</button>
                <button onclick="loadGoldenQuestions()" style="flex: 1; background: var(--bg-elev2); color: var(--fg-muted); border: 1px solid var(--line); padding: 8px; border-radius: 3px; font-size: 12px; cursor: pointer;">Cancel</button>
            </div>
        </div>
    `;
}

// Save edited question
async function saveEditQuestion(index) {
    const q = document.getElementById(`edit-q-${index}`).value.trim();
    const repo = document.getElementById(`edit-repo-${index}`).value;
    const pathsStr = document.getElementById(`edit-paths-${index}`).value.trim();

    if (!q) {
        alert('Question cannot be empty');
        return;
    }

    const expect_paths = pathsStr ? pathsStr.split(',').map(p => p.trim()).filter(p => p) : [];

    try {
        const response = await fetch(`/api/golden/${index}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ q, repo, expect_paths })
        });

        const data = await response.json();
        if (data.ok) {
            await loadGoldenQuestions();
            showToast('Question updated', 'success');
        } else {
            throw new Error(data.error || 'Failed to update');
        }
    } catch (error) {
        console.error('Failed to update question:', error);
        alert('Failed to update: ' + error.message);
    }
}

// Delete question
async function deleteQuestion(index) {
    if (!confirm('Delete this question?')) return;

    try {
        const response = await fetch(`/api/golden/${index}`, {
            method: 'DELETE'
        });

        const data = await response.json();
        if (data.ok) {
            await loadGoldenQuestions();
            showToast('Question deleted', 'success');
        } else {
            throw new Error('Failed to delete');
        }
    } catch (error) {
        console.error('Failed to delete question:', error);
        alert('Failed to delete: ' + error.message);
    }
}

// Export questions as JSON
/**
 * ---agentspec
 * what: |
 *   Exports goldenQuestions array to JSON file. Creates blob, generates download link, triggers browser download, cleans up object URL.
 *
 * why: |
 *   Standard browser pattern for client-side file export without server round-trip.
 *
 * guardrails:
 *   - DO NOT call without user interaction; may be blocked by popup filters
 *   - NOTE: URL.revokeObjectURL must execute after click to prevent premature cleanup
 * ---/agentspec
 */
function exportGoldenQuestions() {
    const dataStr = JSON.stringify(goldenQuestions, null, 2);
    const blob = new Blob([dataStr], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'golden_questions_export.json';
    a.click();
    URL.revokeObjectURL(url);
    showToast('Questions exported', 'success');
}

// Helper: escape HTML
/**
 * ---agentspec
 * what: |
 *   Escapes HTML special characters by setting textContent on a DOM element, then reading innerHTML. Returns sanitized string safe for HTML insertion.
 *
 * why: |
 *   Leverages browser's native HTML parsing to avoid manual character mapping; showToast is stub for notification UI.
 *
 * guardrails:
 *   - DO NOT use for user-generated content in security-critical contexts; this is DOM-based escaping, not cryptographic sanitization
 *   - NOTE: showToast lacks implementation; add toast container and styling before production
 * ---/agentspec
 */
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// Helper: show toast notification
/**
 * ---agentspec
 * what: |
 *   Creates and displays a toast notification. Accepts message string and type ('info'|'success'|'error'). Renders fixed-position div with color mapped to type.
 *
 * why: |
 *   Centralizes toast UI logic; reusable across app for user feedback.
 *
 * guardrails:
 *   - DO NOT hardcode colors; use CSS vars (--accent, --err, --link, --panel)
 *   - NOTE: Fixed positioning may overlap; consider z-index and queue management
 *   - ASK USER: Should toasts auto-dismiss? Current code doesn't remove element.
 * ---/agentspec
 */
function showToast(message, type = 'info') {
    // Simple toast - you can enhance this
    const color = type === 'success' ? 'var(--accent)' : type === 'error' ? 'var(--err)' : 'var(--link)';
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

// Initialize when DOM is ready
if (typeof window !== 'undefined') {
    // Event listeners
    window.addEventListener('DOMContentLoaded', () => {
        const btnAdd = document.getElementById('btn-golden-add');
        const btnRefresh = document.getElementById('btn-golden-refresh');
        const btnExport = document.getElementById('btn-golden-export');
        const btnTestNew = document.getElementById('btn-golden-test-new');

    if (btnAdd) btnAdd.addEventListener('click', addGoldenQuestion);
    if (btnRefresh) btnRefresh.addEventListener('click', loadGoldenQuestions);
    if (btnExport) btnExport.addEventListener('click', exportGoldenQuestions);
    if (btnTestNew) {
            btnTestNew.addEventListener('click', async () => {
                const q = document.getElementById('golden-new-q').value.trim();
                const repo = document.getElementById('golden-new-repo').value;
                const pathsStr = document.getElementById('golden-new-paths').value.trim();

                if (!q) {
                    alert('Please enter a question');
                    return;
                }

                const expect_paths = pathsStr ? pathsStr.split(',').map(p => p.trim()).filter(p => p) : [];

                try {
                    const response = await fetch('/api/golden/test', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ q, repo, expect_paths, final_k: 5, use_multi: true })
                    });

                    const data = await response.json();
                    const result = data.top1_hit ? '✓ Top-1 Hit!' : data.topk_hit ? '✓ Top-K Hit' : '✗ Miss';
                    const color = data.top1_hit ? 'var(--accent)' : data.topk_hit ? 'var(--warn)' : 'var(--err)';
                    showToast(result, data.top1_hit ? 'success' : 'error');
                    console.log('Test result:', data);
                } catch (error) {
                    showToast('Test failed: ' + error.message, 'error');
                }
            });
        }

        const btnLoad = document.getElementById('btn-golden-load-recommended');
        if (btnLoad) btnLoad.addEventListener('click', bulkAddRecommended);
        const btnRunAll = document.getElementById('btn-golden-run-tests');
        if (btnRunAll) btnRunAll.addEventListener('click', runAllGoldenTests);

        // Auto-load on Tools tab activation
        const toolsTab = document.querySelector('[data-tab="tools"]');
        if (toolsTab) {
            toolsTab.addEventListener('click', () => {
                setTimeout(loadGoldenQuestions, 100);
            });
        }
    });
}

// Export for use in edit inline function
if (typeof window !== 'undefined') {
    window.saveEditQuestion = saveEditQuestion;
    window.bulkAddRecommended = bulkAddRecommended;
    window.runAllGoldenTests = runAllGoldenTests;
}

// ---- Bulk helpers ----
async function bulkAddRecommended() {
    try {
        let added = 0;
        for (const q of RECOMMENDED_GOLDEN) {
            const r = await fetch('/api/golden', {
                method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(q)
            });
            const d = await r.json();
            if (d && d.ok) added += 1;
        }
        await loadGoldenQuestions();
        showToast(`Loaded ${added} recommended questions`, added ? 'success' : 'error');
    } catch (e) {
        console.error('bulkAddRecommended failed', e);
        showToast('Failed to load recommended questions: ' + e.message, 'error');
    }
}

async function runAllGoldenTests() {
    try {
        const btn = document.getElementById('btn-golden-run-tests');
        if (btn) { btn.disabled = true; btn.style.opacity = '0.7'; btn.textContent = 'Running…'; }
        if (typeof showStatus === 'function') showStatus('Running all golden questions…', 'loading');
        if (!goldenQuestions.length) await loadGoldenQuestions();
        let top1 = 0, topk = 0, total = goldenQuestions.length;
        for (let i = 0; i < goldenQuestions.length; i++) {
            const q = goldenQuestions[i];
            const resp = await fetch('/api/golden/test', {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ q: q.q, repo: q.repo, expect_paths: q.expect_paths || [], final_k: 5, use_multi: true })
            });
            const data = await resp.json();
            if (data.top1_hit) top1 += 1; else if (data.topk_hit) topk += 1;
            // Paint per-question result under item
            const slot = document.getElementById(`test-results-${i}`);
            if (slot) {
                const color = data.top1_hit ? 'var(--accent)' : data.topk_hit ? 'var(--warn)' : 'var(--err)';
                slot.style.display = 'block';
                slot.innerHTML = `
                    <div style="font-size:12px;color:${color};">
                        ${data.top1_hit ? '✓ Top‑1 Hit' : data.topk_hit ? '✓ Top‑K Hit' : '✗ Miss'}
                        <span style="color:var(--fg-muted)"> — ${escapeHtml(q.q)}</span>
                    </div>
                `;
            }
        }
        const msg = `Golden tests: Top‑1 ${top1}/${total}, Top‑K ${topk}/${total}`;
        showToast(msg, 'success');
        if (typeof showStatus === 'function') showStatus(msg, 'success');
    } catch (e) {
        console.error('runAllGoldenTests failed', e);
        showToast('Run tests failed: ' + e.message, 'error');
    } finally {
        const btn = document.getElementById('btn-golden-run-tests');
        if (btn) { btn.disabled = false; btn.style.opacity = ''; btn.textContent = 'Run All Tests'; }
    }
}

// Initialization function for rag-evaluate view (PRIMARY module)
window.initGoldenQuestions = function() {
    console.log('[golden_questions.js] Initializing golden questions for rag-evaluate view');
    loadGoldenQuestions();
    bindGoldenQuestions();
};

// Register view (PRIMARY module for rag-evaluate)
if (window.Navigation && typeof window.Navigation.registerView === 'function') {
    window.Navigation.registerView({
        id: 'rag-evaluate',
        title: 'Evaluate',
        mount: () => {
            console.log('[golden_questions.js] Mounted rag-evaluate view');
            // Initialize golden questions (primary)
            if (typeof window.initGoldenQuestions === 'function') window.initGoldenQuestions();
            // Initialize eval runner
            if (typeof window.initEvalRunner === 'function') window.initEvalRunner();
        },
        unmount: () => {
            console.log('[golden_questions.js] Unmounted from rag-evaluate');
        }
    });
} else {
    console.warn('[golden_questions.js] Navigation API not available, falling back to legacy mode');
    // Legacy mode: auto-init
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => {
            loadGoldenQuestions();
            bindGoldenQuestions();
        });
    } else {
        loadGoldenQuestions();
        bindGoldenQuestions();
    }
}

// Defensive binding via event delegation (in case direct bind missed)
document.addEventListener('click', (e) => {
    const run = e.target && (e.target.id === 'btn-golden-run-tests' || (e.target.closest && e.target.closest('#btn-golden-run-tests')));
    const load = e.target && (e.target.id === 'btn-golden-load-recommended' || (e.target.closest && e.target.closest('#btn-golden-load-recommended')));
    if (run) { e.preventDefault(); runAllGoldenTests(); }
    if (load) { e.preventDefault(); bulkAddRecommended(); }
}, true);

console.log('[golden_questions.js] Module loaded (PRIMARY for rag-evaluate, coordinates eval_runner.js)');
