// Chat interface for RAG system
// Handles sending questions to /answer endpoint and displaying responses

// Default chat settings
const DEFAULT_CHAT_SETTINGS = {
    model: '',  // Empty = use GEN_MODEL
    temperature: 0.0,
    maxTokens: 1000,
    multiQuery: 3,
    finalK: 20,
    confidence: 0.55,
    showCitations: true,
    showConfidence: false,
    autoScroll: true,
    syntaxHighlight: false,
    systemPrompt: '',
    // History settings
    historyEnabled: true,
    historyLimit: 100,  // Maximum number of messages to store
    showHistoryOnLoad: true  // Auto-load history when page loads
};

let chatMessages = [];
let chatSettings = loadChatSettings();

// Load settings from localStorage
/**
 * ---agentspec
 * what: |
 *   Loads chat settings from localStorage. Merges saved JSON with DEFAULT_CHAT_SETTINGS; returns merged object or defaults on parse failure.
 *
 * why: |
 *   Graceful fallback ensures app never crashes on corrupted localStorage data.
 *
 * guardrails:
 *   - DO NOT assume localStorage is always available; wrap in try-catch
 *   - NOTE: Silent console.warn on parse error; consider user-facing alert if settings are critical
 *   - DO NOT mutate DEFAULT_CHAT_SETTINGS; spread operator creates new object
 * ---/agentspec
 */
function loadChatSettings() {
    try {
        const saved = localStorage.getItem('tribrid_chat_settings');
        if (saved) {
            return { ...DEFAULT_CHAT_SETTINGS, ...JSON.parse(saved) };
        }
    } catch (e) {
        console.warn('Failed to load chat settings:', e);
    }
    return { ...DEFAULT_CHAT_SETTINGS };
}

// Save settings to localStorage
/**
 * ---agentspec
 * what: |
 *   Reads chat UI form fields (model, temperature, maxTokens, multiQuery, finalK, confidence). Parses & saves settings object.
 *
 * why: |
 *   Centralizes settings persistence from DOM to prevent scattered state mutations.
 *
 * guardrails:
 *   - DO NOT validate ranges here; add client-side constraints on inputs
 *   - NOTE: Throws if DOM IDs missing; add existence checks before parse
 *   - ASK USER: Where does this save? (localStorage, API, state?)
 * ---/agentspec
 */
function saveChatSettings() {
    try {
        const settings = {
            model: document.getElementById('chat-model').value,
            temperature: parseFloat(document.getElementById('chat-temperature').value),
            maxTokens: parseInt(document.getElementById('chat-max-tokens').value),
            multiQuery: parseInt(document.getElementById('chat-multi-query').value),
            finalK: parseInt(document.getElementById('chat-final-k').value),
            confidence: parseFloat(document.getElementById('chat-confidence').value),
            showCitations: document.getElementById('chat-show-citations').value === '1',
            showConfidence: document.getElementById('chat-show-confidence').value === '1',
            autoScroll: document.getElementById('chat-auto-scroll').value === '1',
            syntaxHighlight: document.getElementById('chat-syntax-highlight').value === '1',
            systemPrompt: document.getElementById('chat-system-prompt').value,
            // History settings
            historyEnabled: document.getElementById('chat-history-enabled').value === '1',
            historyLimit: Math.min(1000, Math.max(1, parseInt(document.getElementById('chat-history-limit').value) || 100)),
            showHistoryOnLoad: document.getElementById('chat-show-history-on-load').value === '1'
        };

        localStorage.setItem('tribrid_chat_settings', JSON.stringify(settings));
        chatSettings = settings;

        // Persist to backend as the source of truth (non-blocking)
        try {
            const apiBase = (window.CoreUtils && typeof window.CoreUtils.api === 'function')
                ? window.CoreUtils.api('/chat/config')
                : '/api/chat/config';
            fetch(apiBase, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(settings)
            }).catch(() => { /* ignore network errors in UI toast */ });
        } catch {}

        updateStorageDisplay();
        showToast('Chat settings saved', 'success');
    } catch (e) {
        console.error('Failed to save chat settings:', e);
        const msg = window.ErrorHelpers ? window.ErrorHelpers.createAlertError('Failed to save chat settings', {
            message: e.message,
            causes: [
                'Browser localStorage is disabled or unavailable',
                'Storage quota exceeded (too many chat settings)',
                'Invalid data type in form input',
                'DOM element reference changed or missing'
            ],
            fixes: [
                'Enable localStorage in browser settings (Privacy & Security)',
                'Clear old chat data or reset settings to defaults',
                'Check form inputs are filled with valid values',
                'Refresh the page and try saving again'
            ],
            links: [
                ['Web Storage API', 'https://developer.mozilla.org/en-US/docs/Web/API/Web_Storage_API']
            ]
        }) : 'Failed to save settings: ' + e.message;
        showToast(msg, 'error');
    }
}

// Reset settings to defaults
/**
 * ---agentspec
 * what: |
 *   Resets chat settings to defaults after user confirmation. Clears localStorage, reapplies defaults, shows success toast.
 *
 * why: |
 *   Confirmation prevents accidental loss; localStorage removal ensures clean state on reload.
 *
 * guardrails:
 *   - DO NOT reset without confirm() dialog; user must opt-in
 *   - NOTE: applyChatSettings() must exist and handle empty/default state
 * ---/agentspec
 */
function resetChatSettings() {
    if (!confirm('Reset all chat settings to defaults?')) return;

    chatSettings = { ...DEFAULT_CHAT_SETTINGS };
    localStorage.removeItem('tribrid_chat_settings');
    applyChatSettings();
    showToast('Chat settings reset to defaults', 'success');
}

// Apply settings to UI inputs
/**
 * ---agentspec
 * what: |
 *   Applies chat configuration settings (model, temperature, max_tokens, multi_query, finalK, confidence) to DOM elements by ID. Maps chatSettings object keys to element values.
 *
 * why: |
 *   Centralizes UI state sync; single source of truth for chat config.
 *
 * guardrails:
 *   - DO NOT assume elements exist; add null checks before assignment
 *   - NOTE: Silent failure if element IDs missing; add error logging
 *   - ASK USER: Should invalid settings reject or warn?
 * ---/agentspec
 */
function applyChatSettings() {
    try {
        const elements = {
            'chat-model': chatSettings.model,
            'chat-temperature': chatSettings.temperature,
            'chat-max-tokens': chatSettings.maxTokens,
            'chat-multi-query': chatSettings.multiQuery,
            'chat-final-k': chatSettings.finalK,
            'chat-confidence': chatSettings.confidence,
            'chat-show-citations': chatSettings.showCitations ? '1' : '0',
            'chat-show-confidence': chatSettings.showConfidence ? '1' : '0',
            'chat-auto-scroll': chatSettings.autoScroll ? '1' : '0',
            'chat-syntax-highlight': chatSettings.syntaxHighlight ? '1' : '0',
            'chat-system-prompt': chatSettings.systemPrompt,
            // History settings
            'chat-history-enabled': chatSettings.historyEnabled ? '1' : '0',
            'chat-history-limit': chatSettings.historyLimit,
            'chat-show-history-on-load': chatSettings.showHistoryOnLoad ? '1' : '0'
        };

        for (const [id, value] of Object.entries(elements)) {
            const el = document.getElementById(id);
            if (el) {
                el.value = value;
            }
        }

        // Update storage display
        updateStorageDisplay();
    } catch (e) {
        console.warn('Failed to apply chat settings:', e);
    }
}

// Send a question to the RAG
async function sendMessage() {
    const input = document.getElementById('chat-input');
    const sendBtn = document.getElementById('chat-send');
    const repoSelect = document.getElementById('chat-repo-select');

    const question = input.value.trim();
    if (!question) return;

    const repo = repoSelect.value || null;

    // Add user message to chat
    addMessage('user', question);
    input.value = '';
    input.style.height = 'auto';

    // Disable input while loading
    input.disabled = true;
    sendBtn.disabled = true;
    sendBtn.textContent = 'Thinking...';

    // Add loading message with animated MODEL indicator
    const loadingId = addMessage('assistant', 'MODEL ', true);

    // Animate the loading dots
    let dotCount = 0;
    const loadingInterval = setInterval(() => {
        const msgEl = document.getElementById(loadingId);
        if (!msgEl) {
            clearInterval(loadingInterval);
            return;
        }
        dotCount = (dotCount + 1) % 4;
        const dots = '.'.repeat(dotCount);
        const contentDiv = msgEl.querySelector('[style*="line-height"]');
        if (contentDiv) {
            contentDiv.textContent = 'MODEL ' + dots;
        }
    }, 300);

    try {
        // Use /api/chat endpoint with full settings support
        const url = new URL('/api/chat', window.location.origin);

        const urlParams = new URLSearchParams(window.location.search || '');
        const fastMode = urlParams.get('fast') === '1' || urlParams.get('smoke') === '1';
        const payload = {
            question: question,
            repo: repo || null,
            model: chatSettings.model || null,
            temperature: chatSettings.temperature,
            max_tokens: chatSettings.maxTokens,
            multi_query: chatSettings.multiQuery,
            final_k: chatSettings.finalK,
            confidence: chatSettings.confidence,
            system_prompt: chatSettings.systemPrompt || null,
            fast_mode: fastMode
        };

        const response = await fetch(url, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(payload)
        });

        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.detail || 'Failed to get answer');
        }

        // Clear loading animation and remove loading message
        clearInterval(loadingInterval);
        removeMessage(loadingId);

        // Add confidence score if enabled
        let answerText = data.answer;
        if (chatSettings.showConfidence && data.confidence) {
            answerText = `[Confidence: ${(data.confidence * 100).toFixed(1)}%]\n\n${answerText}`;
        }

        const msgId = addMessage('assistant', answerText);
        
        // Store event_id globally for click tracking
        if (data.event_id) {
            window.lastChatEventId = data.event_id;
        }
        
        // Add feedback controls; if the helper isn't loaded yet, retry briefly
        if (data.event_id) {
            const attach = () => {
                if (typeof addFeedbackButtons !== 'function') return false;
                const msgEl = document.getElementById(msgId);
                if (!msgEl) return false;
                const contentDiv = msgEl.querySelector('[style*="line-height"]');
                if (!contentDiv) return false;
                try { addFeedbackButtons(contentDiv.parentElement, data.event_id); } catch {}
                return true;
            };
            if (!attach()) {
                let attempts = 0;
                const t = setInterval(() => {
                    attempts += 1;
                    if (attach() || attempts > 600) { // up to ~60s
                        clearInterval(t);
                    }
                }, 100);
            }
        }

    } catch (error) {
        console.error('Chat error:', error);
        clearInterval(loadingInterval);
        removeMessage(loadingId);
        const errorMsg = window.ErrorHelpers ? window.ErrorHelpers.createAlertError('Failed to get AI answer', {
            message: error.message,
            causes: [
                'Backend API server is not running or unreachable',
                'Vector database (Qdrant) connection failed',
                'No relevant documents found in the knowledge base',
                'LLM model API service is unavailable',
                'Network connection interrupted'
            ],
            fixes: [
                'Check Infrastructure tab - verify backend and Qdrant are running',
                'Verify your repository has been indexed (check Data > Indexing status)',
                'Try rephrasing your question with simpler terms',
                'Check system resources (memory, CPU) on Infrastructure tab',
                'Retry the question - temporary network issues may resolve'
            ],
            links: [
                ['Qdrant Vector Database', 'https://qdrant.tech/documentation/concepts/collections/'],
                ['System Health Check', '/api/health']
            ]
        }) : `Error: ${error.message}`;
        addMessage('assistant', errorMsg, false, true);
    } finally {
        input.disabled = false;
        sendBtn.disabled = false;
        sendBtn.textContent = 'Send';
        input.focus();
    }
}

// Add a message to the chat
/**
 * ---agentspec
 * what: |
 *   Adds message DOM element to chat container. Accepts role, content, loading/error flags, history-save toggle. Removes empty-state placeholder on first message.
 *
 * why: |
 *   Centralizes message rendering logic; prevents duplicate empty states and ensures consistent DOM structure.
 *
 * guardrails:
 *   - DO NOT call without messagesContainer element present; will throw
 *   - NOTE: saveToHistory flag controls persistence; set false for transient UI-only messages
 * ---/agentspec
 */
function addMessage(role, content, isLoading = false, isError = false, saveToHistory = true) {
    const messagesContainer = document.getElementById('chat-messages');

    // Remove empty state if present
    const emptyState = messagesContainer.querySelector('[style*="text-align: center"]');
    if (emptyState) {
        emptyState.remove();
    }

    const messageId = `msg-${Date.now()}-${Math.random()}`;
    const messageDiv = document.createElement('div');
    messageDiv.id = messageId;
    messageDiv.style.cssText = 'margin-bottom: 16px; animation: fadeIn 0.2s;';

    const roleColor = role === 'user' ? 'var(--link)' : 'var(--accent)';
    const roleBg = role === 'user' ? 'color-mix(in oklch, var(--link) 12%, var(--card-bg))' : 'color-mix(in oklch, var(--accent) 12%, var(--card-bg))';
    const roleLabel = role === 'user' ? 'You' : 'Assistant';

    // Process content for file links and formatting
    let processedContent = content;
    if (role === 'assistant' && !isLoading) {
        processedContent = formatAssistantMessage(content);
    } else {
        processedContent = escapeHtml(content);
    }

    messageDiv.innerHTML = `
        <div style="display: flex; gap: 12px;">
            <div style="flex-shrink: 0; width: 32px; height: 32px; border-radius: 6px; background: ${roleBg}; border: 1px solid ${roleColor}; display: flex; align-items: center; justify-content: center; font-size: 12px; font-weight: 600; color: ${roleColor};">
                ${roleLabel[0]}
            </div>
            <div style="flex: 1;">
                <div style="font-size: 12px; color: var(--fg-muted); margin-bottom: 4px;">${roleLabel}</div>
                <div style="color: ${isError ? 'var(--err)' : 'var(--fg)'}; line-height: 1.6; white-space: pre-wrap; word-break: break-word;">
                    ${processedContent}
                </div>
            </div>
        </div>
    `;

    messagesContainer.appendChild(messageDiv);

    // Scroll to bottom if auto-scroll is enabled
    if (chatSettings.autoScroll) {
        messagesContainer.scrollTop = messagesContainer.scrollHeight;
    }

    chatMessages.push({ id: messageId, role, content, isLoading, isError });

    // Save to history if enabled and not a loading message
    if (saveToHistory && !isLoading && !isError && chatSettings.historyEnabled) {
        saveMessageToHistory(role, content, messageId);
    }

    return messageId;
}

// Remove a message by ID
/**
 * ---agentspec
 * what: |
 *   Removes message from DOM by ID and filters it from chatMessages array. Input: messageId string. Output: none (side effects only).
 *
 * why: |
 *   Dual removal (DOM + state) ensures UI and data stay synchronized.
 *
 * guardrails:
 *   - DO NOT remove without verifying messageId exists; silent failures hide bugs
 *   - NOTE: No undo; deletion is permanent
 * ---/agentspec
 */
function removeMessage(messageId) {
    const messageDiv = document.getElementById(messageId);
    if (messageDiv) {
        messageDiv.remove();
    }
    chatMessages = chatMessages.filter(m => m.id !== messageId);
}

// Format assistant message with file links and code blocks
/**
 * ---agentspec
 * what: |
 *   Formats assistant message content by escaping HTML and auto-linking file paths with optional line ranges (e.g., server/app.py:123-145). Returns formatted string with clickable file references.
 *
 * why: |
 *   Centralizes message rendering logic to prevent XSS while making code references navigable.
 *
 * guardrails:
 *   - DO NOT execute regex without escapeHtml first; XSS risk
 *   - NOTE: Requires window.lastChatEventId for click tracking; gracefully handles null
 *   - ASK USER: Confirm file path regex covers all required extensions before deploy
 * ---/agentspec
 */
function formatAssistantMessage(content) {
    let formatted = escapeHtml(content);

    // Extract and link file paths (e.g., server/app.py:123-145 or just server/app.py)
    // Store event_id if available for click tracking
    const currentEventId = window.lastChatEventId || null;
    
    formatted = formatted.replace(
        /([a-zA-Z0-9_\-\/\.]+\.(py|js|ts|tsx|jsx|rb|go|rs|java|cs|yml|yaml|json|md|txt))(?::(\d+)(?:-(\d+))?)?/g,
        (match, filePath, ext, startLine, endLine) => {
            const lineRange = startLine ? `:${startLine}${endLine ? `-${endLine}` : ''}` : '';
            const displayText = `${filePath}${lineRange}`;
            const docId = `${filePath}${lineRange}`;
            // Track clicks if event_id is available
            const clickHandler = currentEventId ? `onclick="trackFileClick('${currentEventId}', '${docId}')"` : '';
            return `<a href="vscode://file/${filePath}${startLine ? ':' + startLine : ''}" ${clickHandler} style="color: var(--link); text-decoration: none; border-bottom: 1px solid var(--link); font-family: 'SF Mono', monospace; font-size: 13px; cursor: pointer;" title="Open in editor">${displayText}</a>`;
        }
    );

    // Extract repo header (e.g., [corpus: tribrid-demo])
    formatted = formatted.replace(
        /\[repo:\s*([^\]]+)\]/g,
        '<span style="background: var(--bg-elev2); color: var(--fg-muted); padding: 2px 8px; border-radius: 3px; font-size: 11px; font-family: \'SF Mono\', monospace;">repo: $1</span>'
    );

    // Simple code block formatting (backticks)
    formatted = formatted.replace(
        /`([^`]+)`/g,
        '<code style="background: var(--bg-elev2); color: var(--accent); padding: 2px 6px; border-radius: 3px; font-family: \'SF Mono\', monospace; font-size: 13px;">$1</code>'
    );

    // Multi-line code blocks
    formatted = formatted.replace(
        /```([^\n]*)\n([\s\S]*?)```/g,
        (match, lang, code) => {
            const escapedCode = code.trim();
            return `<pre style="background: var(--card-bg); border: 1px solid var(--line); border-radius: 6px; padding: 12px; overflow-x: auto; margin: 8px 0;"><code style="color: var(--fg); font-family: 'SF Mono', monospace; font-size: 13px;">${escapedCode}</code></pre>`;
        }
    );

    return formatted;
}

// Clear all messages
/**
 * ---agentspec
 * what: |
 *   Clears chat message history after user confirmation. Resets messagesContainer to empty state with placeholder UI.
 *
 * why: |
 *   Confirmation prevents accidental data loss; placeholder provides visual feedback.
 *
 * guardrails:
 *   - DO NOT clear without confirm() dialog; user must opt-in
 *   - NOTE: Clears DOM only; backend persistence not handled here
 * ---/agentspec
 */
function clearChat() {
    if (!confirm('Clear all messages?')) return;

    const messagesContainer = document.getElementById('chat-messages');
    messagesContainer.innerHTML = `
        <div style="text-align: center; color: var(--fg-muted); padding: 40px 20px;">
            <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" style="opacity: 0.3; margin-bottom: 12px;">
                <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"></path>
            </svg>
            <div>Start a conversation with your codebase</div>
            <div style="font-size: 11px; margin-top: 8px;">Try: "Where is OAuth token validated?" or "How do we handle API errors?"</div>
        </div>
    `;
    chatMessages = [];
}

// Helper: escape HTML
/**
 * ---agentspec
 * what: |
 *   Escapes HTML special characters by setting textContent on a DOM element and reading innerHTML. Converts &, <, >, ", ' to safe entities.
 *
 * why: |
 *   DOM-based escaping is browser-native and handles all edge cases without manual regex patterns.
 *
 * guardrails:
 *   - DO NOT use on server-side; document.createElement only works in browsers
 *   - NOTE: Slower than regex for bulk operations; acceptable for per-message escaping
 * ---/agentspec
 */
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// ========== HISTORY MANAGEMENT FUNCTIONS ==========

// Save message to history
/**
 * ---agentspec
 * what: |
 *   Saves chat message to localStorage with role, content, messageId. Returns early if historyEnabled is false.
 *
 * why: |
 *   Persists conversation state client-side; early exit prevents unnecessary writes when history disabled.
 *
 * guardrails:
 *   - DO NOT assume localStorage is always available; wrap in try-catch for quota/permission errors
 *   - NOTE: messageId collision risk if not globally unique; validate upstream
 *   - DO NOT store sensitive data (PII, tokens) in localStorage
 * ---/agentspec
 */
function saveMessageToHistory(role, content, messageId) {
    if (!chatSettings.historyEnabled) return;

    try {
        let history = JSON.parse(localStorage.getItem('tribrid_chat_history') || '[]');

        // Add new message with metadata
        history.push({
            id: messageId,
            role: role,
            content: content,
            timestamp: new Date().toLocaleString(),
            repo: document.getElementById('chat-repo-select').value || 'auto'
        });

        // Enforce history limit
        if (history.length > chatSettings.historyLimit) {
            history = history.slice(-chatSettings.historyLimit);
        }

        localStorage.setItem('tribrid_chat_history', JSON.stringify(history));
        updateStorageDisplay();
    } catch (e) {
        console.warn('Failed to save message to history:', e);
    }
}

// Load chat history from localStorage and render it into the transcript
/**
 * ```
 * ---agentspec
 * what: |
 *   Loads chat history from localStorage. Parses JSON, validates {role, content} structure, returns array or empty fallback.
 *
 * why: |
 *   Graceful degradation: silent fail on parse error or missing key prevents UI crash.
 *
 * guardrails:
 *   - DO NOT assume localStorage is available; wrap in try-catch
 *   - NOTE: Empty array returned on any parse failure; no error thrown
 *   - ASK USER: Add schema validation beyond structure check (e.g., role enum: "user"|"assistant")
 * ---/agentspec
 * ```
 */
function loadChatHistory() {
    if (!chatSettings.historyEnabled || !chatSettings.showHistoryOnLoad) return;

    try {
        const raw = localStorage.getItem('tribrid_chat_history') || '[]';
        let history = [];
        try { history = JSON.parse(raw); } catch { history = []; }

        // Validate structure: ensure array of {role:string, content:string}
        history = Array.isArray(history) ? history.filter(m => m && typeof m.content === 'string' && (m.role === 'user' || m.role === 'assistant')) : [];

        const messagesContainer = document.getElementById('chat-messages');
        if (!messagesContainer) return;

        if (history.length > 0) {
            // Clear the empty state message
            messagesContainer.innerHTML = '';

            // Add separator for historical messages
            const separator = document.createElement('div');
            separator.style.cssText = 'text-align: center; color: var(--fg-muted); margin: 20px 0; font-size: 11px;';
            separator.innerHTML = `
                <div style="display: flex; align-items: center; gap: 12px;">
                    <div style="flex: 1; height: 1px; background: var(--line);"></div>
                    <span>Previous conversation (${history.length} messages)</span>
                    <div style="flex: 1; height: 1px; background: var(--line);"></div>
                </div>
            `;
            messagesContainer.appendChild(separator);

            // Load messages
            history.forEach(msg => {
                addMessage(msg.role, msg.content, false, false, false); // Don't save again
            });

            // Add separator for new session
            const newSessionSeparator = document.createElement('div');
            newSessionSeparator.style.cssText = 'text-align: center; color: var(--fg-muted); margin: 20px 0; font-size: 11px;';
            newSessionSeparator.innerHTML = `
                <div style="display: flex; align-items: center; gap: 12px;">
                    <div style="flex: 1; height: 1px; background: var(--line);"></div>
                    <span>New session started</span>
                    <div style="flex: 1; height: 1px; background: var(--line);"></div>
                </div>
            `;
            messagesContainer.appendChild(newSessionSeparator);
        }

        // Also render a compact history list inside the dropdown for discoverability
        renderHistoryDropdown(history);
    } catch (e) {
        console.warn('Failed to load chat history:', e);
    }
}

// Render compact history list inside the History dropdown (last 20)
/**
 * ---agentspec
 * what: |
 *   Renders chat history dropdown by clearing DOM and rebuilding list. Preserves export/clear buttons; rebuilds item list above them.
 *
 * why: |
 *   Separates DOM mutation (clear + rebuild) from button preservation to avoid re-binding event listeners.
 *
 * guardrails:
 *   - DO NOT rebuild buttons; only list items above them
 *   - NOTE: Assumes exportBtn and clearBtn exist; will silently fail if missing
 *   - ASK USER: Should missing buttons throw error or warn?
 * ---/agentspec
 */
function renderHistoryDropdown(history) {
    try {
        const dropdown = document.getElementById('history-dropdown');
        if (!dropdown) return;
        // Preserve the action buttons; rebuild the list above them
        const exportBtn = document.getElementById('chat-export-history');
        const clearBtn = document.getElementById('chat-clear-history');
        dropdown.innerHTML = '';

        const listWrap = document.createElement('div');
        listWrap.style.cssText = 'max-height: 240px; overflow-y: auto; padding: 6px 0;';

        const items = (history || []).slice(-20).reverse();
        if (items.length === 0) {
            const empty = document.createElement('div');
            empty.style.cssText = 'color:var(--fg-muted); font-size:12px; padding:8px 12px;';
            empty.textContent = 'No saved messages yet';
            listWrap.appendChild(empty);
        } else {
            items.forEach((m, idx) => {
                const btn = document.createElement('button');
                btn.style.cssText = 'display:block;width:100%;text-align:left;background:none;border:none;color: var(--fg);padding:6px 12px;font-size:12px;cursor:pointer;';
                const label = `${m.role === 'user' ? 'You' : 'Assistant'}: ${m.content.replace(/\s+/g,' ').slice(0, 60)}${m.content.length>60?'…':''}`;
                btn.textContent = label;
                btn.title = m.timestamp ? new Date(m.timestamp).toLocaleString() : '';
                btn.addEventListener('click', () => {
                    // Append to transcript for quick reference (do not re-save)
                    addMessage(m.role, m.content, false, false, false);
                    dropdown.style.display = 'none';
                });
                btn.addEventListener('mouseover', () => btn.style.background = 'var(--bg-elev1)');
                btn.addEventListener('mouseout', () => btn.style.background = 'transparent');
                listWrap.appendChild(btn);
            });
        }

        dropdown.appendChild(listWrap);
        // Divider
        const div = document.createElement('div'); div.style.cssText = 'height:1px;background:var(--line);'; dropdown.appendChild(div);
        // Action buttons
        const exp = document.createElement('button');
        exp.id = 'chat-export-history';
        exp.style.cssText = 'display:block;width:100%;text-align:left;background:none;border:none;color: var(--fg);padding:8px 12px;font-size:12px;cursor:pointer;';
        exp.textContent = '📥 Export History';
        exp.addEventListener('click', exportChatHistory);
        const clr = document.createElement('button');
        clr.id = 'chat-clear-history';
        clr.style.cssText = 'display:block;width:100%;text-align:left;background:none;border:none;color:var(--err);padding:8px 12px;font-size:12px;cursor:pointer;';
        clr.textContent = '🗑️ Clear History';
        clr.addEventListener('click', clearChatHistory);
        dropdown.appendChild(exp);
        dropdown.appendChild(document.createElement('div')).style.cssText = 'height:1px;background:var(--line);';
        dropdown.appendChild(clr);
    } catch (e) {
        console.warn('Failed to render history dropdown:', e);
    }
}

// Clear chat history
/**
 * ---agentspec
 * what: |
 *   Clears localStorage chat history after user confirmation. Removes 'tribrid_chat_history' key, updates UI, shows success toast.
 *
 * why: |
 *   Confirmation prevents accidental data loss; try-catch handles storage API failures gracefully.
 *
 * guardrails:
 *   - DO NOT skip confirmation; irreversible operation
 *   - NOTE: Silently fails if localStorage unavailable; consider retry logic for critical data
 * ---/agentspec
 */
function clearChatHistory() {
    if (!confirm('Clear all saved chat history? This cannot be undone.')) return;

    try {
        localStorage.removeItem('tribrid_chat_history');
        updateStorageDisplay();
        showToast('Chat history cleared', 'success');
    } catch (e) {
        console.error('Failed to clear chat history:', e);
        showToast('Failed to clear history: ' + e.message, 'error');
    }
}

// Export chat history as JSON
/**
 * ---agentspec
 * what: |
 *   Exports localStorage chat history to JSON file. Retrieves 'tribrid_chat_history', creates blob, triggers browser download with timestamped filename.
 *
 * why: |
 *   Client-side export avoids server round-trip; localStorage access + blob URL pattern is standard for browser file downloads.
 *
 * guardrails:
 *   - DO NOT assume localStorage exists; wrap in try-catch for private/incognito mode
 *   - NOTE: URL.createObjectURL must be revoked (revokeObjectURL) to prevent memory leak
 *   - DO NOT append/remove DOM elements without cleanup; remove anchor after click
 * ---/agentspec
 */
function exportChatHistory() {
    try {
        const history = localStorage.getItem('tribrid_chat_history') || '[]';
        const blob = new Blob([history], { type: 'application/json' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `chat-history-${new Date().toLocaleDateString().replace(/\//g, '-')}.json`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
        showToast('Chat history exported', 'success');
    } catch (e) {
        console.error('Failed to export chat history:', e);
        showToast('Failed to export history: ' + e.message, 'error');
    }
}

// Calculate and display storage usage
/**
 * ---agentspec
 * what: |
 *   Reads tribrid_chat_history from localStorage, calculates Blob size in KB, parses JSON, updates #chat-storage-display DOM element.
 *
 * why: |
 *   Centralizes storage monitoring for chat history quota tracking.
 *
 * guardrails:
 *   - DO NOT assume displayElement exists; check before update
 *   - NOTE: Blob size may differ from string length due to encoding
 *   - ASK USER: Should this clear history on quota exceeded?
 * ---/agentspec
 */
function updateStorageDisplay() {
    try {
        const historyStr = localStorage.getItem('tribrid_chat_history') || '[]';
        const sizeInBytes = new Blob([historyStr]).size;
        const sizeInKB = (sizeInBytes / 1024).toFixed(2);
        const history = JSON.parse(historyStr);

        const displayElement = document.getElementById('chat-storage-display');
        if (displayElement) {
            displayElement.textContent = `${history.length} messages using ${sizeInKB}KB`;
        }
    } catch (e) {
        console.warn('Failed to update storage display:', e);
    }
}

// Auto-resize textarea
/**
 * ---agentspec
 * what: |
 *   Auto-resizes textarea height based on content scroll height, capped at 120px. Resets height to 'auto' before measuring to prevent stale values.
 *
 * why: |
 *   Prevents layout shift and ensures textarea grows/shrinks with user input without exceeding viewport.
 *
 * guardrails:
 *   - DO NOT remove 'auto' reset; scrollHeight requires it to measure accurately
 *   - NOTE: 120px cap is hardcoded; make configurable if max-height varies
 *   - ASK USER: Is this textarea managed by React? If yes, move logic to useEffect/useLayoutEffect
 * ---/agentspec
 */
function autoResizeTextarea(textarea) {
    textarea.style.height = 'auto';
    const newHeight = Math.min(textarea.scrollHeight, 120);
    textarea.style.height = newHeight + 'px';
}

// Initialize chat UI and event listeners
/**
 * ---agentspec
 * what: |
 *   Initializes legacy chat UI only if React ChatInterface is not present. Checks for data-react-chat="true" marker; skips init if found.
 *
 * why: |
 *   Prevents duplicate chat initialization and conflicts between legacy and React implementations.
 *
 * guardrails:
 *   - DO NOT initialize if data-react-chat="true" exists; React owns the DOM
 *   - NOTE: Relies on React component to set marker; undocumented contract
 * ---/agentspec
 */
function initChatUI() {
    // Skip initialization if React ChatInterface is managing the chat
    // React component sets data-react-chat="true" on its container
    if (document.querySelector('[data-react-chat="true"]')) {
        console.log('[chat.js] React ChatInterface detected, skipping legacy initialization');
        return;
    }

    const input = document.getElementById('chat-input');
    const sendBtn = document.getElementById('chat-send');
    const clearBtn = document.getElementById('chat-clear');
    const historyBtn = document.getElementById('chat-history');
    const exportHistoryBtn = document.getElementById('chat-export-history');
    const clearHistoryBtn = document.getElementById('chat-clear-history');
    const saveSettingsBtn = document.getElementById('chat-save-settings');
    const resetSettingsBtn = document.getElementById('chat-reset-settings');

    if (input) {
        // Send on Ctrl+Enter
        input.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && e.ctrlKey) {
                e.preventDefault();
                sendMessage();
            }
        });

        // Auto-resize as user types
        input.addEventListener('input', () => {
            autoResizeTextarea(input);
        });
    }

    if (sendBtn) {
        sendBtn.addEventListener('click', sendMessage);
    }

    if (clearBtn) {
        clearBtn.addEventListener('click', clearChat);
    }

    if (historyBtn) {
        historyBtn.addEventListener('click', () => {
            const dropdown = document.getElementById('history-dropdown');
            dropdown.style.display = dropdown.style.display === 'block' ? 'none' : 'block';
        });
    }

    if (exportHistoryBtn) {
        exportHistoryBtn.addEventListener('click', exportChatHistory);
    }

    if (clearHistoryBtn) {
        clearHistoryBtn.addEventListener('click', clearChatHistory);
    }

    if (saveSettingsBtn) {
        saveSettingsBtn.addEventListener('click', saveChatSettings);
    }

    if (resetSettingsBtn) {
        resetSettingsBtn.addEventListener('click', resetChatSettings);
    }

    // Apply loaded settings on page load
    applyChatSettings();

    // Load chat history if enabled
    loadChatHistory();

    // Hide dropdown when clicking outside
    document.addEventListener('click', (e) => {
        if (!e.target.closest('#chat-history') && !e.target.closest('#history-dropdown')) {
            const dropdown = document.getElementById('history-dropdown');
            if (dropdown) dropdown.style.display = 'none';
        }
    });
}

// Cleanup function for unmounting
/**
 * ---agentspec
 * what: |
 *   Cleanup function for chat UI. Logs unmount event; placeholder for future resource cleanup (timers, requests).
 *
 * why: |
 *   Ensures graceful teardown when chat component unmounts; prevents memory leaks.
 *
 * guardrails:
 *   - NOTE: Currently no-op; add actual cleanup (clearInterval, abort requests) before production
 *   - DO NOT rely on this for critical resource management until implemented
 * ---/agentspec
 */
function cleanupChatUI() {
    // Clear any pending requests or intervals
    // (Currently no cleanup needed, but placeholder for future)
    console.log('[chat.js] Unmounted');
}

// Register with Navigation API
if (typeof window !== 'undefined') {
    /**
     * ---agentspec
     * what: |
     *   Conditionally initializes chat UI when DOM elements exist or React signals readiness. Wraps initChatUI() in try-catch; logs warnings on failure.
     *
     * why: |
     *   Defers initialization until chat UI is mounted, avoiding errors from missing DOM nodes during page load.
     *
     * guardrails:
     *   - DO NOT initialize before DOM ready; causes null reference errors
     *   - NOTE: Silently fails if initChatUI() throws; consider retry logic for transient failures
     *   - ASK USER: Should failed init attempts retry, or log as fatal?
     * ---/agentspec
     */
    function tryInitOnVisible() {
        // Only initialize if chat UI is present in DOM
        if (document.getElementById('chat-input') || document.getElementById('tab-chat')) {
            try { initChatUI(); } catch (e) { console.warn('[chat.js] initChatUI failed:', e); }
        }
    }

    // React migration hooks: initialize when React signals readiness or when Chat tab mounts
    window.addEventListener('react-ready', tryInitOnVisible);
    window.addEventListener('tribrid:chat:mount', tryInitOnVisible);

    window.addEventListener('DOMContentLoaded', () => {
        // Register view with Navigation system
        if (window.Navigation && typeof window.Navigation.registerView === 'function') {
            window.Navigation.registerView({
                id: 'chat',
                title: 'Chat',
                mount: () => {
                    console.log('[chat.js] Mounted');
                    tryInitOnVisible();
                },
                unmount: () => {
                    cleanupChatUI();
                }
            });
        }

        // Initialize immediately if chat tab is already active
        // This handles backward compatibility with old tab system
        const chatTab = document.getElementById('tab-chat');
        if (chatTab && chatTab.classList.contains('active')) {
            tryInitOnVisible();
        }
    });

    // Expose manual init for React components to call directly
    window.ChatUI = Object.assign({}, window.ChatUI || {}, { init: tryInitOnVisible });
}

// Add fadeIn animation
if (typeof document !== 'undefined' && !document.querySelector('#chat-animations')) {
    const style = document.createElement('style');
    style.id = 'chat-animations';
    style.textContent = `
        @keyframes fadeIn {
            from { opacity: 0; transform: translateY(-4px); }
            to { opacity: 1; transform: translateY(0); }
        }
    `;
    document.head.appendChild(style);
}
