// TriBridRAG - RAG Tab Component (React)
// Main RAG configuration tab with subtab navigation

import { useSubtab } from '@/hooks';
import { RAGSubtabs } from '@/components/RAG/RAGSubtabs';
import { DataQualitySubtab } from '@/components/RAG/DataQualitySubtab';
import { RetrievalSubtab } from '@/components/RAG/RetrievalSubtab';
import { GraphSubtab } from '@/components/RAG/GraphSubtab';
import { RerankerConfigSubtab } from '@/components/RAG/RerankerConfigSubtab';
import { LearningRankerSubtab } from '@/components/RAG/LearningRankerSubtab';
import { IndexingSubtab } from '@/components/RAG/IndexingSubtab';
import { ErrorBoundary } from '@/components/ui/ErrorBoundary';

export default function RAGTab() {
  const { activeSubtab, setSubtab } = useSubtab<string>({ routePath: '/rag', defaultSubtab: 'data-quality' });

  return (
    <div id="tab-rag" className="tab-content">
      {/* Subtab navigation */}
      <RAGSubtabs activeSubtab={activeSubtab} onSubtabChange={setSubtab} />

      {/* All subtabs rendered with visibility controlled by className */}
      <div id="tab-rag-data-quality" className={`rag-subtab-content ${activeSubtab === 'data-quality' ? 'active' : ''}`}>
        <ErrorBoundary context="DataQualitySubtab">
          <DataQualitySubtab />
        </ErrorBoundary>
      </div>

      <div id="tab-rag-retrieval" className={`rag-subtab-content ${activeSubtab === 'retrieval' ? 'active' : ''}`}>
        <ErrorBoundary context="RetrievalSubtab">
          <RetrievalSubtab />
        </ErrorBoundary>
      </div>

      <div id="tab-rag-graph" className={`rag-subtab-content ${activeSubtab === 'graph' ? 'active' : ''}`}>
        <ErrorBoundary context="GraphSubtab">
          <GraphSubtab />
        </ErrorBoundary>
      </div>

      <div id="tab-rag-reranker-config" className={`rag-subtab-content ${activeSubtab === 'reranker-config' ? 'active' : ''}`}>
        <ErrorBoundary context="RerankerConfigSubtab">
          <RerankerConfigSubtab />
        </ErrorBoundary>
      </div>

      <div id="tab-rag-learning-ranker" className={`rag-subtab-content ${activeSubtab === 'learning-ranker' ? 'active' : ''}`}>
        <ErrorBoundary context="LearningRankerSubtab">
          <LearningRankerSubtab />
        </ErrorBoundary>
      </div>

      <div id="tab-rag-indexing" className={`rag-subtab-content ${activeSubtab === 'indexing' ? 'active' : ''}`}>
        <ErrorBoundary context="IndexingSubtab">
          <IndexingSubtab />
        </ErrorBoundary>
      </div>
    </div>
  );
}
