// AGRO GUI - Config Module
// Handles configuration form loading, population, and saving

(function () {
    'use strict';

    // Import utilities
    const { api, $, $$, state } = window.CoreUtils || {};

    if (!api || !$ || !$$ || !state) {
        console.error('[config.js] CoreUtils not loaded!');
        return;
    }

    /**
     * Load configuration from API and populate form
     */
    async function loadConfig() {
        try {
            try { await fetch(api('/api/env/reload'), { method: 'POST' }); } catch {}
            const r = await fetch(api('/api/config'));
            const d = await r.json();
            state.config = d;
            populateConfigForm(d);
            // Apply theme after fields are populated so selects reflect env
            if (window.Theme?.initThemeFromEnv) {
                window.Theme.initThemeFromEnv(d.env || {});
            }
        } catch (e) {
            const msg = window.ErrorHelpers ? window.ErrorHelpers.createAlertError('Failed to load configuration', {
                message: e.message,
                causes: [
                    'Backend API server is not running or not responding',
                    'Configuration file is missing or corrupted',
                    'Network connectivity issue or DNS resolution failure',
                    'Invalid JSON in response from configuration endpoint'
                ],
                fixes: [
                    'Verify backend service is running: check Infrastructure tab',
                    'Check backend logs for configuration loading errors',
                    'Verify network connectivity and firewall rules',
                    'Refresh the page and try loading configuration again'
                ],
                links: [
                    ['Fetch API Documentation', 'https://developer.mozilla.org/en-US/docs/Web/API/Fetch_API'],
                    ['JSON Parsing Guide', 'https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Global_Objects/JSON/parse']
                ]
            }) : `Failed to load config: ${e.message}`;
            console.error('[config.js] Failed to load config:', msg);
        }
    }

    /**
     * Populate config form fields from data
     * @param {Object} data - Config data with env and repos
     */
    /**
     * ---agentspec
     * what: |
     *   Populates HTML form fields from env object. Iterates over key-value pairs, matches to form inputs by name attribute, sets values (handles checkboxes).
     *
     * why: |
     *   Centralizes config hydration logic; decouples data structure from DOM manipulation.
     *
     * guardrails:
     *   - DO NOT assume all env keys have corresponding form fields; silently skip missing fields
     *   - NOTE: Checkbox handling incomplete; only iterates, does not set checked state
     *   - ASK USER: Should non-checkbox fields validate type before assignment?
     * ---/agentspec
     */
    function populateConfigForm(data) {
        const env = data.env || {};

        // Fill all env variable fields
        Object.entries(env).forEach(([k, v]) => {
            const field = document.querySelector(`[name="${k}"]`);
            if (!field) return;

            if (field.type === 'checkbox') {
                field.checked = String(v).toLowerCase() === 'true' || v === '1' || v === true;
            } else if (field.tagName === 'SELECT') {
                field.value = v;
            } else {
                field.value = v;
            }
        });

        // Populate repo select
        const repoSelect = $('#repo-select');
        if (repoSelect) {
            repoSelect.innerHTML = '';
            (data.repos || []).forEach((repo) => {
                const opt = document.createElement('option');
                opt.value = repo.name;
                opt.textContent = repo.name;
                repoSelect.appendChild(opt);
            });
            if (env.REPO) {
                repoSelect.value = env.REPO;
            } else if (data.default_repo) {
                repoSelect.value = data.default_repo;
            }
        }

        // Seed Cards Builder defaults
        try {
            const def = String(env.CARDS_ENRICH_DEFAULT ?? '1');
            const sel = document.getElementById('cards-enrich-default'); if (sel) sel.value = def;
            const chk = document.getElementById('cards-enrich-toggle'); if (chk) chk.checked = def === '1';
        } catch {}

        // Seed cost panel defaults from pricing if fields are empty
        if (state.models && Array.isArray(state.models.models) && state.models.models.length) {
            const costProviderEl = $('#cost-provider');
            const costModelEl = $('#cost-model');
            if (costProviderEl && !costProviderEl.value) costProviderEl.value = state.models.models[0].provider || '';
            if (costModelEl && !costModelEl.value) costModelEl.value = state.models.models[0].model || '';
        }

        // Cost panel autopopulate from env
        try {
            // Generation provider heuristic: use GEN_MODEL hint if present; otherwise env keys
            let provGuess = '';
            const gm = env.GEN_MODEL || '';
            if (/^gpt-|^o\w+:/i.test(gm)) provGuess = 'openai';
            else if (/^claude/i.test(gm)) provGuess = 'anthropic';
            else if (/^gemini/i.test(gm)) provGuess = 'google';
            else if (env.OLLAMA_URL) provGuess = 'local';
            else if (env.OPENAI_API_KEY) provGuess = 'openai';
            else if (env.ANTHROPIC_API_KEY) provGuess = 'anthropic';
            else if (env.GOOGLE_API_KEY) provGuess = 'google';
            if (provGuess) {
                const provEl = $('#cost-provider');
                if (provEl) provEl.value = provGuess;
            }
            if (env.GEN_MODEL) {
                const modelEl = $('#cost-model');
                if (modelEl) modelEl.value = env.GEN_MODEL;
            }

            // Embeddings
            if (env.EMBEDDING_TYPE) {
                const ep = document.getElementById('cost-embed-provider'); if (ep) ep.value = env.EMBEDDING_TYPE;
                if (env.EMBEDDING_TYPE === 'openai' && document.getElementById('cost-embed-model') && !$('#cost-embed-model').value) $('#cost-embed-model').value = 'text-embedding-3-small';
                if (env.EMBEDDING_TYPE === 'voyage' && document.getElementById('cost-embed-model') && !$('#cost-embed-model').value) $('#cost-embed-model').value = 'voyage-3-large-embed';
            }
            // Reranker
            if (env.RERANK_BACKEND) {
                const rp = document.getElementById('cost-rerank-provider'); if (rp) rp.value = env.RERANK_BACKEND;
            }
            if (env.COHERE_RERANK_MODEL && document.getElementById('cost-rerank-model')) $('#cost-rerank-model').value = env.COHERE_RERANK_MODEL;
            if (env.RERANKER_MODEL && document.getElementById('cost-rerank-model') && !$('#cost-rerank-model').value) $('#cost-rerank-model').value = env.RERANKER_MODEL;
        } catch {}

        // Wizard defaults: seed from env
        try {
            if (typeof window.seedWizardFromEnv === 'function') {
                window.seedWizardFromEnv(env);
            }
        } catch {}
        if (typeof window.updateWizardSummary === 'function') {
            window.updateWizardSummary();
        }

        // Populate repos metadata editor (deferred until element exists)
        window.populateReposSection = function(data) {
            const reposSection = $('#repos-section');
            if (!reposSection) {
                return false; // Element doesn't exist yet
            }
            reposSection.innerHTML = '';
            (data.repos || []).forEach((repo) => {
                const div = document.createElement('div');
                div.style.cssText = 'background: var(--card-bg); border: 1px solid var(--line); border-radius: 6px; padding: 16px; margin-bottom: 16px;';
                const rname = repo.name;
                div.innerHTML = `
                    <h4 style="color: var(--accent); font-size: 14px; margin-bottom: 12px;">Repo: ${repo.name}</h4>
                    <div class="input-group" style="margin-bottom: 12px;">
                        <label>Path</label>
                        <input type="text" name="repo_path_${repo.name}" value="${repo.path || ''}" />
                    </div>
                    <div class="input-group" style="margin-bottom: 12px;">
                        <label>Keywords (comma-separated)</label>
                        <input type="text" name="repo_keywords_${repo.name}" value="${(repo.keywords||[]).join(',')}" list="keywords-list" placeholder="search or type to add" />
                    </div>
                    <div class="input-group" style="margin-bottom: 12px;">
                        <label>Path Boosts (comma-separated)</label>
                        <input type="text" name="repo_pathboosts_${repo.name}" value="${(repo.path_boosts||[]).join(',')}" />
                    </div>
                    <div class="input-group">
                        <label>Layer Bonuses (JSON)</label>
                        <textarea name="repo_layerbonuses_${repo.name}" rows="3">${repo.layer_bonuses ? JSON.stringify(repo.layer_bonuses, null, 2) : ''}</textarea>
                    </div>
                    <div class="input-group full-width" style="margin-top:12px;">
                        <label>Keyword Manager</label>
                        <div style="display:grid; grid-template-columns: 1fr auto 1fr; gap:8px; align-items:center;">
                            <div>
                                <div style="display:flex; gap:6px; margin-bottom:6px;">
                                    <input type="text" id="kw-filter-${rname}" placeholder="filter..." style="width:60%;">
                                    <select id="kw-src-${rname}">
                                        <option value="all">All</option>
                                        <option value="discriminative">Discriminative</option>
                                        <option value="semantic">Semantic</option>
                                        <option value="repos">Repo</option>
                                    </select>
                                    <button class="small-button" id="kw-new-${rname}" style="background:var(--accent); color: var(--accent-contrast); padding:4px 8px; font-size:11px;" title="Add New Keyword">+</button>
                                </div>
                                <select id="kw-all-${rname}" multiple size="8" style="width:100%;"></select>
                            </div>
                            <div style="display:flex; flex-direction:column; gap:8px;">
                                <button class="small-button" id="kw-add-${rname}">&gt;&gt;</button>
                                <button class="small-button" id="kw-rem-${rname}">&lt;&lt;</button>
                            </div>
                            <div>
                                <div class="small" style="margin-bottom:6px;">Repo Keywords</div>
                                <select id="kw-repo-${rname}" multiple size="8" style="width:100%;"></select>
                            </div>
                        </div>
                    </div>
                `;
                reposSection.appendChild(div);

                // Hook keyword manager events
                const fld = div.querySelector(`[name="repo_keywords_${rname}"]`);
                const allSel = div.querySelector(`#kw-all-${rname}`);
                const repoSel = div.querySelector(`#kw-repo-${rname}`);
                const srcSel = div.querySelector(`#kw-src-${rname}`);
                // Ensure LLM source option is available
                try {
                    if (srcSel && !Array.from(srcSel.options).some(o => o.value === 'llm')) {
                        const opt = document.createElement('option');
                        opt.value = 'llm';
                        opt.textContent = 'LLM';
                        const before = Array.from(srcSel.options).find(o => o.value === 'repos');
                        if (before) srcSel.insertBefore(opt, before); else srcSel.appendChild(opt);
                    }
                } catch {}
                const filter = div.querySelector(`#kw-filter-${rname}`);
                const addBtn = div.querySelector(`#kw-add-${rname}`);
                const remBtn = div.querySelector(`#kw-rem-${rname}`);
                const newBtn = div.querySelector(`#kw-new-${rname}`);

                function currentRepoKws() {
                    return (fld.value || '').split(',').map(s => s.trim()).filter(Boolean);
                }
                function setRepoKws(arr) {
                    fld.value = arr.join(',');
                    // repaint repo list
                    repoSel.innerHTML = '';
                    arr.forEach(k => { const o=document.createElement('option'); o.value=k; o.textContent=k; repoSel.appendChild(o); });
                }
                function sourceList() {
                    const cat = (srcSel.value||'all');
                    const catMap = (state.keywordsCatalog||{});
                    let base = [];
                    if (cat === 'all') base = catMap.keywords||[]; else base = catMap[cat]||[];
                    const f = (filter.value||'').toLowerCase();
                    const inRepo = new Set(currentRepoKws());
                    return base.filter(k => !inRepo.has(k) && (!f || k.toLowerCase().includes(f)));
                }
                function paintSource() {
                    allSel.innerHTML = '';
                    sourceList().slice(0,500).forEach(k => { const o=document.createElement('option'); o.value=k; o.textContent=k; allSel.appendChild(o); });
                }
                addBtn.addEventListener('click', () => {
                    const cur = currentRepoKws();
                    const selected = Array.from(allSel.selectedOptions).map(o=>o.value);
                    const next = Array.from(new Set([...cur, ...selected]));
                    setRepoKws(next); paintSource();
                });
                remBtn.addEventListener('click', () => {
                    const cur = currentRepoKws();
                    const remove = new Set(Array.from(repoSel.selectedOptions).map(o=>o.value));
                    const next = cur.filter(k => !remove.has(k));
                    setRepoKws(next); paintSource();
                });
                srcSel.addEventListener('change', paintSource);
                filter.addEventListener('input', paintSource);

                // Handle add new keyword button
                newBtn.addEventListener('click', () => {
                    // Create a custom dialog for adding keywords
                    const dialog = document.createElement('div');
                    dialog.style.cssText = `
                        position: fixed;
                        top: 50%;
                        left: 50%;
                        transform: translate(-50%, -50%);
                        background: var(--card-bg);
                        border: 1px solid var(--accent);
                        border-radius: 8px;
                        padding: 20px;
                        z-index: 10000;
                        min-width: 300px;
                        box-shadow: 0 8px 24px rgba(0,0,0,0.8);
                    `;

                    dialog.innerHTML = `
                        <h4 style="color: var(--accent); margin-bottom: 16px;">Add New Keyword</h4>
                        <div style="margin-bottom: 12px;">
                            <label style="display: block; color: var(--fg-muted); font-size: 11px; margin-bottom: 4px;">Keyword</label>
                            <input type="text" id="new-kw-input" style="width: 100%; background: var(--bg-elev2); border: 1px solid var(--line); color: var(--fg); padding: 8px; border-radius: 4px;" placeholder="Enter keyword...">
                        </div>
                        <div style="margin-bottom: 16px;">
                            <label style="display: block; color: var(--fg-muted); font-size: 11px; margin-bottom: 4px;">Category (optional)</label>
                            <select id="new-kw-category" style="width: 100%; background: var(--bg-elev2); border: 1px solid var(--line); color: var(--fg); padding: 8px; border-radius: 4px;">
                                <option value="">None (appears in All only)</option>
                                <option value="discriminative">Discriminative</option>
                                <option value="semantic">Semantic</option>
                            </select>
                        </div>
                        <div style="display: flex; gap: 8px; justify-content: flex-end;">
                            <button id="cancel-kw" style="background: var(--bg-elev2); color: var(--fg-muted); border: 1px solid var(--line); padding: 6px 16px; border-radius: 4px; cursor: pointer;">Cancel</button>
                            <button id="add-kw" style="background: var(--accent); color: var(--accent-contrast); border: none; padding: 6px 16px; border-radius: 4px; cursor: pointer; font-weight: 600;">Add</button>
                        </div>
                    `;

                    // Add backdrop
                    const backdrop = document.createElement('div');
                    backdrop.style.cssText = 'position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: rgba(0,0,0,0.5); z-index: 9999;';

                    document.body.appendChild(backdrop);
                    document.body.appendChild(dialog);

                    const input = dialog.querySelector('#new-kw-input');
                    const categorySelect = dialog.querySelector('#new-kw-category');
                    const addButton = dialog.querySelector('#add-kw');
                    const cancelButton = dialog.querySelector('#cancel-kw');

                    // Focus input
                    input.focus();

                    const cleanup = () => {
                        document.body.removeChild(dialog);
                        document.body.removeChild(backdrop);
                    };

                    const addKeyword = async () => {
                        const newKeyword = input.value.trim();
                        const category = categorySelect.value;

                        if (newKeyword) {
                            // Add to global catalog if not exists
                            if (!state.keywordsCatalog) state.keywordsCatalog = { keywords: [] };
                            if (!state.keywordsCatalog.keywords) state.keywordsCatalog.keywords = [];

                            // Add to the 'all' category if not already there
                            if (!state.keywordsCatalog.keywords.includes(newKeyword)) {
                                state.keywordsCatalog.keywords.push(newKeyword);
                                state.keywordsCatalog.keywords.sort();

                                // Also add to specific category if selected
                                if (category) {
                                    if (!state.keywordsCatalog[category]) state.keywordsCatalog[category] = [];
                                    if (!state.keywordsCatalog[category].includes(newKeyword)) {
                                        state.keywordsCatalog[category].push(newKeyword);
                                        state.keywordsCatalog[category].sort();
                                    }
                                }

                                // Update the datalist for autocomplete
                                const list = document.getElementById('keywords-list');
                                if (list) {
                                    const opt = document.createElement('option');
                                    opt.value = newKeyword;
                                    list.appendChild(opt);
                                }

                                // Update keywords count display
                                const kc = document.getElementById('keywords-count');
                                if (kc) kc.textContent = String(state.keywordsCatalog.keywords.length);

                                // Save to server for persistence
                                try {
                                    if (typeof window.showStatus === 'function') {
                                        const response = await fetch(api('/api/keywords/add'), {
                                            method: 'POST',
                                            headers: { 'Content-Type': 'application/json' },
                                            body: JSON.stringify({ keyword: newKeyword, category: category })
                                        });
                                        const result = await response.json();
                                        if (result.ok) {
                                            window.showStatus(`Added keyword: ${newKeyword}${category ? ` (${category})` : ''}`, 'success');
                                        } else {
                                            window.showStatus(`Failed to persist keyword: ${result.error}`, 'warning');
                                        }
                                    }
                                } catch (e) {
                                    const msg = window.ErrorHelpers ? window.ErrorHelpers.createAlertError('Failed to persist keyword to server', {
                                        message: e.message,
                                        causes: [
                                            'Backend API service is not running or responding',
                                            'Keywords database connection failed',
                                            'Network connectivity issue or timeout',
                                            'Invalid or duplicate keyword in the system'
                                        ],
                                        fixes: [
                                            'Verify backend service is running in Infrastructure tab',
                                            'Check database connectivity and status',
                                            'Verify network connectivity between frontend and backend',
                                            'Try adding a different keyword or refresh the page'
                                        ],
                                        links: [
                                            ['Fetch API Documentation', 'https://developer.mozilla.org/en-US/docs/Web/API/Fetch_API']
                                        ]
                                    }) : `Failed to save keyword to server: ${e.message}`;
                                    console.warn('[config.js] Failed to save keyword:', msg);
                                }
                            }

                            // Refresh the source list to show the new keyword
                            paintSource();

                            // Select the new keyword in the all list if visible
                            setTimeout(() => {
                                const options = Array.from(allSel.options);
                                const newOption = options.find(o => o.value === newKeyword);
                                if (newOption) {
                                    newOption.selected = true;
                                    // Auto-focus to make it visible
                                    allSel.focus();
                                }
                            }, 100);

                            cleanup();
                        }
                    };

                    // Event handlers
                    addButton.addEventListener('click', addKeyword);
                    cancelButton.addEventListener('click', cleanup);
                    input.addEventListener('keydown', (e) => {
                        if (e.key === 'Enter') addKeyword();
                        if (e.key === 'Escape') cleanup();
                    });
                });

                // initial fill using existing values + catalog (if loaded later, loadKeywords will repaint)
                setRepoKws((repo.keywords||[]));
                if (state.keywordsCatalog) paintSource();
            });
            return true;
        };

        // Try to populate repos section immediately, or retry until element exists
        if (!window.populateReposSection(data)) {
            let retries = 0;
            const retryPopulate = setInterval(() => {
                if (window.populateReposSection(data) || ++retries > 50) {
                    clearInterval(retryPopulate);
                }
            }, 100);
        }

        // Attach tooltips after DOM is populated
        try { window.Tooltips && window.Tooltips.attachTooltips && window.Tooltips.attachTooltips(); } catch {}
    }

    /**
     * Gather form data into config update object
     * @returns {Object|null} Config update object or null if validation fails
     */
    /**
     * ---agentspec
     * what: |
     *   Collects environment variables from form fields (excluding repo_* fields). Builds update object with env dict and repos array.
     *
     * why: |
     *   Separates env config from repo config by filtering field name prefixes.
     *
     * guardrails:
     *   - DO NOT assume all form fields are env vars; filter repo_* prefix correctly
     *   - NOTE: Incomplete—missing value extraction logic and repos population
     *   - ASK USER: Should null/empty env values be included or skipped?
     * ---/agentspec
     */
    function gatherConfigForm() {
        const update = { env: {}, repos: [] };

        // Gather all env vars from form
        const envFields = $$('[name]').filter(f => !f.name.startsWith('repo_'));
        envFields.forEach(field => {
            const key = field.name;
            let val;

            if (field.type === 'checkbox') {
                val = field.checked;
            } else if (field.type === 'number') {
                val = field.value;
            } else {
                val = field.value;
            }

            if (val !== '' && val !== null && val !== undefined) {
                update.env[key] = val;
            }
        });

        // Gather repo-specific fields
        const repoFields = $$('[name^="repo_"]');
        const repoMap = {};

        repoFields.forEach(field => {
            const parts = field.name.split('_');
            const fieldType = parts[1]; // path, keywords, pathboosts, layerbonuses
            const repoName = parts.slice(2).join('_');

            if (!repoMap[repoName]) {
                repoMap[repoName] = { name: repoName };
            }

            if (fieldType === 'keywords' || fieldType === 'pathboosts') {
                const key = fieldType === 'pathboosts' ? 'path_boosts' : 'keywords';
                repoMap[repoName][key] = field.value.split(',').map(s => s.trim()).filter(Boolean);
            } else if (fieldType === 'layerbonuses') {
                try {
                    repoMap[repoName]['layer_bonuses'] = field.value ? JSON.parse(field.value) : {};
                } catch (e) {
                    alert(`Invalid JSON for ${repoName} layer_bonuses: ${e.message}`);
                    return null;
                }
            } else if (fieldType === 'path') {
                repoMap[repoName]['path'] = field.value;
            }
        });

        update.repos = Object.values(repoMap);
        return update;
    }

    /**
     * Save configuration to API
     */
    async function saveConfig() {
        const body = gatherConfigForm();
        if (!body) return;

        try {
            const r = await fetch(api('/api/config'), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body)
            });

            if (!r.ok) {
                let detail = 'Save failed';
                try {
                    const err = await r.json();
                    detail = err?.detail || err?.error || detail;
                } catch (e) {}
                alert(detail);
                return;
            }

            const result = await r.json();
            if (result.status === 'success') {
                alert('Configuration updated successfully!');
                await loadConfig(); // Reload to confirm
            } else if (result.status === 'error') {
                alert(result.error || 'Save failed');
            }
        } catch (e) {
            const msg = window.ErrorHelpers ? window.ErrorHelpers.createAlertError('Failed to save configuration', {
                message: e.message,
                causes: [
                    'Backend configuration API service is unavailable',
                    'Invalid configuration values submitted in form',
                    'Backend validation rejected the configuration changes',
                    'Insufficient permissions to save configuration'
                ],
                fixes: [
                    'Verify all required fields are filled with valid values',
                    'Check backend logs for validation error details',
                    'Verify backend service is running in Infrastructure tab',
                    'Ensure you have proper permissions to modify configuration'
                ],
                links: [
                    ['Fetch API Documentation', 'https://developer.mozilla.org/en-US/docs/Web/API/Fetch_API'],
                    ['JSON Stringification Guide', 'https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Global_Objects/JSON/stringify']
                ]
            }) : `Error saving config: ${e.message}`;
            alert(msg);
            console.error('[config.js] Failed to save config:', msg);
        }
    }

    // Split initialization based on which view is active
    /**
     * ---agentspec
     * what: |
     *   Initializes config retrieval view. Loads config, calls initModelFlows if available. Prepares UI for RAG retrieval workflows.
     *
     * why: |
     *   Centralizes startup logic for retrieval-specific initialization in one entry point.
     *
     * guardrails:
     *   - DO NOT assume initModelFlows exists; guard with typeof check (already done)
     *   - NOTE: Future retrieval UI init belongs here, not scattered in handlers
     * ---/agentspec
     */
    function initConfigRetrieval() {
        console.log('[config.js] Initializing for rag-retrieval view');
        loadConfig();
        // Initialize model flows module
        if (typeof window.initModelFlows === 'function') window.initModelFlows();
        // Future: Add retrieval-specific UI initialization here
    }

    // Register for rag-retrieval tab
    if (window.Navigation && typeof window.Navigation.registerView === 'function') {
        window.Navigation.registerView({
            id: 'rag-retrieval',
            title: 'Retrieval',
            mount: () => {
                console.log('[config.js] Mounted for rag-retrieval');
                initConfigRetrieval();
            },
            unmount: () => {
                console.log('[config.js] Unmounted from rag-retrieval');
            }
        });
    } else {
        console.warn('[config.js] Navigation API not available, falling back to legacy mode');
        // Legacy mode: initialize immediately
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', loadConfig);
        } else {
            loadConfig();
        }
    }

    // Export to window
    window.Config = {
        loadConfig,
        populateConfigForm,
        gatherConfigForm,
        saveConfig,
        initConfigRetrieval
    };

    console.log('[config.js] Module loaded (rag-retrieval)');
})();
