import type { ActiveSources, Corpus, RecallIntensity } from '@/types/generated';
import { useEffect, useRef, useState } from 'react';
import { TooltipIcon } from '@/components/ui/TooltipIcon';
import { useRepoStore } from '@/stores/useRepoStore';

type SourceDropdownProps = {
  value: ActiveSources;
  onChange: (next: ActiveSources) => void;
  corpora: Corpus[];
  includeVector: boolean;
  includeSparse: boolean;
  includeGraph: boolean;
  onIncludeVectorChange: (v: boolean) => void;
  onIncludeSparseChange: (v: boolean) => void;
  onIncludeGraphChange: (v: boolean) => void;
  recallIntensity: RecallIntensity | null;
  onRecallIntensityChange: (v: RecallIntensity | null) => void;
  webEnabled: boolean;
  onWebEnabledChange: (v: boolean) => void;
  onCleanupUnindexed?: () => void | Promise<void>;
};

const RECALL_CORPUS_ID = 'recall_default' as const;

function dedupePreserveOrder(items: string[]): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const item of items) {
    if (seen.has(item)) continue;
    seen.add(item);
    out.push(item);
  }
  return out;
}

function toggleInOrderedSet(items: string[], id: string): string[] {
  const has = items.includes(id);
  const next = has ? items.filter((x) => x !== id) : [...items, id];
  return dedupePreserveOrder(next);
}

export function SourceDropdown(props: SourceDropdownProps) {
  const loadRepos = useRepoStore((state) => state.loadRepos);
  const registryError = useRepoStore((state) => state.error);
  const corpusIds = props.value.corpus_ids ?? [];
  const [confirmCleanup, setConfirmCleanup] = useState(false);
  const detailsRef = useRef<HTMLDetailsElement | null>(null);
  const summaryRef = useRef<HTMLElement | null>(null);
  const [cleanupRunning, setCleanupRunning] = useState(false);

  const isChecked = (id: string) => corpusIds.includes(id);

  const handleCorpusToggle = (id: string) => {
    const nextIds = toggleInOrderedSet(corpusIds, id);
    props.onChange({ ...props.value, corpus_ids: nextIds });
  };

  const availableCorpora = props.corpora.filter((c) => c.corpus_id !== RECALL_CORPUS_ID);
  const unindexedCount = availableCorpora.filter((c) => !c.last_indexed).length;

  // Recall is a source, not a corpus. Counting it as one made "2 selected" read for a single
  // corpus plus Recall, and would have said "1 selected" with no corpus at all (M-96/B-20).
  const realCorpusCount = corpusIds.filter((id) => id && id !== RECALL_CORPUS_ID).length;
  const recallSelected = corpusIds.includes(RECALL_CORPUS_ID);
  const summaryParts = [
    realCorpusCount > 0 ? `${realCorpusCount} ${realCorpusCount === 1 ? 'corpus' : 'corpora'}` : null,
    recallSelected ? 'Recall' : null,
    props.webEnabled ? 'Web' : null,
  ].filter(Boolean);
  const summaryLabel = summaryParts.length > 0 ? summaryParts.join(' + ') : 'None';

  // A native <details> dismisses on neither Escape nor an outside click, so this popover
  // survived both - and survived opening History and New chat, which is how the drive ended
  // up with three popovers stacked open at once (M-161/B-28).
  //
  // Escape returns focus to the control that opened it, so a keyboard operator is never
  // left inside a widget they just dismissed. A pointer dismissal does not steal focus:
  // the operator is already on their way somewhere else, and moving focus back would fight
  // the control they just pressed.
  useEffect(() => {
    const closeIfOpen = (restoreFocus: boolean): void => {
      const details = detailsRef.current;
      if (!details || !details.open) return;
      details.open = false;
      if (restoreFocus) summaryRef.current?.focus();
    };

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return;
      closeIfOpen(true);
    };
    // pointerdown, not click: History and New chat open on their own press, so waiting for
    // the click would leave both popovers on screen for the length of the gesture.
    const onPointerDown = (event: PointerEvent) => {
      const details = detailsRef.current;
      if (!details || !details.open) return;
      const target = event.target as Node | null;
      if (target && details.contains(target)) return;
      closeIfOpen(false);
    };

    document.addEventListener('keydown', onKeyDown);
    document.addEventListener('pointerdown', onPointerDown, true);
    return () => {
      document.removeEventListener('keydown', onKeyDown);
      document.removeEventListener('pointerdown', onPointerDown, true);
    };
  }, []);

  useEffect(() => {
    if (!confirmCleanup) return;
    const t = window.setTimeout(() => setConfirmCleanup(false), 4000);
    return () => window.clearTimeout(t);
  }, [confirmCleanup]);

  const handleCleanupClick = async () => {
    if (!props.onCleanupUnindexed) return;
    if (cleanupRunning) return;
    if (!confirmCleanup) {
      setConfirmCleanup(true);
      return;
    }
    setConfirmCleanup(false);
    setCleanupRunning(true);
    try {
      await props.onCleanupUnindexed();
    } finally {
      setCleanupRunning(false);
    }
  };

  return (
    <details
      ref={detailsRef}
      data-testid="source-dropdown"
      onToggle={(event) => {
        if (event.currentTarget.open) void loadRepos({ force: true });
      }}
      style={{
        position: 'relative',
        display: 'inline-block',
      }}
    >
      <summary
        ref={summaryRef}
        data-testid="source-dropdown-trigger"
        style={{
          listStyle: 'none',
          cursor: 'pointer',
          userSelect: 'none',
          padding: '8px 10px',
          borderRadius: '8px',
          border: '1px solid var(--line)',
          background: 'var(--bg-elev1)',
          color: 'var(--fg)',
          fontSize: '13px',
          display: 'flex',
          alignItems: 'center',
          gap: '10px',
          minWidth: '180px',
        }}
      >
        <span style={{ fontWeight: 600 }}>Sources</span>
        <span style={{ color: 'var(--fg-muted)', marginLeft: 'auto' }}>{summaryLabel}</span>
      </summary>

      <div
        style={{
          marginTop: '8px',
          padding: '12px',
          borderRadius: '12px',
          border: '1px solid var(--line)',
          background: 'var(--bg-elev1)',
          boxShadow: '0 10px 25px rgba(0,0,0,0.35)',
          minWidth: '320px',
          zIndex: 50,
        }}
      >
        <div style={{ fontSize: '12px', color: 'var(--fg-muted)', marginBottom: '8px' }}>
          Live sources
        </div>

        <label
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '10px',
            padding: '9px 10px',
            marginBottom: '12px',
            borderRadius: '9px',
            border: props.webEnabled ? '1px solid var(--accent)' : '1px solid var(--line)',
            background: props.webEnabled ? 'rgba(99, 179, 237, 0.08)' : 'transparent',
          }}
        >
          <input
            data-testid="source-web"
            type="checkbox"
            checked={props.webEnabled}
            onChange={(event) => props.onWebEnabledChange(event.target.checked)}
          />
          <span style={{ flex: 1 }}>
            <strong>Web</strong>
            <span style={{ display: 'block', color: 'var(--fg-muted)', fontSize: '11px', marginTop: '2px' }}>
              Search current public information when the model needs it
            </span>
          </span>
        </label>

        <div style={{ fontSize: '12px', color: 'var(--fg-muted)', marginBottom: '8px' }}>
          Corpus retrieval legs
        </div>

        <div style={{ display: 'flex', gap: '14px', flexWrap: 'wrap', marginBottom: '14px' }}>
          <label style={{ display: 'inline-flex', alignItems: 'center', gap: '8px' }}>
            <input
              data-testid="source-toggle-vector"
              type="checkbox"
              checked={props.includeVector}
              onChange={(e) => props.onIncludeVectorChange(e.target.checked)}
            />
            <span>Vector</span>
          </label>

          <label style={{ display: 'inline-flex', alignItems: 'center', gap: '8px' }}>
            <input
              data-testid="source-toggle-sparse"
              type="checkbox"
              checked={props.includeSparse}
              onChange={(e) => props.onIncludeSparseChange(e.target.checked)}
            />
            <span>Sparse</span>
          </label>

          <label style={{ display: 'inline-flex', alignItems: 'center', gap: '8px' }}>
            <input
              data-testid="source-toggle-graph"
              type="checkbox"
              checked={props.includeGraph}
              onChange={(e) => props.onIncludeGraphChange(e.target.checked)}
            />
            <span>Graph</span>
          </label>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '10px', marginBottom: '8px' }}>
          <div style={{ fontSize: '12px', color: 'var(--fg-muted)' }}>Corpora</div>
          {registryError && (
            <div role="alert" style={{ fontSize: '12px', color: 'var(--err)' }}>
              Corpus list refresh failed: {registryError}
            </div>
          )}

          {props.onCleanupUnindexed && unindexedCount > 0 && (
            <button
              type="button"
              data-testid="cleanup-unindexed-corpora"
              onClick={() => void handleCleanupClick()}
              disabled={cleanupRunning}
              style={{
                padding: '6px 10px',
                borderRadius: '8px',
                border: '1px solid var(--err)',
                background: confirmCleanup ? 'var(--err)' : 'transparent',
                color: confirmCleanup ? 'white' : 'var(--err)',
                fontSize: '11px',
                fontWeight: 800,
                cursor: cleanupRunning ? 'not-allowed' : 'pointer',
                opacity: cleanupRunning ? 0.65 : 1,
              }}
              title={
                confirmCleanup
                  ? 'Click again to confirm deleting all NOT INDEXED corpora'
                  : `Delete all NOT INDEXED corpora (${unindexedCount})`
              }
            >
              {confirmCleanup ? 'CONFIRM DELETE' : `DELETE NOT INDEXED (${unindexedCount})`}
            </button>
          )}
        </div>

        <div style={{ display: 'grid', gap: '10px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <label style={{ display: 'flex', alignItems: 'center', gap: '10px', flex: 1 }}>
              <input
                data-testid="source-recall"
                type="checkbox"
                checked={isChecked(RECALL_CORPUS_ID)}
                onChange={() => handleCorpusToggle(RECALL_CORPUS_ID)}
              />
              <span>🧠 Recall</span>
            </label>

            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <TooltipIcon name="chat_recall_intensity" />
              <select
                data-testid="recall-intensity-select"
                value={(props.recallIntensity ?? 'auto') as string}
                disabled={!isChecked(RECALL_CORPUS_ID)}
                onChange={(e) => {
                  const v = e.target.value;
                  props.onRecallIntensityChange(v === 'auto' ? null : (v as RecallIntensity));
                }}
                style={{
                  padding: '6px 8px',
                  background: 'var(--input-bg)',
                  border: '1px solid var(--line)',
                  borderRadius: '8px',
                  color: 'var(--fg)',
                  fontSize: '12px',
                }}
                aria-label="Recall intensity override"
              >
                <option value="auto">auto</option>
                <option value="skip">skip this message</option>
                <option value="light">light (sparse-only)</option>
                <option value="standard">standard</option>
                <option value="deep">deep</option>
              </select>
            </div>
          </div>

          {availableCorpora.map((corpus) => (
            <label
              key={corpus.corpus_id}
              style={{ display: 'flex', alignItems: 'center', gap: '10px' }}
            >
              <input
                type="checkbox"
                checked={isChecked(corpus.corpus_id)}
                data-testid={`source-corpus-${corpus.corpus_id}`}
                onChange={() => handleCorpusToggle(corpus.corpus_id)}
              />
              <span style={{ flex: 1 }}>{corpus.name}</span>
              <span
                style={{
                  fontSize: '11px',
                  color: corpus.last_indexed ? 'var(--ok)' : 'var(--warn)',
                  fontWeight: 700,
                  opacity: 0.9,
                }}
                title={
                  corpus.last_indexed
                    ? `Indexed: ${corpus.last_indexed}`
                    : 'Not indexed yet. Go to RAG → Indexing to build an index.'
                }
              >
                {corpus.last_indexed ? 'indexed' : 'not indexed'}
              </span>
            </label>
          ))}
        </div>
      </div>
    </details>
  );
}
