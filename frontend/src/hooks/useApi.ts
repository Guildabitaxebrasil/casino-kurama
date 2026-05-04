import { useState, useCallback, useRef, useEffect } from 'react';
import { usePolling as _usePolling } from './usePolling';
export const usePolling = _usePolling;

interface UseApiState<T> {
  data: T | null;
  error: string | null;
  loading: boolean;
}

export function useApi<T>(
  fetchFn: () => Promise<T>,
  deps: any[] = [],
  enabled: boolean = true
): UseApiState<T> & { refresh: () => void } {
  const [state, setState] = useState<UseApiState<T>>({
    data: null,
    error: null,
    loading: true,
  });
  const mountedRef = useRef(true);

  const execute = useCallback(async () => {
    if (!enabled) return;
    setState(prev => ({ ...prev, loading: true, error: null }));
    try {
      const data = await fetchFn();
      if (mountedRef.current) {
        setState({ data, error: null, loading: false });
      }
    } catch (err: any) {
      if (mountedRef.current) {
        setState({
          data: null,
          error: err?.response?.data?.error || err.message || 'Erro ao carregar dados',
          loading: false,
        });
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  useEffect(() => {
    mountedRef.current = true;
    execute();
    return () => { mountedRef.current = false; };
  }, [execute]);

  return { ...state, refresh: execute };
}

// Hook for paginated data
export function usePaginatedApi<T>(
  fetchFn: (page: number) => Promise<{ transactions: T[]; total: number; page: number; per_page: number; total_pages: number }>,
  deps: any[] = []
) {
  const [page, setPage] = useState(1);
  const apiState = useApi(() => fetchFn(page), [...deps, page]);

  return {
    ...apiState,
    page,
    setPage,
    nextPage: () => setPage(p => p + 1),
    prevPage: () => setPage(p => Math.max(1, p - 1)),
    goToPage: setPage,
  };
}

// Combined hook: auto-polls + manages loading/error/data state
export function usePolledApi<T>(
  fetchFn: () => Promise<T>,
  intervalMs: number,
  deps: any[] = []
) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const execute = useCallback(async () => {
    try {
      const result = await fetchFn();
      setData(result);
      setError(null);
    } catch (err: any) {
      const msg = err?.response?.data?.error || err.message || 'Erro ao carregar dados';
      setError(msg);
    } finally {
      setLoading(false);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  usePolling(execute, intervalMs);

  return { data, error, loading, refresh: execute };
}
