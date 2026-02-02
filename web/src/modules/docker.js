// TriBridRAG GUI - Docker Management Module
// Handles Docker status, containers, and infrastructure services

(function () {
    'use strict';

    const { api, $, state } = window.CoreUtils || {};

    if (!api || !$ || !state) {
        console.error('[docker.js] CoreUtils not loaded!');
        return;
    }

    /**
     * Check Docker status
     */
    async function checkDockerStatus() {
        const display = $('#docker-status-display');
        if (!display) return;

        try {
            const response = await fetch(api('/api/docker/status'));
            const data = await response.json();

            let html = `
                <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 12px;">
                    <div style="background: var(--card-bg); border: 1px solid ${data.running ? 'var(--ok)' : 'var(--err)'}; border-radius: 6px; padding: 16px;">
                        <div style="color: var(--fg-muted); font-size: 11px; text-transform: uppercase; margin-bottom: 8px;">Docker Status</div>
                        <div style="color: ${data.running ? 'var(--ok)' : 'var(--err)'}; font-size: 20px; font-weight: 700;">
                            ${data.running ? '✓ Running' : '✗ Not Running'}
                        </div>
                    </div>
                    <div style="background: var(--card-bg); border: 1px solid var(--line); border-radius: 6px; padding: 16px;">
                        <div style="color: var(--fg-muted); font-size: 11px; text-transform: uppercase; margin-bottom: 8px;">Runtime</div>
                        <div style="color: var(--link); font-size: 16px; font-weight: 600;">
                            ${data.runtime || 'Unknown'}
                        </div>
                    </div>
                    <div style="background: var(--card-bg); border: 1px solid var(--line); border-radius: 6px; padding: 16px;">
                        <div style="color: var(--fg-muted); font-size: 11px; text-transform: uppercase; margin-bottom: 8px;">Containers</div>
                        <div style="color: var(--warn); font-size: 20px; font-weight: 700;">
                            ${data.containers_count || 0}
                        </div>
                    </div>
                </div>
            `;

            display.innerHTML = html;
        } catch (e) {
            const errorHtml = window.ErrorHelpers ? window.ErrorHelpers.createHelpfulError({
                title: 'Failed to check Docker status',
                message: e.message,
                causes: [
                    'Backend server is not running',
                    'Docker daemon is not installed or not running',
                    'Backend lacks permissions to access Docker socket',
                    'Docker API endpoint misconfigured'
                ],
                fixes: [
                    'Start the backend server (check Infrastructure > Services)',
                    'Verify Docker is installed: run "docker --version" in terminal',
                    'Ensure Docker daemon is running: "docker ps" should work',
                    'Check backend logs for Docker connection errors'
                ],
                links: [
                    ['Install Docker', 'https://docs.docker.com/get-docker/'],
                    ['Docker Daemon Setup', 'https://docs.docker.com/config/daemon/'],
                    ['Backend Health', '/api/health']
                ]
            }) : '<div style="color: var(--err); padding: 16px;">Failed to check Docker status: ' + e.message + '</div>';
            display.innerHTML = errorHtml;
            console.error('[docker] Status check failed:', e);
        }
    }

    /**
     * List Docker containers
     */
    async function listContainers() {
        const grid = $('#docker-containers-grid');
        if (!grid) return;

        try {
            const response = await fetch(api('/api/docker/containers/all'));
            const data = await response.json();

            if (!data.containers || data.containers.length === 0) {
                grid.innerHTML = '<div style="color: var(--fg-muted); padding: 16px;">No containers found</div>';
                return;
            }

            let html = '';
            data.containers.forEach(container => {
                const isRunning = container.state === 'running';
                const isPaused = container.state === 'paused';
                const isExited = container.state === 'exited';
                
                let statusColor = 'var(--fg-muted)';
                let statusIcon = '○';
                if (isRunning) { statusColor = 'var(--ok)'; statusIcon = '●'; }
                else if (isPaused) { statusColor = 'var(--warn)'; statusIcon = '⏸'; }
                else if (isExited) { statusColor = 'var(--err)'; statusIcon = '■'; }

                html += `
                    <div style="background: var(--card-bg); border: 1px solid var(--line); border-radius: 6px; padding: 16px;">
                        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                            <div style="font-weight: 600; color: var(--fg);">${container.name}</div>
                            <div style="font-size: 10px; color: ${statusColor};">${statusIcon} ${container.state.toUpperCase()}</div>
                        </div>
                        <div style="font-size: 11px; color: var(--fg-muted); font-family: 'SF Mono', monospace; margin-bottom: 8px;">
                            ${container.image}
                        </div>
                        ${container.ports ? `<div style="font-size: 10px; color: var(--link); margin-bottom: 8px;">${container.ports}</div>` : ''}
                        
                        <div style="display: flex; gap: 4px; margin-top: 12px;">
                            ${isRunning ? `
                                <button class="small-button" onclick="window.Docker.pauseContainer('${container.id}')" 
                                    style="flex: 1; background: var(--bg-elev1); color: var(--warn); border: 1px solid var(--warn); padding: 6px; font-size: 10px;">
                                    ⏸ Pause
                                </button>
                                <button class="small-button" onclick="window.Docker.stopContainer('${container.id}')" 
                                    style="flex: 1; background: var(--bg-elev1); color: var(--err); border: 1px solid var(--err); padding: 6px; font-size: 10px;">
                                    ■ Stop
                                </button>
                            ` : ''}
                            ${isPaused ? `
                                <button class="small-button" onclick="window.Docker.unpauseContainer('${container.id}')" 
                                    style="flex: 1; background: var(--bg-elev1); color: var(--ok); border: 1px solid var(--ok); padding: 6px; font-size: 10px;">
                                    ▶ Unpause
                                </button>
                                <button class="small-button" onclick="window.Docker.stopContainer('${container.id}')" 
                                    style="flex: 1; background: var(--bg-elev1); color: var(--err); border: 1px solid var(--err); padding: 6px; font-size: 10px;">
                                    ■ Stop
                                </button>
                            ` : ''}
                            ${isExited ? `
                                <button class="small-button" onclick="window.Docker.startContainer('${container.id}')" 
                                    style="flex: 1; background: var(--bg-elev1); color: var(--ok); border: 1px solid var(--ok); padding: 6px; font-size: 10px;">
                                    ▶ Start
                                </button>
                                <button class="small-button" onclick="window.Docker.removeContainer('${container.id}')" 
                                    style="flex: 1; background: var(--bg-elev1); color: var(--err); border: 1px solid var(--err); padding: 6px; font-size: 10px;">
                                    🗑 Remove
                                </button>
                            ` : ''}
                            <button class="small-button" onclick="window.Docker.toggleLogs('${container.id}', '${container.name}')" 
                                id="btn-logs-${container.id}"
                                style="flex: 1; background: var(--bg-elev1); color: var(--link); border: 1px solid var(--link, var(--link)); padding: 6px; font-size: 10px;">
                                📄 Logs ▼
                            </button>
                        </div>

                        <!-- Collapsible Logs Section -->
                        <div id="logs-${container.id}" style="display: none; margin-top: 12px; border-top: 1px solid var(--line); padding-top: 12px;">
                            <div style="background: var(--code-bg); border: 1px solid var(--line); border-radius: 4px; padding: 12px; max-height: 400px; overflow-y: auto; font-family: 'SF Mono', Consolas, monospace; font-size: 11px; line-height: 1.4;">
                                <div id="logs-content-${container.id}" style="color: var(--code-fg);">
                                    Loading logs...
                                </div>
                            </div>
                            <div style="display: flex; gap: 8px; margin-top: 8px;">
                                <button class="small-button" onclick="window.Docker.refreshLogs('${container.id}')" 
                                    style="flex: 1; background: var(--bg-elev1); color: var(--link); border: 1px solid var(--link, var(--link)); padding: 6px; font-size: 10px;">
                                    ↻ Refresh Logs
                                </button>
                                <button class="small-button" onclick="window.Docker.downloadLogs('${container.id}', '${container.name}')" 
                                    style="flex: 1; background: var(--bg-elev1); color: var(--ok); border: 1px solid var(--ok); padding: 6px; font-size: 10px;">
                                    ⬇ Download Full Logs
                                </button>
                            </div>
                        </div>
                    </div>
                `;
            });

            grid.innerHTML = html;
        } catch (e) {
            const errorHtml = window.ErrorHelpers ? window.ErrorHelpers.createHelpfulError({
                title: 'Failed to list Docker containers',
                message: e.message,
                causes: [
                    'Backend server is not responding',
                    'Docker daemon connection lost',
                    'Invalid Docker API response format',
                    'Insufficient permissions to list containers'
                ],
                fixes: [
                    'Check backend server status: Infrastructure > Services',
                    'Verify Docker is running: "docker ps" in terminal',
                    'Refresh this page to retry',
                    'Check user permissions: may need sudo or docker group'
                ],
                links: [
                    ['Docker Container Commands', 'https://docs.docker.com/engine/reference/commandline/ps/'],
                    ['Docker Permissions', 'https://docs.docker.com/engine/install/linux-postinstall/#manage-docker-as-a-non-root-user'],
                    ['Backend Logs', '/docs/DEBUGGING.md#backend-logs']
                ]
            }) : '<div style="color: var(--err); padding: 16px;">Failed to list containers: ' + e.message + '</div>';
            grid.innerHTML = errorHtml;
            console.error('[docker] Container list failed:', e);
        }
    }

    /**
     * Container control functions
     */
    async function pauseContainer(containerId) {
        try {
            const r = await fetch(api(`/api/docker/container/${containerId}/pause`), { method: 'POST' });
            const d = await r.json();
            if (d.success) {
                if (window.showStatus) window.showStatus('✓ Container paused', 'success');
                await listContainers();
            } else throw new Error(d.error);
        } catch (e) {
            const msg = window.ErrorHelpers ? window.ErrorHelpers.createAlertError('Failed to pause container', {
                message: e.message,
                causes: [
                    'Backend server not responding to pause request',
                    'Container does not support pause operation',
                    'Docker daemon connection lost',
                    'Container already paused'
                ],
                fixes: [
                    'Verify server is running (check Infrastructure > Services)',
                    'Confirm container is in running state before pausing',
                    'Try pausing again after waiting a moment',
                    'Check Docker logs for permission issues'
                ],
                links: [
                    ['Docker Pause Command', 'https://docs.docker.com/engine/reference/commandline/pause/'],
                    ['Container States', 'https://docs.docker.com/engine/reference/api/docker_remote_api_v1.24/#pause-a-container'],
                    ['Server Health', '/api/health']
                ]
            }) : `Failed to pause container: ${e.message}`;
            if (window.showStatus) window.showStatus(msg, 'error');
            else alert(msg);
        }
    }

    async function unpauseContainer(containerId) {
        try {
            const r = await fetch(api(`/api/docker/container/${containerId}/unpause`), { method: 'POST' });
            const d = await r.json();
            if (d.success) {
                if (window.showStatus) window.showStatus('✓ Container resumed', 'success');
                await listContainers();
            } else throw new Error(d.error);
        } catch (e) {
            const msg = window.ErrorHelpers ? window.ErrorHelpers.createAlertError('Failed to resume container', {
                message: e.message,
                causes: [
                    'Backend server not responding to unpause request',
                    'Container is not in paused state',
                    'Docker daemon connection lost',
                    'Container was removed while paused'
                ],
                fixes: [
                    'Verify server is running (check Infrastructure > Services)',
                    'Confirm container is in paused state before resuming',
                    'Refresh container list to see current state',
                    'Try again after checking Docker daemon status'
                ],
                links: [
                    ['Docker Unpause Command', 'https://docs.docker.com/engine/reference/commandline/unpause/'],
                    ['Container Lifecycle', 'https://docs.docker.com/engine/reference/api/docker_remote_api_v1.24/#unpause-a-container'],
                    ['Troubleshooting', '/docs/INFRASTRUCTURE.md#container-management']
                ]
            }) : `Failed to resume container: ${e.message}`;
            if (window.showStatus) window.showStatus(msg, 'error');
            else alert(msg);
        }
    }

    async function stopContainer(containerId) {
        try {
            const r = await fetch(api(`/api/docker/container/${containerId}/stop`), { method: 'POST' });
            const d = await r.json();
            if (d.success) {
                if (window.showStatus) window.showStatus('✓ Container stopped', 'success');
                await listContainers();
            } else throw new Error(d.error);
        } catch (e) {
            const msg = window.ErrorHelpers ? window.ErrorHelpers.createAlertError('Failed to stop container', {
                message: e.message,
                causes: [
                    'Backend API endpoint not accessible',
                    'Container is already stopped',
                    'Docker daemon is not responding',
                    'Insufficient permissions to stop container'
                ],
                fixes: [
                    'Check that backend server is running (Infrastructure > Services)',
                    'Verify the container is currently running',
                    'Wait 10 seconds and retry (Docker needs time)',
                    'Check Docker permission settings'
                ],
                links: [
                    ['Docker Stop Reference', 'https://docs.docker.com/engine/reference/commandline/stop/'],
                    ['Container Management', 'https://docs.docker.com/engine/containers/'],
                    ['API Documentation', '/docs/API.md#docker-endpoints']
                ]
            }) : `Failed to stop container: ${e.message}`;
            if (window.showStatus) window.showStatus(msg, 'error');
            else alert(msg);
        }
    }

    async function startContainer(containerId) {
        try {
            const r = await fetch(api(`/api/docker/container/${containerId}/start`), { method: 'POST' });
            const d = await r.json();
            if (d.success) {
                if (window.showStatus) window.showStatus('✓ Container started', 'success');
                await listContainers();
            } else throw new Error(d.error);
        } catch (e) {
            const msg = window.ErrorHelpers ? window.ErrorHelpers.createAlertError('Failed to start container', {
                message: e.message,
                causes: [
                    'Backend server is not running or not accessible',
                    'Container is already running',
                    'Required Docker image is missing or corrupted',
                    'Port binding conflict (another service using the port)'
                ],
                fixes: [
                    'Check server status: Infrastructure > Services tab',
                    'Verify container is not already running',
                    'Check available disk space for container startup',
                    'Check for port conflicts with other services (e.g., Qdrant, Redis)'
                ],
                links: [
                    ['Docker Start Reference', 'https://docs.docker.com/engine/reference/commandline/start/'],
                    ['Port Binding Issues', 'https://docs.docker.com/config/containers/container-networking/'],
                    ['Troubleshooting Guide', '/docs/INFRASTRUCTURE.md#service-startup']
                ]
            }) : `Failed to start container: ${e.message}`;
            if (window.showStatus) window.showStatus(msg, 'error');
            else alert(msg);
        }
    }

    async function removeContainer(containerId) {
        if (!confirm('WARNING: This will permanently delete the container. Are you sure?')) return;
        try {
            const r = await fetch(api(`/api/docker/container/${containerId}/remove`), { method: 'POST' });
            const d = await r.json();
            if (d.success) {
                if (window.showStatus) window.showStatus('✓ Container removed', 'success');
                await listContainers();
            } else throw new Error(d.error);
        } catch (e) {
            const msg = window.ErrorHelpers ? window.ErrorHelpers.createAlertError('Failed to remove container', {
                message: e.message,
                causes: [
                    'Container is still running (must stop before removing)',
                    'Backend API not accessible',
                    'Insufficient permissions to remove container',
                    'Container has mounted volumes that need cleanup'
                ],
                fixes: [
                    'Stop the container first, then try removing again',
                    'Verify backend server is running (Infrastructure > Services)',
                    'Check Docker permissions for your user',
                    'Remove mounted volumes separately if needed'
                ],
                links: [
                    ['Docker Remove Reference', 'https://docs.docker.com/engine/reference/commandline/rm/'],
                    ['Container Volumes', 'https://docs.docker.com/storage/volumes/'],
                    ['Cleanup Guide', '/docs/MAINTENANCE.md#container-cleanup']
                ]
            }) : `Failed to remove container: ${e.message}`;
            if (window.showStatus) window.showStatus(msg, 'error');
            else alert(msg);
        }
    }

    /**
     * Format and colorize log lines
     */
    /**
     * ---agentspec
     * what: |
     *   Formats raw log strings into HTML. Splits by newline, filters empty lines, builds formatted output string.
     *
     * why: |
     *   Centralizes log display logic for consistent UI rendering across components.
     *
     * guardrails:
     *   - DO NOT parse log content; only format structure
     *   - NOTE: Returns muted placeholder if rawLogs is falsy
     * ---/agentspec
     */
    function formatLogs(rawLogs) {
        if (!rawLogs) return '<span style="color: var(--fg-muted);">No logs available</span>';
        
        const lines = rawLogs.split('\n');
        let formatted = '';
        
        lines.forEach(line => {
            if (!line.trim()) return;
            
            // Try to extract timestamp (common formats: ISO8601, unix timestamp, etc)
            let timestamp = '';
            let logContent = line;
            
            // ISO timestamp pattern (2024-01-15T10:30:45.123Z or similar)
            const isoMatch = line.match(/^(\d{4}-\d{2}-\d{2}[T\s]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?)/);
            if (isoMatch) {
                const date = new Date(isoMatch[1]);
                timestamp = date.toLocaleString('en-US', { 
                    hour12: false,
                    year: 'numeric',
                    month: '2-digit', 
                    day: '2-digit',
                    hour: '2-digit',
                    minute: '2-digit',
                    second: '2-digit'
                });
                logContent = line.substring(isoMatch[0].length).trim();
            }
            // Docker timestamp pattern ([timestamp])
            else if (line.match(/^\[?\d{4}-\d{2}-\d{2}/)) {
                const parts = line.split(/\s+/, 2);
                timestamp = parts[0].replace(/[\[\]]/g, '');
                logContent = line.substring(parts[0].length).trim();
            }
            
            // Determine color based on log level
            let color = 'var(--accent)'; // default green
            const upperLine = line.toUpperCase();
            
            if (upperLine.includes('ERROR') || upperLine.includes('FATAL') || upperLine.includes('CRITICAL')) {
                color = 'var(--err)'; // red for errors
            } else if (upperLine.includes('WARN') || upperLine.includes('WARNING')) {
                color = 'var(--warn)'; // orange for warnings
            } else if (upperLine.includes('INFO')) {
                color = 'var(--link)'; // blue for info
            } else if (upperLine.includes('DEBUG') || upperLine.includes('TRACE')) {
                color = 'var(--fg-muted)'; // gray for debug
            }
            
            // Build formatted line
            if (timestamp) {
                formatted += `<div style="color: ${color}; margin-bottom: 2px;">`;
                formatted += `<span style="color: var(--fg-muted);">[${timestamp}]</span> `;
                formatted += `${escapeHtml(logContent)}`;
                formatted += `</div>`;
            } else {
                formatted += `<div style="color: ${color}; margin-bottom: 2px;">${escapeHtml(line)}</div>`;
            }
        });
        
        return formatted || '<span style="color: var(--fg-muted);">No logs available</span>';
    }

    /**
     * Escape HTML to prevent injection
     */
    /**
     * ---agentspec
     * what: |
     *   Escapes HTML special characters by setting textContent on a DOM element, then reading innerHTML. Converts raw text → safe HTML string.
     *
     * why: |
     *   Leverages browser's native HTML encoding; simpler than manual char-by-char replacement.
     *
     * guardrails:
     *   - DO NOT use on already-HTML content; only raw text
     *   - NOTE: Creates temporary DOM node; avoid in tight loops
     * ---/agentspec
     */
    function escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    /**
     * Toggle logs visibility
     */
    async function toggleLogs(containerId, containerName) {
        const logsDiv = $(`#logs-${containerId}`);
        const btn = $(`#btn-logs-${containerId}`);
        
        if (!logsDiv) return;
        
        if (logsDiv.style.display === 'none') {
            // Show logs
            logsDiv.style.display = 'block';
            if (btn) btn.innerHTML = '📄 Logs ▲';
            // Load logs
            await refreshLogs(containerId);
        } else {
            // Hide logs
            logsDiv.style.display = 'none';
            if (btn) btn.innerHTML = '📄 Logs ▼';
        }
    }

    /**
     * Refresh logs for a container
     */
    async function refreshLogs(containerId) {
        const contentDiv = $(`#logs-content-${containerId}`);
        if (!contentDiv) return;
        
        contentDiv.innerHTML = '<span style="color: var(--warn);">Loading logs...</span>';
        
        try {
            const r = await fetch(api(`/api/docker/container/${containerId}/logs`));
            const d = await r.json();
            
            if (d.success) {
                contentDiv.innerHTML = formatLogs(d.logs);
                // Auto-scroll to bottom
                contentDiv.parentElement.scrollTop = contentDiv.parentElement.scrollHeight;
            } else {
                throw new Error(d.error);
            }
        } catch (e) {
            const errorMsg = window.ErrorHelpers ? window.ErrorHelpers.createHelpfulError({
                title: 'Failed to load container logs',
                message: e.message,
                causes: [
                    'Backend logs endpoint is not accessible',
                    'Container has no log output yet',
                    'Docker daemon connection lost while fetching logs',
                    'Log file is corrupted or inaccessible'
                ],
                fixes: [
                    'Verify backend server is running (Infrastructure > Services)',
                    'Wait a moment for the container to produce output',
                    'Refresh the page and try again',
                    'Check Docker permissions for log access'
                ],
                links: [
                    ['Docker Logs Reference', 'https://docs.docker.com/engine/reference/commandline/logs/'],
                    ['Container Logging', 'https://docs.docker.com/config/containers/logging/'],
                    ['API Health', '/api/health']
                ]
            }) : `<span style="color: var(--err);">Failed to load logs: ${escapeHtml(e.message)}</span>`;
            contentDiv.innerHTML = errorMsg;
        }
    }

    /**
     * Download full logs
     */
    async function downloadLogs(containerId, containerName) {
        try {
            const r = await fetch(api(`/api/docker/container/${containerId}/logs?tail=1000`));
            const d = await r.json();
            
            if (d.success) {
                // Create blob and download
                const blob = new Blob([d.logs], { type: 'text/plain' });
                const url = window.URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = `${containerName}-${new Date().toISOString().slice(0,19).replace(/:/g,'-')}.log`;
                document.body.appendChild(a);
                a.click();
                document.body.removeChild(a);
                window.URL.revokeObjectURL(url);
                
                if (window.showStatus) window.showStatus('Logs downloaded', 'success');
            } else {
                throw new Error(d.error);
            }
        } catch (e) {
            const msg = window.ErrorHelpers ? window.ErrorHelpers.createAlertError('Failed to download container logs', {
                message: e.message,
                causes: [
                    'Backend logs endpoint returned an error',
                    'Browser blocked the file download',
                    'Container has no recent logs to download',
                    'Network connection interrupted during download'
                ],
                fixes: [
                    'Check server status: Infrastructure > Services',
                    'Allow downloads in browser settings',
                    'Refresh this page and try again',
                    'Check that container has been running and has log output'
                ],
                links: [
                    ['Docker Logs API', 'https://docs.docker.com/engine/api/v1.24/#get-container-logs'],
                    ['Browser Download Help', 'https://support.google.com/chrome/answer/95759'],
                    ['Docker Log Drivers', 'https://docs.docker.com/config/containers/logging/']
                ]
            }) : `Failed to download logs: ${e.message}`;
            if (window.showStatus) window.showStatus(msg, 'error');
            else alert(msg);
        }
    }

    /**
     * Check infrastructure service status
     */
    async function checkInfraStatus() {
        // Check Qdrant
        try {
            const qdrantStatus = $('#qdrant-status');
            const r = await fetch('http://127.0.0.1:6333/collections', { mode: 'no-cors' });
            if (qdrantStatus) qdrantStatus.innerHTML = '<span style="color: var(--accent);">✓ Running</span>';
        } catch {
            const qdrantStatus = $('#qdrant-status');
            if (qdrantStatus) qdrantStatus.innerHTML = '<span style="color: var(--err);">✗ Not Running</span>';
        }

        // Check Redis
        try {
            const response = await fetch(api('/api/docker/redis/ping'));
            const data = await response.json();
            const redisStatus = $('#redis-status');
            if (redisStatus) {
                redisStatus.innerHTML = data.success ? 
                    '<span style="color: var(--accent);">✓ Running</span>' : 
                    '<span style="color: var(--err);">✗ Not Running</span>';
            }
        } catch {
            const redisStatus = $('#redis-status');
            if (redisStatus) redisStatus.innerHTML = '<span style="color: var(--err);">✗ Not Running</span>';
        }

        // Check Prometheus
        try {
            await fetch('http://127.0.0.1:9090/-/ready', { mode: 'no-cors' });
            const prometheusStatus = $('#prometheus-status');
            if (prometheusStatus) prometheusStatus.innerHTML = '<span style="color: var(--accent);">✓ Running</span>';
        } catch {
            const prometheusStatus = $('#prometheus-status');
            if (prometheusStatus) prometheusStatus.innerHTML = '<span style="color: var(--err);">✗ Not Running</span>';
        }

        // Check Grafana
        try {
            await fetch('http://127.0.0.1:3000/api/health', { mode: 'no-cors' });
            const grafanaStatus = $('#grafana-status');
            if (grafanaStatus) grafanaStatus.innerHTML = '<span style="color: var(--accent);">✓ Running</span>';
        } catch {
            const grafanaStatus = $('#grafana-status');
            if (grafanaStatus) grafanaStatus.innerHTML = '<span style="color: var(--err);">✗ Not Running</span>';
        }
    }

    /**
     * Start all infrastructure
     */
    async function startInfra() {
        const btn = $('#btn-infra-up');
        if (btn) btn.disabled = true;

        try {
            const response = await fetch(api('/api/docker/infra/up'), { method: 'POST' });
            const data = await response.json();

            if (data.success) {
                if (window.showStatus) {
                    window.showStatus('Infrastructure started successfully', 'success');
                } else {
                    alert('Infrastructure started!');
                }
                await checkInfraStatus();
                await checkDockerStatus();
                await listContainers();
            } else {
                throw new Error(data.error || 'Failed to start infrastructure');
            }
        } catch (e) {
            const msg = window.ErrorHelpers ? window.ErrorHelpers.createAlertError('Failed to start infrastructure', {
                message: e.message,
                causes: [
                    'Docker daemon not running',
                    'Insufficient system resources (memory, disk space)',
                    'Port conflicts with existing services',
                    'Network configuration issues'
                ],
                fixes: [
                    'Verify Docker is running: `docker ps`',
                    'Check system resources: `df -h` for disk, `free -h` for memory',
                    'Check for port conflicts: `lsof -i :6333` (Qdrant), `lsof -i :6379` (Redis)',
                    'Review Docker compose logs: `docker compose logs -f`'
                ],
                links: [
                    ['Docker Getting Started', 'https://docs.docker.com/get-started/'],
                    ['Docker Compose Documentation', 'https://docs.docker.com/compose/']
                ]
            }) : `Failed to start infrastructure: ${e.message}`;
            if (window.showStatus) {
                window.showStatus(msg, 'error');
            } else {
                alert(msg);
            }
        } finally {
            if (btn) btn.disabled = false;
        }
    }

    /**
     * Stop all infrastructure
     */
    async function stopInfra() {
        const btn = $('#btn-infra-down');
        if (btn) btn.disabled = true;

        try {
            const response = await fetch(api('/api/docker/infra/down'), { method: 'POST' });
            const data = await response.json();

            if (data.success) {
                if (window.showStatus) {
                    window.showStatus('Infrastructure stopped', 'success');
                } else {
                    alert('Infrastructure stopped!');
                }
                await checkInfraStatus();
                await checkDockerStatus();
                await listContainers();
            } else {
                throw new Error(data.error || 'Failed to stop infrastructure');
            }
        } catch (e) {
            const msg = window.ErrorHelpers ? window.ErrorHelpers.createAlertError('Failed to stop infrastructure', {
                message: e.message,
                causes: [
                    'Docker daemon not running',
                    'Container stuck in stopping state',
                    'Network connectivity issues',
                    'Insufficient permissions'
                ],
                fixes: [
                    'Verify Docker is running: `docker ps`',
                    'Force stop stuck containers: `docker compose kill`',
                    'Check network connectivity to Docker daemon',
                    'Ensure you have Docker permissions: `docker info`'
                ],
                links: [
                    ['Docker Compose Stop Command', 'https://docs.docker.com/engine/reference/commandline/compose_stop/'],
                    ['Redis Documentation', 'https://redis.io/docs/']
                ]
            }) : `Failed to stop infrastructure: ${e.message}`;
            if (window.showStatus) {
                window.showStatus(msg, 'error');
            } else {
                alert(msg);
            }
        } finally {
            if (btn) btn.disabled = false;
        }
    }

    /**
     * Initialize Docker UI
     */
    /**
     * ---agentspec
     * what: |
     *   Initializes Docker UI controls. Binds click handlers to refresh, up, down buttons. Triggers checkDockerStatus() on refresh.
     *
     * why: |
     *   Centralizes event listener setup for Docker management interface.
     *
     * guardrails:
     *   - DO NOT assume jQuery elements exist; check before binding
     *   - NOTE: checkDockerStatus() must be defined before this runs
     * ---/agentspec
     */
    function initDocker() {
        // Bind buttons
        const btnDockerRefresh = $('#btn-docker-refresh');
        const btnContainersRefresh = $('#btn-docker-refresh-containers');
        const btnInfraUp = $('#btn-infra-up');
        const btnInfraDown = $('#btn-infra-down');

        if (btnDockerRefresh) btnDockerRefresh.addEventListener('click', () => {
            checkDockerStatus();
            listContainers();
            checkInfraStatus();
        });
        
        if (btnContainersRefresh) btnContainersRefresh.addEventListener('click', listContainers);
        if (btnInfraUp) btnInfraUp.addEventListener('click', startInfra);
        if (btnInfraDown) btnInfraDown.addEventListener('click', stopInfra);

        // Service UI open buttons
        const btnQdrantOpen = $('#btn-qdrant-open');
        const btnPrometheusOpen = $('#btn-prometheus-open');
        const btnGrafanaOpen = $('#btn-grafana-open');

        if (btnQdrantOpen) btnQdrantOpen.addEventListener('click', () => window.open('http://127.0.0.1:6333/dashboard', '_blank'));
        if (btnPrometheusOpen) btnPrometheusOpen.addEventListener('click', () => window.open('http://127.0.0.1:9090', '_blank'));
        if (btnGrafanaOpen) btnGrafanaOpen.addEventListener('click', () => window.open('http://127.0.0.1:3000', '_blank'));

        // Redis ping
        const btnRedisPing = $('#btn-redis-ping');
        if (btnRedisPing) {
            btnRedisPing.addEventListener('click', async () => {
                try {
                    const r = await fetch(api('/api/docker/redis/ping'));
                    const d = await r.json();
                    alert(d.success ? '✓ Redis PONG!' : '✗ Redis not responding');
                } catch (e) {
                    alert('✗ Failed to ping Redis');
                }
            });
        }

        // Save docker settings
        const btnSaveSettings = $('#btn-save-docker-settings');
        if (btnSaveSettings && window.Config) {
            btnSaveSettings.addEventListener('click', async () => {
                if (window.Config.saveConfig) {
                    await window.Config.saveConfig();
                }
            });
        }

        // Initial load
        checkDockerStatus();
        listContainers();
        checkInfraStatus();

        console.log('[docker] Initialized');
    }

    // Export to window
    window.Docker = {
        initDocker,
        checkDockerStatus,
        listContainers,
        checkInfraStatus,
        startInfra,
        stopInfra,
        pauseContainer,
        unpauseContainer,
        stopContainer,
        startContainer,
        removeContainer,
        toggleLogs,
        refreshLogs,
        downloadLogs
    };

    // Initialization function called by mcp_server.js when infrastructure view mounts
    // Does NOT register view - mcp_server.js handles that
    window.initDocker = function() {
        console.log('[docker.js] Initializing docker for infrastructure view');
        initDocker();
    };

    // Legacy mode: auto-init
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initDocker);
    } else {
        initDocker();
    }

    console.log('[docker.js] Module loaded (coordination with mcp_server.js for infrastructure view)');
})();

