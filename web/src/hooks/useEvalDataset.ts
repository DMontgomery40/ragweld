/**
 * useEvalDataset - Hook for managing evaluation dataset entries
 *
 * Uses types from generated.ts (Pydantic-first architecture):
 * - EvalDatasetItem (the individual dataset entries)
 *
 * USAGE:
 *   const {
 *     entries,
 *     loading,
 *     error,
 *     addEntry,
 *     updateEntry,
 *     deleteEntry,
 *     refreshEntries
 *   } = useEvalDataset();
 */

import { useState, useCallback, useEffect } from 'react';
import type { EvalDatasetItem } from '@/types/generated';
import { useRepoStore } from '@/stores';
import { apiUrl } from '@/api/client';

// API endpoint for evaluation datasets (file-backed per corpus)
const DATASET_API_BASE = '/api/dataset';

interface DatasetState {
  entries: EvalDatasetItem[];
  loading: boolean;
  error: string | null;
  saving: boolean;
}

// Input type for creating new entries (without generated fields)
interface NewDatasetEntry {
  question: string;
  expected_paths: string[];
  expected_answer?: string;
  tags?: string[];
}

export function useEvalDataset() {
  const { activeRepo } = useRepoStore();
  const [state, setState] = useState<DatasetState>({
    entries: [],
    loading: false,
    error: null,
    saving: false,
  });

  /**
   * Fetch all entries for the current dataset
   */
  const refreshEntries = useCallback(async () => {
    if (!activeRepo) {
      setState((prev) => ({ ...prev, entries: [], error: null }));
      return;
    }

    setState((prev) => ({ ...prev, loading: true, error: null }));

    try {
      const url = apiUrl(`${DATASET_API_BASE}?corpus_id=${encodeURIComponent(activeRepo)}`);

      const response = await fetch(url);

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        throw new Error(errorData.detail || `Failed to load entries: ${response.status}`);
      }

      const entries: EvalDatasetItem[] = await response.json();

      setState((prev) => ({
        ...prev,
        entries,
        loading: false,
      }));
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to load entries';
      setState((prev) => ({
        ...prev,
        loading: false,
        error: message,
      }));
    }
  }, [activeRepo]);

  // Load entries when repo changes
  useEffect(() => {
    refreshEntries();
  }, [refreshEntries]);

  /**
   * Add a new entry to the dataset
   */
  const addEntry = useCallback(
    async (entry: NewDatasetEntry): Promise<EvalDatasetItem | null> => {
      if (!activeRepo) {
        setState((prev) => ({ ...prev, error: 'No repository selected' }));
        return null;
      }

      setState((prev) => ({ ...prev, saving: true, error: null }));

      try {
        const url = apiUrl(`${DATASET_API_BASE}?corpus_id=${encodeURIComponent(activeRepo)}`);

        const response = await fetch(url, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(entry),
        });

        if (!response.ok) {
          const errorData = await response.json().catch(() => ({}));
          throw new Error(errorData.detail || `Failed to add entry: ${response.status}`);
        }

        const newEntry: EvalDatasetItem = await response.json();

        setState((prev) => ({
          ...prev,
          entries: [...prev.entries, newEntry],
          saving: false,
        }));

        return newEntry;
      } catch (err) {
        const message = err instanceof Error ? err.message : 'Failed to add entry';
        setState((prev) => ({
          ...prev,
          saving: false,
          error: message,
        }));
        return null;
      }
    },
    [activeRepo]
  );

  /**
   * Update an existing entry
   */
  const updateEntry = useCallback(
    async (
      entryId: string,
      updates: Partial<NewDatasetEntry>
    ): Promise<EvalDatasetItem | null> => {
      if (!activeRepo) {
        setState((prev) => ({ ...prev, error: 'No repository selected' }));
        return null;
      }

      setState((prev) => ({ ...prev, saving: true, error: null }));

      try {
        const existing = state.entries.find((e) => e.entry_id === entryId);
        if (!existing) {
          throw new Error(`Entry not found: ${entryId}`);
        }

        const payload: EvalDatasetItem = {
          question: updates.question ?? existing.question,
          expected_paths: updates.expected_paths ?? existing.expected_paths,
          expected_answer: updates.expected_answer ?? existing.expected_answer ?? null,
          tags: updates.tags ?? existing.tags ?? [],
        };

        const url = apiUrl(`${DATASET_API_BASE}/${encodeURIComponent(entryId)}?corpus_id=${encodeURIComponent(activeRepo)}`);

        const response = await fetch(url, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });

        if (!response.ok) {
          const errorData = await response.json().catch(() => ({}));
          throw new Error(errorData.detail || `Failed to update entry: ${response.status}`);
        }

        const updatedEntry: EvalDatasetItem = await response.json();

        setState((prev) => ({
          ...prev,
          entries: prev.entries.map((e) =>
            e.entry_id === entryId ? updatedEntry : e
          ),
          saving: false,
        }));

        return updatedEntry;
      } catch (err) {
        const message = err instanceof Error ? err.message : 'Failed to update entry';
        setState((prev) => ({
          ...prev,
          saving: false,
          error: message,
        }));
        return null;
      }
    },
    [activeRepo, state.entries]
  );

  /**
   * Delete an entry from the dataset
   */
  const deleteEntry = useCallback(
    async (entryId: string): Promise<boolean> => {
      if (!activeRepo) {
        setState((prev) => ({ ...prev, error: 'No repository selected' }));
        return false;
      }

      setState((prev) => ({ ...prev, saving: true, error: null }));

      try {
        const url = apiUrl(`${DATASET_API_BASE}/${encodeURIComponent(entryId)}?corpus_id=${encodeURIComponent(activeRepo)}`);

        const response = await fetch(url, {
          method: 'DELETE',
        });

        if (!response.ok) {
          const errorData = await response.json().catch(() => ({}));
          throw new Error(errorData.detail || `Failed to delete entry: ${response.status}`);
        }

        setState((prev) => ({
          ...prev,
          entries: prev.entries.filter((e) => e.entry_id !== entryId),
          saving: false,
        }));

        return true;
      } catch (err) {
        const message = err instanceof Error ? err.message : 'Failed to delete entry';
        setState((prev) => ({
          ...prev,
          saving: false,
          error: message,
        }));
        return false;
      }
    },
    [activeRepo, state.entries]
  );

  /**
   * Filter entries by tags
   */
  const getEntriesByTags = useCallback(
    (tags: string[]): EvalDatasetItem[] => {
      if (tags.length === 0) return state.entries;
      return state.entries.filter((entry) =>
        tags.some((tag) => entry.tags?.includes(tag))
      );
    },
    [state.entries]
  );

  /**
   * Get all unique tags from entries
   */
  const getAllTags = useCallback((): string[] => {
    const tagSet = new Set<string>();
    state.entries.forEach((entry) => {
      entry.tags?.forEach((tag) => tagSet.add(tag));
    });
    return Array.from(tagSet).sort();
  }, [state.entries]);

  /**
   * Clear error state
   */
  const clearError = useCallback(() => {
    setState((prev) => ({ ...prev, error: null }));
  }, []);

  return {
    // State
    entries: state.entries,
    loading: state.loading,
    error: state.error,
    saving: state.saving,

    // CRUD operations
    addEntry,
    updateEntry,
    deleteEntry,
    refreshEntries,

    // Helpers
    getEntriesByTags,
    getAllTags,
    clearError,

    // Derived state
    entryCount: state.entries.length,
    isEmpty: state.entries.length === 0,
  };
}

export default useEvalDataset;
