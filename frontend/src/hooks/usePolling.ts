import { useEffect, useRef } from 'react';

export function usePolling(callback: () => void, intervalMs: number, enabled: boolean = true) {
  const savedCallback = useRef(callback);

  useEffect(() => {
    savedCallback.current = callback;
  }, [callback]);

  useEffect(() => {
    if (!enabled) return;

    savedCallback.current();

    const interval = setInterval(() => {
      savedCallback.current();
    }, intervalMs);

    return () => clearInterval(interval);
  }, [intervalMs, enabled]);
}
