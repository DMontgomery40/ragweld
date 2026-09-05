import type { ReadyIndexEstimate } from '@/api/indexing';
import type { ConfirmDialogOptions } from '@/components/ui/confirmDialog';
import { formatBytes, formatDuration, formatNumber } from '@/utils/formatters';

type EstimateConsentContext = {
  corpusName: string;
  /** Material consequences of this action, such as replacement or an audited override. */
  notices?: string[];
};

export function formatEstimateCostUsd(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return 'Unknown';
  if (value > 0 && value < 0.00000001) return `$${value.toPrecision(2)}`;
  return new Intl.NumberFormat('en-US', {
    style: 'currency', currency: 'USD', minimumFractionDigits: 2, maximumFractionDigits: 8,
  }).format(value);
}

function seconds(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return 'Unknown';
  return formatDuration(Math.round(Math.max(0, value) * 1000));
}

/** One presentation boundary for both consent callers; null totals stay unknown. */
export function indexEstimateConsent(
  estimate: ReadyIndexEstimate,
  { corpusName, notices = [] }: EstimateConsentContext,
): Pick<ConfirmDialogOptions, 'message' | 'details'> {
  const assumptions = estimate.assumptions ?? [];
  const semanticActive = estimate.semantic_kg_cost_usd != null
    || estimate.estimated_seconds_semantic_kg != null;
  const figureActive = estimate.estimated_figures != null || estimate.figure_description_cost_usd != null;
  const uncertainties: string[] = [];
  if (estimate.total_cost_usd == null) {
    const unknownParts = [
      estimate.embedding_cost_usd == null ? 'embedding' : null,
      semanticActive && estimate.semantic_kg_cost_usd == null ? 'Semantic KG' : null,
      figureActive && estimate.figure_description_cost_usd == null ? 'figure' : null,
    ].filter(Boolean);
    uncertainties.push(unknownParts.length ? `${unknownParts.join(', ')} cost unknown` : 'total cost unknown');
  }
  if (assumptions.some((line) => /status=(?:error|cancelled)|failed[- ]run/i.test(line))) {
    uncertainties.push('baseline from a failed or cancelled run');
  }
  if (assumptions.some((line) => /attempts have no usable output sample|incomplete (?:native|output|request).*coverage/i.test(line))) {
    uncertainties.push('partial output evidence');
  }
  if (assumptions.some((line) => /historical configuration differs/i.test(line))) {
    uncertainties.push('historical settings differ');
  }
  const costBreakdown = [
    `Embed ${formatEstimateCostUsd(estimate.embedding_cost_usd)}`,
    semanticActive ? `Semantic KG ${formatEstimateCostUsd(estimate.semantic_kg_cost_usd)}` : null,
    figureActive
      ? `Figures ${estimate.figure_description_cost_usd == null ? 'Unknown' : `≤ ${formatEstimateCostUsd(estimate.figure_description_cost_usd)}`}${
          estimate.estimated_figures != null ? ` (~${formatNumber(estimate.estimated_figures)} figures)` : ''
        }`
      : null,
  ].filter(Boolean).join(' + ');
  const timeBreakdown = [
    `Embed ${seconds(estimate.estimated_seconds_embedding)}`,
    semanticActive ? `Semantic KG ${seconds(estimate.estimated_seconds_semantic_kg)}` : null,
    figureActive ? `Figures ${seconds(estimate.estimated_seconds_figures)}` : null,
    `startup ${seconds(estimate.estimated_seconds_overhead)}`,
  ].filter(Boolean).join(' + ');
  const message = [
    `Index estimate for "${corpusName}"`,
    `Files: ${formatNumber(estimate.total_files)} • Chunks (est): ${formatNumber(estimate.estimated_total_chunks)}`,
    `Estimated cost: ${formatEstimateCostUsd(estimate.total_cost_usd)} • Time: ${seconds(estimate.estimated_seconds)}`,
    ...(uncertainties.length ? [`Uncertainty: ${uncertainties.join('; ')}.`] : []),
    semanticActive
      ? 'Semantic KG uses a sample-based forecast; time is approximate and retries can change charges. Cost is not a spending limit.'
      : 'Time and cost are estimates.',
    ...notices,
  ].join('\n');

  return {
    message,
    details: (
      <div>
        <div style={{ whiteSpace: 'pre-wrap' }}>
          {[
            `Source: ${estimate.repo_path}`,
            `Size: ${formatBytes(estimate.total_size_bytes)} • Skipped as too large: ${formatNumber(estimate.skipped_large_files)}`,
            `Estimated tokens: ${formatNumber(estimate.estimated_total_tokens)} (${formatNumber(estimate.estimated_tokens_low)}–${formatNumber(estimate.estimated_tokens_high)})`,
            `Estimated chunks: ${formatNumber(estimate.estimated_total_chunks)} (${formatNumber(estimate.estimated_chunks_low)}–${formatNumber(estimate.estimated_chunks_high)})`,
            `Measured by chunking ${formatNumber(estimate.sampled_files)} sampled files in ${seconds(estimate.elapsed_seconds)} • band ±${Math.round(estimate.estimate_relative_error * 100)}%`,
            `Embedding: ${estimate.embedding_provider || '—'}/${estimate.embedding_model || '—'} (${estimate.embedding_backend}${estimate.skip_dense ? ', dense skipped' : ''})`,
            `Cost breakdown: ${costBreakdown}`,
            `Time range: ${seconds(estimate.estimated_seconds_low)}–${seconds(estimate.estimated_seconds_high)}`,
            `Time breakdown (est): ${timeBreakdown}`,
          ].join('\n')}
        </div>
        {assumptions.length > 0 ? (
          <div style={{ marginTop: 12 }}>
            <strong>Saved estimate assumptions</strong>
            <ul style={{ paddingLeft: 18, margin: '6px 0 0' }}>
              {assumptions.map((assumption, index) => (
                <li key={index} style={{ marginBottom: 6 }}>{assumption}</li>
              ))}
            </ul>
          </div>
        ) : null}
      </div>
    ),
  };
}
