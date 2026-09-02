// Imported from react/rag-tab-and-modules (db2229d)
// TriBridRAG - RAGSubtabs Component
// Subtab navigation for RAG mega-tab

import { useEffect } from 'react';

type RAGSubtabsProps = {
  activeSubtab: string;
  onSubtabChange: (subtab: string) => void;
};

export function RAGSubtabs({ activeSubtab, onSubtabChange }: RAGSubtabsProps) {
  const subtabs = [
    { id: 'data-quality', title: 'Data Quality' },
    { id: 'retrieval', title: 'Retrieval' },
    { id: 'graph', title: 'Graph' },
    { id: 'reranker', title: 'Reranker' },
    { id: 'learning-reranker', title: 'Learning Reranker' },
    { id: 'learning-agent', title: 'Learning Agent Studio' },
    { id: 'indexing', title: 'Indexing' },
    { id: 'synthetic', title: 'Synthetic Lab' }
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
