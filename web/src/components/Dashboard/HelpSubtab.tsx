// TriBrid RAG - Help Subtab
// Documentation, guides, and helpful resources

export function HelpSubtab() {
  return (
    <div
      id="tab-dashboard-help"
      className="dashboard-subtab"
      style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}
    >
      {/* Getting Started */}
      <div className="settings-section" style={{ background: 'var(--panel)', borderLeft: '3px solid var(--accent)' }}>
        <h3
          style={{
            fontSize: '20px',
            marginBottom: '20px',
            display: 'flex',
            alignItems: 'center',
            gap: '12px'
          }}
        >
          <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <circle cx="12" cy="12" r="10" />
            <path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3" />
            <line x1="12" y1="17" x2="12.01" y2="17" />
          </svg>
          Help & Documentation
        </h3>

        <p style={{ color: 'var(--fg-muted)', marginBottom: '32px', lineHeight: '1.6', fontSize: '14px' }}>
          Welcome to TriBrid RAG (Vector + Sparse + Graph). This guide will help you get started and understand key concepts.
        </p>

        {/* Quick Start Guide */}
        <div
          style={{
            background: 'var(--card-bg)',
            border: '1px solid var(--line)',
            borderRadius: '8px',
            padding: '24px',
            marginBottom: '24px'
          }}
        >
          <h4
            style={{
              margin: '0 0 16px 0',
              fontSize: '16px',
              fontWeight: '600',
              color: 'var(--accent)',
              display: 'flex',
              alignItems: 'center',
              gap: '8px'
            }}
          >
            <span style={{ fontSize: '24px' }}>🚀</span>
            Quick Start Guide
          </h4>

          <ol style={{ margin: 0, paddingLeft: '24px', lineHeight: '2', fontSize: '14px', color: 'var(--fg)' }}>
            <li>
              <strong>Index Your Repository:</strong> Navigate to the Dashboard and click "Run Indexer" to create embeddings
              and indices for your codebase.
            </li>
            <li>
              <strong>Configure RAG Settings:</strong> Use the RAG tab to adjust retrieval parameters like top_k, hybrid search
              alpha, and reranking options.
            </li>
            <li>
              <strong>Test Your Setup:</strong> Go to the Chat tab to test queries against your indexed repository.
            </li>
            <li>
              <strong>Evaluate Performance:</strong> Use the Evaluate subtab under RAG to run eval dataset tests and measure
              retrieval quality.
            </li>
            <li>
              <strong>Compare Configurations:</strong> Use the Admin tab to save and compare different RAG configurations
              for different use cases.
            </li>
          </ol>
        </div>

        {/* Key Concepts */}
        <div
          style={{
            background: 'var(--card-bg)',
            border: '1px solid var(--line)',
            borderRadius: '8px',
            padding: '24px',
            marginBottom: '24px'
          }}
        >
          <h4
            style={{
              margin: '0 0 16px 0',
              fontSize: '16px',
              fontWeight: '600',
              color: 'var(--link)',
              display: 'flex',
              alignItems: 'center',
              gap: '8px'
            }}
          >
            <span style={{ fontSize: '24px' }}>📚</span>
            Key Concepts
          </h4>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px' }}>
            <ConceptCard
              title="Hybrid Search"
              description="Combines dense (embedding-based) and sparse (BM25) retrieval. The alpha parameter controls the balance: 0 = pure sparse, 1 = pure dense, 0.5 = balanced."
            />
            <ConceptCard
              title="Reranking"
              description="Post-retrieval scoring using cross-encoder models. Improves relevance by re-scoring top-k results with a more expensive but accurate model."
            />
            <ConceptCard
              title="Chunk Summaries"
              description="Pre-computed document summaries that provide context without full content. Enables faster RAG with lower token costs."
            />
            <ConceptCard
              title="Learning Ranker"
              description="Train custom reranking models on your query patterns. Uses user feedback (clicks, ratings) to improve relevance over time."
            />
            <ConceptCard
              title="Multi-Query Rewrites"
              description="Expands user queries into multiple variations to improve recall. Uses LLMs to generate semantically similar questions."
            />
            <ConceptCard
              title="Configuration Presets"
              description="Named configurations that bundle embedding models, chunking strategies, and retrieval settings for easy switching."
            />
          </div>
        </div>

        {/* Common Tasks */}
        <div
          style={{
            background: 'var(--card-bg)',
            border: '1px solid var(--line)',
            borderRadius: '8px',
            padding: '24px',
            marginBottom: '24px'
          }}
        >
          <h4
            style={{
              margin: '0 0 16px 0',
              fontSize: '16px',
              fontWeight: '600',
              color: 'var(--warn)',
              display: 'flex',
              alignItems: 'center',
              gap: '8px'
            }}
          >
            <span style={{ fontSize: '24px' }}>⚡</span>
            Common Tasks
          </h4>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
            <TaskLink
              title="How do I change the embedding model?"
              description="Go to RAG → Indexing, select a new embedding model, then re-run the indexer."
            />
            <TaskLink
              title="How do I improve retrieval quality?"
              description="Try adjusting hybrid_alpha (0.3-0.7), enabling reranking, or increasing final_k in RAG → Retrieval settings."
            />
            <TaskLink
              title="How do I add a new repository?"
              description="Use Admin → General to add repository paths, then run the indexer for each repo."
            />
            <TaskLink
              title="How do I set up evaluation datasets?"
              description="Go to RAG → Evaluate, add questions with expected context, then run evaluations to measure quality."
            />
            <TaskLink
              title="How do I monitor system health?"
              description="Check Dashboard → Monitoring for alerts, traces, and Loki logs. Infrastructure → Monitoring for Grafana dashboards."
            />
          </div>
        </div>

        {/* External Resources */}
        <div
          style={{
            background: 'var(--card-bg)',
            border: '1px solid var(--line)',
            borderRadius: '8px',
            padding: '24px'
          }}
        >
          <h4
            style={{
              margin: '0 0 16px 0',
              fontSize: '16px',
              fontWeight: '600',
              color: 'var(--ok)',
              display: 'flex',
              alignItems: 'center',
              gap: '8px'
            }}
          >
            <span style={{ fontSize: '24px' }}>🔗</span>
            External Resources
          </h4>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
            <ExternalLink
              title="pgvector Documentation"
              href="https://github.com/pgvector/pgvector"
              description="PostgreSQL vector similarity search extension"
            />
            <ExternalLink
              title="Neo4j Graph Database"
              href="https://neo4j.com/docs/"
              description="Knowledge graph storage and traversal for graph RAG"
            />
            <ExternalLink
              title="BM25 Algorithm"
              href="https://en.wikipedia.org/wiki/Okapi_BM25"
              description="Understand sparse retrieval and ranking functions"
            />
            <ExternalLink
              title="RAG Best Practices"
              href="https://www.anthropic.com/index/contextual-retrieval"
              description="Anthropic's guide to retrieval-augmented generation"
            />
            <ExternalLink
              title="Cross-Encoder Models"
              href="https://www.sbert.net/examples/applications/cross-encoder/README.html"
              description="Deep dive into reranking with transformers"
            />
          </div>
        </div>
      </div>
    </div>
  );
}

interface ConceptCardProps {
  title: string;
  description: string;
}

function ConceptCard({ title, description }: ConceptCardProps) {
  return (
    <div
      style={{
        background: 'var(--bg-elev1)',
        border: '1px solid var(--line)',
        borderRadius: '6px',
        padding: '16px'
      }}
    >
      <h5 style={{ margin: '0 0 8px 0', fontSize: '13px', fontWeight: '600', color: 'var(--accent)' }}>{title}</h5>
      <p style={{ margin: 0, fontSize: '12px', lineHeight: '1.6', color: 'var(--fg-muted)' }}>{description}</p>
    </div>
  );
}

interface TaskLinkProps {
  title: string;
  description: string;
}

function TaskLink({ title, description }: TaskLinkProps) {
  return (
    <div
      style={{
        padding: '12px',
        background: 'var(--bg-elev1)',
        borderLeft: '3px solid var(--accent)',
        borderRadius: '4px'
      }}
    >
      <div style={{ fontSize: '13px', fontWeight: '600', color: 'var(--fg)', marginBottom: '4px' }}>{title}</div>
      <div style={{ fontSize: '11px', color: 'var(--fg-muted)' }}>{description}</div>
    </div>
  );
}

interface ExternalLinkProps {
  title: string;
  href: string;
  description: string;
}

function ExternalLink({ title, href, description }: ExternalLinkProps) {
  return (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        padding: '12px',
        background: 'var(--bg-elev1)',
        border: '1px solid var(--line)',
        borderRadius: '6px',
        textDecoration: 'none',
        color: 'var(--fg)',
        transition: 'all 0.2s ease'
      }}
      onMouseEnter={(e) => {
        e.currentTarget.style.borderColor = 'var(--link)';
        e.currentTarget.style.background = 'var(--bg-elev2)';
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.borderColor = 'var(--line)';
        e.currentTarget.style.background = 'var(--bg-elev1)';
      }}
    >
      <div style={{ flex: 1 }}>
        <div style={{ fontSize: '13px', fontWeight: '600', color: 'var(--link)', marginBottom: '4px' }}>{title}</div>
        <div style={{ fontSize: '11px', color: 'var(--fg-muted)' }}>{description}</div>
      </div>
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" />
        <polyline points="15 3 21 3 21 9" />
        <line x1="10" y1="14" x2="21" y2="3" />
      </svg>
    </a>
  );
}
