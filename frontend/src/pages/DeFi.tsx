import { useState } from 'react';
import { getChainInfo, readToken, readOraclePrice, readLendingPosition } from '../api/defi';
import { getStats } from '../api/client';
import LoadingSpinner from '../components/LoadingSpinner';
import EvmWalletCard from '../components/EvmWalletCard';
import SwapCard from '../components/SwapCard';
import UniswapCard from '../components/UniswapCard';
import StatCard from '../components/StatCard';

export default function DeFi() {
  const [chainInfo, setChainInfo] = useState<any>(null);
  const [stats, setStats] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Seções de DeFi
  const [tab, setTab] = useState<'overview' | 'token' | 'oracle' | 'swap' | 'uniswap' | 'lending'>('overview');
  const [tokenAddress, setTokenAddress] = useState('');
  const [tokenInfo, setTokenInfo] = useState<any>(null);
  const [tokenLoading, setTokenLoading] = useState(false);
  const [tokenError, setTokenError] = useState<string | null>(null);

  const [feedAddress, setFeedAddress] = useState('');
  const [oraclePrice, setOraclePrice] = useState<any>(null);
  const [oracleLoading, setOracleLoading] = useState(false);
  const [oracleError, setOracleError] = useState<string | null>(null);

  const [poolAddress, setPoolAddress] = useState('');
  const [userAddress, setUserAddress] = useState('');
  const [position, setPosition] = useState<any>(null);
  const [positionLoading, setPositionLoading] = useState(false);
  const [positionError, setPositionError] = useState<string | null>(null);

  // Carrega dados gerais
  const loadGeneral = async () => {
    try {
      const [c, s] = await Promise.all([getChainInfo(), getStats()]);
      setChainInfo(c);
      setStats(s);
    } catch (err: any) {
      setError(err?.response?.data?.error || err?.message || 'Erro ao carregar dados da blockchain');
    } finally {
      setLoading(false);
    }
  };

  // Token
  const loadToken = async () => {
    if (!tokenAddress) return;
    setTokenLoading(true);
    setTokenError(null);
    try {
      const t = await readToken(tokenAddress);
      setTokenInfo(t);
    } catch (err: any) {
      setTokenError(err?.message || 'Erro ao ler token');
    } finally {
      setTokenLoading(false);
    }
  };

  // Oracle
  const loadOracle = async () => {
    if (!feedAddress) return;
    setOracleLoading(true);
    setOracleError(null);
    try {
      const p = await readOraclePrice(feedAddress);
      setOraclePrice(p);
    } catch (err: any) {
      setOracleError(err?.message || 'Erro ao ler oráculo');
    } finally {
      setOracleLoading(false);
    }
  };

  // Lending position
  const loadPosition = async () => {
    if (!poolAddress || !userAddress) return;
    setPositionLoading(true);
    setPositionError(null);
    try {
      const p = await readLendingPosition(poolAddress, userAddress);
      setPosition(p);
    } catch (err: any) {
      setPositionError(err?.message || 'Erro ao ler posição lending');
    } finally {
      setPositionLoading(false);
    }
  };

  // Carrega geral ao mount
  useState(() => { loadGeneral(); });

  if (loading) {
    return <LoadingSpinner />;
  }

  if (error) {
    return (
      <div className="flex flex-col items-center justify-center py-20">
        <p className="text-kur-red text-lg mb-4">Erro ao carregar interface DeFi</p>
        <p className="text-kur-text-muted text-sm mb-6">{error}</p>
        <button onClick={loadGeneral} className="px-6 py-2 bg-kur-accent/10 text-kur-accent border border-kur-accent/30 rounded-lg hover:bg-kur-accent/20 transition-colors">
          Tentar novamente
        </button>
      </div>
    );
  }

  const s = stats || {};
  const c = chainInfo || {};

  return (
    <div className="max-w-full overflow-x-hidden">
      <h1 className="text-xl sm:text-2xl font-bold text-kur-text mb-4 sm:mb-6">DeFi — Kurama Chain</h1>

      {/* Estado geral da blockchain EVM */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3 sm:gap-4 mb-6">
        <StatCard title="Chain ID" value={String(c.chainId ?? 0)} icon="🔗" accent="text-kur-accent" />
        <StatCard title="Bloco EVM" value={String(c.blockNumber ?? 0)} icon="🧱" accent="text-kur-green" />
        <StatCard title="Blocos on-chain" value={String(s.blocks ?? 0)} icon="⛓️" accent="text-kur-yellow" />
        <StatCard title="Supply (on-chain)" value={(s.total_supply ?? 0).toLocaleString()} icon="🪙" subtitle={s.token_symbol || 'KUR'} accent="text-kur-orange" />
      </div>

      {/* Abas */}
      <div className="flex flex-wrap gap-2 mb-6 border-b border-kur-border pb-3">
        {(['overview', 'token', 'oracle', 'swap', 'uniswap', 'lending'] as const).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
              tab === t
                ? 'bg-kur-accent/10 text-kur-accent border border-kur-accent/20'
                : 'text-kur-text-muted hover:text-kur-text hover:bg-kur-bg-hover border border-transparent'
            }`}
          >
            {t === 'overview' && 'Visão geral'}
            {t === 'token' && 'Token (ERC-20)'}
            {t === 'oracle' && 'Oráculo'}
            {t === 'swap' && 'Swap (DEX)'}
            {t === 'uniswap' && 'Uniswap (Polygon)'}
            {t === 'lending' && 'Lending'}
          </button>
        ))}
      </div>

      {/* Visão geral */}
      {tab === 'overview' && (
        <>
        <EvmWalletCard />
        <div className="bg-kur-bg-card border border-kur-border rounded-xl p-4 sm:p-5">
          <h2 className="text-base sm:text-lg font-semibold text-kur-text mb-3">Estado da Camada DeFi</h2>
          <p className="text-xs sm:text-sm text-kur-text-muted mb-4">
            A KuramaChain roda uma EVM (fork London) integrada ao PoW. Contratos Solidity podem ser implantados via{' '}
            <code className="text-kur-accent bg-kur-accent/5 px-1 rounded">POST /rpc</code> (JSON-RPC eth_*).
          </p>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-xs sm:text-sm">
            <div className="bg-kur-bg/50 rounded-lg p-3">
              <span className="text-kur-text-muted block mb-1">Supply on-chain</span>
              <span className="text-kur-green font-medium">{(s.total_supply ?? 0).toLocaleString()} KUR</span>
            </div>
            <div className="bg-kur-bg/50 rounded-lg p-3">
              <span className="text-kur-text-muted block mb-1">Transações on-chain</span>
              <span className="text-kur-text font-medium">{s.total_transactions ?? 0}</span>
            </div>
            <div className="bg-kur-bg/50 rounded-lg p-3">
              <span className="text-kur-text-muted block mb-1">Pendentes</span>
              <span className="text-kur-orange font-medium">{s.pending_transactions ?? 0}</span>
            </div>
            <div className="bg-kur-bg/50 rounded-lg p-3">
              <span className="text-kur-text-muted block mb-1">Cadeia válida</span>
              <span className={`font-medium ${s.chain_valid ? 'text-kur-green' : 'text-kur-red'}`}>
                {String(s.chain_valid)}
              </span>
            </div>
          </div>
          <div className="mt-4 p-3 bg-kur-yellow/5 border border-kur-yellow/20 rounded-lg text-xs sm:text-sm text-kur-text-muted">
            💡 Para usar DeFi real, implantar os contratos (KurToken, KurPriceFeed, KurOracle, KurFactory/Pair/Router,
            KurLendingPool, KurStaking, KurBridge) via <code>evm/deploy.py</code>, depois conectar endereços nas abas abaixo.
          </div>
          <div className="mt-3 p-3 bg-kur-bg-hover rounded-lg text-xs sm:text-sm text-kur-text-muted">
            🌉 Bridge: <code>KurBridge</code> trava o ativo na origem e cunha o <code>KurWrappedToken</code> no destino,
            com atestação m-de-n de validadores (<code>evm/bridge.py</code> traz o relayer).
            🌱 Staking: <code>KurStaking</code> paga recompensas por segundo por pool (KUR ou LP tokens).
          </div>
        </div>
        </>
      )}

      {/* Token ERC-20 */}
      {tab === 'token' && (
        <div className="bg-kur-bg-card border border-kur-border rounded-xl p-4 sm:p-5">
          <h2 className="text-base sm:text-lg font-semibold text-kur-text mb-3">Ler Token (ERC-20)</h2>
          <div className="flex flex-col sm:flex-row gap-3 mb-4">
            <input
              type="text"
              value={tokenAddress}
              onChange={(e) => setTokenAddress(e.target.value)}
              placeholder="0x... (endereço do contrato KurToken)"
              className="flex-1 px-3 py-2.5 bg-kur-bg-hover border border-kur-border rounded-lg text-xs sm:text-sm text-kur-text placeholder-kur-text-muted/50 focus:outline-none focus:border-kur-accent/50 font-mono"
            />
            <button
              onClick={loadToken}
              disabled={tokenLoading || !tokenAddress}
              className="px-5 py-2.5 bg-kur-accent/10 text-kur-accent border border-kur-accent/30 rounded-lg hover:bg-kur-accent/20 transition-colors text-sm disabled:opacity-50"
            >
              {tokenLoading ? 'Lendo...' : 'Ler token'}
            </button>
          </div>
          {tokenError && <p className="text-kur-red text-sm mb-3">{tokenError}</p>}
          {tokenInfo && (
            <div className="grid grid-cols-2 gap-3 text-xs sm:text-sm">
              <div className="bg-kur-bg/50 rounded-lg p-3">
                <span className="text-kur-text-muted block">Nome</span>
                <span className="text-kur-text font-medium">{tokenInfo.name}</span>
              </div>
              <div className="bg-kur-bg/50 rounded-lg p-3">
                <span className="text-kur-text-muted block">Símbolo</span>
                <span className="text-kur-text font-medium">{tokenInfo.symbol}</span>
              </div>
              <div className="bg-kur-bg/50 rounded-lg p-3">
                <span className="text-kur-text-muted block">Decimals</span>
                <span className="text-kur-text font-medium">{tokenInfo.decimals}</span>
              </div>
              <div className="bg-kur-bg/50 rounded-lg p-3">
                <span className="text-kur-text-muted block">Total Supply</span>
                <span className="text-kur-green font-medium font-mono">{tokenInfo.totalSupply.toString()}</span>
              </div>
              <div className="bg-kur-bg/50 rounded-lg p-3 sm:col-span-2">
                <span className="text-kur-text-muted block">Saldo (conta do nó)</span>
                <span className="text-kur-green font-medium font-mono">{tokenInfo.balance.toString()}</span>
              </div>
            </div>
          )}
        </div>
      )}

      {/* Oráculo */}
      {tab === 'oracle' && (
        <div className="bg-kur-bg-card border border-kur-border rounded-xl p-4 sm:p-5">
          <h2 className="text-base sm:text-lg font-semibold text-kur-text mb-3">Preço do Oráculo (KurPriceFeed)</h2>
          <div className="flex flex-col sm:flex-row gap-3 mb-4">
            <input
              type="text"
              value={feedAddress}
              onChange={(e) => setFeedAddress(e.target.value)}
              placeholder="0x... (endereço do KurPriceFeed)"
              className="flex-1 px-3 py-2.5 bg-kur-bg-hover border border-kur-border rounded-lg text-xs sm:text-sm text-kur-text placeholder-kur-text-muted/50 focus:outline-none focus:border-kur-accent/50 font-mono"
            />
            <button
              onClick={loadOracle}
              disabled={oracleLoading || !feedAddress}
              className="px-5 py-2.5 bg-kur-accent/10 text-kur-accent border border-kur-accent/30 rounded-lg hover:bg-kur-accent/20 transition-colors text-sm disabled:opacity-50"
            >
              {oracleLoading ? 'Lendo...' : 'Ler preço'}
            </button>
          </div>
          {oracleError && <p className="text-kur-red text-sm mb-3">{oracleError}</p>}
          {oraclePrice && (
            <div className="bg-kur-bg/50 rounded-lg p-3">
              <span className="text-kur-text-muted block mb-1">Status</span>
              <span className={`inline-block px-2 py-1 rounded text-xs font-medium ${
                oraclePrice.status === 'ok' ? 'bg-kur-green/10 text-kur-green' :
                oraclePrice.status === 'stale' ? 'bg-kur-orange/10 text-kur-orange' :
                'bg-kur-red/10 text-kur-red'
              }`}>
                {oraclePrice.status}
              </span>
              <span className="block mt-2 text-kur-text font-medium">
                Preço: {oraclePrice.price} ({oraclePrice.decimals} decimais)
              </span>
            </div>
          )}
          <div className="mt-4 p-3 bg-kur-bg-hover rounded-lg text-xs sm:text-sm text-kur-text-muted">
            O feed usa AggregatorV3Interface (Chainlink): reporters autorizados enviam preço e a rodada fecha com a
            mediana quando o quórum é atingido. Se o feed estiver obsoleto, o KurOracle cai no fallback TWAP do par AMM.
          </div>
        </div>
      )}

      {/* Swap */}
      {tab === 'swap' && <SwapCard />}

      {/* Uniswap (Polygon) */}
      {tab === 'uniswap' && <UniswapCard />}

      {/* Lending */}
      {tab === 'lending' && (
        <div className="bg-kur-bg-card border border-kur-border rounded-xl p-4 sm:p-5">
          <h2 className="text-base sm:text-lg font-semibold text-kur-text mb-3">Lending (KurLendingPool)</h2>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 mb-4">
            <input
              type="text"
              value={poolAddress}
              onChange={(e) => setPoolAddress(e.target.value)}
              placeholder="0x... (KurLendingPool)"
              className="px-3 py-2.5 bg-kur-bg-hover border border-kur-border rounded-lg text-xs sm:text-sm text-kur-text placeholder-kur-text-muted/50 focus:outline-none focus:border-kur-accent/50 font-mono"
            />
            <input
              type="text"
              value={userAddress}
              onChange={(e) => setUserAddress(e.target.value)}
              placeholder="0x... (endereço do usuário)"
              className="px-3 py-2.5 bg-kur-bg-hover border border-kur-border rounded-lg text-xs sm:text-sm text-kur-text placeholder-kur-text-muted/50 focus:outline-none focus:border-kur-accent/50 font-mono"
            />
          </div>
          <div className="flex justify-end mb-4">
            <button
              onClick={loadPosition}
              disabled={positionLoading || !poolAddress || !userAddress}
              className="px-5 py-2.5 bg-kur-accent/10 text-kur-accent border border-kur-accent/30 rounded-lg hover:bg-kur-accent/20 transition-colors text-sm disabled:opacity-50"
            >
              {positionLoading ? 'Lendo...' : 'Ver posição'}
            </button>
          </div>
          {positionError && <p className="text-kur-red text-sm mb-3">{positionError}</p>}
          {position && (
            <div className="grid grid-cols-2 gap-3 text-xs sm:text-sm">
              <div className="bg-kur-bg/50 rounded-lg p-3">
                <span className="text-kur-text-muted block">Colateral</span>
                <span className="text-kur-green font-medium font-mono">{position.collateral}</span>
              </div>
              <div className="bg-kur-bg/50 rounded-lg p-3">
                <span className="text-kur-text-muted block">Dívidas</span>
                <span className="text-kur-red font-medium font-mono">{position.debt}</span>
              </div>
              <div className="bg-kur-bg/50 rounded-lg p-3">
                <span className="text-kur-text-muted block">Disponível</span>
                <span className="text-kur-text font-medium font-mono">{position.available}</span>
              </div>
              <div className="bg-kur-bg/50 rounded-lg p-3">
                <span className="text-kur-text-muted block">Health Factor</span>
                <span className={`font-medium font-mono ${
                  (position.healthFactor ?? 0) < 1 ? 'text-kur-red' : 'text-kur-green'
                }`}>
                  {position.healthFactor}
                </span>
              </div>
              <div className="bg-kur-bg/50 rounded-lg p-3 sm:col-span-2">
                <span className="text-kur-text-muted block">LTV</span>
                <span className="text-kur-text font-medium font-mono">{position.ltv}</span>
              </div>
            </div>
          )}
          <div className="mt-4 p-3 bg-kur-bg-hover rounded-lg text-xs sm:text-sm text-kur-text-muted">
            O pool usa KurPriceOracle pra não calcular colateral com preço velho. Quem liquidar paga parte da dívida
            (limitada pelo closeFactor) e recebe o colateral + bônus.
          </div>
        </div>
      )}

      {/* Rodapé técnico */}
      <div className="mt-8 text-[10px] sm:text-xs text-kur-text-muted border-t border-kur-border pt-4">
        Conectado ao KuramaChain node em {new URL(window.location.href).protocol.replace(':', '')}://{window.location.hostname}:{window.location.port || '5173'} → backend{' '}
        <span className="font-mono">{c.chainId ? `chainId=${c.chainId} (EVM)` : 'EVM'}</span> via{' '}
        <span className="font-mono">POST /rpc</span>.
      </div>
    </div>
  );
}
