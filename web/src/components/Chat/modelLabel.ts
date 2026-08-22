import type { ChatModelInfo } from '@/types/generated';

/** Upstream provider group for a gateway alias (catalog-backed), or the gateway name itself. */
export function chatModelGroup(model: ChatModelInfo): string {
  return String(model.catalog_provider || '').trim() || String(model.provider || 'LiteLLM').trim();
}

/** Human-readable name for one gateway alias: catalog display name, else catalog id, else the alias. */
export function chatModelName(model: ChatModelInfo): string {
  return String(model.display_name || model.catalog_model || model.id || '').trim();
}

/** `provider · name` label used by every generation-model select. */
export function chatModelLabel(model: ChatModelInfo): string {
  return `${chatModelGroup(model)} · ${chatModelName(model)}`;
}

function formatPer1k(value: number | null | undefined): string | null {
  if (typeof value !== 'number' || !Number.isFinite(value)) return null;
  if (value === 0) return '$0';
  return `$${value.toFixed(value < 0.001 ? 5 : 4)}`;
}

/** Tooltip detail: alias, context window and per-1k pricing when the catalog knows them. */
export function chatModelDetail(model: ChatModelInfo): string {
  const parts: string[] = [`alias ${model.id}`];
  if (typeof model.context === 'number' && model.context > 0) {
    parts.push(`${model.context.toLocaleString()} ctx`);
  }
  const input = formatPer1k(model.input_per_1k);
  const output = formatPer1k(model.output_per_1k);
  if (input !== null && output !== null) {
    parts.push(`${input} in / ${output} out per 1k`);
  }
  if (model.supports_vision) parts.push('vision');
  return parts.join(' · ');
}

/** Stable provider-grouped ordering: local serving row first, then providers A-Z, names A-Z. */
export function groupChatModels(models: ChatModelInfo[]): Array<{ group: string; models: ChatModelInfo[] }> {
  const byGroup = new Map<string, ChatModelInfo[]>();
  for (const model of models) {
    const group = chatModelGroup(model);
    const bucket = byGroup.get(group);
    if (bucket) bucket.push(model);
    else byGroup.set(group, [model]);
  }
  const groups = Array.from(byGroup.entries()).map(([group, rows]) => ({
    group,
    models: [...rows].sort((a, b) => chatModelName(a).localeCompare(chatModelName(b))),
  }));
  groups.sort((a, b) => {
    if (a.group === 'ragweld') return -1;
    if (b.group === 'ragweld') return 1;
    return a.group.localeCompare(b.group);
  });
  return groups;
}
