// TriBridRAG GUI - MCP Server Management Module
// Handles MCP HTTP server management and stdio testing

(function () {
    'use strict';

    // Import utilities
    const { api, $, state } = window.CoreUtils || {};

    if (!api || !$ || !state) {
        console.error('[mcp_server.js] CoreUtils not loaded!');
        return;
    }

    /**
     * Update HTTP MCP server status
     */
    async function updateHTTPStatus() {
        const statusEl = $('#mcp-http-status');
        if (!statusEl) return;

        try {
            const response = await fetch(api('/api/mcp/http/status'));
            const data = await response.json();

            if (data.running) {
                statusEl.innerHTML = `
                    <span style="color: var(--accent);">✓ Running</span>
                    <div style="font-size: 10px; color: var(--fg-muted); margin-top: 4px;">
                        Port: ${data.port} | Mode: ${data.mode} | URL: ${data.url || 'N/A'}
                    </div>
                `;
                statusEl.style.borderColor = 'var(--accent)';
            } else {
                statusEl.innerHTML = `<span style="color: var(--err);">✗ Not Running</span>`;
                statusEl.style.borderColor = 'var(--err)';
            }
        } catch (e) {
            statusEl.innerHTML = `<span style="color: var(--warn);">⚠ Cannot check status</span>`;
            statusEl.style.borderColor = 'var(--warn)';
            console.error('Failed to check HTTP MCP status:', e);
        }
    }

    /**
     * Start HTTP MCP server
     */
    async function startHTTPServer() {
        const btn = $('#btn-mcp-http-start');
        if (btn) btn.disabled = true;

        try {
            const response = await fetch(api('/api/mcp/http/start'), { method: 'POST' });
            const data = await response.json();

            if (data.success) {
                if (window.showStatus) {
                    window.showStatus(`HTTP MCP started on port ${data.port}`, 'success');
                } else {
                    alert(`HTTP MCP started on port ${data.port}!`);
                }
                await updateHTTPStatus();
            } else {
                throw new Error(data.error || 'Failed to start HTTP MCP server');
            }
        } catch (e) {
            if (window.showStatus) {
                window.showStatus(`Failed to start HTTP MCP: ${e.message}`, 'error');
            } else {
                alert(`Error: ${e.message}`);
            }
        } finally {
            if (btn) btn.disabled = false;
        }
    }

    /**
     * Stop HTTP MCP server
     */
    async function stopHTTPServer() {
        const btn = $('#btn-mcp-http-stop');
        if (btn) btn.disabled = true;

        try {
            const response = await fetch(api('/api/mcp/http/stop'), { method: 'POST' });
            const data = await response.json();

            if (data.success) {
                if (window.showStatus) {
                    window.showStatus('HTTP MCP stopped', 'success');
                } else {
                    alert('HTTP MCP stopped!');
                }
                await updateHTTPStatus();
            } else {
                throw new Error(data.error || 'Failed to stop HTTP MCP server');
            }
        } catch (e) {
            if (window.showStatus) {
                window.showStatus(`Failed to stop HTTP MCP: ${e.message}`, 'error');
            } else {
                alert(`Error: ${e.message}`);
            }
        } finally {
            if (btn) btn.disabled = false;
        }
    }

    /**
     * Restart HTTP MCP server
     */
    async function restartHTTPServer() {
        const btn = $('#btn-mcp-http-restart');
        if (btn) btn.disabled = true;

        try {
            const response = await fetch(api('/api/mcp/http/restart'), { method: 'POST' });
            const data = await response.json();

            if (data.success) {
                if (window.showStatus) {
                    window.showStatus('HTTP MCP restarted successfully', 'success');
                } else {
                    alert('HTTP MCP restarted!');
                }
                await updateHTTPStatus();
            } else {
                throw new Error(data.error || 'Failed to restart HTTP MCP server');
            }
        } catch (e) {
            if (window.showStatus) {
                window.showStatus(`Failed to restart HTTP MCP: ${e.message}`, 'error');
            } else {
                alert(`Error: ${e.message}`);
            }
        } finally {
            if (btn) btn.disabled = false;
        }
    }

    /**
     * Test stdio MCP server
     */
    async function testStdioServer() {
        const btn = $('#btn-mcp-test');
        const outputEl = $('#mcp-test-output');
        
        if (btn) btn.disabled = true;
        if (outputEl) {
            outputEl.style.display = 'block';
            outputEl.textContent = 'Testing stdio MCP server...';
        }

        try {
            const response = await fetch(api('/api/mcp/test'));
            const data = await response.json();

            if (data.success) {
                const toolsList = data.tools ? data.tools.join(', ') : 'None';
                const output = `✓ stdio MCP Test Passed!\n\nTools (${data.tools_count || 0}): ${toolsList}\n\n${data.output || ''}`;
                
                if (outputEl) outputEl.textContent = output;
                
                if (window.showStatus) {
                    window.showStatus(`stdio MCP test passed! ${data.tools_count || 0} tools available`, 'success');
                }
            } else {
                const output = `✗ stdio MCP Test Failed\n\nError: ${data.error || 'Unknown error'}\n\n${data.output || ''}`;
                if (outputEl) outputEl.textContent = output;
                
                if (window.showStatus) {
                    window.showStatus(`stdio MCP test failed: ${data.error}`, 'error');
                }
            }
        } catch (e) {
            if (outputEl) outputEl.textContent = `✗ Error: ${e.message}`;
            
            if (window.showStatus) {
                window.showStatus(`stdio MCP test failed: ${e.message}`, 'error');
            }
        } finally {
            if (btn) btn.disabled = false;
        }
    }

    /**
     * Initialize MCP server management UI
     */
    /**
     * ---agentspec
     * what: |
     *   Binds click handlers to MCP HTTP server UI buttons (start, stop, restart, check). Attaches event listeners to DOM elements via jQuery selectors.
     *
     * why: |
     *   Centralizes UI initialization; decouples button binding from handler definitions.
     *
     * guardrails:
     *   - DO NOT assume buttons exist; check truthiness before addEventListener
     *   - NOTE: Missing restart and check button bindings; incomplete implementation
     *   - ASK USER: Should restart/check handlers be added?
     * ---/agentspec
     */
    function initMCPServerUI() {
        // Bind HTTP server buttons
        const btnHTTPStart = $('#btn-mcp-http-start');
        const btnHTTPStop = $('#btn-mcp-http-stop');
        const btnHTTPRestart = $('#btn-mcp-http-restart');
        const btnHTTPCheck = $('#btn-mcp-http-check');

        if (btnHTTPStart) btnHTTPStart.addEventListener('click', startHTTPServer);
        if (btnHTTPStop) btnHTTPStop.addEventListener('click', stopHTTPServer);
        if (btnHTTPRestart) btnHTTPRestart.addEventListener('click', restartHTTPServer);
        if (btnHTTPCheck) btnHTTPCheck.addEventListener('click', updateHTTPStatus);

        // Bind stdio test button
        const btnTest = $('#btn-mcp-test');
        if (btnTest) btnTest.addEventListener('click', testStdioServer);

        // Initial status check
        updateHTTPStatus();

        // Auto-refresh status every 30 seconds if on infrastructure tab
        setInterval(() => {
            const infraTab = $('#tab-infrastructure');
            if (infraTab && infraTab.classList.contains('active')) {
                updateHTTPStatus();
            }
        }, 30000);
    }

    // Export to window
    window.MCPServer = {
        updateHTTPStatus,
        startHTTPServer,
        stopHTTPServer,
        restartHTTPServer,
        testStdioServer,
        initMCPServerUI
    };

    // Initialization function for infrastructure view
    window.initMCPServer = function() {
        console.log('[mcp_server.js] Initializing MCP server for infrastructure view');
        initMCPServerUI();
    };

    // Register view (PRIMARY module for infrastructure)
    if (window.Navigation && typeof window.Navigation.registerView === 'function') {
        window.Navigation.registerView({
            id: 'infrastructure',
            title: 'Infrastructure',
            mount: () => {
                console.log('[mcp_server.js] Mounted infrastructure view');
                // Initialize MCP server (primary)
                if (typeof window.initMCPServer === 'function') window.initMCPServer();
                // Initialize docker
                if (typeof window.initDocker === 'function') window.initDocker();
            },
            unmount: () => {
                console.log('[mcp_server.js] Unmounted from infrastructure');
            }
        });
    } else {
        console.warn('[mcp_server.js] Navigation API not available, falling back to legacy mode');
        // Legacy mode: auto-init
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', initMCPServerUI);
        } else {
            initMCPServerUI();
        }
    }

    console.log('[mcp_server.js] Module loaded (PRIMARY for infrastructure, coordinates docker.js)');
})();
