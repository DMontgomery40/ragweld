// Storage Calculator Hook
// Full calculation logic for storage requirements and optimization

import { useState, useCallback, useEffect } from 'react';
import type {
  CalculatorInputs,
  Calculator2Inputs,
  StorageResults,
  Calculator2Results,
  PrecisionResults
} from '@web/types/storage';
import { formatBytes } from '@web/utils/formatters';

/**
 * Hook for Calculator 1: Full Storage Requirements
 * Calculates exact storage needs for a given configuration
 */
/**
 * ---agentspec
 * what: |
 *   Custom React hook that manages state for a storage calculator component.
 *   Initializes and provides access to calculator input parameters: repository size (with unit conversion), chunk size (with unit conversion), embedding dimensions, and floating-point precision.
 *   Returns an `inputs` object containing all calculator parameters and a `setInputs` function to update them.
 *   Stores numeric values with their corresponding unit multipliers (e.g., repoUnit: 1073741824 for GiB conversion to bytes).
 *   Handles no edge cases internally; validation and computation logic must be implemented by consuming components.
 *
 * why: |
 *   Centralizes calculator state management in a reusable hook to avoid prop drilling and duplicate state logic across multiple components.
 *   Uses unit multipliers (1073741824 for GiB, 1024 for KiB) to enable flexible unit selection while maintaining consistent byte-based calculations downstream.
 *   Separates state initialization from business logic, allowing the hook to remain simple and testable.
 *
 * guardrails:
 *   - DO NOT add calculation logic to this hook; keep it a pure state container to maintain separation of concerns
 *   - ALWAYS ensure unit multipliers match standard byte conversion factors (1024 for binary units, 1000 for decimal) to prevent silent calculation errors
 *   - NOTE: Default precision value of 4 assumes float32; if precision semantics change, update documentation and validate all dependent calculations
 *   - ASK USER: Before adding derived state (e.g., computed total storage), confirm whether calculations should live in this hook or in a separate custom hook
 * ---/agentspec
 */
export function useStorageCalculator() {
  // Input state
  const [inputs, setInputs] = useState<CalculatorInputs>({
    repoSize: 5,
    repoUnit: 1073741824, // GiB
    chunkSize: 4,
    chunkUnit: 1024, // KiB
    embeddingDim: 512,
    precision: 4, // float32
    qdrantOverhead: 1.5,
    hydrationPercent: 100,
    replicationFactor: 3,
  });

  // Results state
  const [results, setResults] = useState<StorageResults>({
    chunks: 0,
    rawEmbeddings: 0,
    qdrantSize: 0,
    bm25Index: 0,
    cardsSummary: 0,
    hydration: 0,
    reranker: 0,
    singleInstance: 0,
    replicated: 0,
  });

  // Calculate storage requirements
  const calculate = useCallback(() => {
    const R = inputs.repoSize * inputs.repoUnit;
    const C = inputs.chunkSize * inputs.chunkUnit;

    // Guard against invalid chunk size
    if (!C || C <= 0) {
      console.warn('Chunk size must be > 0');
      return;
    }

    const D = inputs.embeddingDim;
    const B = inputs.precision;
    const Q = inputs.qdrantOverhead;
    const hydrationPct = inputs.hydrationPercent / 100;
    const replFactor = inputs.replicationFactor;

    // Calculate components
    const N = Math.ceil(R / C);
    const E = N * D * B;
    const Q_bytes = E * Q;
    const BM25 = 0.20 * R;
    const CARDS = 0.10 * R;
    const HYDR = hydrationPct * R;
    const RER = 0.5 * E;

    // Totals
    const singleTotal = E + Q_bytes + BM25 + CARDS + HYDR + RER;
    const criticalComponents = E + Q_bytes + HYDR + CARDS + RER;
    const replicatedTotal = singleTotal + (replFactor - 1) * criticalComponents;

    setResults({
      chunks: N,
      rawEmbeddings: E,
      qdrantSize: Q_bytes,
      bm25Index: BM25,
      cardsSummary: CARDS,
      hydration: HYDR,
      reranker: RER,
      singleInstance: singleTotal,
      replicated: replicatedTotal,
    });
  }, [inputs]);

  // Auto-calculate on input changes
  useEffect(() => {
    calculate();
  }, [calculate]);

  // Update individual input fields
  const updateInput = useCallback(<K extends keyof CalculatorInputs>(
    key: K,
    value: CalculatorInputs[K]
  ) => {
    setInputs((prev) => ({ ...prev, [key]: value }));
  }, []);

  return {
    inputs,
    results,
    updateInput,
    calculate,
  };
}

/**
 * Hook for Calculator 2: Optimization & Fitting
 * Compares different strategies to fit within a target storage limit
 */
/**
 * ---agentspec
 * what: |
 *   React hook that manages state for an optimization calculator component.
 *   Accepts optional CalculatorInputs parameter (calculator1Inputs) but does not use it; initializes Calculator2Inputs state with hardcoded defaults.
 *   Returns state object containing repoSize, repoUnit, targetSize, targetUnit, chunkSize, chunkUnit as numbers.
 *   Provides setInputs function to update calculator state.
 *   No side effects on mount; state persists across re-renders until component unmounts.
 *
 * why: |
 *   Encapsulates calculator state management in a reusable hook to separate UI logic from state handling.
 *   Hardcoded defaults (5 GiB repo, 5 GiB target, 4 KiB chunks) provide sensible starting values for typical optimization scenarios.
 *   Units stored as byte multipliers (1073741824 for GiB, 1024 for KiB) to enable unit-agnostic calculations downstream.
 *
 * guardrails:
 *   - DO NOT remove the unused calculator1Inputs parameter without confirming it was intentionally deprecated; ASK USER if this parameter should be integrated or formally removed
 *   - ALWAYS ensure setInputs updates maintain the Calculator2Inputs type contract; adding new fields requires type definition updates
 *   - NOTE: Hardcoded defaults are not configurable; if defaults need to vary by context, consider accepting them as hook parameters
 *   - ASK USER: Clarify whether calculator1Inputs parameter should be merged into initial state or if it represents a deprecated API that can be removed
 * ---/agentspec
 */
export function useOptimizationCalculator(calculator1Inputs?: CalculatorInputs) {
  // Input state
  const [inputs, setInputs] = useState<Calculator2Inputs>({
    repoSize: 5,
    repoUnit: 1073741824, // GiB
    targetSize: 5,
    targetUnit: 1073741824, // GiB
    chunkSize: 4,
    chunkUnit: 1024, // KiB
    embeddingDim: 512,
    bm25Percent: 20,
    cardsPercent: 10,
  });

  // Results state
  const [results, setResults] = useState<Calculator2Results>({
    chunks: 0,
    baseStorage: 0,
    precisions: {
      float32: 0,
      float16: 0,
      int8: 0,
      pq8: 0,
    },
    aggressivePlan: {
      name: 'Minimal (No Hydration)',
      description: [],
      total: 0,
      replicated: 0,
      fits: false,
    },
    conservativePlan: {
      name: 'Low Latency (Full Cache)',
      description: [],
      total: 0,
      replicated: 0,
      fits: false,
    },
    statusMessage: '',
    statusType: 'success',
  });

  // Calculate optimization plans
  const calculate = useCallback(() => {
    const R = inputs.repoSize * inputs.repoUnit;
    const targetBytes = inputs.targetSize * inputs.targetUnit;
    const C = inputs.chunkSize * inputs.chunkUnit;

    // Guard against invalid chunk size
    if (!C || C <= 0) {
      console.warn('Chunk size must be > 0');
      return;
    }

    const D = inputs.embeddingDim;
    const bm25Pct = inputs.bm25Percent / 100;
    const cardsPct = inputs.cardsPercent / 100;

    // Get shared parameters from calculator1 if available
    const qdrantMultiplier = calculator1Inputs?.qdrantOverhead ?? 1.5;
    const hydrationPct = calculator1Inputs
      ? calculator1Inputs.hydrationPercent / 100
      : 1.0;
    const replicationFactor = calculator1Inputs?.replicationFactor ?? 3;

    // Derived values
    const N = Math.ceil(R / C);
    const E_float32 = N * D * 4;
    const E_float16 = E_float32 / 2;
    const E_int8 = E_float32 / 4;
    const E_pq8 = E_float32 / 8;

    const BM25 = bm25Pct * R;
    const CARDS = cardsPct * R;

    const precisions: PrecisionResults = {
      float32: E_float32,
      float16: E_float16,
      int8: E_int8,
      pq8: E_pq8,
    };

    // Aggressive plan: PQ 8x, no local hydration (hydrate = 0)
    const aggressiveEmbedding = E_pq8;
    const aggressiveQ = E_pq8 * qdrantMultiplier;
    const aggressiveRer = 0.5 * E_pq8;
    const aggressiveTotal = aggressiveEmbedding + aggressiveQ + BM25 + CARDS + aggressiveRer;
    const aggressiveCritical = aggressiveEmbedding + aggressiveQ + CARDS + aggressiveRer;
    const aggressiveReplicated = aggressiveTotal + (replicationFactor - 1) * aggressiveCritical;
    const aggressiveFits = aggressiveTotal <= targetBytes;

    // Conservative plan: float16 precision, full hydration
    const conservativeEmbedding = E_float16;
    const conservativeQ = conservativeEmbedding * qdrantMultiplier;
    const conservativeRer = 0.5 * conservativeEmbedding;
    const conservativeHydration = hydrationPct * R;
    const conservativeTotal = conservativeEmbedding + conservativeQ + conservativeHydration + BM25 + CARDS + conservativeRer;
    const conservativeCritical = conservativeEmbedding + conservativeQ + conservativeHydration + CARDS + conservativeRer;
    const conservativeReplicated = conservativeTotal + (replicationFactor - 1) * conservativeCritical;
    const conservativeFits = conservativeTotal <= targetBytes;

    // Status message
    let statusMessage = '';
    let statusType: 'success' | 'warning' | 'error' = 'success';

    if (aggressiveFits && conservativeFits) {
      statusType = 'success';
      statusMessage = `✓ Both configurations fit within your ${formatBytes(targetBytes)} limit`;
    } else if (aggressiveFits) {
      statusType = 'warning';
      statusMessage = `⚠ Only Minimal config fits. Low Latency config needs ${formatBytes(conservativeTotal - targetBytes)} more storage.`;
    } else {
      statusType = 'warning';
      statusMessage = `⚠ Both exceed limit. Minimal needs ${formatBytes(aggressiveTotal - targetBytes)} more. Consider larger chunks or stronger compression.`;
    }

    setResults({
      chunks: N,
      baseStorage: R,
      precisions,
      aggressivePlan: {
        name: 'Minimal (No Hydration)',
        description: [
          'Product Quantized vectors',
          'Qdrant index',
          'BM25 search',
          'Cards/metadata',
          'Reranker cache',
          'Excludes: Raw data (fetched on-demand)',
        ],
        total: aggressiveTotal,
        replicated: aggressiveReplicated,
        fits: aggressiveFits,
      },
      conservativePlan: {
        name: 'Low Latency (Full Cache)',
        description: [
          'float16 vectors',
          'Qdrant index',
          'BM25 search',
          'Cards/metadata',
          'Reranker cache',
          `Data in RAM (${Math.round(hydrationPct * 100)}% hydration)`,
        ],
        total: conservativeTotal,
        replicated: conservativeReplicated,
        fits: conservativeFits,
      },
      statusMessage,
      statusType,
    });
  }, [inputs, calculator1Inputs]);

  // Auto-calculate on input changes
  useEffect(() => {
    calculate();
  }, [calculate]);

  // Update individual input fields
  const updateInput = useCallback(<K extends keyof Calculator2Inputs>(
    key: K,
    value: Calculator2Inputs[K]
  ) => {
    setInputs((prev) => ({ ...prev, [key]: value }));
  }, []);

  return {
    inputs,
    results,
    updateInput,
    calculate,
  };
}
