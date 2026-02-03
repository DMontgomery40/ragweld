import { useCallback, useEffect, useMemo, useState } from 'react';
import { useAPI } from '@/hooks/useAPI';
import { MCPServerService, type MCPActionResponse, type MCPHttpStatusResponse, type MCPStdioTestResponse } from '@/services/MCPServerService';
import type { MCPStatusResponse } from '@/types/generated';

type MCPServerState = {
  status: MCPStatusResponse | null;
  httpStatus: MCPHttpStatusResponse | null;
  stdioTest: MCPStdioTestResponse | null;
  loading: boolean;
  error: string | null;
  lastAction: MCPActionResponse | null;
};

export function useMCPServer() {
  const { api } = useAPI();
  const service = useMemo(() => new MCPServerService(api), [api]);

  const [state, setState] = useState<MCPServerState>({
    status: null,
    httpStatus: null,
    stdioTest: null,
    loading: false,
    error: null,
    lastAction: null,
  });

  const clearError = useCallback(() => setState((s) => ({ ...s, error: null })), []);

  const refresh = useCallback(async () => {
    setState((s) => ({ ...s, loading: true, error: null }));
    try {
      const [status, httpStatus] = await Promise.all([service.getStatus(), service.getHttpStatus().catch(() => null)]);
      setState((s) => ({ ...s, status, httpStatus, loading: false }));
      return { status, httpStatus };
    } catch (e) {
      const msg = e instanceof Error ? e.message : 'Failed to load MCP status';
      setState((s) => ({ ...s, loading: false, error: msg, status: null }));
      throw e;
    }
  }, [service]);

  const startHttp = useCallback(async () => {
    setState((s) => ({ ...s, loading: true, error: null }));
    try {
      const res = await service.startHttp();
      setState((s) => ({ ...s, lastAction: res, loading: false }));
      await refresh();
      return res;
    } catch (e) {
      const msg = e instanceof Error ? e.message : 'Failed to start MCP HTTP';
      setState((s) => ({ ...s, loading: false, error: msg }));
      throw e;
    }
  }, [refresh, service]);

  const stopHttp = useCallback(async () => {
    setState((s) => ({ ...s, loading: true, error: null }));
    try {
      const res = await service.stopHttp();
      setState((s) => ({ ...s, lastAction: res, loading: false }));
      await refresh();
      return res;
    } catch (e) {
      const msg = e instanceof Error ? e.message : 'Failed to stop MCP HTTP';
      setState((s) => ({ ...s, loading: false, error: msg }));
      throw e;
    }
  }, [refresh, service]);

  const restartHttp = useCallback(async () => {
    setState((s) => ({ ...s, loading: true, error: null }));
    try {
      const res = await service.restartHttp();
      setState((s) => ({ ...s, lastAction: res, loading: false }));
      await refresh();
      return res;
    } catch (e) {
      const msg = e instanceof Error ? e.message : 'Failed to restart MCP HTTP';
      setState((s) => ({ ...s, loading: false, error: msg }));
      throw e;
    }
  }, [refresh, service]);

  const testStdio = useCallback(async () => {
    setState((s) => ({ ...s, loading: true, error: null }));
    try {
      const res = await service.testStdio();
      setState((s) => ({ ...s, stdioTest: res, loading: false }));
      return res;
    } catch (e) {
      const msg = e instanceof Error ? e.message : 'Failed to test stdio MCP';
      setState((s) => ({ ...s, loading: false, error: msg }));
      throw e;
    }
  }, [service]);

  useEffect(() => {
    void refresh();
    const id = setInterval(() => void refresh(), 30000);
    return () => clearInterval(id);
  }, [refresh]);

  return {
    status: state.status,
    httpStatus: state.httpStatus,
    stdioTestResult: state.stdioTest,
    loading: state.loading,
    error: state.error,
    lastAction: state.lastAction,
    clearError,
    refresh,
    startHttp,
    stopHttp,
    restartHttp,
    testStdio,
  };
}

