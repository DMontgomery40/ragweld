import { TrainingStudio } from '@/components/AgentTraining/TrainingStudio';
import { SyntheticCallout } from '@/components/RAG/SyntheticCallout';

export function LearningAgentSubtab() {
  return (
    <section className="learning-agent-subtab" data-testid="learning-agent-subtab">
      <header className="learning-reranker-header">
        <h3 className="learning-reranker-title">Learning Agent Studio</h3>
        <p className="learning-reranker-subtitle">
          High-density command center for training ragweld LoRA agent adapters with live telemetry. Promotion sets the active
          training artifact (the baseline for later runs and lineage); chat generation keeps routing through LiteLLM.
        </p>
      </header>

      <SyntheticCallout context="learning-agent" />

      <TrainingStudio />
    </section>
  );
}
