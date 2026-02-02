/**
 * TriBridRAG Live Terminal Component
 * Provides real-time streaming output for long-running operations
 *
 * Features:
 * - Smooth slide-down animation
 * - Auto-scroll to bottom
 * - ANSI color support (basic)
 * - Collapsible/expandable
 * - Progress bar integration
 * - Dark terminal aesthetic
 */

(function() {
    'use strict';

    class LiveTerminal {
        constructor(containerId) {
            this.containerId = containerId;
            this.terminal = null;
            this.outputElement = null;
            this.progressBar = null;
            this.isVisible = false;
            this.autoScroll = true;
            this.lastLineCount = 0;

            this.createTerminal();
        }

        createTerminal() {
            const container = document.getElementById(this.containerId);
            if (!container) {
                console.error(`[LiveTerminal] Container #${this.containerId} not found`);
                return;
            }

            // Create terminal HTML
            const terminalHTML = `
                <div class="live-terminal" style="
                    max-height: 0;
                    overflow: hidden;
                    transition: max-height 0.4s cubic-bezier(0.4, 0, 0.2, 1);
                    margin-top: 16px;
                    border-radius: 8px;
                    background: #1a1a1a;
                    border: 1px solid var(--line);
                    box-shadow: 0 4px 6px rgba(0, 0, 0, 0.3);
                ">
                    <div class="terminal-header" style="
                        display: flex;
                        justify-content: space-between;
                        align-items: center;
                        padding: 10px 16px;
                        background: #252525;
                        border-bottom: 1px solid var(--line);
                        border-radius: 8px 8px 0 0;
                    ">
                        <div style="display: flex; align-items: center; gap: 8px;">
                            <div style="display: flex; gap: 6px;">
                                <div style="width: 12px; height: 12px; border-radius: 50%; background: #ff5f57;"></div>
                                <div style="width: 12px; height: 12px; border-radius: 50%; background: #ffbd2e;"></div>
                                <div style="width: 12px; height: 12px; border-radius: 50%; background: #28c840;"></div>
                            </div>
                            <span class="terminal-title" style="
                                font-family: 'SF Mono', 'Monaco', monospace;
                                font-size: 13px;
                                color: #e0e0e0;
                                font-weight: 500;
                            ">Live Output</span>
                        </div>
                        <div style="display: flex; gap: 8px; align-items: center;">
                            <button class="terminal-scroll-toggle" style="
                                background: transparent;
                                border: 1px solid var(--line);
                                color: var(--fg-muted);
                                padding: 4px 10px;
                                border-radius: 4px;
                                cursor: pointer;
                                font-size: 11px;
                                font-family: 'SF Mono', monospace;
                            " title="Toggle auto-scroll">
                                📜 Auto
                            </button>
                            <button class="terminal-clear" style="
                                background: transparent;
                                border: 1px solid var(--line);
                                color: var(--fg-muted);
                                padding: 4px 10px;
                                border-radius: 4px;
                                cursor: pointer;
                                font-size: 11px;
                                font-family: 'SF Mono', monospace;
                            " title="Clear output">
                                🗑️ Clear
                            </button>
                            <button class="terminal-collapse" style="
                                background: transparent;
                                border: none;
                                color: var(--fg-muted);
                                cursor: pointer;
                                font-size: 16px;
                                padding: 0 4px;
                            " title="Collapse terminal">
                                ▼
                            </button>
                        </div>
                    </div>

                    <div class="terminal-progress" style="display: none; padding: 8px 16px; background: #1f1f1f; border-bottom: 1px solid var(--line);">
                        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px;">
                            <span class="progress-label" style="font-family: 'SF Mono', monospace; font-size: 11px; color: var(--accent);"></span>
                            <span class="progress-percent" style="font-family: 'SF Mono', monospace; font-size: 11px; color: var(--fg-muted);"></span>
                        </div>
                        <div style="width: 100%; height: 6px; background: #0a0a0a; border-radius: 3px; overflow: hidden;">
                            <div class="progress-fill" style="
                                width: 0%;
                                height: 100%;
                                background: linear-gradient(90deg, var(--accent) 0%, var(--link) 100%);
                                transition: width 0.3s ease-out;
                                border-radius: 3px;
                            "></div>
                        </div>
                    </div>

                    <div class="terminal-body" style="
                        height: 350px;
                        overflow-y: auto;
                        padding: 12px 16px;
                        font-family: 'SF Mono', 'Monaco', 'Consolas', monospace;
                        font-size: 12px;
                        line-height: 1.6;
                        color: #e0e0e0;
                        background: #1a1a1a;
                        border-radius: 0 0 8px 8px;
                    ">
                        <pre class="terminal-output" style="
                            margin: 0;
                            white-space: pre-wrap;
                            word-wrap: break-word;
                            color: #e0e0e0;
                        "><span style="color: #888;">Waiting for output...</span></pre>
                    </div>
                </div>
            `;

            container.insertAdjacentHTML('beforeend', terminalHTML);

            this.terminal = container.querySelector('.live-terminal');
            this.outputElement = this.terminal.querySelector('.terminal-output');
            this.progressBar = {
                container: this.terminal.querySelector('.terminal-progress'),
                fill: this.terminal.querySelector('.progress-fill'),
                label: this.terminal.querySelector('.progress-label'),
                percent: this.terminal.querySelector('.progress-percent')
            };

            this.attachEventListeners();
        }

        attachEventListeners() {
            // Collapse button
            const collapseBtn = this.terminal.querySelector('.terminal-collapse');
            if (collapseBtn) {
                collapseBtn.addEventListener('click', () => {
                    if (this.isVisible) {
                        this.hide();
                    }
                });
            }

            // Auto-scroll toggle
            const scrollToggle = this.terminal.querySelector('.terminal-scroll-toggle');
            if (scrollToggle) {
                scrollToggle.addEventListener('click', () => {
                    this.autoScroll = !this.autoScroll;
                    scrollToggle.textContent = this.autoScroll ? '📜 Auto' : '📜 Manual';
                    scrollToggle.style.color = this.autoScroll ? 'var(--accent)' : 'var(--fg-muted)';
                    if (this.autoScroll) {
                        this.scrollToBottom();
                    }
                });
            }

            // Clear button
            const clearBtn = this.terminal.querySelector('.terminal-clear');
            if (clearBtn) {
                clearBtn.addEventListener('click', () => {
                    this.clear();
                });
            }

            // Detect manual scroll (disable auto-scroll if user scrolls up)
            const terminalBody = this.terminal.querySelector('.terminal-body');
            if (terminalBody) {
                terminalBody.addEventListener('scroll', () => {
                    const atBottom = terminalBody.scrollHeight - terminalBody.scrollTop <= terminalBody.clientHeight + 50;
                    if (!atBottom && this.autoScroll) {
                        this.autoScroll = false;
                        const scrollToggle = this.terminal.querySelector('.terminal-scroll-toggle');
                        if (scrollToggle) {
                            scrollToggle.textContent = '📜 Manual';
                            scrollToggle.style.color = 'var(--fg-muted)';
                        }
                    }
                });
            }
        }

        show() {
            if (!this.isVisible) {
                this.isVisible = true;
                this.terminal.style.maxHeight = '500px';

                // Smooth slide-down animation
                requestAnimationFrame(() => {
                    this.terminal.style.opacity = '1';
                });
            }
        }

        hide() {
            if (this.isVisible) {
                this.isVisible = false;
                this.terminal.style.maxHeight = '0';
                this.terminal.style.opacity = '0';
            }
        }

        clear() {
            this.outputElement.innerHTML = '<span style="color: #888;">Waiting for output...</span>';
            this.lastLineCount = 0;
        }

        appendLine(line) {
            // Remove "waiting" message on first line
            if (this.lastLineCount === 0) {
                this.outputElement.innerHTML = '';
            }

            // Basic ANSI color support
            line = this.parseANSI(line);

            // Append line
            const lineElement = document.createElement('div');
            lineElement.innerHTML = line;
            this.outputElement.appendChild(lineElement);

            this.lastLineCount++;

            // Auto-scroll if enabled
            if (this.autoScroll) {
                this.scrollToBottom();
            }
        }

        appendLines(lines) {
            lines.forEach(line => this.appendLine(line));
        }

        setContent(lines) {
            this.clear();
            this.appendLines(lines);
        }

        parseANSI(text) {
            // Basic ANSI color code support
            const colorMap = {
                '30': '#000', '31': '#ff5f57', '32': '#28c840', '33': '#ffbd2e',
                '34': '#5c9fd8', '35': '#c678dd', '36': '#56b6c2', '37': '#e0e0e0',
                '90': '#666', '91': '#ff6b6b', '92': '#5af78e', '93': '#f9f871',
                '94': '#6baeff', '95': '#e599f7', '96': '#76e1ff', '97': '#fff'
            };

            // Replace ANSI codes with HTML
            text = text.replace(/\x1b\[([0-9;]+)m/g, (match, code) => {
                if (code === '0') return '</span>';
                const color = colorMap[code];
                return color ? `<span style="color: ${color};">` : '';
            });

            // Escape HTML
            text = text.replace(/</g, '&lt;').replace(/>/g, '&gt;');

            return text;
        }

        scrollToBottom() {
            const terminalBody = this.terminal.querySelector('.terminal-body');
            if (terminalBody) {
                terminalBody.scrollTop = terminalBody.scrollHeight;
            }
        }

        updateProgress(percent, message = '') {
            if (this.progressBar) {
                this.progressBar.container.style.display = 'block';
                this.progressBar.fill.style.width = percent + '%';
                this.progressBar.percent.textContent = Math.round(percent) + '%';
                if (message) {
                    this.progressBar.label.textContent = message;
                }
            }
        }

        hideProgress() {
            if (this.progressBar) {
                this.progressBar.container.style.display = 'none';
            }
        }

        setTitle(title) {
            const titleElement = this.terminal.querySelector('.terminal-title');
            if (titleElement) {
                titleElement.textContent = title;
            }
        }
    }

    // Export to window
    window.LiveTerminal = LiveTerminal;

    console.log('[LiveTerminal] Module loaded');
})();
