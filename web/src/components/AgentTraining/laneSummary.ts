import type { LearningAgentRuntimeCapability } from '@/types/generated';

// Pure rendering rules for the Learning Agent Studio header. No runtime imports: this
// module is also exercised by the node:test unit suite (web/tests/unit).

export type LearningAgentLaneState = 'host_ready' | 'host_unavailable' | 'flyte_task';

export type LearningAgentLaneSummary = {
  state: LearningAgentLaneState;
  /** The host's own sentence about the lane (runtime capabilities availability_detail). */
  headline: string;
  /** Verbatim configured values; the UI never invents a model or path. */
  executionBackend: string;
  baseModel: string;
  artifactPath: string;
};

export function describeLearningAgentLane(lane: LearningAgentRuntimeCapability): LearningAgentLaneSummary {
  const executionBackend = String(lane.execution_backend || '').trim() || '(unset)';
  const baseModel = String(lane.base_model || '').trim() || '(unset)';
  const artifactPath = String(lane.artifact_path || '').trim() || '(unset)';
  const headline = String(lane.availability_detail || '').trim();
  const state: LearningAgentLaneState =
    lane.execution_locus === 'flyte_task' ? 'flyte_task' : lane.host_available === true ? 'host_ready' : 'host_unavailable';
  return { state, headline, executionBackend, baseModel, artifactPath };
}

/** The full header blurb: what this host can run, then what the configured lane trains and promotes. */
export function learningAgentLaneBlurb(summary: LearningAgentLaneSummary): string {
  const lead =
    summary.state === 'host_ready'
      ? `Train local adapters for ${summary.baseModel} on the host ${summary.executionBackend} backend.`
      : summary.headline;
  return (
    `${lead} Configured base model ${summary.baseModel}; adapters promote to ${summary.artifactPath} ` +
    '(the training-only baseline for later runs; never served by the chat gateway). ' +
    'Only artifacts trained on the configured base can be promoted.'
  );
}
