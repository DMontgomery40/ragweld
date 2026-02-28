import { TrainingStudio } from '@/components/AgentTraining/TrainingStudio';
import { SyntheticCallout } from '@/components/RAG/SyntheticCallout';

export function LearningAgentSubtab() {
  return (
    <section className="learning-agent-subtab" data-testid="learning-agent-subtab">
      <header className="learning-reranker-header">
        <h3 className="learning-reranker-title">Learning Agent Studio</h3>
        <p className="learning-reranker-subtitle">
          High-density command center for training a ragweld in-process agent adapter with live telemetry and instant promotion.
        </p>
      </header>

      <SyntheticCallout context="learning-agent" />

      <TrainingStudio />
    </section>
  );
}
