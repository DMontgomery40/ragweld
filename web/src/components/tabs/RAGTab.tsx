// TriBridRAG - RAG Tab Component (React)
// Main RAG configuration tab with subtab navigation

import { lazy, Suspense } from 'react';
import { useSubtab } from '@/hooks/useSubtab';
import { RAGSubtabs } from '@/components/RAG/RAGSubtabs';
import { DataQualitySubtab } from '@/components/RAG/DataQualitySubtab';
import { RetrievalSubtab } from '@/components/RAG/RetrievalSubtab';
import { RerankerConfigSubtab } from '@/components/RAG/RerankerConfigSubtab';
import { LearningRankerSubtab } from '@/components/RAG/LearningRankerSubtab';
import { LearningAgentSubtab } from '@/components/RAG/LearningAgentSubtab';
import { IndexingSubtab } from '@/components/RAG/IndexingSubtab';
import { SyntheticLabSubtab } from '@/components/RAG/SyntheticLabSubtab';
import { ErrorBoundary } from '@/components/ui/ErrorBoundary';

const GraphSubtab = lazy(async () => {
  const module = await import('@/components/RAG/GraphSubtab');
  return { default: module.GraphSubtab };
});

export default function RAGTab() {
  const { activeSubtab, setSubtab } = useSubtab<string>({ routePath: '/rag', defaultSubtab: 'data-quality' });

  return (
    <div id="tab-rag" className="tab-content">
      {/* Subtab navigation */}
      <RAGSubtabs activeSubtab={activeSubtab} onSubtabChange={setSubtab} />

      {/* All subtabs rendered with visibility controlled by className */}
      <div id="tab-rag-data-quality" className={`rag-subtab-content ${activeSubtab === 'data-quality' ? 'active' : ''}`}>
        <ErrorBoundary context="DataQualitySubtab">
          {activeSubtab === 'data-quality' ? <DataQualitySubtab /> : null}
        </ErrorBoundary>
      </div>

      <div id="tab-rag-retrieval" className={`rag-subtab-content ${activeSubtab === 'retrieval' ? 'active' : ''}`}>
        <ErrorBoundary context="RetrievalSubtab">
          {activeSubtab === 'retrieval' ? <RetrievalSubtab /> : null}
        </ErrorBoundary>
      </div>

      <div id="tab-rag-graph" className={`rag-subtab-content ${activeSubtab === 'graph' ? 'active' : ''}`}>
        <ErrorBoundary context="GraphSubtab">
          {activeSubtab === 'graph' ? (
            <Suspense fallback={<div className="loading">Loading graph view…</div>}>
              <GraphSubtab />
            </Suspense>
          ) : null}
        </ErrorBoundary>
      </div>

      <div id="tab-rag-reranker-config" className={`rag-subtab-content ${activeSubtab === 'reranker-config' ? 'active' : ''}`}>
        <ErrorBoundary context="RerankerConfigSubtab">
          {activeSubtab === 'reranker-config' ? <RerankerConfigSubtab /> : null}
        </ErrorBoundary>
      </div>

      <div id="tab-rag-learning-ranker" className={`rag-subtab-content ${activeSubtab === 'learning-ranker' ? 'active' : ''}`}>
        <ErrorBoundary context="LearningRankerSubtab">
          {activeSubtab === 'learning-ranker' ? <LearningRankerSubtab /> : null}
        </ErrorBoundary>
      </div>

      <div id="tab-rag-learning-agent" className={`rag-subtab-content ${activeSubtab === 'learning-agent' ? 'active' : ''}`}>
        <ErrorBoundary context="LearningAgentSubtab">
          {activeSubtab === 'learning-agent' ? <LearningAgentSubtab /> : null}
        </ErrorBoundary>
      </div>

      <div id="tab-rag-indexing" className={`rag-subtab-content ${activeSubtab === 'indexing' ? 'active' : ''}`}>
        <ErrorBoundary context="IndexingSubtab">
          {activeSubtab === 'indexing' ? <IndexingSubtab /> : null}
        </ErrorBoundary>
      </div>

      <div id="tab-rag-synthetic" className={`rag-subtab-content ${activeSubtab === 'synthetic' ? 'active' : ''}`}>
        <ErrorBoundary context="SyntheticLabSubtab">
          {activeSubtab === 'synthetic' ? <SyntheticLabSubtab /> : null}
        </ErrorBoundary>
      </div>
    </div>
  );
}
