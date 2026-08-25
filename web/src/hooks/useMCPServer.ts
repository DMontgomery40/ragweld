import { useCallback, useEffect, useMemo, useState } from 'react';
import { useAPI } from '@/hooks/useAPI';
import { MCPServerService } from '@/services/MCPServerService';
import type { MCPRagSearchResponse, MCPStatusResponse } from '@/types/generated';

type MCPServerState = {
  status: MCPStatusResponse | null;
  probe: MCPRagSearchResponse | null;
  probeQuestion: string | null;
  loading: boolean;
  probing: boolean;
  error: string | null;
};

export function useMCPServer() {
  const { api } = useAPI();
  const service = useMemo(() => new MCPServerService(api), [api]);
  const [state, setState] = useState<MCPServerState>({
    status: null,
    probe: null,
    probeQuestion: null,
    loading: false,
    probing: false,
    error: null,
  });

  const clearError = useCallback(() => setState((s) => ({ ...s, error: null })), []);

  const refresh = useCallback(async () => {
    setState((s) => ({ ...s, loading: true, error: null }));
    try {
      const status = await service.getStatus();
      setState((s) => ({ ...s, status, loading: false }));
      return status;
    } catch (e) {
      const msg = e instanceof Error ? e.message : 'Failed to load MCP status';
      setState((s) => ({ ...s, loading: false, error: msg, status: null }));
      return null;
    }
  }, [service]);

  const probeSearch = useCallback(
    async (question: string, corpusId: string) => {
      setState((s) => ({ ...s, probing: true, error: null }));
      try {
        const probe = await service.probeSearch(question, corpusId);
        setState((s) => ({ ...s, probe, probeQuestion: question, probing: false }));
        return probe;
      } catch (e) {
        const msg = e instanceof Error ? e.message : 'MCP search probe failed';
        setState((s) => ({ ...s, probing: false, error: msg }));
        throw e;
      }
    },
    [service]
  );

  useEffect(() => {
    void refresh();
    const id = setInterval(() => void refresh(), 30000);
    return () => clearInterval(id);
  }, [refresh]);

  return {
    status: state.status,
    probe: state.probe,
    probeQuestion: state.probeQuestion,
    loading: state.loading,
    probing: state.probing,
    error: state.error,
    clearError,
    refresh,
    probeSearch,
  };
}
