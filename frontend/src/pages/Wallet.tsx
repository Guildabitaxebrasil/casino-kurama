import { useState, useEffect } from 'react';
import TransactionTable from '../components/TransactionTable';
import { getBalance, newWallet, getAllTransactions } from '../api/client';
import { saveWallet } from '../utils/walletStorage';
import { getCachedBalance, setCachedBalance } from '../utils/balanceCache';
import { useWallet } from '../context/WalletContext';
import type { Transaction } from '../api/types';

export default function Wallet() {
  const { currentAddress, isConnected, connect } = useWallet();
  const [address, setAddress] = useState('');
  const [queryAddress, setQueryAddress] = useState('');
  const [balance, setBalance] = useState<number | null>(null);
  const [sentTxs, setSentTxs] = useState<any[]>([]);
  const [receivedTxs, setReceivedTxs] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [showWallet, setShowWallet] = useState(false);
  const [generatedWallet, setGeneratedWallet] = useState<any>(null);

  // Se tem uma carteira conectada, carrega automaticamente
  useEffect(() => {
    if (isConnected && currentAddress && !queryAddress) {
      setAddress(currentAddress);
      setQueryAddress(currentAddress);
    }
  }, [isConnected, currentAddress]);

  const fetchWalletData = (addr: string) => {
    setLoading(true);
    setError('');
    setShowWallet(false);

    // Tenta cache primeiro
    const cached = getCachedBalance(addr);
    if (cached !== null) {
      setBalance(cached);
    }

    Promise.all([
      getBalance(addr).catch(() => ({ balance: 0 } as any)),
      getAllTransactions({ sender: addr }).catch(() => ({ transactions: [] })),
      getAllTransactions({ receiver: addr }).catch(() => ({ transactions: [] })),
    ])
      .then(([bal, sent, recv]) => {
        const balance = (bal as any).balance ?? 0;
        setBalance(balance);
        setCachedBalance(addr, balance); // Atualiza cache
        setSentTxs((sent as any).transactions || []);
        setReceivedTxs((recv as any).transactions || []);
      })
      .catch((err: any) => setError(err.message || 'Erro ao consultar endereço'))
      .finally(() => setLoading(false));
  };

  const handleSearch = () => {
    if (!address.trim()) return;
    setQueryAddress(address.trim());
    fetchWalletData(address.trim());
  };

  const handleGenerate = async () => {
    try {
      const wallet = await newWallet();
      setGeneratedWallet(wallet);
      setAddress(wallet.address);
      setShowWallet(true);
      // Salva no localStorage para usar no SendTransaction
      saveWallet({
        address: wallet.address,
        public_key: wallet.public_key_pem || '',
        private_key_pem: wallet.private_key_pem || '',
        label: `Carteira #${Date.now() % 10000}`,
        created_at: Date.now(),
      });
      // Conecta automaticamente
      connect(wallet.address, wallet.private_key_pem, wallet.public_key_pem);
    } catch (err: any) {
      setError(err.message || 'Erro ao gerar carteira');
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') handleSearch();
  };

  const allTxs = [...sentTxs.map((t: any) => ({ ...t, _direction: 'sent' as const })),
    ...receivedTxs.map((t: any) => ({ ...t, _direction: 'received' as const }))]
    .sort((a, b) => (b.timestamp || 0) - (a.timestamp || 0));

  return (
    <div>
      <h1 className="text-2xl font-bold text-kur-text mb-6">Carteira</h1>

      <div className="bg-kur-bg-card border border-kur-border rounded-xl p-5 mb-6">
        <div className="flex flex-col sm:flex-row gap-3 mb-4">
          <input placeholder="Digite um endereço da blockchain..." value={address}
            onChange={e => setAddress(e.target.value)} onKeyDown={handleKeyDown}
            className="flex-1 bg-kur-bg border border-kur-border rounded-lg px-4 py-2.5 text-sm text-kur-text placeholder-kur-text-muted font-mono focus:outline-none focus:border-kur-accent" />
          <button onClick={handleSearch}
            className="px-6 py-2.5 bg-kur-accent/10 text-kur-accent border border-kur-accent/30 rounded-lg hover:bg-kur-accent/20 transition-colors text-sm font-medium whitespace-nowrap">
            Consultar
          </button>
          <button onClick={handleGenerate}
            className="px-6 py-2.5 bg-kur-green/10 text-kur-green border border-kur-green/30 rounded-lg hover:bg-kur-green/20 transition-colors text-sm font-medium whitespace-nowrap">
            + Gerar Carteira
          </button>
        </div>          {isConnected && queryAddress === currentAddress && (
            <div className="bg-kur-green/5 border border-kur-green/20 rounded-lg p-3 mb-4">
              <p className="text-xs text-kur-green font-medium">🔗 Carteira conectada</p>
              <p className="text-[10px] font-mono text-kur-text-muted mt-0.5">Usando carteira do topo da página</p>
            </div>
          )}

          {showWallet && generatedWallet && (
            <div className="bg-kur-bg rounded-lg p-4 border border-kur-border">
              <p className="text-kur-text-muted text-xs uppercase tracking-wider mb-2">Nova Carteira Gerada</p>
              <div className="space-y-1 text-sm">
                <div><span className="text-kur-text-muted">Endereço: </span><span className="text-kur-text font-mono text-xs">{generatedWallet.address}</span></div>
                <div><span className="text-kur-text-muted">Chave Privada: </span><span className="text-kur-text font-mono text-xs">{generatedWallet.private_key_pem?.slice(0, 40)}...</span></div>
              </div>
              <p className="text-kur-yellow text-xs mt-3">⚠ Guarde a chave privada com segurança! Ela foi salva no navegador para uso no formulário de envio.</p>
            </div>
          )}
      </div>

      {!queryAddress ? (
        <div className="flex flex-col items-center py-16">
          <p className="text-kur-text-muted text-lg">Digite um endereço ou gere uma nova carteira</p>
        </div>
      ) : loading ? (
        <div className="space-y-4">
          <div className="bg-kur-bg-card border border-kur-border rounded-xl p-6 animate-pulse">
            <div className="h-4 w-16 bg-kur-bg-hover rounded mb-3" />
            <div className="h-8 w-40 bg-kur-bg-hover rounded" />
          </div>
          <div className="bg-kur-bg-card border border-kur-border rounded-xl p-5 animate-pulse">
            {[1,2,3].map(i => <div key={i} className="h-12 bg-kur-bg-hover rounded mb-3 last:mb-0" />)}
          </div>
        </div>
      ) : error ? (
        <div className="flex flex-col items-center py-12">
          <p className="text-kur-red mb-4">{error}</p>
          <button onClick={() => fetchWalletData(queryAddress)}
            className="px-6 py-2 bg-kur-accent/10 text-kur-accent border border-kur-accent/30 rounded-lg hover:bg-kur-accent/20">
            Tentar novamente
          </button>
        </div>
      ) : (
        <div className="space-y-6">
          <div className="bg-kur-bg-card border border-kur-border rounded-xl p-6">
            <p className="text-kur-text-muted text-xs uppercase tracking-wider mb-1">Saldo</p>
            <p className="text-4xl font-bold text-kur-accent font-mono">
              {balance?.toFixed(2) || '0.00'} <span className="text-lg text-kur-text-muted">KUR</span>
            </p>
            <p className="text-kur-text-muted text-xs font-mono mt-2 break-all">{queryAddress}</p>
          </div>

          {allTxs.length === 0 ? (
            <div className="bg-kur-bg-card border border-kur-border rounded-xl p-8 text-center">
              <p className="text-kur-text-muted">Nenhuma transação para este endereço</p>
            </div>
          ) : (
            <div className="bg-kur-bg-card border border-kur-border rounded-xl p-5">
              <h2 className="text-lg font-semibold text-kur-text mb-4">Histórico de Transações ({allTxs.length})</h2>
              <TransactionTable transactions={allTxs} showBlock />
            </div>
          )}
        </div>
      )}
    </div>
  );
}
