// Imported from react/rag-tab-and-modules (db2229d)
// TriBridRAG - RAGSubtabs Component
// Subtab navigation for RAG mega-tab

import { useEffect } from 'react';

type RAGSubtabsProps = {
  activeSubtab: string;
  onSubtabChange: (subtab: string) => void;
};

/**
 * ---agentspec
 * what: |
 *   Renders tabbed navigation for RAG pipeline stages. Takes activeSubtab ID and onSubtabChange callback; renders 6 subtab buttons (Data Quality, Retrieval, Graph, Reranker, Learning Reranker, Indexing).
 *
 * why: |
 *   Centralizes RAG workflow UI into reusable component with consistent tab state management.
 *
 * guardrails:
 *   - DO NOT hardcode subtab list; accept as prop for extensibility
 *   - NOTE: Requires activeSubtab and onSubtabChange in parent state
 * ---/agentspec
 */
export function RAGSubtabs({ activeSubtab, onSubtabChange }: RAGSubtabsProps) {
  const subtabs = [
    { id: 'data-quality', title: 'Data Quality' },
    { id: 'retrieval', title: 'Retrieval' },
    { id: 'graph', title: 'Graph' },
    { id: 'reranker-config', title: 'Reranker' },
    { id: 'learning-ranker', title: 'Learning Reranker' },
    { id: 'indexing', title: 'Indexing' }
  ];

  // Ensure a default subtab is selected
  useEffect(() => {
    if (!activeSubtab) {
      onSubtabChange('data-quality');
    }
  }, [activeSubtab, onSubtabChange]);

  return (
    <div className="subtab-bar" id="rag-subtabs" data-state="visible">
      {subtabs.map(subtab => (
        <button
          key={subtab.id}
          className={`subtab-btn ${activeSubtab === subtab.id ? 'active' : ''}`}
          data-subtab={subtab.id}
          onClick={() => onSubtabChange(subtab.id)}
        >
          {subtab.title}
        </button>
      ))}
    </div>
  );
}
