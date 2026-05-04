import { useState, useEffect, useCallback } from 'react';
import { getAllTransactions } from '../api/client';
import TransactionTable from '../components/TransactionTable';
import Pagination from '../components/Pagination';

const PER_PAGE = 20;

export default function Transactions() {
  const [page, setPage] = useState(1);
  const [txs, setTxs] = useState<any[]>([]);
  const [total, setTotal] = useState(0);
  const [totalPages, setTotalPages] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [filters, setFilters] = useState({ sender: '', receiver: '', minAmount: '', maxAmount: '', block: '' });
  const [applied, setApplied] = useState(filters);

  const fetchData = useCallback(() => {
    setLoading(true);
    setError('');
    const params: any = { page, per_page: PER_PAGE };
    if (applied.sender) params.sender = applied.sender;
    if (applied.receiver) params.receiver = applied.receiver;
    if (applied.minAmount) params.min_amount = parseFloat(applied.minAmount);
    if (applied.maxAmount) params.max_amount = parseFloat(applied.maxAmount);
    if (applied.block) params.block = parseInt(applied.block);

    getAllTransactions(params)
      .then((res: any) => {
        setTxs(res.transactions || []);
        setTotal(res.total || 0);
        setTotalPages(res.total_pages || 1);
      })
      .catch((err: any) => setError(err.message || 'Erro ao carregar transações'))
      .finally(() => setLoading(false));
  }, [page, applied]);

  useEffect(() => { fetchData(); }, [fetchData]);

  const handleApply = () => {
    setPage(1);
    setApplied(filters);
  };

  return (
    <div className="max-w-6xl mx-auto space-y-4">
      <div>
        <h1 className="text-2xl font-bold text-kur-text">Transações</h1>
        <p className="text-sm text-kur-text-muted mt-1">{total} transações encontradas</p>
      </div>

      <div className="bg-kur-bg-card border border-kur-border rounded-lg p-4">
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-3">
          <input placeholder="Remetente" value={filters.sender}
            onChange={e => setFilters(p => ({ ...p, sender: e.target.value }))}
            className="bg-kur-bg border border-kur-border rounded px-3 py-2 text-sm text-kur-text placeholder-kur-text-muted focus:outline-none focus:border-kur-accent transition-colors" />
          <input placeholder="Destinatário" value={filters.receiver}
            onChange={e => setFilters(p => ({ ...p, receiver: e.target.value }))}
            className="bg-kur-bg border border-kur-border rounded px-3 py-2 text-sm text-kur-text placeholder-kur-text-muted focus:outline-none focus:border-kur-accent transition-colors" />
          <input placeholder="Valor min" type="number" value={filters.minAmount}
            onChange={e => setFilters(p => ({ ...p, minAmount: e.target.value }))}
            className="bg-kur-bg border border-kur-border rounded px-3 py-2 text-sm text-kur-text placeholder-kur-text-muted focus:outline-none focus:border-kur-accent transition-colors" />
          <input placeholder="Valor max" type="number" value={filters.maxAmount}
            onChange={e => setFilters(p => ({ ...p, maxAmount: e.target.value }))}
            className="bg-kur-bg border border-kur-border rounded px-3 py-2 text-sm text-kur-text placeholder-kur-text-muted focus:outline-none focus:border-kur-accent transition-colors" />
          <button onClick={handleApply}
            className="px-4 py-2 bg-kur-accent/10 text-kur-accent border border-kur-accent/30 rounded-lg hover:bg-kur-accent/20 transition-colors text-sm font-medium">
            Aplicar Filtros
          </button>
        </div>
      </div>

      {loading ? (
        <div className="bg-kur-bg-card border border-kur-border rounded-lg p-4">
          {Array.from({ length: 5 }).map((_, i) => <div key={i} className="skeleton h-12 w-full mb-3 last:mb-0" />)}
        </div>
      ) : error ? (
        <div className="flex flex-col items-center py-16">
          <p className="text-kur-red mb-4">{error}</p>
          <button onClick={fetchData} className="px-6 py-2 bg-kur-accent/10 text-kur-accent border border-kur-accent/30 rounded-lg hover:bg-kur-accent/20 transition-colors">
            Tentar novamente
          </button>
        </div>
      ) : txs.length === 0 ? (
        <div className="flex flex-col items-center py-16">
          <p className="text-kur-text-muted text-lg">Nenhuma transação encontrada</p>
        </div>
      ) : (
        <>
          <TransactionTable transactions={txs} />
          {totalPages > 1 && (
            <Pagination currentPage={page} totalPages={totalPages} onPageChange={setPage} />
          )}
        </>
      )}
    </div>
  );
}
