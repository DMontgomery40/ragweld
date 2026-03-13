import type { RuntimeCapabilitiesResponse } from '@/types/generated';

export function describeEmbeddingProviderStrategy(
  provider: string,
  capabilities?: RuntimeCapabilitiesResponse
): { badge: string; detail: string } {
  const p = String(provider || '').trim().toLowerCase();
  if (!p) return { badge: 'unknown', detail: 'Unknown strategy' };
  if (!capabilities) return { badge: 'unknown', detail: 'Loading runtime capabilities…' };

  const match = (capabilities?.embedding?.providers || []).find(
    (item) => String(item.provider || '').trim().toLowerCase() === p
  );
  if (match) {
    return {
      badge: String(match.badge || 'unknown'),
      detail: String(match.description || match.label || 'Unknown strategy'),
    };
  }

  return { badge: 'catalog', detail: 'Catalog only / not runtime-selectable today' };
}
