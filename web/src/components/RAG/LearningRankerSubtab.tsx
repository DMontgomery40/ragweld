import { useMemo } from 'react';
import { useConfigField } from '@/hooks';
import { TrainingStudio } from '@/components/RerankerTraining/TrainingStudio';

export function LearningRankerSubtab() {
  const [rerankerMode] = useConfigField<string>('reranking.reranker_mode', 'local');

  const modeWarning = useMemo(() => {
    const mode = String(rerankerMode || '').toLowerCase();
    if (mode === 'learning') return null;
    return `Reranker mode is "${rerankerMode}". Switch to "learning" in the Reranker subtab for training to affect retrieval.`;
  }, [rerankerMode]);

  return (
    <section className="learning-reranker-subtab" data-testid="learning-reranker-subtab">
      <header className="learning-reranker-header">
        <h3 className="learning-reranker-title">Learning Reranker Studio</h3>
        <p className="learning-reranker-subtitle">
          High-density command center for triplet mining, training, promotion, and real-time telemetry.
        </p>
      </header>

      {modeWarning ? (
        <div className="studio-callout studio-callout-warn" data-testid="learning-reranker-mode-warning">
          {modeWarning}
        </div>
      ) : null}

      <TrainingStudio />
    </section>
  );
}
