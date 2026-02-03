import { useCallback, useMemo, useState } from 'react';
import { ModelFlowsService, type ModelsUpsertRequest, type ModelsUpsertResponse } from '@/services/ModelFlowsService';

export function useModelFlows() {
  const service = useMemo(() => new ModelFlowsService(), []);

  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastResponse, setLastResponse] = useState<ModelsUpsertResponse | null>(null);

  const upsertModel = useCallback(
    async (entry: ModelsUpsertRequest) => {
      setSaving(true);
      setError(null);
      try {
        const res = await service.upsertModel(entry);
        setLastResponse(res);
        if (res && (res.error || res.ok === false || res.success === false)) {
          throw new Error(String(res.error || 'Upsert failed'));
        }
        return res;
      } catch (e) {
        const msg = e instanceof Error ? e.message : 'Model upsert failed';
        setError(msg);
        throw e;
      } finally {
        setSaving(false);
      }
    },
    [service]
  );

  const clearError = useCallback(() => setError(null), []);

  return {
    saving,
    error,
    lastResponse,
    clearError,
    upsertModel,
  };
}

