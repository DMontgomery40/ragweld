export function describeEmbeddingProviderStrategy(provider: string): { badge: string; detail: string } {
  const p = String(provider || '').trim().toLowerCase();
  if (!p) return { badge: 'unknown', detail: 'Unknown strategy' };

  // Local / on-device execution.
  if (p === 'local' || p === 'huggingface') return { badge: 'local', detail: 'Local (Python runtime)' };
  if (p === 'ollama') return { badge: 'local', detail: 'Local (Ollama server)' };

  // Cloud APIs.
  if (p === 'openai') return { badge: 'cloud', detail: 'Cloud API (OpenAI)' };
  if (p === 'voyage') return { badge: 'cloud', detail: 'Cloud API (Voyage)' };
  if (p === 'cohere') return { badge: 'cloud', detail: 'Cloud API (Cohere)' };
  if (p === 'jina') return { badge: 'cloud', detail: 'Cloud API (Jina)' };
  if (p === 'google') return { badge: 'cloud', detail: 'Cloud API (Google)' };
  if (p === 'mistral') return { badge: 'cloud', detail: 'Cloud API (Mistral)' };

  return { badge: 'unknown', detail: 'Unknown strategy' };
}

