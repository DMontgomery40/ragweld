import { useCallback, useEffect, useMemo, useState } from 'react';
import { CostService, type CostEstimateLocal, type CostEstimatePipelineRequest, type CostEstimatePipelineResponse, type CostEstimateRequest, type CostModelType } from '@/services/CostService';
 
type UseCostState = {
  providers: string[];
  modelsByProvider: Record<string, string[]>;
  loadingCatalog: boolean;
  catalogError: string | null;
};
 
/**
 * useCost
 * Hook wrapper around CostService (replaces legacy window.CostLogic).
 */
export function useCost() {
  const service = useMemo(() => new CostService(), []);
 
  const [state, setState] = useState<UseCostState>({
    providers: [],
    modelsByProvider: {},
    loadingCatalog: true,
    catalogError: null,
  });
 
  const [estimating, setEstimating] = useState(false);
  const [estimateError, setEstimateError] = useState<string | null>(null);
  const [lastLocalEstimate, setLastLocalEstimate] = useState<CostEstimateLocal | null>(null);
  const [lastApiEstimate, setLastApiEstimate] = useState<CostEstimatePipelineResponse | null>(null);
 
  const refreshCatalog = useCallback(async () => {
    setState((s) => ({ ...s, loadingCatalog: true, catalogError: null }));
    try {
      const providers = await service.listProviders();
      const modelsByProvider: Record<string, string[]> = {};
      await Promise.all(
        providers.map(async (p) => {
          modelsByProvider[p] = await service.listModels(p);
        })
      );
      setState({ providers, modelsByProvider, loadingCatalog: false, catalogError: null });
    } catch (e) {
      setState({ providers: [], modelsByProvider: {}, loadingCatalog: false, catalogError: e instanceof Error ? e.message : String(e) });
    }
  }, [service]);
 
  useEffect(() => {
    void refreshCatalog();
  }, [refreshCatalog]);
 
  const listModels = useCallback(
    async (provider: string, modelType: CostModelType | null = null) => {
      return await service.listModels(provider, modelType);
    },
    [service]
  );
 
  const estimateLocal = useCallback(
    async (req: CostEstimateRequest): Promise<CostEstimateLocal> => {
      setEstimating(true);
      setEstimateError(null);
      try {
        const out = await service.estimateLocal(req);
        setLastLocalEstimate(out);
        return out;
      } catch (e) {
        const msg = e instanceof Error ? e.message : 'Cost estimate failed';
        setEstimateError(msg);
        throw e;
      } finally {
        setEstimating(false);
      }
    },
    [service]
  );
 
  const estimateViaApi = useCallback(
    async (payload: CostEstimatePipelineRequest): Promise<CostEstimatePipelineResponse> => {
      setEstimating(true);
      setEstimateError(null);
      try {
        const out = await service.estimateViaApi(payload);
        setLastApiEstimate(out);
        return out;
      } catch (e) {
        const msg = e instanceof Error ? e.message : 'Cost estimate failed';
        setEstimateError(msg);
        throw e;
      } finally {
        setEstimating(false);
      }
    },
    [service]
  );
 
  return {
    // catalog
    providers: state.providers,
    modelsByProvider: state.modelsByProvider,
    loadingCatalog: state.loadingCatalog,
    catalogError: state.catalogError,
    refreshCatalog,
    listModels,
 
    // estimation
    estimating,
    estimateError,
    lastLocalEstimate,
    lastApiEstimate,
    estimateLocal,
    estimateViaApi,
  };
}

