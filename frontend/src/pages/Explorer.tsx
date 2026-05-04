import { useState, useMemo, useEffect } from 'react';
import { useApi } from '../hooks/useApi';
import { getChain } from '../api/client';
import Pagination from '../components/Pagination';
import BlockCard from '../components/BlockCard';
import LoadingSpinner from '../components/LoadingSpinner';

export default function Explorer() {
  const [page, setPage] = useState(1);
  const { data, loading, error, refresh } = useApi(() => getChain(), []);

  const blocks = useMemo(() => {
    if (!data) return [];
    return [...data.chain].reverse();
  }, [data]);

  const totalPages = Math.max(1, Math.ceil(blocks.length / 10));

  const pageBlocks = useMemo(() => {
    const start = (page - 1) * 10;
    return blocks.slice(start, start + 10);
  }, [blocks, page]);

  const totalTx = useMemo(() => {
    return (data?.chain || []).reduce((sum: number, b: any) => sum + (b.transactions?.length || 0), 0);
  }, [data]);

  useEffect(() => {
    if (page > totalPages && totalPages > 0) setPage(totalPages);
  }, [page, totalPages]);

  if (loading && !data) {
    return (
      <div className="max-w-4xl mx-auto space-y-4">
        <div className="skeleton h-8 w-48 mb-4" />
        {Array.from({ length: 5 }).map((_, i) => <div key={i} className="skeleton h-24 w-full" />)}
      </div>
    );
  }

  if (error && !data) {
    return (
      <div className="max-w-4xl mx-auto flex flex-col items-center py-20">
        <p className="text-kur-red text-lg mb-4">Erro ao carregar blocos</p>
        <p className="text-kur-text-muted text-sm mb-6">{error}</p>
        <button onClick={refresh} className="px-6 py-2 bg-kur-accent/10 text-kur-accent border border-kur-accent/30 rounded-lg hover:bg-kur-accent/20 transition-colors">
          Tentar novamente
        </button>
      </div>
    );
  }

  if (!data || data.chain.length === 0) {
    return (
      <div className="max-w-4xl mx-auto flex flex-col items-center py-20">
        <p className="text-4xl mb-4">⛓️</p>
        <p className="text-kur-text-muted text-lg">Nenhum bloco ainda. Crie uma transação e minere!</p>
      </div>
    );
  }

  return (
    <div className="max-w-4xl mx-auto space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-kur-text">Blockchain Explorer</h1>
          <p className="text-sm text-kur-text-muted mt-1">
            {data.chain.length} blocos · {totalTx} transações
          </p>
        </div>
      </div>

      {totalPages > 1 && (
        <Pagination currentPage={page} totalPages={totalPages} onPageChange={setPage} />
      )}

      <div className="space-y-3">
        {pageBlocks.map((block: any) => (
          <BlockCard key={block.index} block={block} />
        ))}
      </div>

      {totalPages > 1 && (
        <Pagination currentPage={page} totalPages={totalPages} onPageChange={setPage} />
      )}
    </div>
  );
}
