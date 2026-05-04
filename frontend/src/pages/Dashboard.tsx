import { useState, useEffect } from 'react';
import { useApi, usePolling } from '../hooks/useApi';
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

  usePolling(refreshStats, 5000);
  usePolling(refreshChain, 5000);

  const isLoading = statsLoading || chainLoading;
  const hasError = statsError || chainError;

  if (isLoading) {
    return (
      <div>
        <h1 className="text-2xl font-bold text-kur-text mb-6">Dashboard</h1>
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
    <div>
      <h1 className="text-2xl font-bold text-kur-text mb-6">Dashboard</h1>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
        <StatCard title="Total de Blocos" value={s.total_blocks ?? 0} icon="📦" accent="text-kur-accent" />
        <StatCard title="Total de Transações" value={s.total_transactions ?? 0} icon="📝" accent="text-kur-green" />
        <StatCard title="Nós Ativos" value={s.active_nodes ?? 0} icon="🌐" accent="text-kur-purple" />
        <StatCard title="Dificuldade" value={s.difficulty ?? 0} icon="⚡" accent="text-kur-yellow" />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 mb-8">
        <div className="lg:col-span-2 bg-kur-bg-card border border-kur-border rounded-xl p-5">
          <h2 className="text-lg font-semibold text-kur-text mb-4">📈 Crescimento da Blockchain</h2>
          {chartData.length > 0 ? (
            <ChainGrowthChart data={chartData} loading={chartLoading} />
          ) : (
            <p className="text-kur-text-muted text-sm py-10 text-center">Nenhum dado de gráfico disponível</p>
          )}
        </div>

        <div className="bg-kur-bg-card border border-kur-border rounded-xl p-5">
          <h2 className="text-lg font-semibold text-kur-text mb-4">🔄 Mempool</h2>
          <MempoolWidget stats={mempool} loading={mempoolLoading} />
        </div>
      </div>

      <div className="bg-kur-bg-card border border-kur-border rounded-xl p-5">
        <h2 className="text-lg font-semibold text-kur-text mb-4">🔗 Blocos Recentes</h2>
        {recentBlocks.length === 0 ? (
          <p className="text-kur-text-muted text-sm py-6 text-center">
            Nenhum bloco ainda. Crie uma transação e minere!
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
