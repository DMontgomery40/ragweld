// AGRO GUI - Tabs Module
// Handles main tab navigation, subtab switching, and lazy loading

(function () {
    'use strict';

    // Import utilities
    const { $$, $ } = window.CoreUtils || {};

    if (!$$ || !$) {
        console.error('[tabs.js] CoreUtils not loaded!');
        return;
    }

    // State
    let storageCalculatorLoaded = false;

    /**
     * Lazy load storage calculator when analytics tab is opened
     */
    /**
     * ---agentspec
     * what: |
     *   Loads storage calculator widget into DOM container. Calls getStorageCalculatorHTML() to fetch template, injects into #storage-calculator-container element.
     *
     * why: |
     *   Lazy-loads UI component only when needed; guards against duplicate initialization with storageCalculatorLoaded flag.
     *
     * guardrails:
     *   - DO NOT proceed if container missing; silently return to avoid errors
     *   - NOTE: Depends on getStorageCalculatorHTML() function existing; no fallback defined
     *   - ASK USER: Add error handling for missing function or container
     * ---/agentspec
     */
    function loadStorageCalculator() {
        if (storageCalculatorLoaded) return;
        const container = document.getElementById('storage-calculator-container');
        if (!container) return;

        // Load the HTML template
        if (typeof getStorageCalculatorHTML === 'function') {
            container.innerHTML = getStorageCalculatorHTML();

            // Initialize the calculator
            if (typeof initStorageCalculator === 'function') {
                initStorageCalculator();
            }

            storageCalculatorLoaded = true;
        }
    }

    // Tab ID aliases for backward compatibility
    // Maps old tab IDs to new Navigation view IDs
    const TAB_ALIASES = {
        // Old main tabs → new view IDs
        'onboarding': 'start',
        'config': 'rag',
        'data': 'rag',
        'devtools': 'vscode',
        'analytics': 'profiles',
        'metrics': 'grafana',
        'settings': 'admin',

        // Old subtabs → new view IDs
        'tab-onboarding': 'start',
        'tab-metrics': 'grafana',
        'tab-devtools-editor': 'vscode',
        'tab-devtools-testing': 'rag-evaluate',
        'tab-data-indexing': 'rag-indexing',
        'tab-reranker': 'rag-learning-ranker',
        'tab-devtools-reranker': 'rag-learning-ranker',
        'tab-config-models': 'rag-retrieval',
        'tab-config-retrieval': 'rag-retrieval',
        'tab-config-repos': 'rag-data-quality',
        'tab-analytics-cost': 'profiles',
        'tab-settings-profiles': 'profiles',
        'tab-config-infra': 'infrastructure',
        'tab-settings-docker': 'infrastructure',
        'tab-devtools-integrations': 'infrastructure',
        'tab-analytics-performance': 'infrastructure',
        'tab-analytics-usage': 'infrastructure',
        'tab-analytics-tracing': 'infrastructure',
        'tab-settings-general': 'admin',
        'tab-settings-integrations': 'admin',
        'tab-settings-secrets': 'admin',
        'tab-devtools-debug': 'admin'
    };

    /**
     * Switch to a main tab and its default subtabs
     * @param {string} tabName - Main tab identifier (e.g., 'config', 'data', 'analytics')
     */
    /**
     * ---agentspec
     * what: |
     *   Switches active tab by name. Resolves aliases via TAB_ALIASES, routes via Navigation API if available, falls back to direct ID lookup.
     *
     * why: |
     *   Centralizes tab routing logic with graceful degradation for older browsers.
     *
     * guardrails:
     *   - DO NOT assume Navigation API exists; check window.Navigation first
     *   - NOTE: TAB_ALIASES must be defined globally before switchTab() call
     *   - DO NOT proceed if target div #tab-{newTabId} missing; add validation
     * ---/agentspec
     */
    function switchTab(tabName) {
        console.log(`[tabs.js] switchTab called with: ${tabName}`);

        // If Navigation API is available, use it with alias resolution
        if (window.Navigation && typeof window.Navigation.navigateTo === 'function') {
            const newTabId = TAB_ALIASES[tabName] || tabName;
            console.log(`[tabs.js] Routing ${tabName} → ${newTabId} via Navigation API`);
            console.log(`[tabs.js] Looking for div: #tab-${newTabId}`);

            // CHECK: Does the div exist?
            const targetDiv = document.getElementById(`tab-${newTabId}`);
            console.log(`[tabs.js] Div exists: ${!!targetDiv}`);
            if (targetDiv) {
                console.log(`[tabs.js] Div content length: ${targetDiv.innerHTML.length}`);
            }

            window.Navigation.navigateTo(newTabId);

            // Emit old-style event for backward compatibility
            if (window.CoreUtils && window.CoreUtils.events) {
                window.CoreUtils.events.emit('tab-switched', {
                    tab: newTabId,
                    from: tabName
                });
            }
            return;
        }

        // Keep sidepanel visible for all tabs (requested behavior)

        // Fallback to old tab switching (compatibility mode)
        const groups = {
            start: ['onboarding'],
            dashboard: ['dashboard'],
            chat: ['chat'],
            vscode: ['devtools-editor'],  // New promoted tab
            grafana: ['metrics'],  // New promoted tab
            rag: ['config-models'],  // New mega-tab (defaults to retrieval)
            profiles: ['analytics-cost'],  // New consolidated tab
            infrastructure: ['settings-docker'],  // New consolidated tab
            admin: ['settings-general'],  // New consolidated tab
            config: ['config-models'],  // Keep for compatibility
            data: ['data-indexing'],  // Keep for compatibility
            devtools: ['devtools-editor'],  // Keep for compatibility
            analytics: ['analytics-cost'],  // Keep for compatibility
            metrics: ['metrics'],  // Keep for compatibility
            settings: ['settings-general']  // Keep for compatibility
        };
        const show = groups[tabName] || [tabName];
        $$('.tab-content').forEach(el => el.classList.remove('active'));
        show.forEach(id => { const el = document.getElementById(`tab-${id}`); if (el) el.classList.add('active'); });
        $$('.tab-bar button').forEach(el => el.classList.remove('active'));
        const btn = document.querySelector(`.tab-bar button[data-tab="${tabName}"]`);
        if (btn) btn.classList.add('active');

        // Load storage calculator when the tab is opened
        if (tabName === 'analytics' || tabName === 'profiles') {
            loadStorageCalculator();
        }

        // Initialize onboarding when first opened
        if (tabName === 'start' || tabName === 'onboarding') {
            if (typeof window.ensureOnboardingInit === 'function') {
                window.ensureOnboardingInit();
            }
        }
    }

    /**
     * Bind click handlers to main tab buttons
     */
    /**
     * ---agentspec
     * what: |
     *   Binds click handlers to tab-bar buttons. On click, extracts data-tab attribute and calls switchTab(). Optionally references trace button.
     *
     * why: |
     *   Centralizes tab navigation setup; decouples button markup from event logic.
     *
     * guardrails:
     *   - DO NOT assume switchTab() exists; will throw if undefined
     *   - NOTE: traceBtn reference unused; remove if not needed
     * ---/agentspec
     */
    function bindTabs() {
        $$('.tab-bar button').forEach(btn => {
            btn.addEventListener('click', () => {
                const tab = btn.getAttribute('data-tab');
                switchTab(tab);
            });
        });
        const traceBtn = document.getElementById('btn-trace-latest');
        if (traceBtn) {
            traceBtn.addEventListener('click', () => {
                if (typeof window.loadLatestTrace === 'function') {
                    window.loadLatestTrace();
                }
            });
        }
    }

    /**
     * Bind click handlers to RAG subtab buttons
     */
    /**
     * ---agentspec
     * what: |
     *   Binds click handlers to RAG subtab buttons. On click, retrieves data-subtab attribute and triggers subtab switch (implementation incomplete).
     *
     * why: |
     *   Centralizes event delegation for subtab navigation in RAG UI.
     *
     * guardrails:
     *   - NOTE: Handler retrieves subtabId but does not show/hide content; implementation incomplete
     *   - ASK USER: What should happen after subtabId is retrieved? (show panel, fetch data, etc.)
     *   - DO NOT assume querySelectorAll finds all buttons; verify selector matches intended buttons
     * ---/agentspec
     */
    function bindRagSubtabs() {
        const ragSubtabsBar = document.getElementById('rag-subtabs');
        if (!ragSubtabsBar) return;

        ragSubtabsBar.querySelectorAll('button').forEach(btn => {
            btn.addEventListener('click', () => {
                const subtabId = btn.getAttribute('data-subtab');
                if (!subtabId) return;

                console.log(`[tabs.js] RAG subtab clicked: ${subtabId}`);

                // Hide all RAG subtabs
                $$('#tab-rag .rag-subtab-content').forEach(el => el.classList.remove('active'));

                // Show selected subtab
                const targetSubtab = document.getElementById(`tab-rag-${subtabId}`);
                if (targetSubtab) {
                    targetSubtab.classList.add('active');
                    console.log(`[tabs.js] Showing RAG subtab: tab-rag-${subtabId}`);
                }

                // Update button states
                ragSubtabsBar.querySelectorAll('button').forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
            });
        });
    }

    /**
     * Bind click handlers to subtab buttons
     */
    /**
     * ---agentspec
     * what: |
     *   Binds click handlers to subtab buttons with data-parent attribute. On click, retrieves subtab ID and parent context; stops editor health check when leaving editor subtab.
     *
     * why: |
     *   Centralizes subtab navigation logic; excludes RAG subtabs (handled separately) to avoid duplicate binding.
     *
     * guardrails:
     *   - DO NOT bind RAG subtabs here; bindRagSubtabs() handles those separately
     *   - NOTE: Editor health check cleanup required on subtab exit
     *   - ASK USER: Is editor health check stop logic complete? (code snippet truncated)
     * ---/agentspec
     */
    function bindSubtabs() {
        // Only bind generic subtabs that declare a parent context.
        // RAG subtabs are handled separately by bindRagSubtabs().
        $$('.subtab-btn[data-parent]').forEach(btn => {
            btn.addEventListener('click', () => {
                const subtab = btn.getAttribute('data-subtab');
                const parent = btn.getAttribute('data-parent');

                // Stop editor health check when leaving editor subtab
                const wasEditorActive = document.querySelector('.subtab-btn[data-subtab="devtools-editor"].active');
                if (wasEditorActive && subtab !== 'devtools-editor') {
                    if (typeof window.stopEditorHealthCheck === 'function') {
                        window.stopEditorHealthCheck();
                    }
                }

                // Hide all parent tab contents first
                $$('.tab-content').forEach(el => el.classList.remove('active'));
                // Ensure the parent tab container is re-activated so its section-subtabs can be visible
                const parentWrap = document.getElementById(`tab-${parent}`);
                if (parentWrap) parentWrap.classList.add('active');
                // Then collapse any section-subtab within the same parent tab container
                if (parentWrap) parentWrap.querySelectorAll('.section-subtab').forEach(el => el.classList.remove('active'));
                const target = document.getElementById(`tab-${subtab}`);
                if (target) {
                    target.classList.add('active');
                } else {
                    console.warn(`[tabs.js] Subtab target not found: #tab-${subtab}`);
                }

                // Update button states for this parent group
                $$(`.subtab-btn[data-parent="${parent}"]`).forEach(b => b.classList.remove('active'));
                btn.classList.add('active');

                // Trigger editor health check if editor subtab is activated
                if (subtab === 'devtools-editor') {
                    console.log('[Editor] devtools-editor subtab clicked');
                    if (typeof window.initEditorHealthCheck === 'function') {
                        window.initEditorHealthCheck();
                    } else {
                        console.error('[Editor] initEditorHealthCheck not found!');
                    }
                }
            });
        });
    }

    // Export to window
    window.Tabs = {
        switchTab,
        bindTabs,
        bindSubtabs,
        loadStorageCalculator
    };

    // Auto-initialize when DOM is ready
    /**
     * ---agentspec
     * what: |
     *   Initializes tab UI bindings on page load. Calls bindTabs(), bindSubtabs(), bindRagSubtabs(). Logs readiness.
     *
     * why: |
     *   Defers initialization until DOM is ready to ensure elements exist.
     *
     * guardrails:
     *   - DO NOT call initTabs() before DOMContentLoaded; binding will fail on missing elements
     *   - NOTE: Assumes bindTabs, bindSubtabs, bindRagSubtabs are defined globally
     * ---/agentspec
     */
    function initTabs() {
        bindTabs();
        bindSubtabs();
        bindRagSubtabs();
        console.log('[tabs.js] Tab buttons bound and ready');
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initTabs);
    } else {
        // DOM already loaded
        initTabs();
    }

    console.log('[tabs.js] Module loaded');
})();
