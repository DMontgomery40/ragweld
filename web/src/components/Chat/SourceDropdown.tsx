import type { ActiveSources, Corpus, RecallIntensity } from '@/types/generated';

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
  const corpusIds = props.value.corpus_ids ?? [];

  const isChecked = (id: string) => corpusIds.includes(id);

  const handleCorpusToggle = (id: string) => {
    const nextIds = toggleInOrderedSet(corpusIds, id);
    props.onChange({ ...props.value, corpus_ids: nextIds });
  };

  const availableCorpora = props.corpora.filter((c) => c.corpus_id !== RECALL_CORPUS_ID);

  const selectedCount = corpusIds.length;
  const summaryLabel = selectedCount === 0 ? 'None' : `${selectedCount} selected`;

  return (
    <details
      data-testid="source-dropdown"
      style={{
        position: 'relative',
        display: 'inline-block',
      }}
    >
      <summary
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
          Retrieval legs
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

        <div style={{ fontSize: '12px', color: 'var(--fg-muted)', marginBottom: '8px' }}>
          Corpora
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

          {availableCorpora.map((corpus) => (
            <label
              key={corpus.corpus_id}
              style={{ display: 'flex', alignItems: 'center', gap: '10px' }}
            >
              <input
                type="checkbox"
                checked={isChecked(corpus.corpus_id)}
                onChange={() => handleCorpusToggle(corpus.corpus_id)}
              />
              <span>{corpus.name}</span>
            </label>
          ))}
        </div>
      </div>
    </details>
  );
}
