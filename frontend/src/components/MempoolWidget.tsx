import type { MempoolStats } from '../api/types';
import LoadingSpinner from './LoadingSpinner';

interface Props {
  stats: MempoolStats | null;
  loading: boolean;
}

function formatAge(seconds: number): string {
  if (seconds < 60) return `${seconds}s atrás`;
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${m}m ${s}s atrás`;
}

export default function MempoolWidget({ stats, loading }: Props) {
  if (loading) {
    return (
      <div className="animate-pulse space-y-3">
        <div className="h-16 bg-kur-bg-card rounded-lg" />
        <div className="h-10 bg-kur-bg-card rounded-lg" />
        <div className="h-10 bg-kur-bg-card rounded-lg" />
      </div>
    );
  }

  if (!stats || stats.total === 0) {
    return (
      <div className="text-center py-8 text-kur-text-muted">
        <p className="text-lg mb-1">Mempool vazia</p>
        <p className="text-sm">Nenhuma transação pendente no momento</p>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <div className="text-center">
        <p className="text-4xl font-bold text-kur-yellow font-mono">{stats.total}</p>
        <p className="text-xs text-kur-text-muted mt-1">Transações Pendentes</p>
      </div>

      <div className="grid grid-cols-2 gap-3 text-sm">
        <div className="bg-kur-bg rounded-lg p-3">
          <p className="text-kur-text-muted text-xs mb-1">Mínimo</p>
          <p className="text-kur-text font-mono font-medium">{stats.min_value.toFixed(2)}</p>
        </div>
        <div className="bg-kur-bg rounded-lg p-3">
          <p className="text-kur-text-muted text-xs mb-1">Máximo</p>
          <p className="text-kur-text font-mono font-medium">{stats.max_value.toFixed(2)}</p>
        </div>
        <div className="bg-kur-bg rounded-lg p-3">
          <p className="text-kur-text-muted text-xs mb-1">Média</p>
          <p className="text-kur-text font-mono font-medium">{stats.avg_value.toFixed(2)}</p>
        </div>
        <div className="bg-kur-bg rounded-lg p-3">
          <p className="text-kur-text-muted text-xs mb-1">Mais Antiga</p>
          <p className="text-kur-text font-mono font-medium text-xs">{formatAge(stats.oldest_tx)}</p>
        </div>
      </div>

      {stats.coinbase_count > 0 && (
        <p className="text-xs text-kur-text-muted text-center">
          Inclui {stats.coinbase_count} transação(ões) coinbase
        </p>
      )}
    </div>
  );
}
