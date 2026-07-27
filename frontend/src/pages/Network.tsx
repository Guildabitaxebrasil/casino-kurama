import { useApi } from '../hooks/useApi';
import { useSSE } from '../hooks/useSSE';
import { getNodes } from '../api/client';

export default function Network() {
  const { data, loading, error, refresh } = useApi(() => getNodes(), []);
  useSSE('/api/events', {
    chain_updated: () => refresh(),
  });

  if (loading && !data) {
    return <div className="skeleton h-96 w-full rounded-xl" />;
  }

  if (error && !data) {
    return (
      <div className="flex flex-col items-center py-20">
        <p className="text-kur-red text-lg mb-4">Erro ao carregar rede</p>
        <p className="text-kur-text-muted text-sm mb-6">{error}</p>
        <button onClick={refresh}
          className="px-6 py-2 bg-kur-accent/10 text-kur-accent border border-kur-accent/30 rounded-lg hover:bg-kur-accent/20 transition-colors">
          Tentar novamente
        </button>
      </div>
    );
  }

  const nodeList = data?.nodes || [];
  const total = data?.total ?? nodeList.length;
  const active = data?.active ?? nodeList.filter((n: any) => n.active).length;
  const inactive = total - active;

  return (
    <div className="max-w-6xl mx-auto space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-kur-text">Visão da Rede</h1>
          <p className="text-sm text-kur-text-muted mt-1">{total} nós na rede</p>
        </div>
        <div className="flex items-center gap-2 text-sm text-kur-accent">
          <span className="w-2 h-2 rounded-full bg-kur-green animate-pulse" />
          {active} ativos
        </div>
      </div>

      <div className="bg-kur-bg-card border border-kur-border rounded-xl p-6">
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-6">
          <div className="text-center p-4 rounded-lg bg-kur-bg/50">
            <p className="text-kur-text-muted text-xs uppercase tracking-wider">Total</p>
            <p className="text-2xl font-bold text-kur-text mt-1">{total}</p>
          </div>
          <div className="text-center p-4 rounded-lg bg-kur-bg/50">
            <p className="text-kur-text-muted text-xs uppercase tracking-wider">Ativos</p>
            <p className="text-2xl font-bold text-kur-green mt-1">{active}</p>
          </div>
          <div className="text-center p-4 rounded-lg bg-kur-bg/50">
            <p className="text-kur-text-muted text-xs uppercase tracking-wider">Inativos</p>
            <p className="text-2xl font-bold text-kur-red mt-1">{inactive}</p>
          </div>
        </div>
      </div>

      {nodeList.length === 0 ? (
        <div className="bg-kur-bg-card border border-kur-border rounded-xl p-16 text-center">
          <p className="text-4xl mb-4">🌐</p>
          <p className="text-kur-text-muted text-lg">Nenhum nó conectado</p>
          <p className="text-kur-text-muted text-sm mt-2">
            Registre nós para construir a rede P2P
          </p>
        </div>
      ) : (
        <div className="bg-kur-bg-card border border-kur-border rounded-xl overflow-hidden">
          <table className="w-full">
            <thead>
              <tr className="border-b border-kur-border">
                <th className="py-3 px-4 text-left text-xs font-medium text-kur-text-muted uppercase tracking-wider">Nó</th>
                <th className="py-3 px-4 text-left text-xs font-medium text-kur-text-muted uppercase tracking-wider">URL</th>
                <th className="py-3 px-4 text-right text-xs font-medium text-kur-text-muted uppercase tracking-wider">Blocos</th>
                <th className="py-3 px-4 text-right text-xs font-medium text-kur-text-muted uppercase tracking-wider">Latência</th>
                <th className="py-3 px-4 text-right text-xs font-medium text-kur-text-muted uppercase tracking-wider">Dif.</th>
                <th className="py-3 px-4 text-center text-xs font-medium text-kur-text-muted uppercase tracking-wider">Status</th>
              </tr>
            </thead>
            <tbody>
              {nodeList.map((node) => (
                <tr key={node.node_id} className="border-t border-kur-border hover:bg-kur-bg-hover transition-colors">
                  <td className="py-3 px-4">
                    <span className="font-mono text-xs text-kur-accent">
                      {node.node_id?.slice(0, 16)}...
                    </span>
                  </td>
                  <td className="py-3 px-4 font-mono text-xs text-kur-text">{node.url}</td>
                  <td className="py-3 px-4 text-right font-mono text-kur-text">{node.blocks ?? '-'}</td>
                  <td className="py-3 px-4 text-right font-mono text-xs text-kur-text-muted">
                    {node.latency_ms != null ? `${node.latency_ms}ms` : '-'}
                  </td>
                  <td className="py-3 px-4 text-right font-mono text-kur-text">{node.difficulty ?? '-'}</td>
                  <td className="py-3 px-4 text-center">
                    <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium ${
                      node.active
                        ? 'bg-kur-green/10 text-kur-green'
                        : 'bg-kur-red/10 text-kur-red'
                    }`}>
                      <span className={`w-1.5 h-1.5 rounded-full ${node.active ? 'bg-kur-green' : 'bg-kur-red'}`} />
                      {node.active ? 'Online' : 'Offline'}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
