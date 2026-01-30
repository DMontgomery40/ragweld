// Storage Calculator HTML Template
// This function generates the HTML structure for the storage calculator

/**
 * ---agentspec
 * what: |
 *   Renders HTML storage calculator UI for AGRO RAG system. Displays configuration inputs and memory planning tools.
 *
 * why: |
 *   Centralizes storage estimation UI in single reusable function.
 *
 * guardrails:
 *   - DO NOT hardcode user data; accept config as parameter
 *   - NOTE: Returns raw HTML string; sanitize before DOM insertion
 * ---/agentspec
 */
function getStorageCalculatorHTML() {
    return `
        <div class="storage-calc-wrapper">
            <div class="storage-calc-header">
                <h1><span class="brand">AGRO</span> Storage Calculator Suite</h1>
                <p class="subtitle">Another Good RAG Option • Enterprise Memory Planning</p>
                <div class="info-box">
                    <p>
                        <strong>Left:</strong> Calculate exact storage needs for your configuration.<br>
                        <strong>Right:</strong> See if your data fits within a target limit using different strategies.
                    </p>
                </div>
            </div>

            <div class="calculators-grid">
                <!-- Calculator 1: Comprehensive Storage Requirements -->
                <div class="calculator">
                    <div class="calculator-title">
                        Storage Requirements
                        <span class="calculator-badge">Full Stack</span>
                    </div>

                    <p style="font-size: 12px; color: var(--fg-muted); margin-bottom: 20px; line-height: 1.5;">
                        Calculate total storage for your chosen configuration with all components.
                    </p>

                    <div class="input-section">
                        <div class="input-row">
                            <div class="input-group">
                                <label>
                                    <div class="label-with-tooltip">
                                        Repository Size
                                        <span class="tooltip" title="Total size of your data/documents to index">?</span>
                                    </div>
                                </label>
                                <div class="unit-input">
                                    <input type="number" id="calc1-repoSize" value="5" step="0.1" min="0.1" aria-label="Repository size value">
                                    <select id="calc1-repoUnit" aria-label="Repository size unit">
                                        <option value="1073741824" selected>GiB</option>
                                        <option value="1099511627776">TiB</option>
                                        <option value="1048576">MiB</option>
                                    </select>
                                </div>
                            </div>
                            <div class="input-group">
                                <label>
                                    <div class="label-with-tooltip">
                                        Chunk Size
                                        <span class="tooltip" title="Size of text chunks for embedding. Typically 1-8 KiB">?</span>
                                    </div>
                                </label>
                                <div class="unit-input">
                                    <input type="number" id="calc1-chunkSize" value="4" step="1" min="0.001" aria-label="Chunk size value">
                                    <select id="calc1-chunkUnit" aria-label="Chunk size unit">
                                        <option value="1024" selected>KiB</option>
                                        <option value="1048576">MiB</option>
                                    </select>
                                </div>
                            </div>
                        </div>

                        <div class="input-row">
                            <div class="input-group">
                                <label>
                                    <div class="label-with-tooltip">
                                        Embedding Dimension
                                        <span class="tooltip" title="Vector size: 512 (small), 768 (BERT), 1536 (OpenAI)">?</span>
                                    </div>
                                </label>
                                <input type="number" id="calc1-embDim" value="512" step="1" min="1" aria-label="Embedding dimension">
                            </div>
                            <div class="input-group">
                                <label>
                                    <div class="label-with-tooltip">
                                        Precision
                                        <span class="tooltip" title="float32: full precision, float16: half size, int8: quarter size">?</span>
                                    </div>
                                </label>
                                <select id="calc1-precision" aria-label="Data precision">
                                    <option value="4" selected>float32</option>
                                    <option value="2">float16</option>
                                    <option value="1">int8</option>
                                </select>
                            </div>
                        </div>

                        <div class="input-row">
                            <div class="input-group">
                                <label>
                                    <div class="label-with-tooltip">
                                        Qdrant Overhead
                                        <span class="tooltip" title="Vector DB index overhead. Typically 1.5x embedding size">?</span>
                                    </div>
                                </label>
                                <input type="number" id="calc1-qdrant" value="1.5" step="0.1" min="1" aria-label="Qdrant overhead multiplier">
                            </div>
                            <div class="input-group">
                                <label>
                                    <div class="label-with-tooltip">
                                        Hydration %
                                        <span class="tooltip" title="% of raw data kept in RAM for instant retrieval. 0% = fetch from disk, 100% = everything in memory">?</span>
                                    </div>
                                </label>
                                <input type="number" id="calc1-hydration" value="100" step="10" min="0" max="100" aria-label="Hydration percentage">
                            </div>
                        </div>

                        <div class="input-row">
                            <div class="input-group">
                                <label>
                                    <div class="label-with-tooltip">
                                        Redis Cache (MiB)
                                        <span class="tooltip" title="Session/chat memory storage">?</span>
                                    </div>
                                </label>
                                <input type="number" id="calc1-redis" value="400" step="50" min="0" aria-label="Redis cache size">
                            </div>
                            <div class="input-group">
                                <label>
                                    <div class="label-with-tooltip">
                                        Replication Factor
                                        <span class="tooltip" title="Number of copies for HA/scaling">?</span>
                                    </div>
                                </label>
                                <input type="number" id="calc1-replication" value="3" step="1" min="1" aria-label="Replication factor">
                            </div>
                        </div>
                    </div>

                    <div class="results">
                        <div class="result-grid">
                            <div class="result-item">
                                <span class="result-label">Chunks</span>
                                <span class="result-value" id="calc1-chunks">-</span>
                            </div>
                            <div class="result-item">
                                <span class="result-label">Raw Embeddings</span>
                                <span class="result-value" id="calc1-embeddings">-</span>
                            </div>
                            <div class="result-item">
                                <span class="result-label">Qdrant</span>
                                <span class="result-value" id="calc1-qdrantSize">-</span>
                            </div>
                            <div class="result-item">
                                <span class="result-label">BM25 Index</span>
                                <span class="result-value" id="calc1-bm25">-</span>
                            </div>
                            <div class="result-item">
                                <span class="result-label">Cards/Summary</span>
                                <span class="result-value" id="calc1-cards">-</span>
                            </div>
                            <div class="result-item">
                                <span class="result-label">Hydration</span>
                                <span class="result-value" id="calc1-hydr">-</span>
                            </div>
                            <div class="result-item">
                                <span class="result-label">Reranker</span>
                                <span class="result-value" id="calc1-reranker">-</span>
                            </div>
                            <div class="result-item">
                                <span class="result-label">Redis</span>
                                <span class="result-value" id="calc1-redisSize">-</span>
                            </div>
                        </div>

                        <div class="total-row">
                            <div class="result-item">
                                <span class="result-label">Single Instance</span>
                                <span class="result-value" id="calc1-single">-</span>
                            </div>
                            <div class="result-item">
                                <span class="result-label">Replicated (×<span id="calc1-repFactor">3</span>)</span>
                                <span class="result-value" id="calc1-replicated">-</span>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- Calculator 2: Optimization & Fitting -->
                <div class="calculator">
                    <div class="calculator-title">
                        Optimization Planner
                        <span class="calculator-badge">Fit Analysis</span>
                    </div>

                    <p style="font-size: 12px; color: var(--fg-muted); margin-bottom: 20px; line-height: 1.5;">
                        Compare two strategies: <strong>Minimal</strong> (smallest footprint, fetches data on-demand) vs <strong>Low Latency</strong> (everything in RAM for instant access).
                    </p>

                    <div class="input-section">
                        <div class="input-row">
                            <div class="input-group">
                                <label>
                                    <div class="label-with-tooltip">
                                        Repository Size
                                        <span class="tooltip" title="Same as left calculator - your total data">?</span>
                                    </div>
                                </label>
                                <div class="unit-input">
                                    <input type="number" id="calc2-repoSize" value="5" step="0.1" min="0.1" aria-label="Repository size value">
                                    <select id="calc2-repoUnit" aria-label="Repository size unit">
                                        <option value="1073741824" selected>GiB</option>
                                        <option value="1099511627776">TiB</option>
                                        <option value="1048576">MiB</option>
                                    </select>
                                </div>
                            </div>
                            <div class="input-group">
                                <label>
                                    <div class="label-with-tooltip">
                                        Target Limit
                                        <span class="tooltip" title="Max storage you want to use">?</span>
                                    </div>
                                </label>
                                <div class="unit-input">
                                    <input type="number" id="calc2-targetSize" value="5" step="0.5" min="0.1" aria-label="Target storage limit">
                                    <select id="calc2-targetUnit" aria-label="Target limit unit">
                                        <option value="1073741824" selected>GiB</option>
                                        <option value="1099511627776">TiB</option>
                                    </select>
                                </div>
                            </div>
                        </div>

                        <div class="input-row">
                            <div class="input-group">
                                <label>
                                    <div class="label-with-tooltip">
                                        Chunk Size
                                        <span class="tooltip" title="Smaller chunks = more vectors = more storage">?</span>
                                    </div>
                                </label>
                                <div class="unit-input">
                                    <input type="number" id="calc2-chunkSize" value="4" step="1" min="0.001" aria-label="Chunk size value">
                                    <select id="calc2-chunkUnit" aria-label="Chunk size unit">
                                        <option value="1024" selected>KiB</option>
                                        <option value="1048576">MiB</option>
                                    </select>
                                </div>
                            </div>
                            <div class="input-group">
                                <label>
                                    <div class="label-with-tooltip">
                                        Embedding Dims
                                        <span class="tooltip" title="Must match your model choice">?</span>
                                    </div>
                                </label>
                                <input type="number" id="calc2-embDim" value="512" step="1" min="1" aria-label="Embedding dimension">
                            </div>
                        </div>

                        <div class="input-row">
                            <div class="input-group">
                                <label>
                                    <div class="label-with-tooltip">
                                        BM25 Overhead %
                                        <span class="tooltip" title="Text search index, typically 20% of data">?</span>
                                    </div>
                                </label>
                                <input type="number" id="calc2-bm25pct" value="20" step="5" min="0" max="100" aria-label="BM25 overhead percentage">
                            </div>
                            <div class="input-group">
                                <label>
                                    <div class="label-with-tooltip">
                                        Cards/Summary %
                                        <span class="tooltip" title="Metadata/summaries, typically 10% of data">?</span>
                                    </div>
                                </label>
                                <input type="number" id="calc2-cardspct" value="10" step="5" min="0" max="100" aria-label="Cards/summary percentage">
                            </div>
                        </div>
                    </div>

                    <div class="results">
                        <div class="result-grid">
                            <div class="result-item">
                                <span class="result-label">Chunks</span>
                                <span class="result-value" id="calc2-chunks">-</span>
                            </div>
                            <div class="result-item">
                                <span class="result-label">Repository</span>
                                <span class="result-value" id="calc2-baseStorage">-</span>
                            </div>
                        </div>

                        <div class="plan-title">Embedding Size by Precision (raw vectors only)</div>
                        <div class="result-grid">
                            <div class="result-item">
                                <span class="result-label">float32 (baseline)</span>
                                <span class="result-value" id="calc2-float32">-</span>
                            </div>
                            <div class="result-item">
                                <span class="result-label">float16 (half size)</span>
                                <span class="result-value" id="calc2-float16">-</span>
                            </div>
                            <div class="result-item">
                                <span class="result-label">int8 (quarter size)</span>
                                <span class="result-value" id="calc2-int8">-</span>
                            </div>
                            <div class="result-item">
                                <span class="result-label">
                                    Product Quantization
                                    <span class="tooltip" title="Aggressive compression: 8× smaller but ~5% accuracy loss" style="margin-left: 4px;">?</span>
                                </span>
                                <span class="result-value" id="calc2-pq8">-</span>
                            </div>
                        </div>

                        <div class="plans-section">
                            <div class="plan-title">Configuration Plans</div>
                            <div class="plan-grid">
                                <div class="plan-card" id="calc2-aggressive-plan">
                                    <div class="plan-name">Minimal (No Hydration)</div>
                                    <div class="plan-details" id="calc2-aggressive-details" style="line-height: 1.8;">
                                        <strong>Includes:</strong><br>
                                        • Product Quantized vectors<br>
                                        • Qdrant index<br>
                                        • BM25 search<br>
                                        • Cards/metadata<br>
                                        • Reranker cache<br>
                                        • Redis<br>
                                        <strong>Excludes:</strong><br>
                                        • Raw data (fetched on-demand)
                                    </div>
                                    <div class="plan-total" id="calc2-aggressive-total">-</div>
                                </div>
                                <div class="plan-card" id="calc2-conservative-plan">
                                    <div class="plan-name">Low Latency (Full Cache)</div>
                                    <div class="plan-details" id="calc2-conservative-details" style="line-height: 1.8;">
                                        <strong>Includes:</strong><br>
                                        • float16 vectors<br>
                                        • Qdrant index<br>
                                        • BM25 search<br>
                                        • Cards/metadata<br>
                                        • Reranker cache<br>
                                        • Redis<br>
                                        • <span style="color: var(--warn);">Data in RAM (per left hydration %)</span>
                                    </div>
                                    <div class="plan-total" id="calc2-conservative-total">-</div>
                                </div>
                            </div>

                            <p style="font-size: 11px; color: var(--fg-muted); margin: 16px 0 8px; padding: 12px; background: var(--card-bg); border-radius: 4px; line-height: 1.5;">
                                💡 <strong>Why the big difference?</strong> Low Latency keeps data in RAM based on hydration % from left panel (currently adding <span id="hydrationInfo">100%</span> of repo size). Minimal only stores compressed vectors and indexes, fetching actual data from disk when needed.
                            </p>

                            <div class="total-row" style="margin-top: 20px;">
                                <div class="result-item">
                                    <span class="result-label">Minimal × <span id="calc2-aggRepFactor">3</span> replicas</span>
                                    <span class="result-value" id="calc2-aggressive-replicated">-</span>
                                </div>
                                <div class="result-item">
                                    <span class="result-label">Low Latency × <span id="calc2-consRepFactor">3</span> replicas</span>
                                    <span class="result-value" id="calc2-conservative-replicated">-</span>
                                </div>
                            </div>

                            <div id="calc2-status" style="margin-top: 12px;"></div>
                        </div>
                    </div>
                </div>
            </div>

            <div class="storage-calc-footer">
                <p>AGRO (Another Good RAG Option) • Enterprise Storage Calculator v1.2</p>
                <p>Precision calculations for vector search infrastructure</p>
            </div>
        </div>
    `;
}

// Export for use in main app
if (typeof module !== 'undefined' && module.exports) {
    module.exports = { getStorageCalculatorHTML };
}
