import { useEffect, useState } from 'react';
import { runtimeCapabilitiesApi } from '@/api/runtimeCapabilities';
import type { RuntimeCapabilitiesResponse } from '@/types/generated';

let capabilitiesCache: RuntimeCapabilitiesResponse | null = null;
let capabilitiesPromise: Promise<RuntimeCapabilitiesResponse> | null = null;

async function loadRuntimeCapabilities(): Promise<RuntimeCapabilitiesResponse> {
  if (capabilitiesCache) return capabilitiesCache;
  if (capabilitiesPromise) return capabilitiesPromise;

  capabilitiesPromise = runtimeCapabilitiesApi.get().then((data) => {
    capabilitiesCache = data;
    capabilitiesPromise = null;
    return data;
  }).catch((error) => {
    capabilitiesPromise = null;
    throw error;
  });

  return capabilitiesPromise;
}

export function useRuntimeCapabilities() {
  const [capabilities, setCapabilities] = useState<RuntimeCapabilitiesResponse | null>(capabilitiesCache);
  const [loading, setLoading] = useState<boolean>(() => !capabilitiesCache);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let mounted = true;
    if (capabilitiesCache) {
      setCapabilities(capabilitiesCache);
      setLoading(false);
      return () => { mounted = false; };
    }

    setLoading(true);
    setError(null);
    loadRuntimeCapabilities()
      .then((data) => {
        if (!mounted) return;
        setCapabilities(data);
        setLoading(false);
      })
      .catch((err) => {
        if (!mounted) return;
        setError(err instanceof Error ? err.message : 'Failed to load runtime capabilities');
        setLoading(false);
      });

    return () => { mounted = false; };
  }, []);

  return { capabilities, loading, error };
}
