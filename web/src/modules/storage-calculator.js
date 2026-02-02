// TriBridRAG Storage Calculator v1.2 - JavaScript Logic
// This file contains all the calculation logic for the storage calculator

// Improved formatBytes function with consistent formatting
/**
 * ---agentspec
 * what: |
 *   Converts byte count to human-readable string (B, KB, MB, GB, TB). Returns formatted string with up to 3 decimals.
 *
 * why: |
 *   Intl.NumberFormat ensures locale-aware formatting; early returns handle edge cases (non-finite, zero).
 *
 * guardrails:
 *   - DO NOT use for negative bytes; abs() masks sign
 *   - NOTE: Returns '0 B' for zero and non-finite values
 * ---/agentspec
 */
function formatBytes(bytes) {
    if (!isFinite(bytes) || bytes === 0) return '0 B';
    const abs = Math.abs(bytes);
    const KB = 1024;
    const MB = KB * 1024;
    const GB = MB * 1024;
    const TB = GB * 1024;
    const nf = new Intl.NumberFormat('en-US', { maximumFractionDigits: 3 });

    if (abs < KB) return `${bytes.toFixed(0)} B`;
    if (abs < MB) return `${nf.format(bytes / KB)} KiB`;
    if (abs < GB) return `${nf.format(bytes / MB)} MiB`;
    if (abs < TB) return `${nf.format(bytes / GB)} GiB`;
    return `${nf.format(bytes / TB)} TiB`;
}

/**
 * ---agentspec
 * what: |
 *   Formats numbers using Intl.NumberFormat. Accepts number, returns locale-formatted string (e.g., 1000 → "1,000").
 *
 * why: |
 *   Centralizes locale-aware formatting to avoid repeated Intl instantiation.
 *
 * guardrails:
 *   - NOTE: Hardcoded to 'en-US'; parameterize locale if multi-region needed
 *   - DO NOT use for currency/percent without explicit formatter type
 * ---/agentspec
 */
function formatNumber(num) {
    return new Intl.NumberFormat('en-US').format(num);
}

// Calculator 1: Full Storage Requirements
/**
 * ---agentspec
 * what: |
 *   Calculates storage chunks from repo size and chunk size inputs. Multiplies parsed values by unit scalars, returns numeric result.
 *
 * why: |
 *   Centralizes storage math with unit conversion; guards against zero/invalid chunk sizes.
 *
 * guardrails:
 *   - DO NOT proceed if chunk size ≤ 0; warn and halt
 *   - NOTE: Assumes unit selectors contain valid numeric multipliers
 * ---/agentspec
 */
function calculateStorage1() {
    const R = parseFloat(document.getElementById('calc1-repoSize').value) *
             parseFloat(document.getElementById('calc1-repoUnit').value);
    const C = parseFloat(document.getElementById('calc1-chunkSize').value) *
             parseFloat(document.getElementById('calc1-chunkUnit').value);

    // Guard against invalid chunk size
    if (!C || C <= 0) {
        console.warn("Chunk size must be > 0");
        return;
    }

    const D = parseFloat(document.getElementById('calc1-embDim').value);
    const B = parseFloat(document.getElementById('calc1-precision').value);
    const Q = parseFloat(document.getElementById('calc1-qdrant').value);
    const hydrationPct = parseFloat(document.getElementById('calc1-hydration').value) / 100;
    const redisBytes = parseFloat(document.getElementById('calc1-redis').value) * 1048576;
    const replFactor = parseFloat(document.getElementById('calc1-replication').value);

    // Calculate
    const N = Math.ceil(R / C);
    const E = N * D * B;
    const Q_bytes = E * Q;
    const BM25 = 0.20 * R;
    const CARDS = 0.10 * R;
    const HYDR = hydrationPct * R;
    const RER = 0.5 * E;

    // Update display
    document.getElementById('calc1-chunks').textContent = formatNumber(N);
    document.getElementById('calc1-embeddings').textContent = formatBytes(E);
    document.getElementById('calc1-qdrantSize').textContent = formatBytes(Q_bytes);
    document.getElementById('calc1-bm25').textContent = formatBytes(BM25);
    document.getElementById('calc1-cards').textContent = formatBytes(CARDS);
    document.getElementById('calc1-hydr').textContent = formatBytes(HYDR);
    document.getElementById('calc1-reranker').textContent = formatBytes(RER);
    document.getElementById('calc1-redisSize').textContent = formatBytes(redisBytes);

    // Totals
    const singleTotal = E + Q_bytes + BM25 + CARDS + HYDR + RER + redisBytes;
    const criticalComponents = E + Q_bytes + HYDR + CARDS + RER;
    const replicatedTotal = singleTotal + (replFactor - 1) * criticalComponents;

    document.getElementById('calc1-single').textContent = formatBytes(singleTotal);
    document.getElementById('calc1-replicated').textContent = formatBytes(replicatedTotal);
    document.getElementById('calc1-repFactor').textContent = replFactor;
}

// Calculator 2: Optimization & Fitting (corrected version)
/**
 * ---agentspec
 * what: |
 *   Reads repo size, target size, chunk size from DOM inputs with unit multipliers. Converts all to bytes. Returns numeric storage calculation inputs.
 *
 * why: |
 *   Centralizes unit conversion logic before downstream storage math.
 *
 * guardrails:
 *   - DO NOT assume DOM values are valid; add parseFloat guards + NaN checks
 *   - NOTE: Unit multipliers must be pre-populated in select elements or calculation silently fails
 *   - ASK USER: Is chunk size calculation complete? Function appears truncated
 * ---/agentspec
 */
function calculateStorage2() {
    // Read base values (uses same unit semantics as calc1)
    const R = parseFloat(document.getElementById('calc2-repoSize').value) *
              parseFloat(document.getElementById('calc2-repoUnit').value);

    const targetBytes = parseFloat(document.getElementById('calc2-targetSize').value) *
                        parseFloat(document.getElementById('calc2-targetUnit').value);

    const C = parseFloat(document.getElementById('calc2-chunkSize').value) *
              parseFloat(document.getElementById('calc2-chunkUnit').value);

    // Guard against invalid chunk size
    if (!C || C <= 0) {
        console.warn("Chunk size must be > 0");
        return;
    }

    const D = parseFloat(document.getElementById('calc2-embDim').value);
    const bm25Pct = parseFloat(document.getElementById('calc2-bm25pct').value) / 100;
    const cardsPct = parseFloat(document.getElementById('calc2-cardspct').value) / 100;

    // Try to reuse calc1 inputs if present (keeps both calculators consistent)
    const qdrantMultiplier = (document.getElementById('calc1-qdrant') ? parseFloat(document.getElementById('calc1-qdrant').value) : 1.5);
    const hydrationPct = (document.getElementById('calc1-hydration') ? (parseFloat(document.getElementById('calc1-hydration').value) / 100) : 1.0);
    const redisBytesInput = (document.getElementById('calc1-redis') ? parseFloat(document.getElementById('calc1-redis').value) * 1048576 : 390 * 1048576);
    const replicationFactor = (document.getElementById('calc1-replication') ? parseFloat(document.getElementById('calc1-replication').value) : 3);

    // Derived values
    const N = Math.ceil(R / C);
    const E_float32 = N * D * 4;
    const E_float16 = E_float32 / 2;
    const E_int8 = E_float32 / 4;
    const E_pq8 = E_float32 / 8;

    const BM25 = bm25Pct * R;
    const CARDS = cardsPct * R;

    // Update display
    document.getElementById('calc2-chunks').textContent = formatNumber(N);
    document.getElementById('calc2-baseStorage').textContent = formatBytes(R);
    document.getElementById('calc2-float32').textContent = formatBytes(E_float32);
    document.getElementById('calc2-float16').textContent = formatBytes(E_float16);
    document.getElementById('calc2-int8').textContent = formatBytes(E_int8);
    document.getElementById('calc2-pq8').textContent = formatBytes(E_pq8);

    // Aggressive plan: PQ 8x, no local hydration (hydrate = 0)
    const aggressiveEmbedding = E_pq8;
    const aggressiveQ = E_pq8 * qdrantMultiplier;
    const aggressiveRer = 0.5 * E_pq8; // reranker scaled with PQ embedding bytes
    const aggressiveTotal = aggressiveEmbedding + aggressiveQ + BM25 + CARDS + redisBytesInput + aggressiveRer;
    const aggressiveCritical = aggressiveEmbedding + aggressiveQ + CARDS + aggressiveRer; // no hydration
    const aggressiveReplicated = aggressiveTotal + (replicationFactor - 1) * aggressiveCritical;
    const aggressiveFits = aggressiveTotal <= targetBytes;

    document.getElementById('calc2-aggressive-total').textContent = formatBytes(aggressiveTotal);
    document.getElementById('calc2-aggressive-replicated').textContent = formatBytes(aggressiveReplicated);
    document.getElementById('calc2-aggressive-plan').className = 'plan-card ' + (aggressiveFits ? 'fits' : 'exceeds');

    // Conservative plan: float16 precision, full hydration
    const conservativeEmbedding = E_float16;
    const conservativeQ = conservativeEmbedding * qdrantMultiplier;
    const conservativeRer = 0.5 * conservativeEmbedding;
    const conservativeHydration = hydrationPct * R;
    const conservativeTotal = conservativeEmbedding + conservativeQ + conservativeHydration + BM25 + CARDS + conservativeRer + redisBytesInput;
    const conservativeCritical = conservativeEmbedding + conservativeQ + conservativeHydration + CARDS + conservativeRer;
    const conservativeReplicated = conservativeTotal + (replicationFactor - 1) * conservativeCritical;
    const conservativeFits = conservativeTotal <= targetBytes;

    document.getElementById('calc2-conservative-total').textContent = formatBytes(conservativeTotal);
    document.getElementById('calc2-conservative-replicated').textContent = formatBytes(conservativeReplicated);
    document.getElementById('calc2-conservative-plan').className = 'plan-card ' + (conservativeFits ? 'fits' : 'exceeds');

    // Update replication factor display
    document.getElementById('calc2-aggRepFactor').textContent = replicationFactor;
    document.getElementById('calc2-consRepFactor').textContent = replicationFactor;

    // Update hydration info display
    const hydrationInfoEl = document.getElementById('hydrationInfo');
    if (hydrationInfoEl) {
        hydrationInfoEl.textContent = Math.round(hydrationPct * 100) + '%';
    }

    // Status message
    const statusEl = document.getElementById('calc2-status');
    if (aggressiveFits && conservativeFits) {
        statusEl.className = 'success';
        statusEl.textContent = '✓ Both configurations fit within your ' + formatBytes(targetBytes) + ' limit';
    } else if (aggressiveFits) {
        statusEl.className = 'warning';
        statusEl.textContent = '⚠ Only Minimal config fits. Low Latency config needs ' + formatBytes(conservativeTotal - targetBytes) + ' more storage.';
    } else {
        statusEl.className = 'warning';
        statusEl.textContent = '⚠ Both exceed limit. Minimal needs ' + formatBytes(aggressiveTotal - targetBytes) + ' more. Consider larger chunks or stronger compression.';
    }
}

// Initialize event listeners when DOM is loaded
/**
 * ---agentspec
 * what: |
 *   Attaches input event listeners to 10 storage calculator form fields. Triggers calculateStorage1() on any field change.
 *
 * why: |
 *   Real-time UI updates require reactive listeners on all input elements.
 *
 * guardrails:
 *   - DO NOT assume all elements exist; check getElementById null before attach
 *   - NOTE: calculateStorage1() must be defined; listener will fail silently if missing
 * ---/agentspec
 */
function initStorageCalculator() {
    // Event listeners for Calculator 1
    ['calc1-repoSize', 'calc1-repoUnit', 'calc1-chunkSize', 'calc1-chunkUnit',
     'calc1-embDim', 'calc1-precision', 'calc1-qdrant', 'calc1-hydration',
     'calc1-redis', 'calc1-replication'].forEach(id => {
        const element = document.getElementById(id);
        if (element) {
            element.addEventListener('input', () => {
                calculateStorage1();
                calculateStorage2(); // Recalc calc2 when calc1 shared params change
            });
        }
    });

    // Event listeners for Calculator 2
    ['calc2-repoSize', 'calc2-repoUnit', 'calc2-targetSize', 'calc2-targetUnit',
     'calc2-chunkSize', 'calc2-chunkUnit', 'calc2-embDim', 'calc2-bm25pct',
     'calc2-cardspct'].forEach(id => {
        const element = document.getElementById(id);
        if (element) {
            element.addEventListener('input', calculateStorage2);
        }
    });

    // Initial calculations
    calculateStorage1();
    calculateStorage2();
}

// Export functions for external use
if (typeof module !== 'undefined' && module.exports) {
    module.exports = {
        formatBytes,
        formatNumber,
        calculateStorage1,
        calculateStorage2,
        initStorageCalculator
    };
}
