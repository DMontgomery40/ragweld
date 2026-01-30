// AGRO GUI - RAG Tab Navigation
// Handles the mega-tab structure for RAG with subtabs
// Author: AGRO Redesign (Phase 2)

(function() {
    'use strict';

    const { $, $$, events } = window.CoreUtils || {};

    // RAG Subtab mappings to existing content
    const RAG_SUBTAB_MAP = {
        'data-quality': ['config-repos', 'keywords', 'cards'],
        'retrieval': ['config-models', 'config-retrieval'],
        'external-rerankers': ['config-reranking'],
        'learning-ranker': ['reranker'],
        'indexing': ['data-indexing', 'index-profiles'],
        'evaluate': ['devtools-golden', 'devtools-eval']
    };

    // Current subtab state
    let currentSubtab = 'data-quality';

    /**
     * Show RAG subtab navigation
     */
    /**
     * ---agentspec
     * what: |
     *   Toggles RAG subtab bar visibility. Selects #rag-subtabs element and sets display to 'flex' if present.
     *
     * why: |
     *   Encapsulates DOM manipulation for conditional UI state management.
     *
     * guardrails:
     *   - DO NOT assume #rag-subtabs exists; check prevents null errors
     *   - NOTE: Uses jQuery; ensure $ is available in scope
     * ---/agentspec
     */
    function showRagSubtabs() {
        const subtabBar = $('#rag-subtabs');
        if (subtabBar) {
            subtabBar.style.display = 'flex';
        }
    }

    /**
     * Hide RAG subtab navigation
     */
    /**
     * ---agentspec
     * what: |
     *   Hides RAG subtab bar by setting display to 'none'. Selects element via jQuery ID selector.
     *
     * why: |
     *   Conditional UI hiding for RAG workflow state management.
     *
     * guardrails:
     *   - DO NOT assume #rag-subtabs exists; add null check before style mutation
     *   - NOTE: jQuery selector returns falsy if element missing; current code will error on .style access
     * ---/agentspec
     */
    function hideRagSubtabs() {
        const subtabBar = $('#rag-subtabs');
        if (subtabBar) {
            subtabBar.style.display = 'none';
        }
    }

    /**
     * Switch to a RAG subtab
     */
    /**
     * ---agentspec
     * what: |
     *   Switches RAG UI subtab by name. Activates RAG main tab, deactivates all tab-content elements, then marks target subtab active.
     *
     * why: |
     *   Centralizes tab-switching logic to prevent orphaned active states across multiple tab groups.
     *
     * guardrails:
     *   - DO NOT assume subtabName element exists; add null check before classList.add()
     *   - NOTE: Deactivates ALL .tab-content; verify this doesn't hide unrelated tabs
     *   - ASK USER: Should inactive subtabs be hidden (display:none) or just unmarked (active class removed)?
     * ---/agentspec
     */
    function switchRagSubtab(subtabName) {
        console.log(`[RAG] Switching to subtab: ${subtabName}`);

        // Ensure RAG main tab is visible
        const ragTab = $('#tab-rag');
        if (ragTab) {
            $$('.tab-content').forEach(el => el.classList.remove('active'));
            ragTab.classList.add('active');
        }

        // Update active subtab button
        $$('#rag-subtabs button').forEach(btn => {
            const isActive = btn.getAttribute('data-subtab') === subtabName;
            btn.classList.toggle('active', isActive);
        });

        // Toggle internal RAG content panels
        $$('#tab-rag .rag-subtab-content').forEach(el => el.classList.remove('active'));
        const target = $(`#tab-rag-${subtabName}`);
        if (target) {
            target.classList.add('active');
        } else {
            console.warn(`[RAG] Missing panel for subtab: #tab-rag-${subtabName}`);
        }

        currentSubtab = subtabName;

        // Emit event
        if (events) {
            events.emit('rag:subtab-change', { subtab: subtabName });
        }
    }

    /**
     * Handle main tab changes
     */
    /**
     * ---agentspec
     * what: |
     *   Handles tab navigation to RAG section. Activates RAG container, displays subtabs, removes active class from all tab-content elements, then adds active class to RAG tab.
     *
     * why: |
     *   Ensures only one tab is visually active and RAG subtabs are available when RAG tab is selected.
     *
     * guardrails:
     *   - DO NOT call showRagSubtabs() before DOM query; may fail if subtabs not yet rendered
     *   - NOTE: Removes active from ALL .tab-content; verify no other tabs need simultaneous active state
     *   - ASK USER: Should inactive tabs be hidden (display:none) instead of just removing active class?
     * ---/agentspec
     */
    function handleTabChange(tabId) {
        if (tabId === 'rag') {
            showRagSubtabs();
            // Ensure RAG container is active and a subtab is selected
            const ragTab = $('#tab-rag');
            if (ragTab) {
                $$('.tab-content').forEach(el => el.classList.remove('active'));
                ragTab.classList.add('active');
            }
            switchRagSubtab(currentSubtab);
        } else {
            hideRagSubtabs();
        }
        
        // Handle VS Code tab
        if (tabId === 'vscode') {
            if (window.VSCode) {
                window.VSCode.showEditor();
            }
            // Show VS Code content
            const vsCodeTab = $('#tab-vscode');
            if (vsCodeTab) {
                $$('.tab-content').forEach(content => content.classList.remove('active'));
                vsCodeTab.classList.add('active');
            }
        }
        
        // Handle Grafana tab
        if (tabId === 'grafana') {
            if (window.Grafana) {
                window.Grafana.preview();
            }
            // Show Grafana content
            const grafanaTab = $('#tab-metrics');
            if (grafanaTab) {
                $$('.tab-content').forEach(content => content.classList.remove('active'));
                grafanaTab.classList.add('active');
            }
        }
        
        // Handle Profiles tab (was Analytics)
        if (tabId === 'profiles') {
            const profilesTab = $('#tab-analytics-cost');
            if (profilesTab) {
                $$('.tab-content').forEach(content => content.classList.remove('active'));
                profilesTab.classList.add('active');
            }
        }
        
        // Handle Infrastructure tab
        if (tabId === 'infrastructure') {
            const infraTab = $('#tab-settings-docker');
            if (infraTab) {
                $$('.tab-content').forEach(content => content.classList.remove('active'));
                infraTab.classList.add('active');
            }
        }
        
        // Handle Admin tab
        if (tabId === 'admin') {
            const adminTab = $('#tab-settings-general');
            if (adminTab) {
                $$('.tab-content').forEach(content => content.classList.remove('active'));
                adminTab.classList.add('active');
            }
        }
    }

    /**
     * Initialize RAG navigation
     */
    /**
     * ---agentspec
     * what: |
     *   Initializes RAG navigation listener. Subscribes to 'nav:tab-change' events and routes tab switches to handleTabChange(tabId).
     *
     * why: |
     *   Decouples navigation logic from UI; event-driven pattern allows async tab handling.
     *
     * guardrails:
     *   - DO NOT assume events object exists; guard with null check
     *   - NOTE: handleTabChange() must be defined before init() call
     * ---/agentspec
     */
    function init() {
        console.log('[RAG] Initializing RAG navigation');
        
        // Listen for navigation changes
        if (events) {
            events.on('nav:tab-change', (data) => {
                handleTabChange(data.tabId);
            });
        }
        
        // Bind RAG subtab clicks
        $$('#rag-subtabs button').forEach(btn => {
            btn.addEventListener('click', () => {
                const subtab = btn.getAttribute('data-subtab');
                if (subtab) {
                    switchRagSubtab(subtab);
                }
            });
        });
        
        // Override tab bar clicks to use Navigation system
        $$('.tab-bar button[data-tab]').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.preventDefault();
                e.stopPropagation();
                
                const tabId = btn.getAttribute('data-tab');
                if (tabId && window.Navigation) {
                    window.Navigation.navigateTo(tabId);
                }
            });
        });
        
        console.log('[RAG] RAG navigation initialized');
    }

    // Public API
    window.RAGNavigation = {
        showRagSubtabs,
        hideRagSubtabs,
        switchRagSubtab,
        getCurrentSubtab: () => currentSubtab,
        init
    };

    // Initialize on DOM ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

    console.log('[RAG] RAG Navigation module loaded');
})();




