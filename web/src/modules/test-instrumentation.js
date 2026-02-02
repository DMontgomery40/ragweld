// TriBridRAG GUI - Test Instrumentation
// Adds data-testid attributes and test helpers for Playwright
// Author: Agent 4 - Testing & Validation

(function() {
    'use strict';

    // Wait for DOM to be ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

    /**
     * ---agentspec
     * what: |
     *   Initializes test infrastructure by adding data-testid attributes to DOM elements and exposing test helper functions globally.
     *
     * why: |
     *   Centralizes test setup to enable reliable element selection and helper access across test suites.
     *
     * guardrails:
     *   - DO NOT add testids to elements that may be removed/refactored; coordinate with component owners
     *   - NOTE: exposeTestHelpers() must complete before tests run; verify execution order
     *   - ASK USER: Should testids be scoped to avoid collisions in nested components?
     * ---/agentspec
     */
    function init() {
        addTestIds();
        exposeTestHelpers();
    }

    /**
     * Add data-testid attributes to critical elements
     */
    /**
     * ---agentspec
     * what: |
     *   Adds data-testid attributes to tab buttons. Iterates .tab-bar buttons, extracts data-tab value, sets data-testid to `tab-btn-{tabName}`. Supports new tab bar + backward compat.
     *
     * why: |
     *   Enables reliable E2E test selectors without brittle CSS/class dependencies.
     *
     * guardrails:
     *   - DO NOT assume all buttons have data-tab; add null checks
     *   - NOTE: Backward compat branch incomplete; clarify old tab selector strategy
     *   - ASK USER: Should old tabs also get testid prefix, or different naming?
     * ---/agentspec
     */
    function addTestIds() {
        // Tab buttons in new tab bar
        const tabButtons = document.querySelectorAll('.tab-bar button[data-tab]');
        tabButtons.forEach(btn => {
            const tabName = btn.getAttribute('data-tab');
            btn.setAttribute('data-testid', `tab-btn-${tabName}`);
        });

        // Old tab buttons (for backward compat)
        const oldTabButtons = document.querySelectorAll('nav.tabs button[data-tab]');
        oldTabButtons.forEach(btn => {
            const tabName = btn.getAttribute('data-tab');
            btn.setAttribute('data-testid', `old-tab-btn-${tabName}`);
        });

        // RAG subtab buttons
        const ragSubtabs = document.querySelectorAll('#rag-subtabs button[data-subtab]');
        ragSubtabs.forEach(btn => {
            const subtabName = btn.getAttribute('data-subtab');
            btn.setAttribute('data-testid', `rag-subtab-${subtabName}`);
        });

        // Tab content divs
        const tabContents = document.querySelectorAll('[id^="tab-"]');
        tabContents.forEach(div => {
            const id = div.getAttribute('id');
            div.setAttribute('data-testid', `content-${id}`);
        });

        // Health status
        const healthStatus = document.getElementById('health-status');
        if (healthStatus) {
            healthStatus.setAttribute('data-testid', 'health-status');
        }

        // Dashboard health
        const dashHealth = document.getElementById('dash-health');
        if (dashHealth) {
            dashHealth.setAttribute('data-testid', 'dash-health');
        }

        // Index button
        const indexBtn = document.getElementById('index-btn');
        if (indexBtn) {
            indexBtn.setAttribute('data-testid', 'index-btn');
        }

        // Send chat button
        const sendChatBtn = document.getElementById('send-chat');
        if (sendChatBtn) {
            sendChatBtn.setAttribute('data-testid', 'send-chat');
        }

        // Chat input
        const chatInput = document.getElementById('chat-input');
        if (chatInput) {
            chatInput.setAttribute('data-testid', 'chat-input');
        }

        // Global search
        const globalSearch = document.getElementById('global-search');
        if (globalSearch) {
            globalSearch.setAttribute('data-testid', 'global-search');
        }

        // Theme toggle
        const themeToggle = document.getElementById('theme-toggle');
        if (themeToggle) {
            themeToggle.setAttribute('data-testid', 'theme-toggle');
        }
    }

    /**
     * Expose test helpers on window
     */
    /**
     * ---agentspec
     * what: |
     *   Exposes window.TestHelpers object with getAllTestIds() method. Returns array of all data-testid attribute values from DOM.
     *
     * why: |
     *   Centralizes test utilities for consistent test harness access across specs.
     *
     * guardrails:
     *   - DO NOT call before DOM ready; elements may not exist yet
     *   - NOTE: Returns empty array if no [data-testid] elements present
     * ---/agentspec
     */
    function exposeTestHelpers() {
        window.TestHelpers = {
            /**
             * Get all data-testid values
             */
            getAllTestIds() {
                const elements = document.querySelectorAll('[data-testid]');
                return Array.from(elements).map(el => el.getAttribute('data-testid'));
            },

            /**
             * Get module loading status
             */
            getModuleStatus() {
                const modules = [
                    'CoreUtils',
                    'Navigation',
                    'Theme',
                    'Chat',
                    'Config',
                    'Indexing',
                    'Cards',
                    'Keywords',
                    'Reranker',
                    'Grafana',
                    'Cost',
                    'MCP',
                    'Docker',
                    'Health'
                ];

                return modules.map(name => ({
                    name,
                    loaded: typeof window[name] !== 'undefined',
                    hasInit: typeof window[name]?.init === 'function'
                }));
            },

            /**
             * Validate critical elements exist
             */
            validateCriticalElements() {
                const criticalIds = [
                    'tab-btn-dashboard',
                    'tab-btn-chat',
                    'tab-btn-grafana',
                    'tab-btn-rag',
                    'health-status'
                ];

                const missing = criticalIds.filter(id => {
                    return !document.querySelector(`[data-testid="${id}"]`);
                });

                return {
                    valid: missing.length === 0,
                    missing,
                    found: criticalIds.filter(id => {
                        return document.querySelector(`[data-testid="${id}"]`) !== null;
                    })
                };
            },

            /**
             * Get current navigation state
             */
            getNavigationState() {
                if (!window.Navigation) {
                    return { error: 'Navigation API not available' };
                }

                return {
                    currentTab: window.Navigation.getCurrentTab(),
                    compatMode: window.Navigation.isCompatibilityMode(),
                    panels: {
                        grafana: window.Navigation.isPanelVisible('grafana')
                    }
                };
            },

            /**
             * Simulate tab click
             */
            clickTab(tabId) {
                const btn = document.querySelector(`[data-testid="tab-btn-${tabId}"]`);
                if (btn) {
                    btn.click();
                    return true;
                }
                return false;
            },

            /**
             * Simulate RAG subtab click
             */
            clickRAGSubtab(subtabId) {
                const btn = document.querySelector(`[data-testid="rag-subtab-${subtabId}"]`);
                if (btn) {
                    btn.click();
                    return true;
                }
                return false;
            },

            /**
             * Get visible tab content
             */
            getVisibleTab() {
                const activeTab = document.querySelector('.tab-content.active');
                return activeTab ? activeTab.getAttribute('id') : null;
            },

            /**
             * Check if element is visible
             */
            isVisible(selector) {
                const el = document.querySelector(selector);
                if (!el) return false;

                const style = window.getComputedStyle(el);
                return style.display !== 'none' &&
                       style.visibility !== 'hidden' &&
                       style.opacity !== '0';
            },

            /**
             * Wait for element to appear
             */
            async waitForElement(selector, timeout = 5000) {
                const start = Date.now();

                while (Date.now() - start < timeout) {
                    const el = document.querySelector(selector);
                    if (el && this.isVisible(selector)) {
                        return el;
                    }
                    await new Promise(resolve => setTimeout(resolve, 100));
                }

                throw new Error(`Element ${selector} not found within ${timeout}ms`);
            },

            /**
             * Get console errors (if captured)
             */
            getConsoleErrors() {
                return window._testConsoleErrors || [];
            }
        };

        // Capture console errors for testing
        if (typeof window._testConsoleErrors === 'undefined') {
            window._testConsoleErrors = [];
            const originalError = console.error;
            console.error = function(...args) {
                window._testConsoleErrors.push({
                    timestamp: Date.now(),
                    message: args.map(a => String(a)).join(' ')
                });
                originalError.apply(console, args);
            };
        }

        console.log('[TestHelpers] Initialized - data-testid attributes added');
    }
})();
