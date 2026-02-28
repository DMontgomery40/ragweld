import { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useActiveRepo } from '@/stores';
import { syntheticService } from '@/services/SyntheticService';
import type { SyntheticRunMeta, SyntheticRunStartRequest } from '@/types/generated';

type SyntheticContext =
  | 'indexing'
  | 'data-quality'
  | 'retrieval'
  | 'graph'
  | 'reranker-config'
  | 'learning-ranker'
  | 'learning-agent';

type ActionPreset = {
  label: string;
  recipe: NonNullable<SyntheticRunStartRequest['recipe']>;
};

const ACTIONS: Record<SyntheticContext, ActionPreset[]> = {
  indexing: [{ label: 'Starter Pack', recipe: 'full_stack' }],
  'data-quality': [
    { label: 'Semantic Summaries', recipe: 'semantic_cards' },
    { label: 'Corpus Keywords', recipe: 'keywords' },
  ],
  retrieval: [
    { label: 'Retrieval Eval Set', recipe: 'eval_dataset' },
    { label: 'Autotune Retrieval', recipe: 'autotune_retrieval' },
  ],
  graph: [{ label: 'Graph Eval Set', recipe: 'eval_dataset' }],
  'reranker-config': [{ label: 'Synthetic Triplets', recipe: 'triplets' }],
  'learning-ranker': [{ label: 'Synthetic Triplets', recipe: 'triplets' }],
  'learning-agent': [{ label: 'Agent Eval Set', recipe: 'eval_dataset' }],
};

export function SyntheticCallout({ context }: { context: SyntheticContext }) {
  const activeRepo = useActiveRepo();
  const navigate = useNavigate();
  const [latest, setLatest] = useState<SyntheticRunMeta | null>(null);
  const [loading, setLoading] = useState(false);

  const actions = useMemo(() => ACTIONS[context] || [], [context]);

  const loadLatest = useCallback(async () => {
    const corpusId = String(activeRepo || '').trim();
    if (!corpusId) {
      setLatest(null);
      return;
    }
    setLoading(true);
    try {
      const resp = await syntheticService.listRuns(corpusId, 1);
      setLatest((resp.runs || [])[0] || null);
    } catch {
      setLatest(null);
    } finally {
      setLoading(false);
    }
  }, [activeRepo]);

  useEffect(() => {
    void loadLatest();
  }, [loadLatest]);

  const openLab = useCallback(
    (preset?: ActionPreset) => {
      const qs = new URLSearchParams();
      qs.set('subtab', 'synthetic');
      qs.set('synthetic_context', context);
      if (preset?.recipe) {
        qs.set('synthetic_recipe', String(preset.recipe));
      }
      qs.set('synthetic_autorun', '0');
      navigate({ pathname: '/rag', search: `?${qs.toString()}` });
    },
    [context, navigate]
  );

  const status = loading ? 'loading' : latest?.status || 'idle';

  return (
    <div className="studio-callout" style={{ marginBottom: 12 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
        <div>
          <strong>Synthetic Lab</strong>{' '}
          <span className="studio-mono" style={{ opacity: 0.8 }}>
            status={status}
          </span>
          {latest?.run_id ? (
            <span className="studio-mono" style={{ marginLeft: 8, opacity: 0.8 }}>
              run={latest.run_id}
            </span>
          ) : null}
        </div>
        <button className="small-button" onClick={() => openLab()}>
          Open Synthetic Lab
        </button>
      </div>

      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginTop: 8 }}>
        {actions.map((action) => (
          <button
            key={action.label}
            className="small-button"
            disabled={!String(activeRepo || '').trim()}
            onClick={() => openLab(action)}
          >
            {action.label}
          </button>
        ))}
      </div>
    </div>
  );
}
