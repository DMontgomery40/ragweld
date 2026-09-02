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
  | 'reranker'
  | 'learning-reranker'
  | 'learning-agent';

// These buttons were labelled like viewers ("Corpus Keywords", "Starter Pack") but every one
// of them LEAVES the page for Synthetic Lab with a recipe preselected -- Starter Pack for the
// most expensive recipe there is. The label now says it generates and where, and `title`
// carries the recipe the destination will arrive with.
type ActionPreset = {
  label: string;
  title: string;
  recipe: NonNullable<SyntheticRunStartRequest['recipe']>;
};

const ACTIONS: Record<SyntheticContext, ActionPreset[]> = {
  indexing: [
    {
      label: 'Preload a full-stack recipe in Synthetic Lab \u2192',
      title: 'Opens RAG \u203a Synthetic Lab with the full_stack recipe preselected. Nothing runs until you start it there.',
      recipe: 'full_stack',
    },
  ],
  'data-quality': [
    {
      label: 'Generate semantic summaries in Synthetic Lab \u2192',
      title: 'Opens RAG \u203a Synthetic Lab with the semantic summaries recipe preselected. Nothing runs until you start it there.',
      recipe: 'semantic_cards',
    },
    {
      label: 'Generate keywords in Synthetic Lab \u2192',
      title: 'Opens RAG \u203a Synthetic Lab with the keywords recipe preselected. Nothing runs until you start it there.',
      recipe: 'keywords',
    },
  ],
  retrieval: [
    {
      label: 'Generate a retrieval eval set in Synthetic Lab \u2192',
      title: 'Opens RAG \u203a Synthetic Lab with the eval_dataset recipe preselected. Nothing runs until you start it there.',
      recipe: 'eval_dataset',
    },
    {
      label: 'Autotune retrieval in Synthetic Lab \u2192',
      title: 'Opens RAG \u203a Synthetic Lab with the autotune_retrieval recipe preselected. Nothing runs until you start it there.',
      recipe: 'autotune_retrieval',
    },
  ],
  graph: [
    {
      label: 'Generate a graph eval set in Synthetic Lab \u2192',
      title: 'Opens RAG \u203a Synthetic Lab with the eval_dataset recipe preselected. Nothing runs until you start it there.',
      recipe: 'eval_dataset',
    },
  ],
  reranker: [
    {
      label: 'Generate synthetic triplets in Synthetic Lab \u2192',
      title: 'Opens RAG \u203a Synthetic Lab with the triplets recipe preselected. Nothing runs until you start it there.',
      recipe: 'triplets',
    },
  ],
  'learning-reranker': [
    {
      label: 'Generate synthetic triplets in Synthetic Lab \u2192',
      title: 'Opens RAG \u203a Synthetic Lab with the triplets recipe preselected. Nothing runs until you start it there.',
      recipe: 'triplets',
    },
  ],
  'learning-agent': [
    {
      label: 'Generate an agent eval set in Synthetic Lab \u2192',
      title: 'Opens RAG \u203a Synthetic Lab with the eval_dataset recipe preselected. Nothing runs until you start it there.',
      recipe: 'eval_dataset',
    },
  ],
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
      // The corpus the operator was working on has to survive the jump: without it the
      // destination URL is unreloadable and a refresh silently changes which corpus the
      // recipe would run against.
      const corpusId = String(activeRepo || '').trim();
      if (corpusId) qs.set('corpus', corpusId);
      qs.set('synthetic_context', context);
      if (preset?.recipe) {
        qs.set('synthetic_recipe', String(preset.recipe));
      }
      qs.set('synthetic_autorun', '0');
      navigate({ pathname: '/rag', search: `?${qs.toString()}` });
    },
    [activeRepo, context, navigate]
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
            data-testid={`synthetic-generator-${action.recipe}`}
            title={action.title}
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
