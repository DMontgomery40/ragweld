// AGRO GUI - VS Code Integration Module (Compatibility Layer)
// Provides backward-compatible API wrapping the unified Editor module
// This module is now primarily a shim for the newer editor.js implementation
;(function() {
    'use strict';

    /**
     * Show the VS Code editor - delegates to Editor module
     */
    /**
     * ---agentspec
     * what: |
     *   Displays editor UI by unhiding container and triggering Editor module health check. No inputs; side effects only.
     *
     * why: |
     *   Delegates editor initialization to Editor module to maintain separation of concerns.
     *
     * guardrails:
     *   - DO NOT assume Editor module is loaded; check window.Editor exists before calling
     *   - NOTE: Fails silently if container or Editor module missing; add error logging
     * ---/agentspec
     */
    function showEditor() {
        console.log('[VSCode] Delegating showEditor to Editor module');
        const container = document.getElementById('editor-iframe-container');
        if (container) {
            container.style.display = 'block';
        }
        if (window.Editor && typeof window.Editor.initEditorHealthCheck === 'function') {
            window.Editor.initEditorHealthCheck();
        }
    }

    /**
     * Hide the VS Code editor
     */
    /**
     * ---agentspec
     * what: |
     *   Hides editor iframe container and stops health check. Sets display:none on #editor-iframe-container, calls window.Editor.stopEditorHealthCheck() if available.
     *
     * why: |
     *   Centralizes editor lifecycle cleanup in one function to prevent orphaned health checks.
     *
     * guardrails:
     *   - DO NOT assume window.Editor exists; guard with typeof check
     *   - NOTE: Health check must stop before hiding to avoid dangling timers
     * ---/agentspec
     */
    function hideEditor() {
        console.log('[VSCode] Delegating hideEditor to Editor module');
        const container = document.getElementById('editor-iframe-container');
        if (container) {
            container.style.display = 'none';
        }
        if (window.Editor && typeof window.Editor.stopEditorHealthCheck === 'function') {
            window.Editor.stopEditorHealthCheck();
        }
    }

    /**
     * Open editor in new window - delegates to Editor module
     */
    /**
     * ---agentspec
     * what: |
     *   Delegates window-open request to Editor module via window.Editor.openEditorWindow(). Logs delegation; no-op if Editor unavailable.
     *
     * why: |
     *   Decouples UI trigger from Editor implementation; allows Editor module to control window behavior.
     *
     * guardrails:
     *   - DO NOT assume window.Editor exists; check typeof before call
     *   - NOTE: Silent failure if Editor module not loaded; add error callback for UX feedback
     * ---/agentspec
     */
    function openInNewWindow() {
        console.log('[VSCode] Delegating openInNewWindow to Editor module');
        if (window.Editor && typeof window.Editor.openEditorWindow === 'function') {
            window.Editor.openEditorWindow();
        }
    }

    /**
     * Copy editor URL to clipboard
     */
    /**
     * ---agentspec
     * what: |
     *   Delegates URL copy to Editor module via window.Editor.copyEditorUrl(). Logs delegation; no-op if Editor unavailable.
     *
     * why: |
     *   Decouples UI trigger from Editor implementation; allows async module loading.
     *
     * guardrails:
     *   - DO NOT assume window.Editor exists; check before call
     *   - NOTE: Silent failure if Editor module not loaded; add error callback
     * ---/agentspec
     */
    function copyUrl() {
        console.log('[VSCode] Delegating copyUrl to Editor module');
        if (window.Editor && typeof window.Editor.copyEditorUrl === 'function') {
            window.Editor.copyEditorUrl();
        }
    }

    /**
     * Restart VS Code server
     */
    /**
     * ---agentspec
     * what: |
     *   Restarts editor by delegating to window.Editor.restartEditor(). Logs delegation; no-op if Editor module unavailable.
     *
     * why: |
     *   Decouples restart logic from this module; Editor owns restart implementation.
     *
     * guardrails:
     *   - DO NOT restart directly; always delegate to window.Editor
     *   - NOTE: Silent fail if Editor module missing or restartEditor undefined
     * ---/agentspec
     */
    function restart() {
        console.log('[VSCode] Delegating restart to Editor module');
        if (window.Editor && typeof window.Editor.restartEditor === 'function') {
            window.Editor.restartEditor();
        }
    }

    /**
     * Initialize the module - mostly delegated to other modules
     */
    /**
     * ---agentspec
     * what: |
     *   Initializes VS Code compatibility layer. Logs init message; delegates all work to editor.js and editor-settings.js. Exposes showEditor/hideEditor API.
     *
     * why: |
     *   Backward-compatible wrapper decouples VSCode interface from implementation modules.
     *
     * guardrails:
     *   - DO NOT add logic here; keep as thin facade only
     *   - NOTE: Real work must stay in editor.js and editor-settings.js
     *   - ASK USER: Confirm showEditor/hideEditor signatures match callers
     * ---/agentspec
     */
    function init() {
        console.log('[VSCode] Initializing VS Code compatibility layer');
        // All real work is done by editor.js and editor-settings.js
    }

    // Public API - backward compatible interface
    window.VSCode = {
        showEditor,
        hideEditor,
        openInNewWindow,
        copyUrl,
        restart,
        init
    };

    // Initialize on DOM ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

    console.log('[VSCode] Compatibility layer loaded');
})();





