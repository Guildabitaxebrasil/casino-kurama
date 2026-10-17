import { useCallback, useEffect, useState } from 'react';
import {
  connectMetaMask,
  ensureKuramaChain,
  formatKur,
  getEvmBalance,
  getEvmProvider,
  isMetaMaskInstalled,
  KURAMA_CHAIN_ID,
  kuramaRpcUrl,
  shortAddress,
} from '../api/metamask';

/**
 * Card de conexão MetaMask (Fase 6): adiciona/troca para a KuramaChain,
 * mostra endereço/chain/saldo e avisa quando a wallet está fora da rede.
 */
export default function MetaMaskCard() {
  const [address, setAddress] = useState<string | null>(null);
  const [chainId, setChainId] = useState<number | null>(null);
  const [balance, setBalance] = useState<bigint | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const installed = isMetaMaskInstalled();

  const refresh = useCallback(async (account: string | null) => {
    if (!account) {
      setBalance(null);
      return;
    }
    try {
      const eth = getEvmProvider();
      if (eth) {
        const hex = (await eth.request({ method: 'eth_chainId' })) as string;
        setChainId(parseInt(hex, 16));
      }
      setBalance(await getEvmBalance(account));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Erro ao ler a conta');
    }
  }, []);

  // Reconecta silenciosamente se a wallet já autorizou esta origem.
  useEffect(() => {
    const eth = getEvmProvider();
    if (!eth) return;
    eth.request({ method: 'eth_accounts' })
      .then((accounts) => {
        const list = accounts as string[];
        if (list?.length) {
          setAddress(list[0]);
          void refresh(list[0]);
        }
      })
      .catch(() => undefined);
  }, [refresh]);

  // Acompanha troca de conta/rede na wallet.
  useEffect(() => {
    const eth = getEvmProvider();
    if (!eth?.on) return;
    const onAccounts = (...args: unknown[]) => {
      const list = (args[0] as string[]) ?? [];
      setAddress(list[0] ?? null);
      void refresh(list[0] ?? null);
    };
    const onChain = (...args: unknown[]) => {
      const hex = args[0] as string;
      setChainId(parseInt(hex, 16));
    };
    eth.on('accountsChanged', onAccounts);
    eth.on('chainChanged', onChain);
    return () => {
      eth.removeListener?.('accountsChanged', onAccounts);
      eth.removeListener?.('chainChanged', onChain);
    };
  }, [refresh]);

  const handleConnect = async () => {
    setLoading(true);
    setError(null);
    try {
      const account = await connectMetaMask();
      setAddress(account);
      await refresh(account);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Falha ao conectar a MetaMask');
    } finally {
      setLoading(false);
    }
  };

  const handleSwitch = async () => {
    setLoading(true);
    setError(null);
    try {
      await ensureKuramaChain();
      await refresh(address);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Falha ao trocar de rede');
    } finally {
      setLoading(false);
    }
  };

  const onKuramaChain = chainId === KURAMA_CHAIN_ID;

  return (
    <div className="bg-kur-bg-card border border-kur-border rounded-xl p-4 sm:p-5 mb-6">
      <div className="flex items-start justify-between gap-3 mb-3">
        <div>
          <h2 className="text-base sm:text-lg font-semibold text-kur-text">MetaMask (dApp / EVM)</h2>
          <p className="text-xs text-kur-text-muted mt-1">
            Chain ID {KURAMA_CHAIN_ID} · RPC <code className="text-kur-accent">{kuramaRpcUrl()}</code>
          </p>
        </div>
        {installed ? (
          <span className="text-[10px] px-2 py-1 rounded bg-kur-green/10 text-kur-green whitespace-nowrap">
            MetaMask detectada
          </span>
        ) : (
          <span className="text-[10px] px-2 py-1 rounded bg-kur-orange/10 text-kur-orange whitespace-nowrap">
            MetaMask não instalada
          </span>
        )}
      </div>

      {error && (
        <div className="mb-3 bg-kur-red/5 border border-kur-red/20 rounded-lg p-3">
          <p className="text-xs text-kur-red">{error}</p>
        </div>
      )}

      {!address ? (
        <button
          onClick={handleConnect}
          disabled={loading}
          className="px-5 py-2.5 bg-kur-accent/10 text-kur-accent border border-kur-accent/30 rounded-lg hover:bg-kur-accent/20 transition-colors text-sm disabled:opacity-50"
        >
          {loading ? 'Conectando...' : 'Conectar MetaMask'}
        </button>
      ) : (
        <div className="space-y-3">
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 text-xs sm:text-sm">
            <div className="bg-kur-bg/50 rounded-lg p-3">
              <span className="text-kur-text-muted block mb-1">Conta (0x)</span>
              <span className="text-kur-text font-mono" title={address}>{shortAddress(address)}</span>
            </div>
            <div className="bg-kur-bg/50 rounded-lg p-3">
              <span className="text-kur-text-muted block mb-1">Saldo EVM</span>
              <span className="text-kur-green font-medium">
                {balance === null ? '—' : `${formatKur(balance)} KUR`}
              </span>
            </div>
            <div className="bg-kur-bg/50 rounded-lg p-3">
              <span className="text-kur-text-muted block mb-1">Rede</span>
              <span className={`font-medium ${onKuramaChain ? 'text-kur-green' : 'text-kur-orange'}`}>
                {chainId === null ? '—' : onKuramaChain ? `KuramaChain (${chainId})` : `Outra (${chainId})`}
              </span>
            </div>
          </div>
          {!onKuramaChain && (
            <button
              onClick={handleSwitch}
              disabled={loading}
              className="px-4 py-2 bg-kur-yellow/10 text-kur-yellow border border-kur-yellow/30 rounded-lg hover:bg-kur-yellow/20 transition-colors text-sm disabled:opacity-50"
            >
              {loading ? 'Trocando...' : 'Usar a KuramaChain na wallet'}
            </button>
          )}
        </div>
      )}

      <div className="mt-4 p-3 bg-kur-bg-hover rounded-lg text-xs sm:text-sm text-kur-text-muted">
        A wallet assina localmente e envia a transação crua via <code>eth_sendRawTransaction</code>
        {' '}— o nó expõe <code>eth_*</code> (chainId, balance, call, receipt, logs, getBlock) em{' '}
        <code>POST /rpc</code> para ethers.js/web3.js.
      </div>
    </div>
  );
}
