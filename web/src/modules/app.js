// AGRO GUI app.js (main coordinator - modularized)
;(function () {
    'use strict';

    // Import core utilities from CoreUtils module
    const { api, $, $$, state } = window.CoreUtils || {};

    if (!api || !$ || !$$) {
        console.error('[app.js] CoreUtils not loaded! Make sure core-utils.js loads first.');
        return;
    }

    console.log('[app.js] Initializing with API:', window.CoreUtils.API_BASE);

    // ---------------- Theme Engine ----------------
    // Delegated to Theme module (gui/js/theme.js)
    const resolveTheme = window.Theme?.resolveTheme || (() => 'dark');
    const applyTheme = window.Theme?.applyTheme || (() => {});
    const initThemeFromEnv = window.Theme?.initThemeFromEnv || (() => {});

    // ---------------- Tabs ----------------
    // Delegated to Tabs module (gui/js/tabs.js)
    const switchTab = window.Tabs?.switchTab || (() => {});
    const bindTabs = window.Tabs?.bindTabs || (() => {});
    const bindSubtabs = window.Tabs?.bindSubtabs || (() => {});

    // ---------------- Tooltips (modular) ----------------
    // Delegates to external module /gui/js/tooltips.js

    // ---------------- Global Search ----------------
    // Delegated to Search module (gui/js/search.js)
    const clearHighlights = window.Search?.clearHighlights || (() => {});
    const highlightMatches = window.Search?.highlightMatches || (() => {});
    const bindGlobalSearch = window.Search?.bindGlobalSearch || (() => {});

    // ---------------- Git Hooks ----------------
    // Delegated to GitHooks module (gui/js/git-hooks.js)
    const refreshHooksStatus = window.GitHooks?.refreshHooksStatus || (async () => {});
    const installHooks = window.GitHooks?.installHooks || (async () => {});

    // ---------------- Health ----------------
    // Delegated to Health module (gui/js/health.js)
    const checkHealth = window.Health?.checkHealth || (async () => {});

    // ---------------- Routing Trace Panel ----------------
    // Delegated to Trace module (gui/js/trace.js)
    const loadLatestTrace = window.Trace?.loadLatestTrace || (async ()=>{});

    // ---------------- Chat ----------------
    // DISABLED: Chat is now handled by React ChatInterface component
    // These legacy functions are retained for reference only
    /**
     * ---agentspec
     * what: |
     *   Appends chat message DOM element to #chat-messages container. Takes role (user/assistant) and text; skips if React ChatInterface active.
     *
     * why: |
     *   Provides fallback DOM-based chat rendering when React component not present.
     *
     * guardrails:
     *   - DO NOT append if data-react-chat="true"; React owns the DOM
     *   - NOTE: Silent no-op if #chat-messages missing; add error logging if needed
     * ---/agentspec
     */
    function appendChatMessage(role, text){
        // Skip if React ChatInterface is managing the chat
        if (document.querySelector('[data-react-chat="true"]')) return;
        const box = document.getElementById('chat-messages'); if (!box) return;
        const wrap = document.createElement('div');
        wrap.style.marginBottom = '12px';
        const who = document.createElement('div');
        who.style.fontSize = '11px';
        who.style.color = role === 'user' ? 'var(--link)' : 'var(--accent)';
        who.style.textTransform = 'uppercase';
        who.style.letterSpacing = '0.5px';
        who.textContent = role === 'user' ? 'You' : 'Assistant';
        const msg = document.createElement('div');
        msg.style.background = 'var(--code-bg)';
        msg.style.border = '1px solid var(--line)';
        msg.style.borderRadius = '6px';
        msg.style.padding = '10px';
        msg.style.whiteSpace = 'pre-wrap';
        msg.textContent = text;
        wrap.appendChild(who); wrap.appendChild(msg);
        box.appendChild(wrap);
        // auto-scroll if near bottom
        try { box.scrollTop = box.scrollHeight; } catch { /* no-op */ }
    }

    async function sendChat(){
        // Skip if React ChatInterface is managing the chat
        if (document.querySelector('[data-react-chat="true"]')) return;
        const ta = document.getElementById('chat-input'); if (!ta) return;
        const q = (ta.value || '').trim(); if (!q) return;
        appendChatMessage('user', q);
        ta.value = '';
        const repoSel = document.getElementById('chat-repo-select');
        const repo = repoSel && repoSel.value ? repoSel.value : undefined;
        try{
            const qs = new URLSearchParams({ q });
            if (repo) qs.set('repo', repo);
            const r = await fetch(api(`/answer?${qs.toString()}`));
            const d = await r.json();
            const text = (d && d.answer) ? d.answer : '—';
            appendChatMessage('assistant', text);
            // load trace if the dropdown is open
            const det = document.getElementById('chat-trace');
            if (det && det.open){ await loadLatestTrace('chat-trace-output'); }
            // optional auto-open in LangSmith (use latest shared run URL)
            try{
                const env = (state.config?.env)||{};
                if ((env.TRACING_MODE||'').toLowerCase()==='langsmith' && ['1','true','on'].includes(String(env.TRACE_AUTO_LS||'0').toLowerCase())){
                    const prj = (env.LANGCHAIN_PROJECT||'agro');
                    const lsQs = new URLSearchParams({ project: prj, share: 'true' });
                    const lsRes = await fetch(api(`/api/langsmith/latest?${lsQs.toString()}`));
                    const lsData = await lsRes.json();
                    if (lsData && lsData.url) window.open(lsData.url, '_blank');
                }
            }catch{/* no-op */}
        }catch(e){ appendChatMessage('assistant', `Error: ${e.message}`); }
    }

    // ---------------- Config ----------------
    // Delegated to Config module (gui/js/config.js)
    const loadConfig = window.Config?.loadConfig || (async () => {});
    const populateConfigForm = window.Config?.populateConfigForm || (() => {});
    const gatherConfigForm = window.Config?.gatherConfigForm || (() => ({}));
    const saveConfig = window.Config?.saveConfig || (async () => {});


    // ---------------- models & Cost ----------------
    async function loadmodels() {
        try {
            const r = await fetch(api('/api/models'));
            state.models = await r.json();
            populatePriceDatalists();
        } catch (e) {
            console.error('Failed to load models:', e);
        }
    }

    /**
     * ---agentspec
     * what: |
     *   Deduplicates provider and model strings from state.models.models array. Returns two unique arrays: providers and allModels.
     *
     * why: |
     *   Populates datalists with distinct values to avoid duplicate options in UI dropdowns.
     *
     * guardrails:
     *   - DO NOT assume state.models exists; guard with early return
     *   - NOTE: Filters empty/whitespace strings before deduplication
     * ---/agentspec
     */
    function unique(xs) { return Array.from(new Set(xs)); }

    /**
     * ---agentspec
     * what: |
     *   Populates HTML datalists for price filter UI. Extracts unique providers and models from state.models.models array, renders into cost-provider select and model-list datalist.
     *
     * why: |
     *   Centralizes datalist population logic to keep UI sync'd with price data state.
     *
     * guardrails:
     *   - DO NOT render if state.models or state.models.models missing; early return prevents crashes
     *   - NOTE: Assumes cost-provider and model-list elements exist in DOM
     *   - NOTE: Trims whitespace; filters empty strings to avoid blank options
     * ---/agentspec
     */
    function populatePriceDatalists() {
        if (!state.models || !Array.isArray(state.models.models)) return;

        const models = state.models.models;
        const providers = unique(models.map(m => (m.provider || '').trim()).filter(Boolean));
        const allModels = unique(models.map(m => (m.model || '').trim()).filter(Boolean));

        const providerSelect = document.getElementById('cost-provider');
        const modelList = document.getElementById('model-list');
        const genList = document.getElementById('gen-model-list');
        const rrList = document.getElementById('rerank-model-list');
        const embList = document.getElementById('embed-model-list');

        function setOpts(el, vals) {
            if (!el) return;
            el.innerHTML = '';
            vals.forEach(v => {
                const opt = document.createElement('option');
                opt.value = v;
                if (el.tagName === 'SELECT') opt.textContent = v;
                el.appendChild(opt);
            });
        }

        if (providerSelect && providerSelect.tagName === 'SELECT') {
            // refill provider select only if empty, preserve user choice
            if (providerSelect.options.length <= 1) setOpts(providerSelect, providers);
        }

        // Partition models into categories for filtering
        // Inference models: unit == '1k_tokens' and no embed/rerank fields (cost may be 0 for local)
        const isGen = (m)=> {
            const u = String(m.unit || '').toLowerCase();
            const hasEmbed = Object.prototype.hasOwnProperty.call(m, 'embed_per_1k');
            const hasRerank = Object.prototype.hasOwnProperty.call(m, 'rerank_per_1k');
            return u === '1k_tokens' && !hasEmbed && !hasRerank;
        };
        const isEmbed = (m)=> Object.prototype.hasOwnProperty.call(m, 'embed_per_1k');
        const isRerank = (m)=> Object.prototype.hasOwnProperty.call(m, 'rerank_per_1k') || /rerank/i.test(String(m.family||'')+String(m.model||''));
        const genModels = unique(models.filter(isGen).map(m => m.model));
        const rrModels = unique(models.filter(isRerank).map(m => m.model));
        const embModels = unique(models.filter(isEmbed).map(m => m.model));

        // Populate datalists with null checks
        if (modelList) setOpts(modelList, allModels);
        if (genList) setOpts(genList, genModels);
        if (rrList) setOpts(rrList, rrModels);
        if (embList) setOpts(embList, embModels);

        // Default provider only; leave model empty so datalist shows all options on first focus
        const costProvider = $('#cost-provider');
        const costModel = $('#cost-model');
        if (costProvider && !costProvider.value && providers.length) costProvider.value = providers[0];
        if (costModel && !costModel.value) costModel.value = '';

        // Filter model options when provider changes AND update the input value
        const onProv = () => {
            const modelInput = $('#cost-model');
            const costProviderEl = $('#cost-provider');
            if (!modelInput || !modelList || !costProviderEl) return;

            const p = costProviderEl.value.trim().toLowerCase();
            const provModels = unique(models.filter(m => (m.provider||'').toLowerCase()===p && isGen(m)).map(m => m.model));
            if (!provModels.length) {
                // Fall back to all inference models so the dropdown is still usable
                const allGen = unique(models.filter(isGen).map(m => m.model));
                if (modelList) setOpts(modelList, allGen);
                modelInput.value = '';
                try { showStatus(`No inference models for provider "${p}" — showing all models.`, 'warn'); } catch { /* no-op */ }
                return;
            }
            if (modelList) setOpts(modelList, provModels);
            // If current value isn't a model for this provider, clear so the datalist shows all options
            if (!provModels.includes(modelInput.value)) {
                modelInput.value = '';
            }
        };

        if (providerSelect) providerSelect.addEventListener('change', onProv);
        onProv(); // Initialize

        // ---- Provider-specific filtering for Embeddings and Reranker ----
        function normProvList(sel, kind){
            const p = String(sel||'').toLowerCase();
            if (p === 'mxbai') return ['huggingface'];
            if (p === 'hugging face') return ['huggingface'];
            if (p === 'local'){
                // For local: embeddings prefer local/ollama; rerank prefer huggingface/local
                return (kind==='embed') ? ['local','ollama'] : ['huggingface','local','ollama','mlx'];
            }
            return [p];
        }
        function updateEmbedList(){
            const sel = document.getElementById('cost-embed-provider');
            const input = document.getElementById('cost-embed-model');
            if (!sel || !embList) return;
            const prov = String(sel.value||'').toLowerCase();
            const prows = normProvList(prov, 'embed');
            let items = models.filter(m => isEmbed(m) && prows.includes(String(m.provider||'').toLowerCase())).map(m => m.model);
            // If provider is mxbai, prefer Mixedbread embeddings; if none present, include all HF embeddings
            if (prov === 'mxbai') {
                const mb = items.filter(s => /mixedbread/i.test(s));
                items = mb.length ? mb : models.filter(m => isEmbed(m) && String(m.provider||'').toLowerCase()==='huggingface').map(m => m.model);
            }
            if (!items.length) items = unique(models.filter(isEmbed).map(m => m.model));
            if (embList) setOpts(embList, unique(items));
            if (input && items.length && !items.includes(input.value)) input.value = '';
        }
        function normProviderName(p){
            p = String(p||'').toLowerCase();
            if (p === 'hf' || p === 'hugging face') return 'huggingface';
            return p;
        }
        function updateRerankList(){
            const sel = document.getElementById('cost-rerank-provider');
            const input = document.getElementById('cost-rerank-model');
            if (!sel || !rrList) return;
            const p = normProviderName(sel.value||'');
            let items;
            if (!p) {
                items = models.filter(isRerank).map(m => m.model);
            } else if (p === 'cohere') {
                items = models.filter(m => isRerank(m) && String(m.provider||'').toLowerCase()==='cohere').map(m => m.model);
            } else if (p === 'huggingface') {
                items = models.filter(m => isRerank(m) && String(m.provider||'').toLowerCase()==='huggingface').map(m => m.model);
            } else if (p === 'local') {
                // Prefer HF rerankers for local
                items = models.filter(m => isRerank(m) && (String(m.provider||'').toLowerCase()==='huggingface' || String(m.provider||'').toLowerCase()==='local' || String(m.provider||'').toLowerCase()==='ollama')).map(m => m.model);
            } else if (p === 'none') {
                items = [];
            } else {
                items = models.filter(m => isRerank(m) && String(m.provider||'').toLowerCase()===p).map(m => m.model);
            }
            if (!items.length) items = unique(models.filter(isRerank).map(m => m.model));
            if (rrList) setOpts(rrList, unique(items));
            if (input && items.length && !items.includes(input.value)) input.value = '';
        }
        const embProvSel = document.getElementById('cost-embed-provider');
        const rrProvSel = document.getElementById('cost-rerank-provider');
        if (embProvSel) embProvSel.addEventListener('change', updateEmbedList);
        if (rrProvSel) rrProvSel.addEventListener('change', updateRerankList);
        updateEmbedList();
        updateRerankList();
    }

    async function estimateCost() {
        try{
            const d = await (window.CostLogic && window.CostLogic.estimateFromUI ? window.CostLogic.estimateFromUI(window.CoreUtils.API_BASE) : Promise.reject(new Error('CostLogic missing')));
            $('#cost-daily').textContent = `$${Number(d.daily||0).toFixed(4)}`;
            $('#cost-monthly').textContent = `$${Number(d.monthly||0).toFixed(2)}`;
        }catch(e){ alert('Cost estimation failed: ' + e.message); }
    }

    // ---------------- Hardware Scan & Profiles ----------------
    /**
     * ---agentspec
     * what: |
     *   Formats hardware scan object into HTML divs. Input: {info, runtimes} object. Output: HTML string with OS, CPU cores, memory.
     *
     * why: |
     *   Centralizes hardware display logic; guards against null/malformed data.
     *
     * guardrails:
     *   - DO NOT render user input without sanitization; XSS risk in info.os, info.cpu_cores
     *   - NOTE: Returns 'No scan data' if input falsy or not object; silent skip if keys missing
     * ---/agentspec
     */
    function formatHardwareScan(data) {
        if (!data || typeof data !== 'object') return 'No scan data';
        const info = data.info || {};
        const rt = data.runtimes || {};
        const parts = [];

        if (info.os) parts.push(`<div class="section"><span class="key">OS:</span> <span class="value">${info.os}</span></div>`);
        if (info.cpu_cores) parts.push(`<div class="section"><span class="key">CPU Cores:</span> <span class="value">${info.cpu_cores}</span></div>`);
        if (info.mem_gb) parts.push(`<div class="section"><span class="key">Memory:</span> <span class="value">${info.mem_gb} GB</span></div>`);
        if (info.gpu) parts.push(`<div class="section"><span class="key">GPU:</span> <span class="value">${info.gpu}</span></div>`);

        const activeRuntimes = Object.keys(rt).filter(k => rt[k]);
        if (activeRuntimes.length) {
            parts.push(`<div class="section"><span class="key">Runtimes:</span> <span class="value">${activeRuntimes.join(', ')}</span></div>`);
        }

        return parts.join('');
    }

    async function scanHardware() {
        try {
            const r = await fetch(api('/api/scan-hw'), { method: 'POST' });
            const d = await r.json();
            const scanOut = $('#scan-out');
            scanOut.innerHTML = formatHardwareScan(d);
            scanOut.dataset.scanData = JSON.stringify(d);
            updateWizardSummary();
            return d;
        } catch (e) {
            alert('Hardware scan failed: ' + e.message);
            return null;
        }
    }

    /**
     * ---agentspec
     * what: |
     *   Proposes LLM profile (model, embedding, rerank) based on runtime scan + budget. Returns config object with GEN_MODEL, EMBEDDING_TYPE, RERANK_BACKEND, MAX_QUERY_REWRITES.
     *
     * why: |
     *   Budget-aware defaults prevent paid API calls at $0 budget; prefers local runtimes (ollama, coreml) when available.
     *
     * guardrails:
     *   - DO NOT use gpt-4o-mini; only gpt-5 allowed
     *   - NOTE: $0 budget forces local or 'none' provider; paid providers (cohere, openai) only if budget > 0
     *   - ASK USER: Confirm gpt-5 substitution before deployment
     * ---/agentspec
     */
    function proposeProfile(scan, budget) {
        // Budget-aware defaults (avoid paid providers at $0)
        const hasLocal = scan?.runtimes?.ollama || scan?.runtimes?.coreml;
        const rprov = (Number(budget) === 0) ? (hasLocal ? 'local' : 'none') : 'cohere';
        const prof = {
            GEN_MODEL: hasLocal && Number(budget) === 0 ? 'qwen3-coder:14b' : 'gpt-4o-mini',
            EMBEDDING_TYPE: (Number(budget) === 0) ? (hasLocal ? 'local' : 'mxbai') : 'openai',
            RERANKER_MODE: rprov,
            MAX_QUERY_REWRITES: Number(budget) > 50 ? '6' : '3',
            TOPK_SPARSE: '75',
            TOPK_DENSE: '75',
            FINAL_K: Number(budget) > 50 ? '20' : '10',
            HYDRATION_MODE: 'lazy',
        };
        return prof;
    }

    /**
     * ---agentspec
     * what: |
     *   Generates tooltip HTML for a given key. Returns cached map from window.Tooltips.buildTooltipMap() or fallback with key name + docs links.
     *
     * why: |
     *   Centralizes tooltip rendering logic; graceful fallback prevents blank tooltips on missing data.
     *
     * guardrails:
     *   - DO NOT assume window.Tooltips exists; wrapped in try-catch
     *   - NOTE: Fallback always returns valid HTML; never null
     * ---/agentspec
     */
    function _tooltipHtmlForKey(k){
        try{
            const map = (window.Tooltips && window.Tooltips.buildTooltipMap && window.Tooltips.buildTooltipMap()) || {};
            return map[k] || `<span class="tt-title">${k}</span><div>No detailed tooltip available yet. See our docs.</div><div class="tt-links"><a href="/files/README.md" target="_blank" rel="noopener">Main README</a> <a href="/docs/README.md" target="_blank" rel="noopener">Docs Index</a></div>`;
        }catch{return `<span class="tt-title">${k}</span><div>No details found.</div>`}
    }

    /**
     * ---agentspec
     * what: |
     *   Formats configuration profile object into grouped key-value display. Returns string preview or fallback message.
     *
     * why: |
     *   Organizes model/retrieval settings by category (Generation, Embeddings, Reranking, Retrieval) for readable UI output.
     *
     * guardrails:
     *   - DO NOT mutate input prof object
     *   - NOTE: Returns fallback if prof is null/undefined/non-object
     * ---/agentspec
     */
    function formatProfile(prof) {
        if (!prof || typeof prof !== 'object') return '(Preview will appear here)';
        const parts = [];

        const keyGroups = {
            'Generation': ['GEN_MODEL', 'ENRICH_MODEL', 'ENRICH_MODEL_OLLAMA'],
            'Embeddings': ['EMBEDDING_TYPE', 'VOYAGE_EMBED_DIM', 'EMBEDDING_DIM'],
            'Reranking': ['RERANK_BACKEND', 'COHERE_RERANK_MODEL', 'RERANKER_MODEL'],
            'Retrieval': ['MAX_QUERY_REWRITES', 'FINAL_K', 'TOPK_SPARSE', 'TOPK_DENSE', 'HYDRATION_MODE'],
        };

        for (const [group, keys] of Object.entries(keyGroups)) {
            const groupItems = keys.filter(k => prof[k] !== undefined).map(k => {
                const tip = _tooltipHtmlForKey(k);
                const val = String(prof[k]);
                return `<div class="kv">
                    <span class="key">${k}:</span>
                    <span class="value">${val}</span>
                    <span class="tooltip-wrap"><span class="help-icon" tabindex="0" aria-label="Help: ${k}">?</span><div class="tooltip-bubble">${tip}</div></span>
                </div>`;
            });
            if (groupItems.length) {
                parts.push(`<div class="section"><strong style="color:var(--link);">${group}</strong>${groupItems.join('')}</div>`);
            }
        }

        if (prof.__estimate__) {
            const est = prof.__estimate__;
            parts.push(`<div class="section"><strong style="color:var(--link);">Cost Estimate</strong><div><span class="key">Daily:</span> <span class="value">$${Number(est.daily||0).toFixed(4)}</span></div><div><span class="key">Monthly:</span> <span class="value">$${Number(est.monthly||0).toFixed(2)}</span></div></div>`);
        }

        return parts.join('');
    }

    /**
     * ---agentspec
     * what: |
     *   Binds hover/focus listeners to help icons in profile preview. Shows/hides tooltip bubbles on mouseover/focus events.
     *
     * why: |
     *   Centralizes tooltip visibility logic; decouples event handling from markup.
     *
     * guardrails:
     *   - DO NOT assume .tooltip-bubble exists; check presence before classList operations
     *   - NOTE: Requires #profile-preview root; silently exits if missing
     *   - DO NOT attach listeners if wrap or bubble is null; guard all DOM queries
     * ---/agentspec
     */
    function bindPreviewTooltips(){
        const root = document.getElementById('profile-preview');
        if (!root) return;
        root.querySelectorAll('.kv .help-icon').forEach(icon => {
            const wrap = icon.parentElement;
            const bubble = wrap && wrap.querySelector('.tooltip-bubble');
            if (!wrap || !bubble) return;
            function show(){ bubble.classList.add('tooltip-visible'); }
            function hide(){ bubble.classList.remove('tooltip-visible'); }
            icon.addEventListener('mouseenter', show);
            icon.addEventListener('mouseleave', hide);
            icon.addEventListener('focus', show);
            icon.addEventListener('blur', hide);
            icon.addEventListener('click', (e)=>{ e.stopPropagation(); bubble.classList.toggle('tooltip-visible'); });
            document.addEventListener('click', (evt)=>{ if (!wrap.contains(evt.target)) bubble.classList.remove('tooltip-visible'); });
        });
    }

    async function generateProfileWizard() {
        let scan = null;
        const scanOut = $('#scan-out');
        // Try to extract scan from data attribute or re-scan
        if (scanOut.dataset.scanData) {
            try { scan = JSON.parse(scanOut.dataset.scanData); } catch { /* no-op */ }
        }
        if (!scan) scan = await scanHardware();
        const budget = parseFloat($('#budget').value || '0');
        const prof = (window.ProfileLogic && window.ProfileLogic.buildWizardProfile) ? window.ProfileLogic.buildWizardProfile(scan, budget) : {};

        // Try a pipeline cost preview
        const payload = (window.CostLogic && window.CostLogic.buildPayloadFromUI) ? window.CostLogic.buildPayloadFromUI() : {
            gen_provider:'openai', gen_model:'gpt-4o-mini', tokens_in:0, tokens_out:0, embeds:0, reranks:0, requests_per_day:0
        };
        try {
            const r = await fetch(api('/api/cost/estimate_pipeline'), { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(payload) });
            const d = await r.json();
            prof.__estimate__ = d;
        } catch { /* no-op */ }
        $('#profile-preview').innerHTML = formatProfile(prof);
        bindPreviewTooltips();
        $('#profile-preview').dataset.profileData = JSON.stringify(prof);
        updateWizardSummary();
        return prof;
    }

    async function applyProfileWizard() {
        let prof = null;
        const preview = $('#profile-preview');
        if (preview.dataset.profileData) {
            try { prof = JSON.parse(preview.dataset.profileData); } catch { /* no-op */ }
        }
        if (!prof || typeof prof !== 'object') prof = await generateProfileWizard();
        // Remove cost estimate from applied profile
        if (prof.__estimate__) delete prof.__estimate__;
        try {
            const r = await fetch(api('/api/profiles/apply'), { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ profile: prof }) });
            const d = await r.json();
            alert(`Profile applied: ${d.applied_keys?.join(', ') || 'ok'}`);
            await loadConfig();
        } catch (e) { alert('Failed to apply profile: ' + e.message); }
    }

    // Tri-Candidate Generation (from docs)
    /**
     * ---agentspec
     * what: |
     *   Generates 3 model candidates (local, cloud, hybrid) based on runtime scan, memory, budget. Returns array of {name, env, model, cost_estimate}.
     *
     * why: |
     *   Encapsulates candidate selection logic to decouple deployment strategy from caller.
     *
     * guardrails:
     *   - DO NOT assume scan.runtimes exists; validate before access
     *   - NOTE: budgetNum=0 disables cost filtering; clarify intent with caller
     *   - ASK USER: Should hybrid fallback to cloud if local fails?
     * ---/agentspec
     */
    function generateCandidates(scan, budget) {
        const hasLocal = !!(scan?.runtimes?.ollama || scan?.runtimes?.coreml);
        const mem = (scan?.info?.mem_gb || 8);
        const budgetNum = Number(budget) || 0;

        // Three baseline candidates
        const local = {
            name: 'local',
            env: {
                GEN_MODEL: hasLocal ? 'qwen3-coder:14b' : 'gpt-4o-mini',
                EMBEDDING_TYPE: hasLocal ? 'local' : 'mxbai',
                RERANK_BACKEND: hasLocal ? 'local' : 'none',
                MAX_QUERY_REWRITES: mem >= 32 ? '4' : '3',
                FINAL_K: mem >= 32 ? '10' : '8',
                TOPK_DENSE: '60', TOPK_SPARSE: '60', HYDRATION_MODE: 'lazy'
            }
        };
        const cheapCloud = {
            name: 'cheap_cloud',
            env: {
                GEN_MODEL: 'gpt-4o-mini', EMBEDDING_TYPE: 'openai', RERANK_BACKEND: 'local',
                MAX_QUERY_REWRITES: budgetNum > 25 ? '4' : '3',
                FINAL_K: budgetNum > 25 ? '10' : '8',
                TOPK_DENSE: '75', TOPK_SPARSE: '75', HYDRATION_MODE: 'lazy'
            }
        };
        const premium = {
            name: 'premium',
            env: {
                GEN_MODEL: 'gpt-4o-mini', EMBEDDING_TYPE: 'openai', RERANK_BACKEND: 'cohere',
                MAX_QUERY_REWRITES: budgetNum > 100 ? '6' : '4',
                FINAL_K: budgetNum > 100 ? '20' : '12',
                TOPK_DENSE: '120', TOPK_SPARSE: '120', HYDRATION_MODE: 'lazy'
            }
        };
        return [local, cheapCloud, premium];
    }

    async function triCostSelect() {
        // Use current Cost panel inputs for tokens and rpd
        const base = {
            tokens_in: parseInt($('#cost-in').value || '500', 10),
            tokens_out: parseInt($('#cost-out').value || '800', 10),
            embeds: parseInt($('#cost-embeds').value || '0', 10),
            reranks: parseInt($('#cost-rerank').value || '0', 10),
            requests_per_day: parseInt($('#cost-rpd').value || '100', 10)
        };
        const budget = parseFloat($('#budget').value || '0');
        const scanOut = $('#scan-out');
        let scan = null;
        if (scanOut && scanOut.dataset.scanData) {
            try { scan = JSON.parse(scanOut.dataset.scanData); } catch { /* no-op */ }
        }
        if (!scan) scan = await scanHardware();

        const cands = generateCandidates(scan, budget);

        const rows = [];
        for (const c of cands) {
            // Decide provider/model from env for cost call
            const provider = (c.env.GEN_MODEL || '').match(/:/) ? 'local' : 'openai';
            const model = c.env.GEN_MODEL || 'gpt-4o-mini';
            const payload = (window.CostLogic && window.CostLogic.buildPayloadFromUI) ? window.CostLogic.buildPayloadFromUI() : { gen_provider: provider, gen_model: model, ...base };
            payload.gen_provider = provider; payload.gen_model = model;

            // local electricity optional if provider==local
            if (provider === 'local') {
                const kwh = $('#cost-kwh')?.value;
                const watts = $('#cost-watts')?.value;
                const hours = $('#cost-hours')?.value;
                if (kwh) payload.kwh_rate = parseFloat(kwh);
                if (watts) payload.watts = parseInt(watts, 10);
                if (hours) payload.hours_per_day = parseFloat(hours);
            }
            // Call cost API
            const r = await fetch(api('/api/cost/estimate'), {
                method: 'POST',
                headers: {'Content-Type':'application/json'},
                body: JSON.stringify(payload)
            });
            const d = await r.json();
            rows.push({
                name: c.name,
                env: c.env,
                provider,
                model,
                daily: d.daily,
                monthly: d.monthly,
                breakdown: d.breakdown
            });
        }

        // Rank by monthly (ascending), then prefer cheaper that meet budget if budget>0
        const ranked = rows.sort((a,b) => a.monthly - b.monthly);
        let winner = ranked[0];
        if (budget > 0) {
            const within = ranked.filter(r => r.monthly <= budget);
            if (within.length) winner = within[within.length - 1]; // Pick most expensive within budget
        }

        const triOut = $('#tri-out');
        if (triOut) {
            const lines = [];
            ranked.forEach(r => {
                const mark = r.name === winner.name ? '✓' : ' ';
                const header = `${mark} ${r.name.toUpperCase().padEnd(15)} $${r.monthly.toFixed(2)}/mo`;
                lines.push(header);
                lines.push(`  Inference:  ${r.env.GEN_MODEL || '—'}`);
                lines.push(`  Embedding:  ${r.env.EMBEDDING_TYPE || '—'}`);
                lines.push(`  Rerank:     ${r.env.RERANK_BACKEND || 'none'}`);
                lines.push(`  MQ:${r.env.MAX_QUERY_REWRITES||'3'}  Final-K:${r.env.FINAL_K||'10'}  Sparse:${r.env.TOPK_SPARSE||'75'}  Dense:${r.env.TOPK_DENSE||'75'}`);
                lines.push('');
            });
            triOut.textContent = lines.join('\n').trim();
        }

        return { winner, ranked };
    }

    async function triChooseAndApply() {
        console.log('[AUTO-PROFILE] Button clicked - starting triChooseAndApply');

        // Show loading state
        const placeholder = $('#profile-placeholder');
        const resultsContent = $('#profile-results-content');
        console.log('[AUTO-PROFILE] Elements found:', { placeholder: !!placeholder, resultsContent: !!resultsContent });

        if (placeholder) placeholder.style.display = 'flex';
        if (resultsContent) resultsContent.style.display = 'none';

        // Add loading spinner to placeholder
        if (placeholder) {
            placeholder.innerHTML = `
                <div style="display:flex;flex-direction:column;align-items:center;justify-content:center;">
                    <div style="width:48px;height:48px;border:3px solid var(--line);border-top-color:var(--accent);border-radius:50%;animation:spin 1s linear infinite;margin-bottom:16px;"></div>
                    <p style="font-size:14px;color:var(--fg-muted);">Analyzing hardware and generating profile...</p>
                </div>
                <style>@keyframes spin { to { transform: rotate(360deg); } }</style>
            `;
        }

        const { winner, ranked } = await triCostSelect();
        const budget = Number($('#budget')?.value || 0);

        // Scan hardware if not already done
        let scan = state.hwScan;
        if (!scan) {
            try {
                const r = await fetch(api('/api/scan-hw'), { method: 'POST' });
                scan = await r.json();
                state.hwScan = scan;
            } catch (e) {
                console.error('HW scan failed:', e);
                scan = null;
            }
        }

        // Render rich profile display using ProfileRenderer
        if (window.ProfileRenderer && resultsContent) {
            try {
                const html = window.ProfileRenderer.renderProfileResults(winner.env, scan, budget);
                resultsContent.innerHTML = html;
                // Bind tooltips inside the rendered preview
                if (window.ProfileRenderer.bindTooltips) window.ProfileRenderer.bindTooltips(resultsContent);

                // Hide placeholder, show results
                if (placeholder) placeholder.style.display = 'none';
                resultsContent.style.display = 'block';
            } catch (err) {
                console.error('ProfileRenderer error:', err);
                // Fallback to simple display
                if (resultsContent) {
                    resultsContent.innerHTML = '<pre style="color: var(--err);padding:20px;">Error rendering profile: ' + err.message + '</pre>';
                    resultsContent.style.display = 'block';
                    if (placeholder) placeholder.style.display = 'none';
                }
            }
        } else {
            console.error('ProfileRenderer not available:', { hasRenderer: !!window.ProfileRenderer, hasContent: !!resultsContent });
            // Fallback to old method
            if (resultsContent) {
                resultsContent.innerHTML = '<pre style="padding:20px;color: var(--fg-muted);">' + JSON.stringify(winner.env, null, 2) + '</pre>';
                resultsContent.style.display = 'block';
                if (placeholder) placeholder.style.display = 'none';
            }
        }

        // Wire up action buttons (always, regardless of renderer)
        const applyBtn = document.getElementById('apply-profile-btn');
        if (applyBtn) {
            applyBtn.addEventListener('click', async () => {
                const r = await fetch(api('/api/profiles/apply'), {
                    method: 'POST',
                    headers: { 'Content-Type':'application/json' },
                    body: JSON.stringify({ profile: winner.env })
                });
                if (!r.ok) {
                    alert('Apply failed');
                    return;
                }
                alert(`✓ Applied: ${winner.name} ($${winner.monthly.toFixed(2)}/mo)\n\nSettings are now active. Refresh the page to see updated values.`);
                await loadConfig();
            });
        }

        const exportBtn = document.getElementById('export-profile-btn');
        if (exportBtn) {
            exportBtn.addEventListener('click', () => {
                const blob = new Blob([JSON.stringify(winner.env, null, 2)], { type: 'application/json' });
                const url = URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = `profile-${winner.name.toLowerCase().replace(/[^a-z0-9]/g, '-')}-${Date.now()}.json`;
                a.click();
                URL.revokeObjectURL(url);
            });
        }

        const saveBtn = document.getElementById('save-profile-btn');
        if (saveBtn) {
            saveBtn.addEventListener('click', async () => {
                const name = prompt('Profile name:', winner.name.toLowerCase().replace(/[^a-z0-9]/g, '-'));
                if (!name) return;
                const r = await fetch(api('/api/profiles/save'), {
                    method: 'POST',
                    headers: { 'Content-Type':'application/json' },
                    body: JSON.stringify({ name, profile: winner.env })
                });
                if (r.ok) {
                    alert(`✓ Saved as "${name}"`);
                    await loadProfiles();
                } else {
                    alert('Save failed');
                }
            });
        }
    }

    // Wizard helpers
    /**
     * ---agentspec
     * what: |
     *   Builds single wizard profile from system scan + budget. Returns model/embedding/retrieval defaults based on local runtime availability and budget tier.
     *
     * why: |
     *   Legacy compatibility layer; centralizes profile defaults to avoid scattered config logic.
     *
     * guardrails:
     *   - DO NOT use gpt-4o-mini; only gpt-5 allowed for LLM
     *   - NOTE: Hardcoded model names ('qwen3-coder:14b', 'mxbai') may be stale; ASK USER before deploying
     *   - DO NOT assume budgetNum=0 means local-only; verify scan.runtimes actually populated
     * ---/agentspec
     */
    function buildWizardProfile(scan, budget) {
        // Legacy single-profile builder (kept for compatibility)
        const hasLocal = scan?.runtimes?.ollama || scan?.runtimes?.coreml;
        const budgetNum = Number(budget) || 0;
        const defaultGen = hasLocal && budgetNum === 0 ? 'qwen3-coder:14b' : 'gpt-4o-mini';
        const defaultEmb = budgetNum === 0 ? (hasLocal ? 'local' : 'mxbai') : 'openai';
        const defaultRprov = budgetNum === 0 ? (hasLocal ? 'local' : 'none') : 'cohere';

        const profile = {
            GEN_MODEL: defaultGen,
            EMBEDDING_TYPE: defaultEmb,
            RERANK_BACKEND: defaultRprov,
            MAX_QUERY_REWRITES: budgetNum > 50 ? '6' : '3',
            FINAL_K: budgetNum > 50 ? '20' : '10',
            TOPK_SPARSE: budgetNum > 50 ? '120' : '75',
            TOPK_DENSE: budgetNum > 50 ? '120' : '75',
            HYDRATION_MODE: 'lazy',
        };
        return profile;
    }

    /**
     * ---agentspec
     * what: |
     *   Populates wizard form fields (gen model, embedding provider, rerank provider/model) from environment variables. Reads env object, writes to DOM via jQuery selectors.
     *
     * why: |
     *   Initializes UI state from runtime config without manual form entry.
     *
     * guardrails:
     *   - DO NOT assume all env vars exist; checks presence before assignment
     *   - NOTE: Falls back to RERANKER_MODEL if COHERE_RERANK_MODEL absent
     *   - ASK USER: Validate env vars loaded before calling; silent no-op if selectors missing
     * ---/agentspec
     */
    function seedWizardFromEnv(env) {
        const wzGen = $('#wizard-gen-model');
        if (wzGen && env.GEN_MODEL) wzGen.value = env.GEN_MODEL;
        const wzEmb = $('#wizard-embed-provider');
        if (wzEmb && env.EMBEDDING_TYPE) wzEmb.value = env.EMBEDDING_TYPE;
        const wzRprov = $('#wizard-rerank-provider');
        if (wzRprov && env.RERANK_BACKEND) wzRprov.value = env.RERANK_BACKEND;
        const wzRmod = $('#wizard-rerank-model');
        if (wzRmod && (env.COHERE_RERANK_MODEL || env.RERANKER_MODEL)) wzRmod.value = env.COHERE_RERANK_MODEL || env.RERANKER_MODEL;
    }

    /**
     * ---agentspec
     * what: |
     *   Loads wizard config from state.config.env, seeds wizard state, updates UI summary display.
     *
     * why: |
     *   Centralizes env-to-UI sync to prevent stale state.
     *
     * guardrails:
     *   - DO NOT assume state.config exists; check before access
     *   - NOTE: updateWizardSummary() requires #scan-out DOM element present
     * ---/agentspec
     */
    function loadWizardFromEnv() {
        const env = (state.config && state.config.env) || {};
        seedWizardFromEnv(env);
        updateWizardSummary();
    }

    /**
     * ---agentspec
     * what: |
     *   Reads scan data from DOM dataset, parses JSON, extracts CPU cores/RAM/runtimes. Returns formatted hardware string or fallback "(hardware not scanned)".
     *
     * why: |
     *   Centralizes hardware summary generation from cached scan results for UI display.
     *
     * guardrails:
     *   - DO NOT assume scanOut exists; check presence before access
     *   - NOTE: Silently falls back on parse error; consider logging for debugging
     *   - DO NOT mutate s.runtimes; filter only for display
     * ---/agentspec
     */
    function updateWizardSummary() {
        const scanOut = $('#scan-out');
        let hw = '';
        if (scanOut && scanOut.dataset.scanData) {
            try {
                const s = JSON.parse(scanOut.dataset.scanData);
                hw = `${s.info?.cpu_cores||'?'} cores, ${s.info?.mem_gb||'?'} GB RAM, runtimes: ${Object.keys(s.runtimes||{}).filter(k=>s.runtimes[k]).join(', ')||'none'}`;
            } catch { hw = '(hardware not scanned)'; }
        } else {
            hw = '(hardware not scanned)';
        }
        const gen = ($('#wizard-gen-model')?.value || '(GEN_MODEL not set)');
        const emb = ($('#wizard-embed-provider')?.value || (state.config?.env?.EMBEDDING_TYPE || '(use current)'));
        const rprov = ($('#wizard-rerank-provider')?.value || (state.config?.env?.RERANK_BACKEND || '(use current)'));
        const rmod = ($('#wizard-rerank-model')?.value || state.config?.env?.COHERE_RERANK_MODEL || state.config?.env?.RERANKER_MODEL || '');
        const budget = $('#budget')?.value || '0';
        const line = `Hardware: ${hw}\nModels: gen=${gen}, emb=${emb}, rerank=${rprov}${rmod?`:${rmod}`:''}\nBudget: $${budget}/mo`;
        const el = $('#wizard-summary'); if (el) el.textContent = line;
    }

    // Keep summary in sync
    ;['wizard-gen-model','wizard-embed-provider','wizard-rerank-provider','wizard-rerank-model','budget'].forEach(id => {
        const el = document.getElementById(id); if (el) el.addEventListener('input', updateWizardSummary);
    });

    async function applyProfile() {
        const scanText = $('#scan-out').textContent;
        if (!scanText || scanText === '') {
            alert('Please scan hardware first');
            return;
        }

        const scan = JSON.parse(scanText);
        const budget = parseFloat($('#budget').value || '0');
        const prof = proposeProfile(scan, budget);

        try {
            const r = await fetch(api('/api/profiles/apply'), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ profile: prof })
            });

            const d = await r.json();
            alert(`Profile applied: ${d.applied_keys.join(', ')}`);
            await loadConfig();
        } catch (e) {
            alert('Failed to apply profile: ' + e.message);
        }
    }

    async function loadProfiles() {
        try {
            const r = await fetch(api('/api/profiles'));
            const d = await r.json();
            state.profiles = d.profiles || [];
            state.defaultProfile = d.default || null;

            const ul = $('#profiles-ul');
            const tooltip = $('#profile-tooltip');
            if (!ul) {
                // Element doesn't exist in React app, skip DOM manipulation
                return;
            }
            ul.innerHTML = '';

            state.profiles.forEach((name) => {
                const li = document.createElement('li');
                li.textContent = name;
                li.style.cssText = 'padding: 6px 8px; color: var(--fg-muted); cursor: pointer; border-radius: 4px; transition: all 0.15s ease;';

                li.addEventListener('mouseenter', async (e) => {
                    li.style.background = 'var(--bg-elev2)';
                    li.style.color = 'var(--accent)';
                    await showProfileTooltip(name, e);
                });

                li.addEventListener('mouseleave', () => {
                    li.style.background = 'transparent';
                    li.style.color = 'var(--fg-muted)';
                    hideProfileTooltip();
                });

                li.addEventListener('click', () => loadAndApplyProfile(name));
                ul.appendChild(li);
            });
        } catch (e) {
            console.error('Failed to load profiles:', e);
        }
    }

    async function showProfileTooltip(name, event) {
        const tooltip = $('#profile-tooltip');
        if (!tooltip) return;

        try {
            // Fetch the profile data
            const r = await fetch(api(`/api/profiles/${encodeURIComponent(name)}`));
            if (!r.ok) return;

            const d = await r.json();
            const prof = d.profile || {};

            // Build tooltip content
            let html = `<div class="tooltip-header">${name}</div>`;

            const entries = Object.entries(prof);
            if (entries.length === 0) {
                html += '<div style="color: var(--fg-muted); font-size: 11px; font-style: italic;">Empty profile</div>';
            } else {
                entries.forEach(([key, value]) => {
                    const displayValue = String(value).length > 40
                        ? String(value).substring(0, 37) + '...'
                        : String(value);
                    html += `
                        <div class="tooltip-item">
                            <div class="tooltip-key">${key}</div>
                            <div class="tooltip-value">${displayValue}</div>
                        </div>
                    `;
                });
            }

            tooltip.innerHTML = html;

            // Position tooltip near the mouse
            const rect = event.target.getBoundingClientRect();
            tooltip.style.left = (rect.right + 10) + 'px';
            tooltip.style.top = rect.top + 'px';
            tooltip.style.display = 'block';

        } catch (e) {
            console.error('Failed to load profile for tooltip:', e);
        }
    }

    /**
     * ---agentspec
     * what: |
     *   Hides profile tooltip by setting display:none. Loads and applies user profile by name asynchronously.
     *
     * why: |
     *   Separates UI hide logic from profile loading to avoid blocking tooltip removal.
     *
     * guardrails:
     *   - DO NOT assume tooltip exists; check before accessing style property
     *   - NOTE: loadAndApplyProfile incomplete; error handling missing
     *   - ASK USER: What happens on profile load failure?
     * ---/agentspec
     */
    function hideProfileTooltip() {
        const tooltip = $('#profile-tooltip');
        if (tooltip) {
            tooltip.style.display = 'none';
        }
    }

    async function loadAndApplyProfile(name) {
        try {
            // Load the profile data
            const r = await fetch(api(`/api/profiles/${encodeURIComponent(name)}`));
            if (!r.ok) {
                alert(`Failed to load profile "${name}"`);
                return;
            }
            const d = await r.json();
            const prof = d.profile || {};

            // Apply the profile
            const applyRes = await fetch(api('/api/profiles/apply'), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ profile: prof })
            });

            if (!applyRes.ok) {
                alert(`Failed to apply profile "${name}"`);
                return;
            }

            const applyData = await applyRes.json();
            alert(`✓ Profile "${name}" applied successfully!\n\nApplied keys: ${applyData.applied_keys?.join(', ') || 'none'}`);

            // Reload config to show updated values in UI
            await loadConfig();
        } catch (e) {
            alert(`Error loading profile "${name}": ${e.message}`);
        }
    }

    async function saveProfile() {
        const name = $('#profile-name').value.trim();
        if (!name) {
            alert('Enter a profile name');
            return;
        }

        // Prefer wizard preview if present; otherwise build from scan
        let prof = null;
        const preview = $('#profile-preview');
        if (preview.dataset.profileData) {
            try { prof = JSON.parse(preview.dataset.profileData); } catch {}
        }
        if (!prof) {
            const scanOut = $('#scan-out');
            if (!scanOut.dataset.scanData) { alert('Please scan hardware first'); return; }
            const scan = JSON.parse(scanOut.dataset.scanData);
            const budget = parseFloat($('#budget').value || '0');
            prof = proposeProfile(scan, budget);
        }
        // Remove cost estimate before saving
        if (prof.__estimate__) delete prof.__estimate__;

        try {
            const r = await fetch(api('/api/profiles/save'), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name, profile: prof })
            });

            if (!r.ok) {
                alert('Save failed');
                return;
            }

            await loadProfiles();
            alert(`Saved profile: ${name}`);
        } catch (e) {
            alert('Failed to save profile: ' + e.message);
        }
    }

    // ---------------- Secrets Ingest (Drag & Drop) ----------------
    // Delegated to Secrets module (gui/js/secrets.js)
    const bindDropzone = window.Secrets?.bindDropzone || (() => {});
    const ingestFile = window.Secrets?.ingestFile || (async () => {});

    // ---------------- Quick Action Helpers ----------------
    /**
     * ---agentspec
     * what: |
     *   Detects React dashboard presence via window flag or DOM query. Checks if DOM node is contained within dashboard root. Manages button UI state (loading/success/error classes).
     *
     * why: |
     *   Centralizes dashboard detection and button state logic to avoid scattered conditionals.
     *
     * guardrails:
     *   - DO NOT assume window.__AGRO_REACT_DASHBOARD__ persists across navigation; re-check on state changes
     *   - NOTE: getReactDashboardRoot() queries DOM each call; cache if called frequently
     *   - DO NOT apply button state without validating btn exists; setButtonState guards but caller must verify
     * ---/agentspec
     */
    const getReactDashboardRoot = () => document.querySelector('[data-react-dashboard="true"]');
    /**
     * ---agentspec
     * what: |
     *   Detects React dashboard presence and manages button UI states (loading/success/error). Checks window globals and DOM containment.
     *
     * why: |
     *   Centralizes dashboard detection and button state logic to avoid scattered conditional rendering.
     *
     * guardrails:
     *   - DO NOT rely on window.__AGRO_REACT_DASHBOARD__ alone; verify DOM root exists
     *   - NOTE: Button state removal clears all states before applying new one; idempotent
     * ---/agentspec
     */
    const isReactDashboardActive = () => Boolean(window.__AGRO_REACT_DASHBOARD__) || Boolean(getReactDashboardRoot());
    /**
     * ---agentspec
     * what: |
     *   Checks if DOM node is inside React dashboard root. Sets button UI state (loading/success/error) via classList.
     *
     * why: |
     *   Scoped DOM queries prevent side effects outside dashboard; classList toggling avoids inline styles.
     *
     * guardrails:
     *   - DO NOT call setButtonState with null btn; guard already present but silent
     *   - NOTE: isInsideReactDashboard depends on getReactDashboardRoot() availability
     *   - ASK USER: Should error state be handled in setButtonState?
     * ---/agentspec
     */
    const isInsideReactDashboard = (node) => {
        const root = getReactDashboardRoot();
        return Boolean(root && node && root.contains(node));
    };
    /**
     * ---agentspec
     * what: |
     *   setButtonState: Removes all state classes, adds one matching state ('loading'|'success'|'error'). showStatus: Displays message with type. Both mutate DOM.
     *
     * why: |
     *   Centralizes UI state management to avoid scattered classList calls.
     *
     * guardrails:
     *   - DO NOT call setButtonState(null); guard with !btn check
     *   - NOTE: showStatus incomplete; implementation missing
     *   - ASK USER: Where does showStatus render? (toast, modal, inline?)
     * ---/agentspec
     */
    function setButtonState(btn, state) {
        if (!btn) return;
        btn.classList.remove('loading', 'success', 'error');
        if (state === 'loading') btn.classList.add('loading');
        else if (state === 'success') btn.classList.add('success');
        else if (state === 'error') btn.classList.add('error');
    }

    /**
     * ---agentspec
     * what: |
     *   Displays status messages to DOM element #dash-index-status with timestamp, icon, and color. Skips if React dashboard active.
     *
     * why: |
     *   Centralizes UI feedback logic; prevents duplicate messages when React component handles display.
     *
     * guardrails:
     *   - DO NOT call if isReactDashboardActive() returns true; React owns the UI
     *   - NOTE: Requires #dash-index-status and #dash-index-bar elements in DOM
     *   - DO NOT assume color vars (--accent, --err, --link) exist; will fail silently if missing
     * ---/agentspec
     */
    function showStatus(message, type = 'info') {
        if (isReactDashboardActive()) return;
        const status = document.getElementById('dash-index-status');
        const bar = document.getElementById('dash-index-bar');
        if (!status) return;

        const timestamp = new Date().toLocaleTimeString();
        const color = type === 'success' ? 'var(--accent)' : type === 'error' ? 'var(--err)' : 'var(--link)';
        const icon = type === 'success' ? '✓' : type === 'error' ? '✗' : '•';

        status.innerHTML = `<span style="color:${color};">${icon}</span> <span style="color:var(--fg-muted);">[${timestamp}]</span> ${message}`;

        if (bar) {
            if (type === 'loading') {
                bar.style.width = '50%';
                bar.style.opacity = '0.6';
            } else if (type === 'success') {
                bar.style.width = '100%';
                bar.style.opacity = '1';
                setTimeout(() => { bar.style.width = '0%'; }, 2000);
            } else if (type === 'error') {
                bar.style.width = '100%';
                bar.style.background = 'var(--err)';
                bar.style.opacity = '1';
                setTimeout(() => {
                    bar.style.width = '0%';
                    bar.style.background = 'linear-gradient(90deg, var(--warn) 0%, var(--accent) 100%)';
                }, 2000);
            }
        }
    }

    // Simulated progress ticker for long-running actions
    /**
     * ---agentspec
     * what: |
     *   Initializes a progress bar UI element with label and total steps. Returns object with stop() method. Skips if React dashboard active.
     *
     * why: |
     *   Conditional rendering: uses DOM progress bar for vanilla JS, skips for React to avoid conflicts.
     *
     * guardrails:
     *   - DO NOT call stop() multiple times; idempotent but wasteful
     *   - NOTE: Requires 'dash-index-status' and 'dash-index-bar' DOM elements present
     *   - ASK USER: Is tick() interval set elsewhere? Function incomplete (no interval/timeout visible)
     * ---/agentspec
     */
    function startSimProgress(label, total = 80, tips = []) {
        if (isReactDashboardActive()) {
            return { stop: () => {} };
        }
        const status = document.getElementById('dash-index-status');
        const bar = document.getElementById('dash-index-bar');
        let step = 0; let tipIdx = 0;
        function tick() {
            step = Math.min(total, step + 1);
            const pct = Math.min(90, Math.max(5, Math.floor((step / Math.max(1,total)) * 90)));
            if (bar) { bar.style.width = pct + '%'; bar.style.opacity = '0.9'; }
            const tip = tips.length ? (tips[tipIdx % tips.length]) : '';
            tipIdx++;
            if (status) {
                status.innerHTML = `
                    <div class="mono" style="color: var(--fg-muted);">
                        🔎 ${label}<br>
                        Scanning ${step} of ${total}… ${tip ? `<span style='color:var(--fg-muted)'>(${tip})</span>` : ''}
                    </div>
                `;
            }
        }
        const id = setInterval(tick, 3500);
        tick();
        return {
            stop: () => {
                clearInterval(id);
                if (bar) { bar.style.width = '100%'; bar.style.opacity = '1'; setTimeout(()=>{ bar.style.width='0%'; }, 1500); }
            }
        };
    }

    /**
     * ---agentspec
     * what: |
     *   Binds click handler to DOM button by ID. Skips if button missing or inside React dashboard. Sets loading state on click, then executes async handler.
     *
     * why: |
     *   Prevents event binding conflicts in hybrid React/vanilla JS environments.
     *
     * guardrails:
     *   - DO NOT bind if isInsideReactDashboard() returns true; React manages its own events
     *   - NOTE: Handler must be async-safe; setButtonState() called before execution
     * ---/agentspec
     */
    function bindQuickAction(btnId, handler) {
        const btn = document.getElementById(btnId);
        if (!btn) return;
        if (isInsideReactDashboard(btn)) return;

        btn.addEventListener('click', async (e) => {
            e.preventDefault();
            setButtonState(btn, 'loading');

            try {
                await handler();
                setButtonState(btn, 'success');
                setTimeout(() => setButtonState(btn, null), 1500);
            } catch (err) {
                console.error(`[${btnId}] Error:`, err);
                setButtonState(btn, 'error');
                setTimeout(() => setButtonState(btn, null), 2000);
            }
        });
    }

    // ---------------- Quick Actions ----------------
    async function changeRepo() {
        if (isReactDashboardActive()) return;
        showStatus('Loading repositories...', 'loading');

        try {
            const response = await fetch(api('/api/config'));
            const data = await response.json();
            const repos = data.repos || [];
            const currentRepo = (data.env && data.env.REPO) || data.default_repo || 'agro';

            if (repos.length === 0) {
                showStatus('No repositories configured', 'error');
                return;
            }

            // Create a dialog-like selection UI
            const repoHtml = repos.map((repo, idx) => {
                const isActive = repo.slug === currentRepo;
                return `
                    <button
                        class="small-button"
                        data-repo="${repo.slug}"
                        style="
                            margin-bottom: 8px;
                            background: ${isActive ? 'var(--accent)' : 'var(--bg-elev2)'};
                            color: ${isActive ? 'var(--accent-contrast)' : 'var(--fg-muted)'};
                            border: 1px solid ${isActive ? 'var(--accent)' : 'var(--line)'};
                            width: 100%;
                            text-align: left;
                            padding: 12px;
                            display: flex;
                            justify-content: space-between;
                            align-items: center;
                        "
                    >
                        <span>${repo.slug}</span>
                        ${isActive ? '<span>✓ ACTIVE</span>' : ''}
                    </button>
                `;
            }).join('');

            const status = document.getElementById('dash-index-status');
            if (status) {
                status.innerHTML = `
                    <div style="padding: 8px;">
                        <div style="margin-bottom: 12px; color: var(--accent); font-weight: 600;">Select Repository:</div>
                        ${repoHtml}
                    </div>
                `;

                // Bind click handlers
                repos.forEach(repo => {
                    const btn = status.querySelector(`[data-repo="${repo.slug}"]`);
                    if (btn && repo.slug !== currentRepo) {
                        btn.addEventListener('click', async () => {
                            btn.disabled = true;
                            btn.style.opacity = '0.6';
                            showStatus(`Switching to ${repo.slug}...`, 'loading');

                            try {
                                const updateResponse = await fetch(api('/api/config'), {
                                    method: 'POST',
                                    headers: { 'Content-Type': 'application/json' },
                                    body: JSON.stringify({ env: { REPO: repo.slug } })
                                });

                                if (updateResponse.ok) {
                                    showStatus(`✓ Switched to ${repo.slug}`, 'success');
                                    setTimeout(() => refreshDashboard(), 500);
                                } else {
                                    showStatus(`✗ Failed to switch to ${repo.slug}`, 'error');
                                }
                            } catch (err) {
                                showStatus(`✗ Error switching repo: ${err.message}`, 'error');
                            }
                        });
                    }
                });
            }
        } catch (err) {
            showStatus(`Error loading repos: ${err.message}`, 'error');
        }
    }

    async function createKeywords() {
        if (isReactDashboardActive()) return;
        const btn = document.getElementById('btn-generate-keywords');
        setButtonState(btn, 'loading');
        showStatus('Generating keywords (this may take 2–5 minutes)...', 'loading');
        let sim; // progress simulator for keyword generation
        try {
            const response = await fetch(api('/api/config'));
            const data = await response.json();
            const env = (data && data.env) || (state.config && state.config.env) || {};
            const repo = env.REPO || data.default_repo || 'agro';
            const modeSel = document.getElementById('kw-gen-mode');
            const mode = modeSel ? (modeSel.value || 'llm') : 'llm';
            const maxFilesEl = document.querySelector('[name="KEYWORDS_MAX_FILES"]');
            const max_files = maxFilesEl && maxFilesEl.value ? Number(maxFilesEl.value) : undefined;
            // Force OpenAI 4o for this on-click run (per request)
            const backend = 'openai';
            let model = 'gpt-4o';
            const tips = [
                'After keywords, build Semantic Cards in Repos → Indexing',
                'Add Path Boosts to steer retrieval (Repos tab)',
                'Toggle ENRICH_CODE_CHUNKS to store per‑chunk summaries',
                'Use shared profile to reuse indices across branches (Infrastructure)'
            ];
            sim = startSimProgress(
                mode === 'llm' ? `Mode: LLM • Backend: ${backend} • Model: ${model}` : 'Mode: Heuristic • Scanning tokens and file coverage…',
                max_files || 80,
                tips
            );

            // Call the keywords generation endpoint
            const createResponse = await fetch(api('/api/keywords/generate'), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ repo, mode, max_files, backend, openai_model: (backend==='openai'?model:undefined) })
            });

            if (createResponse.ok) {
                const result = await createResponse.json();

                if (result.ok) {
                    // Support both new format (count/keywords) and legacy format (discriminative/semantic/total_count)
                    const total = result.count ?? result.total_count ?? 0;
                    const keywords = result.keywords || [];
                    const duration = result.duration_seconds || 0;

                    // Build detailed status message - simplified for repos.json single source
                    const status = `
                        <div style="font-size:14px;font-weight:600;color:var(--accent);margin-bottom:8px;">
                            ✓ Loaded ${total} keywords for repo: ${repo}
                        </div>
                        <div style="font-size:12px;color:var(--fg);margin-bottom:4px;">
                            Keywords sourced from <span style="color:var(--link);">repos.json</span>
                        </div>
                        <div style="font-size:11px;color:var(--fg-muted);margin-top:8px;">
                            Completed in ${duration}s
                        </div>
                        <div style="font-size:11px;color:var(--fg-muted);margin-top:6px;">
                            → View keywords in <span style="color:var(--accent);font-weight:600;">Repos & Indexing</span> tab
                        </div>
                    `;

                    const statusDiv = document.getElementById('dash-index-status');
                    if (statusDiv) {
                        statusDiv.innerHTML = status + `
                            <div style="margin-top:8px;">
                                <button id="cta-build-cards" class="small-button">Build Cards Now</button>
                            </div>
                        `;
                        const cta = document.getElementById('cta-build-cards');
                        if (cta) cta.addEventListener('click', async () => { try { switchTab('repos'); startCardsBuild(); } catch(e) { showStatus('Unable to start cards build', 'error'); } });
                    }

                    // Reload keywords to populate the UI
                    await loadKeywords();
                    setButtonState(btn, 'success');
                    setTimeout(()=> setButtonState(btn, null), 1500);
                    try { if (sim && sim.stop) sim.stop(); } catch {/* no-op */}
                } else {
                    showStatus(`Failed to generate keywords: ${result.error || 'Unknown error'}`, 'error');
                    setButtonState(btn, 'error');
                    setTimeout(()=> setButtonState(btn, null), 2000);
                    try { if (sim && sim.stop) sim.stop(); } catch {/* no-op */}
                }
            } else {
                const error = await createResponse.text();
                showStatus(`Failed to generate keywords: ${error}`, 'error');
                setButtonState(btn, 'error');
                setTimeout(()=> setButtonState(btn, null), 2000);
                try { if (sim && sim.stop) sim.stop(); } catch {/* no-op */}
            }
        } catch (err) {
            showStatus(`Error generating keywords: ${err.message}`, 'error');
            const btn = document.getElementById('btn-generate-keywords');
            setButtonState(btn, 'error');
            setTimeout(()=> setButtonState(btn, null), 2000);
            try { if (sim && sim.stop) sim.stop(); } catch {/* no-op */}
        }
    }

    async function reloadConfig() {
        showStatus('Reloading configuration...', 'loading');

        try {
            const response = await fetch(api('/api/env/reload'), {
                method: 'POST'
            });

            if (response.ok) {
                showStatus('Configuration reloaded successfully', 'success');
                await loadConfig();
                await refreshDashboard();
            } else {
                const error = await response.text();
                showStatus(`Failed to reload config: ${error}`, 'error');
            }
        } catch (err) {
            showStatus(`Error reloading config: ${err.message}`, 'error');
        }
    }

    // ---------------- Bindings ----------------
    /**
     * ---agentspec
     * what: |
     *   Binds click handlers to UI buttons (health, save, estimate, scan, apply, profile). Each handler triggers corresponding action function.
     *
     * why: |
     *   Centralizes event listener attachment; guards against null elements with conditional checks.
     *
     * guardrails:
     *   - DO NOT assume elements exist; all bindings check null before addEventListener
     *   - NOTE: Mixed jQuery ($) and vanilla DOM selectors; standardize to one approach
     *   - ASK USER: genBtn binding incomplete; handler missing
     * ---/agentspec
     */
    function bindActions() {
        const btnHealth = $('#btn-health'); if (btnHealth) btnHealth.addEventListener('click', checkHealth);
        const saveBtn = $('#save-btn'); if (saveBtn) saveBtn.addEventListener('click', saveConfig);
        const btnEstimate = $('#btn-estimate'); if (btnEstimate) btnEstimate.addEventListener('click', estimateCost);
        const btnScanHw = $('#btn-scan-hw'); if (btnScanHw) btnScanHw.addEventListener('click', scanHardware);
        const legacyApply = document.getElementById('btn-apply-profile');
        if (legacyApply) legacyApply.addEventListener('click', applyProfile);
        const btnSaveProfile = $('#btn-save-profile'); if (btnSaveProfile) btnSaveProfile.addEventListener('click', saveProfile);
        const genBtn = document.getElementById('btn-generate-profile');
        if (genBtn) genBtn.addEventListener('click', generateProfileWizard);
        const applyWizard = document.getElementById('btn-apply-wizard');
        if (applyWizard) applyWizard.addEventListener('click', applyProfileWizard);
        const oneClick = document.getElementById('btn-wizard-oneclick');
        if (oneClick) oneClick.addEventListener('click', onWizardOneClick);
        const loadCur = document.getElementById('btn-wizard-load-cur');
        if (loadCur) loadCur.addEventListener('click', loadWizardFromEnv);

        // Retrieval tab: trace button
        const rt = document.getElementById('btn-trace-latest');
        if (rt) rt.addEventListener('click', ()=>loadLatestTrace('trace-output'));
        const rtLS = document.getElementById('btn-trace-open-ls');
        if (rtLS) rtLS.addEventListener('click', async ()=>{
            try{
                const prj = (state.config?.env?.LANGCHAIN_PROJECT||'agro');
                const qs = new URLSearchParams({ project: prj, share: 'true' });
                const r = await fetch(api(`/api/langsmith/latest?${qs.toString()}`));
                const d = await r.json();
                if (d && d.url) window.open(d.url, '_blank');
                else alert('No recent LangSmith run found. Ask a question first.');
            }catch(e){ alert('Unable to open LangSmith: '+e.message); }
        });

        // Chat bindings - DISABLED when React ChatInterface is active
        if (!document.querySelector('[data-react-chat="true"]')) {
            const chatSend = document.getElementById('chat-send');
            if (chatSend) chatSend.addEventListener('click', sendChat);
            const chatInput = document.getElementById('chat-input');
            if (chatInput) chatInput.addEventListener('keydown', (e)=>{ if ((e.ctrlKey||e.metaKey) && e.key==='Enter') { e.preventDefault(); sendChat(); }});
            const chatClear = document.getElementById('chat-clear');
            if (chatClear) chatClear.addEventListener('click', ()=>{ const box=document.getElementById('chat-messages'); if (box) box.innerHTML='';});
            const chatTrace = document.getElementById('chat-trace');
            if (chatTrace) chatTrace.addEventListener('toggle', ()=>{ if (chatTrace.open) loadLatestTrace('chat-trace-output'); });
        }

        // Dopamine-y feedback on any button click
        document.querySelectorAll('button').forEach(btn => {
            if (isInsideReactDashboard(btn)) return;
            if (btn.dataset && btn.dataset.dopamineBound) return;
            if (!btn.dataset) btn.dataset = {};
            btn.dataset.dopamineBound = '1';
            btn.addEventListener('click', () => {
                const label = (btn.textContent || btn.id || 'button').trim();
                if (label) showStatus(`→ ${label}`, 'info');
            });
        });

        const addGen = document.getElementById('btn-add-gen-model');
        if (addGen) addGen.addEventListener('click', addGenModelFlow);
        const addEmb = document.getElementById('btn-add-embed-model');
        if (addEmb) addEmb.addEventListener('click', addEmbedModelFlow);
        const addRr = document.getElementById('btn-add-rerank-model');
        if (addRr) addRr.addEventListener('click', addRerankModelFlow);
        const addCost = document.getElementById('btn-add-cost-model');
        if (addCost) addCost.addEventListener('click', addCostModelFlow);

        const btnAuto = document.getElementById('btn-autotune-refresh');
        if (btnAuto) btnAuto.addEventListener('click', refreshAutotune);
        const cbAuto = document.getElementById('autotune-enabled');
        if (cbAuto) cbAuto.addEventListener('change', setAutotuneEnabled);

        const btnIndex = document.getElementById('btn-index-start');
        if (btnIndex) btnIndex.addEventListener('click', () => {
            if (window.IndexStatus && typeof window.IndexStatus.startIndexing === 'function') {
                window.IndexStatus.startIndexing();
            }
        });
        document.querySelectorAll('#btn-cards-build').forEach(btn => {
            if (!btn.dataset.cardsBuildBound) { btn.dataset.cardsBuildBound='1'; btn.addEventListener('click', () => startCardsBuild()); }
        });
        const btnCardsRefresh = document.getElementById('btn-cards-refresh');
        if (btnCardsRefresh) btnCardsRefresh.addEventListener('click', refreshCards);
        // Dashboard button bindings with enhanced feedback
        bindQuickAction('dash-index-start', () => {
            if (window.IndexStatus && typeof window.IndexStatus.startIndexing === 'function') {
                window.IndexStatus.startIndexing();
            }
        });
        bindQuickAction('dash-cards-refresh', refreshCards);
        bindQuickAction('dash-change-repo', changeRepo);
        bindQuickAction('dash-reload-config', reloadConfig);
        // Keep cost panel in sync with wizard selections
        const map = [
            ['wizard-gen-model','cost-model'],
            ['wizard-embed-provider','cost-embed-provider'],
            ['wizard-rerank-provider','cost-rerank-provider'],
            ['wizard-rerank-model','cost-rerank-model'],
        ];
        map.forEach(([a,b]) => { const elA = document.getElementById(a), elB = document.getElementById(b); if (elA && elB) elA.addEventListener('input', () => { elB.value = elA.value; }); });
    }

    // ---------------- Collapsible Sections & Resizable Sidepanel ----------------
    // Delegated to UiHelpers module (gui/js/ui-helpers.js)
    const bindCollapsibleSections = window.UiHelpers?.bindCollapsibleSections || (() => console.warn('[app.js] UiHelpers.bindCollapsibleSections not available'));
    const bindResizableSidepanel = window.UiHelpers?.bindResizableSidepanel || (() => console.warn('[app.js] UiHelpers.bindResizableSidepanel not available'));

    // ---------------- Global Search (live) ----------------
    // Delegated to Search module (gui/js/search.js)
    const bindGlobalSearchLive = window.Search?.bindGlobalSearchLive || (() => {});

    // ---------------- MCP RAG Search (debug) ----------------
    const bindMcpRagSearch = window.McpRag?.bind || (()=>{});

    // ---------------- LangSmith (Preview) ----------------
    const bindLangSmithViewer = window.LangSmith?.bind || (()=>{});
    // ---------------- Commit Metadata ----------------
    const loadCommitMeta = window.CommitMeta?.load || (async ()=>{});
    const saveCommitMeta = window.CommitMeta?.save || (async ()=>{});

    // ---------------- Autotune ----------------
    // Delegated to Autotune module (gui/js/autotune.js)
    const refreshAutotune = window.Autotune?.refreshAutotune || (async () => {});
    const setAutotuneEnabled = window.Autotune?.setAutotuneEnabled || fallbackSetAutotuneEnabled;

    // ---------------- Help Tooltips (delegated) ----------------
    const addHelpTooltips = window.Tooltips?.attachTooltips || fallbackAddHelpTooltips;

    const wireDayConverters = window.UiHelpers?.wireDayConverters || (() => {});

    // ---------------- Keywords (delegated) ----------------
    const loadKeywords = window.Keywords?.loadKeywords || (async () => {});

    // ---------------- Init ----------------
    async function init() {
        bindTabs();
        bindSubtabs();
        bindActions();
        bindGlobalSearch();
        bindGlobalSearchLive();
        bindResizableSidepanel();
        bindCollapsibleSections();
        bindDropzone();
        bindMcpRagSearch();
        bindLangSmithViewer();
        const hookBtn = document.getElementById('btn-install-hooks'); if (hookBtn) hookBtn.addEventListener('click', installHooks);
        const saveMetaBtn = document.getElementById('btn-save-commit-meta'); if (saveMetaBtn) saveMetaBtn.addEventListener('click', saveCommitMeta);
        const genKwBtn = document.getElementById('btn-generate-keywords'); if (genKwBtn) genKwBtn.addEventListener('click', createKeywords);

        await Promise.all([
            loadmodels(),
            loadConfig(),
            loadProfiles(),
            loadKeywords(),
            loadCommitMeta()
        ]);

        await checkHealth();
        await refreshAutotune();
        await refreshDashboard();
        await refreshHooksStatus();
        addHelpTooltips();
        // Note: comma formatting removed for cost-* fields since they are type="number" inputs
        wireDayConverters();
    }

    // -------- Embedded Editor (delegated) --------
    const checkEditorHealth = window.Editor?.checkEditorHealth || (async ()=>{});
    const openEditorWindow = window.Editor?.openEditorWindow || (async ()=>{});
    const copyEditorUrl = window.Editor?.copyEditorUrl || (async ()=>{});
    const restartEditor = window.Editor?.restartEditor || (async ()=>{});
    window.initEditorHealthCheck = function(){
        if (window.Editor?.initEditorHealthCheck) window.Editor.initEditorHealthCheck();
    };
    window.stopEditorHealthCheck = function(){
        if (window.Editor?.stopEditorHealthCheck) window.Editor.stopEditorHealthCheck();
    };
    // Ensure init runs even if DOMContentLoaded already fired (scripts at body end)
    if (document.readyState === 'loading') {
        window.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

    // Decide v1 (client) vs v2 (server) auto-profile
    async function onWizardOneClick(e){
        try{
            const v2 = document.getElementById('apv2-enabled');
            if (v2 && v2.checked && window.AutoProfileV2 && typeof window.AutoProfileV2.run === 'function'){
                e.preventDefault();
                await window.AutoProfileV2.run();
                return;
            }
        }catch{}
        return triChooseAndApply();
    }

    // ---------------- Dashboard Summary ----------------
    async function refreshDashboard() {
        if (isReactDashboardActive()) {
            return;
        }
        try {
            const c = state.config || (await (await fetch(api('/api/config'))).json());
            const repo = (c.env && (c.env.REPO || c.default_repo)) || '(none)';
            const reposCount = (c.repos || []).length;
            const dr = document.getElementById('dash-repo'); if (dr) dr.textContent = `${repo} (${reposCount} repos)`;
        } catch {}

        try {
            const h = await (await fetch(api('/health'))).json();
            const dh = document.getElementById('dash-health'); if (dh) dh.textContent = `${h.status}${h.graph_loaded? ' (graph ready)':''}`;
        } catch {}

        try {
            const a = await (await fetch(api('/api/autotune/status'))).json();
            const da = document.getElementById('dash-autotune'); if (da) da.textContent = a.enabled ? (a.current_mode || 'enabled') : 'disabled';
        } catch { const da = document.getElementById('dash-autotune'); if (da) da.textContent = 'Pro required'; }

        try {
            const cards = await (await fetch(api('/api/cards'))).json();
            const dc = document.getElementById('dash-cards'); if (dc) dc.textContent = `${cards.count || 0} cards`;
        } catch {}

        // MCP status (python http, node http, python stdio)
        try {
            const dm = document.getElementById('dash-mcp');
            const r = await fetch(api('/api/mcp/status'));
            if (r.ok) {
                const s = await r.json();
                const parts = [];
                if (s.python_http) {
                    const ph = s.python_http;
                    parts.push(`py-http:${ph.host}:${ph.port}${ph.path} ${ph.running ? '' : '(stopped)'}`.trim());
                }
                if (s.node_http) {
                    const nh = s.node_http;
                    parts.push(`node-http:${nh.host}:${nh.port}${nh.path || ''} ${nh.running ? '' : '(stopped)'}`.trim());
                }
                if (s.python_stdio_available !== undefined) {
                    parts.push(`py-stdio:${s.python_stdio_available ? 'available' : 'missing'}`);
                }
                if (dm) dm.textContent = parts.join(' | ') || 'unknown';
            } else {
                if (dm) dm.textContent = 'unknown';
            }
        } catch { const dm = document.getElementById('dash-mcp'); if (dm) dm.textContent = 'unknown'; }

        // Load initial index status to show metadata (delegated)
        try {
            if (window.IndexStatus && typeof window.IndexStatus.pollIndexStatus === 'function') {
                await window.IndexStatus.pollIndexStatus();
            }
        } catch {}
    }

    // ---------------- Cards Viewer (delegated) ----------------
    // Cards are handled by window.Cards/window.CardsBuilder
    /*
    async function loadCards() {
        try {
            const resp = await fetch(api('/api/cards'));
            const data = await resp.json();
            const cards = Array.isArray(data.cards) ? data.cards : [];
            const last = data.last_build || null;
            const lastBox = document.getElementById('cards-last-build');
            if (lastBox) {
                if (last && last.started_at) {
                    const when = new Date(last.started_at).toLocaleString();
                    const cnt = (last.result && last.result.cards_written) ? ` • ${last.result.cards_written} updated` : '';
                    const dur = (last.result && typeof last.result.duration_s==='number') ? ` • ${last.result.duration_s}s` : '';
                    lastBox.textContent = `Last build: ${when}${cnt}${dur}`;
                    lastBox.style.display = 'block';
                } else {
                    lastBox.style.display = 'none';
                }
            }
            const cardsContainer = document.getElementById('cards-viewer');
            if (cardsContainer) {
                cardsContainer.innerHTML = cards.length === 0 ?
                    `<div style="text-align: center; padding: 24px; color: var(--fg-muted);">
                        <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" style="opacity: 0.3; margin-bottom: 12px;">
                            <rect x="3" y="4" width="18" height="16" rx="2" ry="2"></rect>
                            <line x1="3" y1="9" x2="21" y2="9"></line>
                            <line x1="9" y1="4" x2="9" y2="20"></line>
                        </svg>
                        <div>No cards available</div>
                        <div style="font-size: 11px; margin-top: 8px;">Click "Build Cards" to generate code cards</div>
                    </div>` :
                    cards.map(card => `
                        <div class="card-item" data-filepath="${card.file_path}" data-line="${card.start_line || 1}"
                             style="background: var(--bg-elev2); border: 1px solid var(--line); border-radius: 6px; padding: 12px; cursor: pointer; transition: all 0.2s;"
                             onmouseover="this.style.borderColor='var(--accent)'; this.style.background='var(--bg-elev1)';"
                             onmouseout="this.style.borderColor='var(--line)'; this.style.background='var(--bg-elev2)';">
                            <h4 style="margin: 0 0 8px 0; color: var(--accent); font-size: 14px; font-weight: 600;">
                                ${(card.symbols && card.symbols[0]) ? card.symbols[0] : (card.file_path || '').split('/').slice(-1)[0]}
                            </h4>
                            <p style="margin: 0 0 8px 0; color: var(--fg-muted); font-size: 12px; line-height: 1.4;">
                                ${card.purpose || 'No description available'}
                            </p>
                            <div style="font-size: 10px; color: var(--fg-muted);">
                                <span style="color: var(--link);">${card.file_path || 'Unknown file'}</span>
                                ${card.start_line ? ` : ${card.start_line}` : ''}
                            </div>
                        </div>
                    `).join('');

                // Add click event listeners to cards
                document.querySelectorAll('.card-item[data-filepath]').forEach(card => {
                    card.addEventListener('click', function() {
                        const filePath = this.dataset.filepath;
                        const lineNumber = this.dataset.line;
                        jumpToLine(filePath, lineNumber);
                    });
                });
            }
        } catch (error) {
            console.error('Error loading cards:', error);
            const cardsContainer = document.getElementById('cards-viewer');
            if (cardsContainer) {
                cardsContainer.innerHTML = `<div style="text-align: center; padding: 24px; color: var(--err);">
                    Error loading cards: ${error.message}
                </div>`;
            }
        }
    }

    /**
     * ---agentspec
     * what: |
     *   Navigates to file:line via CustomEvent dispatch. Logs navigation target with emoji prefix.
     *
     * why: |
     *   Decouples navigation logic from UI; allows listeners to handle jumps independently.
     *
     * guardrails:
     *   - DO NOT assume event listener exists; dispatch is fire-and-forget
     *   - NOTE: lineNumber must be positive integer; no validation here
     * ---/agentspec
     */
    function jumpToLine(filePath, lineNumber) {
        // Enhanced navigation with visual feedback
        console.log(`📍 Navigate to: ${filePath}:${lineNumber}`);

        // Visual feedback
        const event = new CustomEvent('cardNavigation', {
            detail: { file: filePath, line: lineNumber }
        });
        window.dispatchEvent(event);

        // You can add VSCode or other IDE integration here
        // For now, show in a notification style
        const notification = document.createElement('div');
        notification.style.cssText = `
            position: fixed; bottom: 20px; right: 20px;
            background: var(--bg-elev2); border: 1px solid var(--accent);
            padding: 12px 16px; border-radius: 6px;
            color: var(--fg); font-size: 13px; z-index: 10000;
            animation: slideInRight 0.3s ease;
        `;
        notification.innerHTML = `
            <div style="display: flex; align-items: center; gap: 8px;">
                <span style="color: var(--accent);">📍</span>
                <span>Navigate to: <strong style="color: var(--link);">${filePath}:${lineNumber}</strong></span>
            </div>
        `;
        document.body.appendChild(notification);
        setTimeout(() => notification.remove(), 3000);
    }

    // Add refresh and build handlers
    // moved to Cards module

    async function buildCards() {
        try {
            const btn = document.getElementById('btn-cards-build');
            if (btn) {
                btn.disabled = true;
                btn.textContent = 'Building Cards...';
            }

            const resp = await fetch(api('/api/cards/build'), { method: 'POST' });
            const data = await resp.json();

            if (data.success || data.status === 'success') {
                console.log('✅ Cards built successfully');
                await loadCards(); // Reload the cards
            } else {
                console.error('❌ Failed to build cards:', data.message || 'Unknown error');
            }
        } catch (error) {
            console.error('Error building cards:', error);
        } finally {
            const btn = document.getElementById('btn-cards-build');
            if (btn) {
                btn.disabled = false;
                btn.innerHTML = '<span style="margin-right: 4px;">⚡</span> Build Cards';
            }
        }
    }

    try { window.jumpToLine = jumpToLine; } catch {}

    // Cards module auto-binds on DOMContentLoaded (see gui/js/cards.js)

    // ---------------- Help Tooltips ----------------
    /**
     * ---agentspec
     * what: |
     *   Adds help tooltips to UI by mapping config keys (GEN_MODEL, OPENAI_API_KEY, etc.) to human-readable descriptions. Returns HELP object with key→tooltip pairs.
     *
     * why: |
     *   Centralizes tooltip text to avoid duplication and enable easy localization/updates.
     *
     * guardrails:
     *   - DO NOT expose secrets in tooltip text; keep descriptions generic
     *   - NOTE: HELP object must match all config keys used in UI
     * ---/agentspec
     */
    function fallbackAddHelpTooltips() {
        const HELP = {
            // Generation
            GEN_MODEL: 'Primary inference model for generation (e.g., gpt-4o-mini or qwen3-coder:14b).',
            OPENAI_API_KEY: 'API key for OpenAI-compatible endpoints (generation/embeddings).',
            OPENAI_BASE_URL: 'Optional OpenAI-compatible base URL (vLLM/proxy).',
            OLLAMA_URL: 'Local model endpoint (Ollama or MLX serve).',
            ENRICH_MODEL: 'Model used to enrich code chunks before embedding (text summaries).',
            ENRICH_MODEL_OLLAMA: 'Local enrich model for Ollama/MLX.',
            GEN_MODEL_HTTP: 'Override GEN_MODEL for HTTP server responses only.',
            GEN_MODEL_MCP: 'Override GEN_MODEL for MCP tool responses only.',
            GEN_MODEL_CLI: 'Override GEN_MODEL for CLI chat only.',
            ENRICH_BACKEND: 'Force enrich backend (mlx or ollama).',

            // Embeddings
            EMBEDDING_TYPE: 'Embedding provider for dense vector search (openai, voyage, mxbai, local).',
            VOYAGE_API_KEY: 'API key for Voyage embeddings.',
            VOYAGE_EMBED_DIM: 'Output dimension for Voyage embeddings.',
            EMBEDDING_DIM: 'Embedding dimension for MXBAI/local models.',
            SKIP_DENSE: 'If 1, skip building dense vectors/Qdrant (sparse-only).',
            ENRICH_CODE_CHUNKS: 'If true, store per-chunk summaries/keywords before embedding.',

            // Reranking (verbose tips)
            RERANK_BACKEND: 'Choose the reranking backend that orders retrieved chunks by semantic relevance.\n• cohere — hosted reranker; highest quality. Requires COHERE_API_KEY.\n• local — local cross-encoder via rerankers lib (e.g., BGE). Requires one-time model download.\n• hf — Hugging Face pipeline (e.g., Jina reranker). Set TRANSFORMERS_TRUST_REMOTE_CODE=1 if required.\n• none — disable reranking (BM25/vector fusion only).\nTip: Start with cohere for quality; fall back to none when fully offline.',
            RERANKER_MODEL: 'Local/HF cross-encoder name used when RERANK_BACKEND=local or hf.\nExamples: cross-encoder/ms-marco-MiniLM-L-12-v2, BAAI/bge-reranker-v2-m3, jinaai/jina-reranker-v3.\nNote: First use may download model files. Keep TRANSFORMERS_TRUST_REMOTE_CODE=1 for Jina variants.',
            COHERE_API_KEY: 'Cohere API key for reranking when RERANK_BACKEND=cohere.\nStored locally in .env and used only on your machine.',
            COHERE_RERANK_MODEL: 'Cohere reranker to use when RERANK_BACKEND=cohere.\nCommon: rerank-3.5 (general), rerank-english-v3.0, rerank-multilingual-v3.0, rerank-english-lite-v3.0.\nPick from the dropdown or type a custom value.',
            TRANSFORMERS_TRUST_REMOTE_CODE: 'Advanced: Allow Hugging Face models that need remote code execution (True/False).\nRequired for some Jina/MXBAI rerankers. Set to 0 to harden if only using Cohere.',
            RERANK_INPUT_SNIPPET_CHARS: 'Max code/text characters sent to the reranker per candidate.\nCohere typical: 700. HF/local typical: 600.\nIncrease for more context (potentially higher latency); decrease for speed.',

            // Retrieval
            MAX_QUERY_REWRITES: 'Multi-query expansion count (more rewrites → better recall, more cost).',
            FINAL_K: 'Final top-K after fusion + rerank (downstream consumers use these).',
            TOPK_DENSE: 'Number of dense candidates (Qdrant) to fuse.',
            TOPK_SPARSE: 'Number of sparse candidates (BM25) to fuse.',
            HYDRATION_MODE: 'lazy: hydrate code snippets on demand; none: skip hydration.',
            HYDRATION_MAX_CHARS: 'Max characters per hydrated code snippet.',
            VENDOR_MODE: 'Prefer first-party or vendor paths when scoring files.',
            project_PATH_BOOSTS: 'CSV of path substrings to boost (e.g., app/,lib/,config/).',
            CARDS_MAX: 'Limit number of cards used for boosting (0 = all).',

            // Confidence
            CONF_TOP1: 'Accept answer if top-1 rerank score exceeds this threshold.',
            CONF_AVG5: 'Accept if average of top-5 rerank scores exceeds this threshold.',
            CONF_ANY: 'Accept if overall confidence exceeds this fallback threshold.',

            // Infra
            QDRANT_URL: 'Qdrant endpoint for vector search.',
            REDIS_URL: 'Redis for LangGraph memory/checkpointer.',
            REPO: 'Active repository tag for routing and output directories.',
            COLLECTION_SUFFIX: 'Optional suffix to group collections in Qdrant.',
            COLLECTION_NAME: 'Override Qdrant collection name.',
            REPO_PATH: 'Fallback path when repos.json is absent.',
            REPO_ROOT: 'Override project root. Affects GUI/docs/files mounts.',
            FILES_ROOT: 'Root directory served at /files.',
            GUI_DIR: 'Directory for shared UI assets (pricing/profile data). Defaults to ./web/public.',
            DOCS_DIR: 'Directory of docs served at /docs.',
            DATA_DIR: 'Directory for local data files (excludes, keywords).',
            REPOS_FILE: 'Path to repos.json configuration file.',
            OUT_DIR_BASE: 'Base output directory for per-repo data.',
            RAG_OUT_BASE: 'Alternate env for OUT_DIR_BASE.',
            MCP_HTTP_HOST: 'Host for MCP HTTP server.',
            MCP_HTTP_PORT: 'Port for MCP HTTP server.',
            MCP_HTTP_PATH: 'Path prefix for MCP HTTP server.',

            // Misc
            AGRO_EDITION: 'Edition gate (oss, pro, enterprise). Pro/Enterprise unlock Autotune/Compat.',
            THREAD_ID: 'LangGraph thread id (http or cli-chat).',
            PORT: 'Uvicorn port for serve entrypoints.',
            PROJECT_PATH: 'Optional reference path used by some helpers.',
            LANGCHAIN_TRACING_V2: 'Enable tracing for LangChain-compatible tooling.',
            LANGCHAIN_PROJECT: 'Tracing project name.',
            NETLIFY_API_KEY: 'Key for Netlify actions (if used).',
            NETLIFY_DOMAINS: 'Comma-separated domains for Netlify deploy (if used).',
        };
        $$('.settings-section .input-group').forEach(g=>{
            const label = g.querySelector('label'); const input = g.querySelector('input,select,textarea');
            if (!label || !input) return; const key = input.name || input.id; const help = HELP[key];
            if (!help) return; if (label.querySelector('.help')) return;
            const tip = document.createElement('span'); tip.className='help'; tip.title = help; tip.textContent='?';
            label.appendChild(tip);
        });
    }

    async function fallbackSetAutotuneEnabled() {
        try {
            const enabled = document.getElementById('autotune-enabled').checked;
            const r = await fetch(api('/api/autotune/status'), {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ enabled, current_mode: null })
            });
            if (!r.ok) {
                if (r.status === 403 || r.status === 402) {
                    alert('Autotune is a Pro feature. Enable it by setting Edition to "pro" (Misc section) or PRO_ENABLED=1.');
                    $('#autotune-enabled').checked = false;
                    return;
                }
                throw new Error('HTTP ' + r.status);
            }
            await refreshAutotune();
        } catch (e) {
            alert('Failed to set Auto‑Tune: ' + e.message);
        }
    }

    // DUPLICATE REMOVED: Indexing + Cards (use window.IndexStatus)
    // ---------------- Indexing + Cards ----------------
    let indexPoll = null;
    /**
     * ---agentspec
     * what: |
     *   Parses log lines to estimate indexing progress. Returns percentage (5–100) based on regex matches for chunk preparation, BM25 save, and Qdrant indexing completion.
     *
     * why: |
     *   Provides real-time progress feedback without blocking on async indexing operations.
     *
     * guardrails:
     *   - DO NOT rely on log order; regex matches are independent
     *   - NOTE: Returns 5% if no patterns match; final state is 100% only after Qdrant confirmation
     * ---/agentspec
     */
    function progressFromLog(lines) {
        const text = (lines||[]).join(' ');
        let pct = 5;
        if (/Prepared \d+ chunks/i.test(text)) pct = 20;
        if (/BM25 index saved/i.test(text)) pct = 60;
        if (/Indexed \d+ chunks to Qdrant/i.test(text)) pct = 100;
        return pct;
    }

    async function startIndexing() {
        try {
            showStatus('Starting indexer...', 'loading');
            await fetch(api('/api/index/start'), { method: 'POST' });
            if (indexPoll) clearInterval(indexPoll);
            indexPoll = setInterval(pollIndexStatus, 2000); // poll every 2 seconds during indexing
            await pollIndexStatus();
        } catch (e) {
            showStatus('Failed to start indexer: ' + e.message, 'error');
            throw e;
        }
    }

    /**
     * ---agentspec
     * what: |
     *   Converts byte count to human-readable format (B, KB, MB, GB). Takes numeric bytes, returns formatted string.
     *
     * why: |
     *   Standardizes file size display across UI without repeated conversion logic.
     *
     * guardrails:
     *   - DO NOT use for network throughput; only file sizes
     *   - NOTE: Returns '0 B' for null/undefined/zero input
     * ---/agentspec
     */
    function formatBytes(bytes) {
        if (!bytes || bytes === 0) return '0 B';
        const k = 1024;
        const sizes = ['B', 'KB', 'MB', 'GB'];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        return Math.round((bytes / Math.pow(k, i)) * 100) / 100 + ' ' + sizes[i];
    }

    /**
     * ---agentspec
     * what: |
     *   Formats index status display. Takes lines array and metadata object; returns HTML div with styled status text or "Ready to index..." placeholder.
     *
     * why: |
     *   Centralizes status rendering logic with conditional metadata handling for consistent UI presentation.
     *
     * guardrails:
     *   - DO NOT render unsanitized user input; escape HTML in lines
     *   - NOTE: Returns muted gray text (13px) when no metadata; metadata path incomplete in code
     * ---/agentspec
     */
    function formatIndexStatus(lines, metadata) {
        if (!metadata) {
            if (!lines || !lines.length) return '<div style="color:var(--fg-muted);font-size:13px;">Ready to index...</div>';
            return `<div style="color: var(--fg-muted);font-size:12px;">${lines.join('<br>')}</div>`;
        }

        // Enterprise-grade comprehensive display
        const html = [];

        // Header with repo/branch
        html.push(`
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;padding-bottom:12px;border-bottom:1px solid var(--line);">
                <div style="display:flex;align-items:center;gap:12px;">
                    <div style="width:6px;height:6px;border-radius:50%;background:var(--accent);box-shadow:0 0 8px var(--accent);"></div>
                    <div>
                        <div style="font-size:16px;font-weight:600;color:var(--fg);letter-spacing:-0.3px;">${metadata.current_repo}</div>
                        <div style="font-size:11px;color:var(--fg-muted);text-transform:uppercase;letter-spacing:0.5px;margin-top:2px;">
                            Branch: <span style="color:var(--link);">${metadata.current_branch}</span>
                        </div>
                    </div>
                </div>
                <div style="text-align:right;font-size:10px;color:var(--fg-muted);">
                    ${new Date(metadata.timestamp).toLocaleString()}
                </div>
            </div>
        `);

        // Configuration section
        html.push(`
            <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:16px;">
                <div style="background:var(--code-bg);padding:12px;border-radius:6px;border:1px solid var(--line);">
                    <div style="font-size:10px;color:var(--fg-muted);text-transform:uppercase;letter-spacing:0.5px;margin-bottom:6px;">Embedding Model</div>
                    <div style="font-size:14px;font-weight:600;color:var(--link);font-family:'SF Mono',monospace;">${metadata.embedding_model}</div>
                </div>
                <div style="background:var(--code-bg);padding:12px;border-radius:6px;border:1px solid var(--line);">
                    <div style="font-size:10px;color:var(--fg-muted);text-transform:uppercase;letter-spacing:0.5px;margin-bottom:6px;">Keywords</div>
                    <div style="font-size:14px;font-weight:600;color:var(--warn);font-family:'SF Mono',monospace;">${metadata.keywords_count.toLocaleString()}</div>
                </div>
            </div>
        `);

        // Index profiles section
        if (metadata.repos && metadata.repos.length > 0) {
            html.push(`<div style="margin-bottom:12px;"><div style="font-size:11px;font-weight:600;color:var(--accent);text-transform:uppercase;letter-spacing:0.5px;margin-bottom:10px;">Index Profiles</div></div>`);

            metadata.repos.forEach(repo => {
                const totalSize = (repo.sizes.chunks || 0) + (repo.sizes.bm25 || 0) + (repo.sizes.cards || 0);

                html.push(`
                    <div style="background:var(--code-bg);border:1px solid ${repo.has_cards ? 'var(--accent)' : 'var(--line)'};border-radius:6px;padding:12px;margin-bottom:8px;">
                        <div style="display:flex;justify-content:space-between;align-items:start;margin-bottom:10px;">
                            <div>
                                <div style="font-size:13px;font-weight:600;color:var(--fg);margin-bottom:4px;">
                                    ${repo.name} <span style="font-size:10px;color:var(--fg-muted);font-weight:400;">/ ${repo.profile}</span>
                                </div>
                                <div style="font-size:11px;color:var(--fg-muted);">
                                    ${repo.chunk_count.toLocaleString()} chunks
                                    ${repo.has_cards ? ' • <span style="color:var(--accent);">✓ Cards</span>' : ' • <span style="color:var(--fg-muted);">No cards</span>'}
                                </div>
                            </div>
                            <div style="text-align:right;">
                                <div style="font-size:14px;font-weight:600;color:var(--accent);font-family:'SF Mono',monospace;">
                                    ${formatBytes(totalSize)}
                                </div>
                            </div>
                        </div>
                        <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:8px;font-size:10px;">
                            ${repo.paths.chunks ? `
                                <div style="background:var(--code-bg);padding:6px 8px;border-radius:4px;border:1px solid var(--line);">
                                    <div style="color:var(--fg-muted);margin-bottom:2px;">Chunks</div>
                                    <div style="color:var(--link);font-family:'SF Mono',monospace;font-size:11px;">${formatBytes(repo.sizes.chunks)}</div>
                                </div>
                            ` : ''}
                            ${repo.paths.bm25 ? `
                                <div style="background:var(--code-bg);padding:6px 8px;border-radius:4px;border:1px solid var(--line);">
                                    <div style="color:var(--fg-muted);margin-bottom:2px;">BM25 Index</div>
                                    <div style="color:var(--warn);font-family:'SF Mono',monospace;font-size:11px;">${formatBytes(repo.sizes.bm25)}</div>
                                </div>
                            ` : ''}
                            ${repo.paths.cards ? `
                                <div style="background:var(--code-bg);padding:6px 8px;border-radius:4px;border:1px solid var(--line);">
                                    <div style="color:var(--fg-muted);margin-bottom:2px;">Cards</div>
                                    <div style="color:var(--accent);font-family:'SF Mono',monospace;font-size:11px;">${formatBytes(repo.sizes.cards)}</div>
                                </div>
                            ` : ''}
                        </div>
                        ${repo.paths.chunks ? `
                            <details style="margin-top:8px;">
                                <summary style="cursor:pointer;font-size:10px;color:var(--fg-muted);padding:4px 0;">
                                    <span style="color:var(--link);">▸</span> File Paths
                                </summary>
                                <div style="margin-top:6px;padding:8px;background:var(--code-bg);border-radius:4px;font-size:10px;font-family:'SF Mono',monospace;color:var(--fg-muted);">
                                    ${repo.paths.chunks ? `<div style="margin-bottom:2px;">📄 ${repo.paths.chunks}</div>` : ''}
                                    ${repo.paths.bm25 ? `<div style="margin-bottom:2px;">📁 ${repo.paths.bm25}</div>` : ''}
                                    ${repo.paths.cards ? `<div>🎴 ${repo.paths.cards}</div>` : ''}
                                </div>
                            </details>
                        ` : ''}
                    </div>
                `);
            });
        }

        // Total storage footer
        html.push(`
            <div style="display:flex;justify-content:space-between;align-items:center;padding-top:12px;border-top:1px solid var(--line);">
                <div style="font-size:12px;color:var(--fg-muted);text-transform:uppercase;letter-spacing:0.5px;">Total Index Storage</div>
                <div style="font-size:18px;font-weight:700;color:var(--accent);font-family:'SF Mono',monospace;">
                    ${formatBytes(metadata.total_storage)}
                </div>
            </div>
        `);

        return html.join('');
    }

    const pollIndexStatus = window.IndexStatus?.pollIndexStatus || (async ()=>{});

    // ---------------- Cards Builder (delegated) ----------------
    const openCardsModal = window.CardsBuilder?.openCardsModal || (()=>{});
    const startCardsBuild = window.CardsBuilder?.startCardsBuild || (async ()=>{});

    async function refreshCards() {
        try {
            showStatus('Refreshing dashboard...', 'loading');
            await refreshDashboard();
            showStatus('Dashboard refreshed', 'success');
        } catch (e) {
            showStatus('Failed to refresh: ' + e.message, 'error');
            throw e;
        }
    }

    // ---------------- Add Model Flows (delegated) ----------------
    const addGenModelFlow = window.ModelFlows?.addGenModelFlow || (async ()=>{});
    const addEmbedModelFlow = window.ModelFlows?.addEmbedModelFlow || (async ()=>{});
    const addRerankModelFlow = window.ModelFlows?.addRerankModelFlow || (async ()=>{});
    const addCostModelFlow = window.ModelFlows?.addCostModelFlow || (async ()=>{});


    // ============================================
    // Onboarding Wizard (delegated)
    // ============================================
    //  window.ensureOnboardingInit = function(){ if (window.Onboarding?.ensureOnboardingInit) window.Onboarding.ensureOnboardingInit(); };
})();
