// Enterprise-grade indexing status display
// Matches storage calculator format with comprehensive metrics

/**
 * ---agentspec
 * what: |
 *   Formats byte counts into human-readable units (B, KB, MB, GB, TB). Input: number of bytes; output: string with value + unit.
 *
 * why: |
 *   Standardizes file size display across UI without repeated conversion logic.
 *
 * guardrails:
 *   - DO NOT use for network throughput; bytes-per-second requires different formatting
 *   - NOTE: Returns '0 B' for null/undefined/zero input
 * ---/agentspec
 */
function formatBytes(bytes) {
    if (!bytes || bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return Math.round((bytes / Math.pow(k, i)) * 100) / 100 + ' ' + sizes[i];
}

/**
 * ---agentspec
 * what: |
 *   Formats index status display HTML. Takes lines array and metadata object; returns styled div with status text or embedding/storage breakdown.
 *
 * why: |
 *   Centralizes UI rendering logic for consistent status presentation across index states.
 *
 * guardrails:
 *   - DO NOT render unsanitized metadata; escape user input before HTML insertion
 *   - NOTE: Falls back to "Ready to index..." if no metadata; requires lines array for fallback text
 *   - ASK USER: Confirm metadata.embedding_config and metadata.storage_breakdown structure before production
 * ---/agentspec
 */
function formatIndexStatusDisplay(lines, metadata) {
    if (!metadata) {
        if (!lines || !lines.length) return '<div style="color:var(--fg-muted);font-size:13px;">Ready to index...</div>';
        return `<div style="color:var(--fg-muted);font-size:12px;">${lines.join('<br>')}</div>`;
    }

    const html = [];
    const emb = metadata.embedding_config || {};
    const storage = metadata.storage_breakdown || {};
    const costs = metadata.costs || {};

    // HEADER: Repo + Branch
    html.push(`
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:20px;padding-bottom:16px;border-bottom:2px solid var(--line);">
            <div style="display:flex;align-items:center;gap:14px;">
                <div style="width:8px;height:8px;border-radius:50%;background:var(--accent);box-shadow:0 0 12px var(--accent);animation:pulse 2s ease-in-out infinite;"></div>
                <div>
                    <div style="font-size:20px;font-weight:700;color: var(--fg);letter-spacing:-0.5px;">${metadata.current_repo}</div>
                    <div style="font-size:11px;color:var(--fg-muted);text-transform:uppercase;letter-spacing:0.8px;margin-top:4px;">
                        <span style="color:var(--fg-muted)">Branch:</span> <span style="color:var(--link);font-weight:600;">${metadata.current_branch}</span>
                    </div>
                </div>
            </div>
            <div style="text-align:right;font-size:10px;color: var(--fg-muted);font-family:'SF Mono',monospace;">
                ${new Date(metadata.timestamp).toLocaleString()}
            </div>
        </div>
    `);

    // EMBEDDING CONFIGURATION
    html.push(`
        <div style="background:linear-gradient(135deg,var(--card-bg) 0%,var(--code-bg) 100%);padding:16px;border-radius:8px;border:1px solid var(--line);margin-bottom:20px;">
            <div style="font-size:11px;font-weight:700;color:var(--link);text-transform:uppercase;letter-spacing:1px;margin-bottom:12px;display:flex;align-items:center;gap:8px;">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="var(--link)" stroke-width="2">
                    <circle cx="12" cy="12" r="10"></circle>
                    <path d="M12 6v6l4 2"></path>
                </svg>
                Embedding Configuration
            </div>
            <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:10px;">
                <div style="background:var(--card-bg);padding:10px;border-radius:6px;border:1px solid var(--bg-elev2);">
                    <div style="font-size:9px;color:var(--fg-muted);text-transform:uppercase;letter-spacing:0.5px;margin-bottom:4px;">Model</div>
                    <div style="font-size:13px;font-weight:700;color:var(--link);font-family:'SF Mono',monospace;">${emb.model || 'N/A'}</div>
                </div>
                <div style="background:var(--card-bg);padding:10px;border-radius:6px;border:1px solid var(--bg-elev2);">
                    <div style="font-size:9px;color:var(--fg-muted);text-transform:uppercase;letter-spacing:0.5px;margin-bottom:4px;">Dimensions</div>
                    <div style="font-size:13px;font-weight:700;color:var(--link);font-family:'SF Mono',monospace;">${emb.dimensions ? emb.dimensions.toLocaleString() : 'N/A'}</div>
                </div>
                <div style="background:var(--card-bg);padding:10px;border-radius:6px;border:1px solid var(--bg-elev2);">
                    <div style="font-size:9px;color:var(--fg-muted);text-transform:uppercase;letter-spacing:0.5px;margin-bottom:4px;">Precision</div>
                    <div style="font-size:13px;font-weight:700;color:var(--warn);font-family:'SF Mono',monospace;">${emb.precision || 'N/A'}</div>
                </div>
            </div>
        </div>
    `);

    // COSTS (if available)
    if (costs.total_tokens > 0) {
        html.push(`
            <div style="background:linear-gradient(135deg,color-mix(in oklch, var(--ok) 6%, var(--bg)) 0%,var(--card-bg) 100%);padding:16px;border-radius:8px;border:1px solid color-mix(in oklch, var(--ok) 30%, var(--bg));margin-bottom:20px;">
                <div style="font-size:11px;font-weight:700;color:var(--accent);text-transform:uppercase;letter-spacing:1px;margin-bottom:12px;display:flex;align-items:center;gap:8px;">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="var(--accent)" stroke-width="2">
                        <line x1="12" y1="1" x2="12" y2="23"></line>
                        <path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"></path>
                    </svg>
                    Indexing Costs
                </div>
                <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;">
                    <div style="background:var(--card-bg);padding:10px;border-radius:6px;border:1px solid color-mix(in oklch, var(--ok) 25%, var(--bg));">
                        <div style="font-size:9px;color:var(--fg-muted);text-transform:uppercase;letter-spacing:0.5px;margin-bottom:4px;">Total Tokens</div>
                        <div style="font-size:15px;font-weight:700;color:var(--accent);font-family:'SF Mono',monospace;">${costs.total_tokens.toLocaleString()}</div>
                    </div>
                    <div style="background:var(--card-bg);padding:10px;border-radius:6px;border:1px solid color-mix(in oklch, var(--ok) 25%, var(--bg));">
                        <div style="font-size:9px;color:var(--fg-muted);text-transform:uppercase;letter-spacing:0.5px;margin-bottom:4px;">Embedding Cost</div>
                        <div style="font-size:15px;font-weight:700;color:var(--accent);font-family:'SF Mono',monospace;">$${costs.embedding_cost.toFixed(4)}</div>
                    </div>
                </div>
            </div>
        `);
    }

    // STORAGE BREAKDOWN (matching calculator format exactly)
    html.push(`
        <div style="background:linear-gradient(135deg,var(--code-bg) 0%,var(--card-bg) 100%);padding:18px;border-radius:8px;border:1px solid var(--line);margin-bottom:20px;">
            <div style="font-size:11px;font-weight:700;color:var(--warn);text-transform:uppercase;letter-spacing:1px;margin-bottom:16px;display:flex;align-items:center;gap:8px;">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="var(--warn)" stroke-width="2">
                    <rect x="2" y="3" width="20" height="18" rx="2" ry="2"></rect>
                    <line x1="2" y1="9" x2="22" y2="9"></line>
                    <line x1="2" y1="15" x2="22" y2="15"></line>
                </svg>
                Storage Requirements
            </div>
            <div style="display:grid;grid-template-columns:repeat(2,1fr);gap:10px;">
                <div style="background:var(--card-bg);padding:12px;border-radius:6px;border:1px solid var(--bg-elev2);display:flex;justify-content:space-between;align-items:center;">
                    <span style="font-size:10px;color:var(--fg-muted);text-transform:uppercase;letter-spacing:0.5px;">Chunks JSON</span>
                    <span style="font-size:13px;font-weight:700;color:var(--link);font-family:'SF Mono',monospace;">${formatBytes(storage.chunks_json)}</span>
                </div>
                <div style="background:var(--card-bg);padding:12px;border-radius:6px;border:1px solid var(--bg-elev2);display:flex;justify-content:space-between;align-items:center;">
                    <span style="font-size:10px;color:var(--fg-muted);text-transform:uppercase;letter-spacing:0.5px;">Raw Embeddings</span>
                    <span style="font-size:13px;font-weight:700;color:var(--link);font-family:'SF Mono',monospace;">${formatBytes(storage.embeddings_raw)}</span>
                </div>
                <div style="background:var(--card-bg);padding:12px;border-radius:6px;border:1px solid var(--bg-elev2);display:flex;justify-content:space-between;align-items:center;">
                    <span style="font-size:10px;color:var(--fg-muted);text-transform:uppercase;letter-spacing:0.5px;">Qdrant (w/overhead)</span>
                    <span style="font-size:13px;font-weight:700;color:var(--warn);font-family:'SF Mono',monospace;">${formatBytes(storage.embeddings_raw + storage.qdrant_overhead)}</span>
                </div>
                <div style="background:var(--card-bg);padding:12px;border-radius:6px;border:1px solid var(--bg-elev2);display:flex;justify-content:space-between;align-items:center;">
                    <span style="font-size:10px;color:var(--fg-muted);text-transform:uppercase;letter-spacing:0.5px;">BM25 Index</span>
                    <span style="font-size:13px;font-weight:700;color:var(--accent);font-family:'SF Mono',monospace;">${formatBytes(storage.bm25_index)}</span>
                </div>
                <div style="background:var(--card-bg);padding:12px;border-radius:6px;border:1px solid var(--bg-elev2);display:flex;justify-content:space-between;align-items:center;">
                    <span style="font-size:10px;color:var(--fg-muted);text-transform:uppercase;letter-spacing:0.5px;">Cards/Summary</span>
                    <span style="font-size:13px;font-weight:700;color:var(--accent);font-family:'SF Mono',monospace;">${formatBytes(storage.cards)}</span>
                </div>
                <div style="background:var(--card-bg);padding:12px;border-radius:6px;border:1px solid var(--bg-elev2);display:flex;justify-content:space-between;align-items:center;">
                    <span style="font-size:10px;color:var(--fg-muted);text-transform:uppercase;letter-spacing:0.5px;">Reranker Cache</span>
                    <span style="font-size:13px;font-weight:700;color:var(--warn);font-family:'SF Mono',monospace;">${formatBytes(storage.reranker_cache)}</span>
                </div>
                <div style="background:var(--card-bg);padding:12px;border-radius:6px;border:1px solid var(--line);display:flex;justify-content:space-between;align-items:center;">
                    <span style="font-size:10px;color:var(--fg-muted);text-transform:uppercase;letter-spacing:0.5px;">Redis Cache</span>
                    <span style="font-size:13px;font-weight:700;color:var(--link);font-family:'SF Mono',monospace;">${formatBytes(storage.redis)}</span>
                </div>
                <div style="background:var(--card-bg);padding:12px;border-radius:6px;border:1px solid var(--line);display:flex;justify-content:space-between;align-items:center;">
                    <span style="font-size:10px;color:var(--fg-muted);text-transform:uppercase;letter-spacing:0.5px;">Keywords</span>
                    <span style="font-size:13px;font-weight:700;color:var(--warn);font-family:'SF Mono',monospace;">${metadata.keywords_count.toLocaleString()}</span>
                </div>
            </div>
        </div>
    `);

    // INDEX PROFILES (collapsible)
    if (metadata.repos && metadata.repos.length > 0) {
        html.push(`
            <details style="margin-bottom:20px;">
                <summary style="cursor:pointer;font-size:11px;font-weight:700;color:var(--fg-muted);text-transform:uppercase;letter-spacing:1px;padding:12px;background:var(--card-bg);border-radius:6px;border:1px solid var(--line);">
                    <span style="color:var(--link);">▸</span> Index Profiles (${metadata.repos.length})
                </summary>
                <div style="margin-top:12px;padding:12px;background:var(--card-bg);border-radius:6px;border:1px solid var(--line);">
        `);

        metadata.repos.forEach(repo => {
            const totalSize = (repo.sizes.chunks || 0) + (repo.sizes.bm25 || 0) + (repo.sizes.cards || 0);
            html.push(`
                <div style="padding:10px;margin-bottom:8px;background:var(--code-bg);border-radius:4px;border:1px solid ${repo.has_cards ? 'color-mix(in oklch, var(--ok) 30%, var(--line))' : 'var(--line)'};">
                    <div style="display:flex;justify-content:space-between;margin-bottom:6px;">
                        <div style="font-size:12px;font-weight:600;color:var(--fg);">${repo.name} <span style="color:var(--fg-muted);font-weight:400;">/ ${repo.profile}</span></div>
                        <div style="font-size:12px;font-weight:700;color:var(--ok);font-family:'SF Mono',monospace;">${formatBytes(totalSize)}</div>
                    </div>
                    <div style="font-size:10px;color:var(--fg-muted);">${repo.chunk_count.toLocaleString()} chunks ${repo.has_cards ? '• <span style="color:var(--ok);">✓ Cards</span>' : ''}</div>
                </div>
            `);
        });

        html.push(`</div></details>`);
    }

    // TOTAL FOOTER
    html.push(`
        <div style="display:flex;justify-content:space-between;align-items:center;padding:18px;background:var(--panel);border-radius:8px;border:2px solid var(--accent);">
            <div style="font-size:13px;font-weight:700;color:var(--fg-muted);text-transform:uppercase;letter-spacing:1px;">Total Index Storage</div>
            <div style="font-size:24px;font-weight:900;color:var(--accent);font-family:'SF Mono',monospace;">
                ${formatBytes(metadata.total_storage)}
            </div>
        </div>
    `);

    return html.join('');
}

// Export for use in app.js
if (typeof window !== 'undefined') {
    window.formatIndexStatusDisplay = formatIndexStatusDisplay;
}
