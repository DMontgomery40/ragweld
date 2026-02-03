import type { ActiveSources, ChunkMatch, RecallPlan } from '@/types/generated';

type StatusBarProps = {
  sources: ActiveSources;
  matches: ChunkMatch[];
  latencyMs: number | null;
  recallPlan: RecallPlan | null;
  showRecallGateDecision: boolean;
};

function formatCorpusLabel(corpusId: string): string {
  if (corpusId === 'recall_default') return 'Recall';
  return corpusId;
}

function recallIntensityBadge(intensity: string): string {
  switch (intensity) {
    case 'skip':
      return '⚡';
    case 'light':
      return '💡';
    case 'deep':
      return '🔎';
    case 'standard':
    default:
      return '🔍';
  }
}

export function StatusBar(props: StatusBarProps) {
  const { matches, latencyMs } = props;

  const counts = new Map<string, number>();
  for (const match of matches) {
    const rawCorpusId = match.metadata?.corpus_id;
    const corpusId =
      typeof rawCorpusId === 'string' && rawCorpusId.trim().length > 0 ? rawCorpusId : 'unknown';
    counts.set(corpusId, (counts.get(corpusId) ?? 0) + 1);
  }

  const recallSelected = (props.sources.corpus_ids ?? []).includes('recall_default');
  const recallCount = counts.get('recall_default') ?? 0;

  const parts: string[] = [];

  if (recallSelected && props.showRecallGateDecision) {
    const intensity = props.recallPlan?.intensity;
    if (typeof intensity === 'string' && intensity.length > 0) {
      const badge = recallIntensityBadge(intensity);
      if (intensity === 'skip') {
        parts.push(`Recall: ${badge}skip`);
      } else {
        parts.push(`Recall: ${badge}${intensity} ${recallCount} matches`);
      }
    }
  }

  const orderedCorpusIds = Array.from(counts.keys())
    .filter((cid) => !(props.showRecallGateDecision && recallSelected && cid === 'recall_default'))
    .sort((a, b) => {
      if (a === 'recall_default' && b !== 'recall_default') return -1;
      if (a !== 'recall_default' && b === 'recall_default') return 1;
      return a.localeCompare(b);
    });

  for (const corpusId of orderedCorpusIds) {
    const label = formatCorpusLabel(corpusId);
    const count = counts.get(corpusId) ?? 0;
    parts.push(`${label}: ${count}`);
  }

  if (latencyMs !== null) {
    parts.push(`${Math.round(latencyMs)}ms`);
  }

  const text = parts.join(' | ');

  return (
    <div
      data-testid="chat-status-bar"
      aria-label="Chat status"
      title={text}
      style={{
        padding: '6px 10px',
        borderTop: '1px solid var(--line)',
        background: 'var(--bg-elev1)',
        fontSize: '11px',
        color: 'var(--fg-muted)',
        whiteSpace: 'nowrap',
        overflow: 'hidden',
        textOverflow: 'ellipsis',
      }}
    >
      {text}
    </div>
  );
}
