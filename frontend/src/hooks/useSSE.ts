/**
 * Hook de Server-Sent Events (SSE) para atualizacoes em tempo real.
 * Substitui o polling por conexao persistente SSE.
 *
 * Uso:
 *   useSSE('/api/events', {
 *     chain_updated: () => refreshChain(),
 *     mempool_updated: () => refreshMempool(),
 *   });
 */

import { useEffect, useRef } from 'react';

type SSEHandlers = Record<string, () => void>;

/**
 * Conecta a um endpoint SSE e executa callbacks para cada tipo de evento.
 * Reconexao automatica em caso de queda (com backoff exponencial).
 *
 * @param url URL do endpoint SSE (ex: '/api/events')
 * @param handlers Mapa de { event_type: callback }
 * @param enabled Se false, nao conecta
 */
export function useSSE(
  url: string,
  handlers: SSEHandlers,
  enabled: boolean = true
): void {
  const savedHandlers = useRef(handlers);
  const retryTimeoutRef = useRef<ReturnType<typeof setTimeout>>();
  const retryDelayRef = useRef(1000); // Comeca com 1s, max 30s

  useEffect(() => {
    savedHandlers.current = handlers;
  }, [handlers]);

  useEffect(() => {
    if (!enabled) return;

    let source: EventSource | null = null;
    let mounted = true;

    function connect() {
      if (!mounted) return;

      // Limpa timeout anterior
      if (retryTimeoutRef.current) {
        clearTimeout(retryTimeoutRef.current);
        retryTimeoutRef.current = undefined;
      }

      // Fecha conexao anterior
      if (source) {
        source.close();
      }

      source = new EventSource(url);

      source.onopen = () => {
        // Reset retry delay on successful connection
        retryDelayRef.current = 1000;
      };

      // Registra handlers para cada tipo de evento
      const handlerKeys = Object.keys(savedHandlers.current);

      for (const eventType of handlerKeys) {
        const handler = (e: MessageEvent) => {
          try {
            savedHandlers.current[eventType]?.();
          } catch {
            // Silencia erros nos callbacks
          }
        };
        source.addEventListener(eventType, handler);
      }

      source.onerror = () => {
        // Fecha e agenda reconexao com backoff exponencial
        if (source) {
          source.close();
          source = null;
        }

        if (mounted) {
          const delay = retryDelayRef.current;
          retryDelayRef.current = Math.min(delay * 2, 30000); // Max 30s
          retryTimeoutRef.current = setTimeout(connect, delay);
        }
      };
    }

    connect();

    return () => {
      mounted = false;
      if (retryTimeoutRef.current) {
        clearTimeout(retryTimeoutRef.current);
      }
      if (source) {
        source.close();
      }
    };
  }, [url, enabled]);
}

// Tambem exporta a funcao de polling padrao para compatibilidade
// com paginas que precisam de ambos
export { usePolling } from './usePolling';
