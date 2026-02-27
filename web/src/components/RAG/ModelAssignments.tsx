/**
 * ModelAssignments - Read-only overview of every model-dependent task in the pipeline.
 *
 * Shows task, provider, effective model (with fallback resolution), system prompt link,
 * and catalog validation status.
 */

import { useMemo } from 'react';
import { useConfig } from '@/hooks';
import { useModels } from '@/hooks';
import { PromptLink } from '@/components/ui/PromptLink';
import { TooltipIcon } from '@/components/ui/TooltipIcon';

interface AssignmentRow {
  task: string;
  provider: string;
  model: string;
  fallbackNote?: string;
  promptKey?: string;
  promptLabel?: string;
}

export function ModelAssignments() {
  const { config } = useConfig();
  const { models: genModels } = useModels('GEN');
  const { models: embModels } = useModels('EMB');
  const { models: rerankModels } = useModels('RERANK');

  const allModels = useMemo(
    () => [...genModels, ...embModels, ...rerankModels],
    [genModels, embModels, rerankModels],
  );

  const rows = useMemo<AssignmentRow[]>(() => {
    if (!config) return [];

    const gen = config.generation;
    const graph = config.graph_indexing;
    const emb = config.embedding;
    const rr = config.reranking;

    const genBackend = gen?.gen_backend || 'openai';
    const enrichBackend = gen?.enrich_backend || 'openai';
    const embType = emb?.embedding_type || 'openai';
    const rrMode = String(rr?.reranker_mode || 'none').toLowerCase();

    const enrichModel = gen?.enrich_model || 'gpt-4o-mini';

    // Resolve semantic_kg_llm_model with fallback to enrich_model
    const kgModel = graph?.semantic_kg_llm_model || '';
    const effectiveKgModel = kgModel || enrichModel;
    const kgFallback = kgModel ? undefined : 'fallback: enrich_model';

    // Resolve embedding model based on type
    let embModel = '';
    if (embType === 'voyage') {
      embModel = emb?.voyage_model || '';
    } else if (embType === 'local' || embType === 'ollama' || embType === 'huggingface') {
      embModel = emb?.embedding_model_local || 'all-MiniLM-L6-v2';
    } else if (embType === 'mlx') {
      embModel = emb?.embedding_model_mlx || '';
    } else {
      embModel = emb?.embedding_model || 'text-embedding-3-large';
    }

    // Resolve reranker
    let rrProvider = rrMode;
    let rrModel = '';
    if (rrMode === 'cloud') {
      rrProvider = rr?.reranker_cloud_provider || 'cohere';
      rrModel = rr?.reranker_cloud_model || '';
    } else if (rrMode === 'learning' || rrMode === 'local') {
      rrProvider = 'learning';
      rrModel = '(local LoRA)';
    } else {
      rrProvider = 'none';
      rrModel = '(disabled)';
    }

    const out: AssignmentRow[] = [
      {
        task: 'Chat Answer',
        provider: genBackend,
        model: gen?.gen_model || 'gpt-4o-mini',
        promptKey: 'main_rag_chat',
        promptLabel: 'Chat Prompt',
      },
      {
        task: 'Enrichment',
        provider: enrichBackend,
        model: enrichModel,
      },
      {
        task: 'Semantic KG LLM',
        provider: enrichBackend,
        model: effectiveKgModel,
        fallbackNote: kgFallback,
      },
      {
        task: 'Query Expansion',
        provider: genBackend,
        model: gen?.gen_model || 'gpt-4o-mini',
        promptKey: 'query_expansion',
        promptLabel: 'Expansion Prompt',
      },
      {
        task: 'Query Rewrite',
        provider: genBackend,
        model: gen?.gen_model || 'gpt-4o-mini',
        promptKey: 'query_rewrite',
        promptLabel: 'Rewrite Prompt',
      },
      {
        task: 'Embedding',
        provider: embType,
        model: embModel,
      },
      {
        task: 'Reranker',
        provider: rrProvider,
        model: rrModel,
      },
    ];

    // Channel overrides (only if set)
    if (gen?.gen_model_http) {
      out.push({
        task: 'HTTP Override',
        provider: genBackend,
        model: gen.gen_model_http,
      });
    }
    if (gen?.gen_model_mcp) {
      out.push({
        task: 'MCP Override',
        provider: genBackend,
        model: gen.gen_model_mcp,
      });
    }
    if (gen?.gen_model_cli) {
      out.push({
        task: 'CLI Override',
        provider: genBackend,
        model: gen.gen_model_cli,
      });
    }
    if (gen?.gen_model_ollama) {
      out.push({
        task: 'Chat Answer (Ollama)',
        provider: 'ollama',
        model: gen.gen_model_ollama,
      });
    }
    if (gen?.enrich_model_ollama) {
      out.push({
        task: 'Enrichment (Ollama)',
        provider: 'ollama',
        model: gen.enrich_model_ollama,
      });
    }

    return out;
  }, [config]);

  // Validate model against catalog
  const isInCatalog = useMemo(() => {
    const catalogSet = new Set(allModels.map((m) => String(m.model || '').trim()));
    return (model: string) => {
      if (!model || model.startsWith('(')) return true; // skip placeholders
      return catalogSet.has(model.trim());
    };
  }, [allModels]);

  if (!config) return null;

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12 }}>
        <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--fg)' }}>
          Model Assignments
        </span>
        <TooltipIcon name="MODEL_ASSIGNMENTS" />
      </div>

      <div style={{ overflowX: 'auto' }}>
        <table
          style={{
            width: '100%',
            borderCollapse: 'collapse',
            fontSize: 12,
          }}
        >
          <thead>
            <tr
              style={{
                borderBottom: '2px solid var(--line)',
                textAlign: 'left',
              }}
            >
              <th style={TH_STYLE}>Task</th>
              <th style={TH_STYLE}>Provider</th>
              <th style={TH_STYLE}>Model</th>
              <th style={TH_STYLE}>System Prompt</th>
              <th style={{ ...TH_STYLE, textAlign: 'center' }}>Status</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => {
              const valid = isInCatalog(row.model);
              return (
                <tr
                  key={row.task}
                  style={{ borderBottom: '1px solid var(--line)' }}
                >
                  <td style={TD_STYLE}>
                    {row.task}
                  </td>
                  <td style={TD_STYLE}>
                    <code style={{ fontSize: 11 }}>{row.provider}</code>
                  </td>
                  <td style={TD_STYLE}>
                    <code style={{ fontSize: 11 }}>{row.model}</code>
                    {row.fallbackNote && (
                      <span style={{ fontSize: 10, color: 'var(--fg-muted)', marginLeft: 6 }}>
                        ({row.fallbackNote})
                      </span>
                    )}
                  </td>
                  <td style={TD_STYLE}>
                    {row.promptKey ? (
                      <PromptLink promptKey={row.promptKey}>{row.promptLabel}</PromptLink>
                    ) : (
                      <span style={{ color: 'var(--fg-muted)' }}>--</span>
                    )}
                  </td>
                  <td style={{ ...TD_STYLE, textAlign: 'center' }}>
                    {valid ? (
                      <span style={{ color: 'var(--ok)' }} title="In catalog">OK</span>
                    ) : (
                      <span style={{ color: 'var(--warn)' }} title="Not found in models.json">custom</span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

const TH_STYLE: React.CSSProperties = {
  padding: '8px 10px',
  fontSize: 11,
  fontWeight: 700,
  color: 'var(--fg-muted)',
  textTransform: 'uppercase',
  letterSpacing: '0.05em',
};

const TD_STYLE: React.CSSProperties = {
  padding: '8px 10px',
  color: 'var(--fg)',
};
