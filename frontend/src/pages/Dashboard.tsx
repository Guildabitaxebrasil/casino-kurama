import { useApi } from '../hooks/useApi';
import { useSSE } from '../hooks/useSSE';
import ChainGrowthChart from '../components/ChainGrowthChart';
import MempoolWidget from '../components/MempoolWidget';
import BlockCard from '../components/BlockCard';
import StatCard from '../components/StatCard';
import LoadingSpinner from '../components/LoadingSpinner';
import { getStats, getChartData, getChain, getMempoolStats } from '../api/client';

export default function Dashboard() {
  const { data: stats, loading: statsLoading, error: statsError, refresh: refreshStats } = useApi(() => getStats(), []);
  const { data: chart, loading: chartLoading } = useApi(() => getChartData(30), []);
  const { data: chain, loading: chainLoading, error: chainError, refresh: refreshChain } = useApi(() => getChain(), []);
  const { data: mempool, loading: mempoolLoading } = useApi(() => getMempoolStats(), []);

  // Tempo real via SSE em vez de polling
  useSSE('/api/events', {
    chain_updated: () => { refreshStats(); refreshChain(); },
    mempool_updated: () => { refreshStats(); },
  });

  const isLoading = statsLoading || chainLoading;
  const hasError = statsError || chainError;

  if (isLoading) {
    return (
      <div className="max-w-full overflow-x-hidden">
        <h1 className="text-xl sm:text-2xl font-bold text-kur-text mb-4 sm:mb-6">Dashboard</h1>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
          {[1,2,3,4].map(i => (
            <div key={i} className="bg-kur-bg-card border border-kur-border rounded-xl p-5 animate-pulse">
              <div className="h-4 w-24 bg-kur-bg-hover rounded mb-3" />
              <div className="h-8 w-20 bg-kur-bg-hover rounded" />
            </div>
          ))}
        </div>
        <div className="bg-kur-bg-card border border-kur-border rounded-xl p-5 animate-pulse">
          <div className="h-[300px] bg-kur-bg-hover rounded" />
        </div>
      </div>
    );
  }

  if (hasError) {
    return (
      <div className="flex flex-col items-center justify-center py-20">
        <p className="text-kur-red text-lg mb-4">Erro ao carregar dados da blockchain</p>
        <p className="text-kur-text-muted text-sm mb-6">{statsError || chainError}</p>
        <button onClick={() => { refreshStats(); refreshChain(); }}
          className="px-6 py-2 bg-kur-accent/10 text-kur-accent border border-kur-accent/30 rounded-lg hover:bg-kur-accent/20 transition-colors">
          Tentar novamente
        </button>
      </div>
    );
  }

  const s = stats || {} as any;
  const blocks = chain?.chain || [];
  const recentBlocks = blocks.slice(-5).reverse();
  const chartData = chart || [];

  return (
    <div className="max-w-full overflow-x-hidden">
      <h1 className="text-xl sm:text-2xl font-bold text-kur-text mb-4 sm:mb-6">Dashboard</h1>

      <div className="grid grid-cols-2 sm:grid-cols-2 lg:grid-cols-4 gap-3 sm:gap-4 mb-4">
        <StatCard title="Blocos" value={s.blocks ?? 0} icon="📦" accent="text-kur-accent" />
        <StatCard title="Transações" value={s.total_transactions ?? 0} icon="📝" accent="text-kur-green" />
        <StatCard title="Supply" value={`${(s.total_supply ?? 0).toLocaleString()}`} icon="🪙" subtitle={s.token_symbol || 'KUR'} accent="text-kur-yellow" />
        <StatCard title="Dificuldade" value={s.difficulty ?? 0} icon="⚡" accent="text-kur-orange" />
      </div>

      {/* Supply progress bar */}
      <div className="bg-kur-bg-card border border-kur-border rounded-xl p-3 sm:p-4 mb-6">
        <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-1 mb-2">
          <span className="text-xs sm:text-sm text-kur-text-muted">
            {s.token_name || 'Kurama'} ({s.token_symbol || 'KUR'}) — Fornecimento
          </span>
          <span className="text-xs sm:text-sm font-semibold text-kur-text">
            {((s.total_supply ?? 0) / 1_000_000).toFixed(2)}M / {(s.supply_cap ?? 0) / 1_000_000}M
          </span>
        </div>
        <div className="w-full bg-kur-bg-hover rounded-full h-2 sm:h-3">
          <div
            className="bg-gradient-to-r from-kur-accent to-kur-green h-full rounded-full transition-all duration-500"
            style={{ width: `${Math.min(100, s.percent_mined ?? 0)}%` }}
          />
        </div>
        <div className="flex justify-between mt-1 sm:mt-2 text-[10px] sm:text-xs text-kur-text-muted">
          <span>0</span>
          <span>{(s.supply_cap ?? 0) / 2_000_000}M</span>
          <span>{(s.supply_cap ?? 0) / 1_000_000}M</span>
        </div>
        <div className="mt-2 text-center">
          <span className="text-xs text-kur-text-muted">{s.percent_mined ?? 0}% minerado</span>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 sm:gap-6 mb-6">
        <div className="lg:col-span-2 bg-kur-bg-card border border-kur-border rounded-xl p-3 sm:p-5 overflow-x-auto">
          <h2 className="text-base sm:text-lg font-semibold text-kur-text mb-3 sm:mb-4">📈 Crescimento da Blockchain</h2>
          {chartData.length > 0 ? (
            <div className="min-w-[400px] sm:min-w-0">
              <ChainGrowthChart data={chartData} loading={chartLoading} />
            </div>
          ) : (
            <p className="text-kur-text-muted text-sm py-8 sm:py-10 text-center">Nenhum dado de gráfico disponível</p>
          )}
        </div>

        <div className="bg-kur-bg-card border border-kur-border rounded-xl p-3 sm:p-5">
          <h2 className="text-base sm:text-lg font-semibold text-kur-text mb-3 sm:mb-4">🔄 Mempool</h2>
          <MempoolWidget stats={mempool} loading={mempoolLoading} />
        </div>
      </div>

      <div className="bg-kur-bg-card border border-kur-border rounded-xl p-5">
        <h2 className="text-lg font-semibold text-kur-text mb-4">🔗 Blocos Recentes</h2>
        {recentBlocks.length === 0 ? (
          <p className="text-kur-text-muted text-sm py-6 text-center">
            Nenhum bloco ainda. Crie uma transação e rode o minerador!
          </p>
        ) : (
          <div className="space-y-3">
            {recentBlocks.map((block: any) => (
              <BlockCard key={block.index} block={block} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
