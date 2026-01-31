import { useState, useEffect, useCallback } from 'react';

const EVAL_HISTORY_KEY = 'agro_eval_history';

export interface EvalHistoryEntry {
  timestamp: string;
  config: string;
  reranker_mode: string;
  reranker_cloud_provider?: string;
  top1: number;
  topk: number;
  total: number;
  secs: number;
  final_k: number;
  use_multi: boolean;
}

export function useEvalHistory() {
  const [runs, setRuns] = useState<EvalHistoryEntry[]>([]);
  const [selectedRunIndex, setSelectedRunIndex] = useState<number | null>(null);

  const loadHistory = useCallback(() => {
    try {
      const raw = localStorage.getItem(EVAL_HISTORY_KEY);
      const parsed = raw ? JSON.parse(raw) : [];
      setRuns(Array.isArray(parsed) ? parsed : []);
    } catch {
      setRuns([]);
    }
  }, []);

  useEffect(() => {
    loadHistory();
  }, [loadHistory]);

  const selectedRun = selectedRunIndex !== null ? runs[selectedRunIndex] : null;

  const selectRun = useCallback((index: number | null) => {
    setSelectedRunIndex(index);
  }, []);

  const clearHistory = useCallback(() => {
    localStorage.removeItem(EVAL_HISTORY_KEY);
    setRuns([]);
    setSelectedRunIndex(null);
  }, []);

  const deleteRun = useCallback((index: number) => {
    const updated = runs.filter((_, i) => i !== index);
    localStorage.setItem(EVAL_HISTORY_KEY, JSON.stringify(updated));
    setRuns(updated);
    if (selectedRunIndex === index) setSelectedRunIndex(null);
  }, [runs, selectedRunIndex]);

  const getDeltaVsPrevious = useCallback((index: number): { top1: number; topk: number; delta: number; improved: boolean } | null => {
    if (index >= runs.length - 1) return null;
    const current = runs[index];
    const previous = runs[index + 1];
    const top1Delta = current.top1 - previous.top1;
    const topkDelta = current.topk - previous.topk;
    // Use average of both deltas as overall delta
    const delta = (top1Delta + topkDelta) / 2;
    return {
      top1: top1Delta,
      topk: topkDelta,
      delta,
      improved: delta >= 0
    };
  }, [runs]);

  const exportHistory = useCallback(() => {
    const blob = new Blob([JSON.stringify(runs, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `eval-history-${new Date().toISOString().slice(0, 10)}.json`;
    a.click();
    URL.revokeObjectURL(url);
  }, [runs]);

  return {
    runs,
    selectedRun,
    selectedRunIndex,
    selectRun,
    clearHistory,
    deleteRun,
    getDeltaVsPrevious,
    exportHistory
  };
}
