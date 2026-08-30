import { create } from 'zustand';
import { configApi } from '@/api/config';
import type { TriBridConfig } from '@/types/generated';
import { formatSaveError, type IndexContractConflict } from '@/utils/saveErrorMessage';
import { indexInvalidatingChanges } from '@/utils/configDiff';

interface ConfigStore {
  config: TriBridConfig | null;
  /** Last server-acknowledged config. `config !== persisted` means unsaved local edits. */
  persisted: TriBridConfig | null;
  loading: boolean;
  error: string | null;
  /**
   * Field-level detail from the last rejected config save, keyed by full dotted TriBridConfig
   * path (e.g. "enrichment.chunk_summaries_max") -- `NumberField`'s `configPath` prop reads this
   * directly. Replaced wholesale on each Apply (a fresh attempt supersedes stale errors) and
   * cleared on a successful save.
   */
  fieldErrors: Record<string, string>;
  /**
   * Set when a save was refused (HTTP 409) because the change would invalidate the stored index
   * contract (`_enforce_index_contract_lock`, server/api/config.py). The footer reads this to
   * offer a reload-and-re-index affordance instead of a bare error string (M-20). Cleared on any
   * successful load or save, and as soon as the operator edits again.
   */
  saveConflict: IndexContractConflict | null;
  saving: boolean;
  // Actions
  loadConfig: () => Promise<void>;
  saveConfig: (config: TriBridConfig) => Promise<void>;
  /**
   * Stage a field edit LOCALLY, with no network write. The working `config` diverges from
   * `persisted` (the footer shows the dirty count) and nothing reaches the server until "Apply"
   * PUTs the whole document. This is the ONE commit model for every config surface: selecting a
   * chunking strategy, toggling a boolean, dragging a slider, applying a model, saving a field
   * all stage, so an edit is never a silent immediate PATCH the operator cannot see, undo, or
   * gate (M-08). The merge mirrors the server's `_deep_merge_dicts` so a nested edit keeps its
   * siblings.
   */
  stageSection: (section: keyof TriBridConfig, updates: Record<string, unknown>) => void;
  /**
   * Stage a WHOLE-section replacement (the Raw Section Editor): `config[section]` becomes `value`
   * exactly, no merge, so a key the operator deleted from the raw JSON is actually dropped. Still
   * local-only until Apply.
   */
  stageSectionReplace: (section: keyof TriBridConfig, value: unknown) => void;
  /**
   * Persist staged edits before a server-side action reads scoped config (an index run, a Paths
   * save). If the staged edits touch a section that invalidates the stored index
   * (chunking/embedding/tokenization), this THROWS instead of committing them silently — the
   * operator must Apply (which confirms the re-index) or discard first (M-08/P2-1). Non-index
   * staged edits are PUT through the safe path so the action sees them.
   */
  flushPendingPatches: () => Promise<void>;
  resetConfig: () => Promise<void>;

  reset: () => void;
}

type PatchObject = Record<string, unknown>;

const isPatchObject = (value: unknown): value is PatchObject =>
  typeof value === 'object' && value !== null && !Array.isArray(value);

/**
 * Merge a staged patch into a config section exactly the way the server does
 * (`_deep_merge_dicts`, server/api/config.py): recurse into nested objects, replace arrays and
 * scalars wholesale. A shallow spread is wrong for any nested config group
 * (`indexing.figures`, `chat.recall`, `chat.multimodal`): `useConfigField('indexing.figures.enabled')`
 * emits `{ figures: { enabled: true } }`, and spreading that over the section would drop every
 * sibling key of `figures`.
 */
const deepMergePatch = (base: PatchObject, updates: PatchObject): PatchObject => {
  const merged: PatchObject = { ...base };
  for (const key of Object.keys(updates)) {
    if (key === '__proto__') continue;
    const current = merged[key];
    const next = updates[key];
    merged[key] = isPatchObject(current) && isPatchObject(next) ? deepMergePatch(current, next) : next;
  }
  return merged;
};

export const useConfigStore = create<ConfigStore>((set) => {
  // One GET /api/config per corpus in flight at a time. Several hooks call `loadConfig` on the
  // same mount (app init, `useConfig`'s mount effect, the corpus-changed listener) and each one
  // used to issue its own request: a single dashboard load spent four round trips fetching the
  // identical document (M-129). This shares the request; it does not cache the answer.
  const inFlightLoadByCorpus: Record<string, Promise<void>> = {};

  const getActiveCorpusId = (): string => {
    try {
      const u = new URL(window.location.href);
      return (
        u.searchParams.get('corpus') ||
        u.searchParams.get('repo') ||
        localStorage.getItem('tribrid_active_corpus') ||
        localStorage.getItem('tribrid_active_repo') ||
        ''
      );
    } catch {
      return (
        localStorage.getItem('tribrid_active_corpus') ||
        localStorage.getItem('tribrid_active_repo') ||
        ''
      );
    }
  };

  const stageSection = (section: keyof TriBridConfig, updates: Record<string, unknown>) => {
    const sectionKey = String(section);
    // Local stage only: merge into the working `config` and leave `persisted` alone, so the edit
    // shows as dirty and nothing is written until Apply. No pending patch, no timer, no request.
    set((state) => {
      const cur = state.config as any;
      if (!cur) return {};
      const curSection = (cur as any)[sectionKey] || {};
      const nextSection = deepMergePatch(curSection as PatchObject, updates);
      return {
        config: { ...cur, [sectionKey]: nextSection } as TriBridConfig,
        // Editing again clears a stale save error / conflict banner.
        error: null,
        saveConflict: null,
      };
    });
  };

  const stageSectionReplace = (section: keyof TriBridConfig, value: unknown) => {
    const sectionKey = String(section);
    set((state) => {
      const cur = state.config as any;
      if (!cur) return {};
      return {
        config: { ...cur, [sectionKey]: value } as TriBridConfig,
        error: null,
        saveConflict: null,
      };
    });
  };

  /** The real load. `loadConfig` wraps it so concurrent callers share one request. */
  const loadConfigOnce = async (): Promise<void> => {
    // A load replaces both the working copy and the server snapshot: navigation and corpus
    // switches never read as an operator edit, and any unapplied staged edits for the old scope
    // are dropped (the staged-form contract — apply before you leave).
    set({ loading: true, error: null });
    try {
      const config = await configApi.load();
      set({ config, persisted: config, loading: false, error: null, fieldErrors: {}, saveConflict: null });
    } catch (error) {
      set({ loading: false, error: formatSaveError(error).message });
    }
  };

  return ({
  config: null,
  persisted: null,
  loading: false,
  error: null,
  fieldErrors: {},
  saveConflict: null,
  saving: false,

  loadConfig: async () => {
    const key = String(getActiveCorpusId() || '');
    const shared = inFlightLoadByCorpus[key];
    if (shared) return shared;

    const run = loadConfigOnce();
    inFlightLoadByCorpus[key] = run;
    try {
      await run;
    } finally {
      if (inFlightLoadByCorpus[key] === run) delete inFlightLoadByCorpus[key];
    }
  },

  saveConfig: async (config: TriBridConfig) => {
    set({ saving: true, error: null });
    try {
      const saved = await configApi.save(config);
      set({ config: saved, persisted: saved, saving: false, error: null, fieldErrors: {}, saveConflict: null });
    } catch (error) {
      // A whole-config PUT validates every section atomically, so a 422 attributes to fields
      // anywhere: replace the field-error map with what this failure named (M-20). A 409/network
      // failure carries no per-field detail, so the map clears.
      const presentation = formatSaveError(error);
      const message = presentation.message;
      set({
        saving: false,
        error: message,
        fieldErrors: Object.fromEntries(presentation.fieldErrors.map((fe) => [fe.path, fe.message])),
        // Any 409 (the structured index-contract lock, or a generic "changed elsewhere" conflict)
        // offers the reload-and-retry affordance; a generic 409 carries no changed legs.
        saveConflict: presentation.conflict ? presentation.contractConflict ?? { changedLegs: [] } : null,
      });
      throw new Error(message);
    }
  },

  stageSection,
  stageSectionReplace,
  flushPendingPatches: async () => {
    const { config, persisted } = useConfigStore.getState();
    if (!config || JSON.stringify(config) === JSON.stringify(persisted)) return;
    // An index-invalidating staged edit must never commit silently through a side-door flush
    // (Index Now, Paths save): block until the operator Applies (which confirms the re-index) or
    // discards it. Non-index staged edits are persisted so the pending action reads them.
    const invalidating = indexInvalidatingChanges(persisted, config);
    if (invalidating.length > 0) {
      throw new Error(
        `Staged changes to ${invalidating.join(', ')} change how the current index was built. ` +
          `Apply them with the "Apply changes" button (which confirms the re-index) or discard them ` +
          `before starting this action — an index-invalidating change is never committed silently.`
      );
    }
    await useConfigStore.getState().saveConfig(config);
  },

  resetConfig: async () => {
    set({ saving: true, error: null });
    try {
      const saved = await configApi.reset();
      set({ config: saved, persisted: saved, saving: false, error: null, fieldErrors: {}, saveConflict: null });
    } catch (error) {
      set({
        saving: false,
        error: formatSaveError(error).message,
      });
    }
  },

  reset: () =>
    set({
      config: null,
      persisted: null,
      loading: false,
      error: null,
      fieldErrors: {},
      saveConflict: null,
      saving: false,
    }),
});
});
