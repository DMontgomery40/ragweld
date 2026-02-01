// TriBridRAG - RAG Tab Component (React)
// Main RAG configuration tab with subtab navigation

import { useCallback, useEffect } from 'react';
import { useSearchParams } from 'react-router-dom';
import { RAGSubtabs } from '@/components/RAG/RAGSubtabs';
import { DataQualitySubtab } from '@/components/RAG/DataQualitySubtab';
import { RetrievalSubtab } from '@/components/RAG/RetrievalSubtab';
import { GraphSubtab } from '@/components/RAG/GraphSubtab';
import { RerankerConfigSubtab } from '@/components/RAG/RerankerConfigSubtab';
import { LearningRankerSubtab } from '@/components/RAG/LearningRankerSubtab';
import { IndexingSubtab } from '@/components/RAG/IndexingSubtab';
import { EvaluateSubtab } from '@/components/RAG/EvaluateSubtab';
import { ErrorBoundary } from '@/components/ui/ErrorBoundary';
import { getRouteByPath } from '@/config/routes';
import { useUIStore } from '@/stores/useUIStore';

export default function RAGTab() {
  const activeSubtab = useUIStore((state) => state.activeSubtab['rag'] || 'data-quality');
  const setActiveSubtab = useUIStore((state) => state.setActiveSubtab);
  const [searchParams] = useSearchParams();
  const subtabParam = searchParams.get('subtab');

  // Read ?subtab=... (no writeback)
  useEffect(() => {
    if (!subtabParam) return;
    if (subtabParam === activeSubtab) return;
    const allowed = getRouteByPath('/rag')?.subtabs?.map((s) => s.id) ?? [];
    if (allowed.includes(subtabParam)) setActiveSubtab('rag', subtabParam);
  }, [activeSubtab, setActiveSubtab, subtabParam]);

  const handleSubtabChange = useCallback((subtab: string) => {
    setActiveSubtab('rag', subtab);
  }, [setActiveSubtab]);

  return (
    <div id="tab-rag" className="tab-content">
      {/* Subtab navigation */}
      <RAGSubtabs activeSubtab={activeSubtab} onSubtabChange={handleSubtabChange} />

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

      <div id="tab-rag-evaluate" className={`rag-subtab-content ${activeSubtab === 'evaluate' ? 'active' : ''}`}>
        <ErrorBoundary context="EvaluateSubtab">
          <EvaluateSubtab />
        </ErrorBoundary>
      </div>
    </div>
  );
}
