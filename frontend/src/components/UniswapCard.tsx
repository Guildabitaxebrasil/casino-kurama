import { useCallback, useEffect, useRef, useState } from 'react';
import {
  connectWallet,
  getEvmProvider,
  isEvmWalletInstalled,
  shortAddress,
  type Eip1193Provider,
} from '../api/evmWallet';
import { isAddress, sameAddress } from '../api/evmAbi';
import {
  FEE_TIERS,
  NATIVE_TOKEN,
  POLYGON_CHAIN_ID,
  POLYGON_TOKENS,
  UNISWAP,
  applySlippage,
  detectFeeTier,
  ensurePolygonChain,
  executeUniswapSwap,
  formatUnits,
  isNativeToken,
  parseUnits,
  polygonscanTx,
  priceTokenInToTokenOut,
  quoteExactInputSingle,
  readPool,
  readPolygonBalance,
  readPolygonToken,
  readRouterAllowance,
  wrappedToken,
  type PolygonToken,
  type UniswapPool,
} from '../api/uniswap';

const FEE_LABELS: Record<number, string> = {
  100: '0,01%',
  500: '0,05%',
  3000: '0,30%',
  10000: '1,00%',
};

type FeeChoice = 'auto' | number;
type Step = 'idle' | 'quoting' | 'approving' | 'swapping' | 'done';

interface Quote {
  fee: number;
  amountIn: bigint;
  amountOut: bigint;
  amountOutMin: bigint;
  allowance: bigint;
  inMeta: PolygonToken;
  outMeta: PolygonToken;
}

function errorMessage(err: unknown): string {
  if (err instanceof Error) {
    const message = err.message;
    if (/revert|execution reverted|CALL_EXCEPTION/i.test(message)) {
      return 'O pool não tem liquidez para essa quantidade — reduza o valor ou escolha outra taxa.';
    }
    return message;
  }
  const raw = err as { message?: string };
  return raw?.message || 'Erro inesperado';
}

/**
 * Card de swap nos pools Uniswap V3 da Polygon (chain 137).
 *
 * A cotação sai do QuoterV2 por `eth_call` no RPC público da Polygon; o swap é
 * montado para o SwapRouter02 e assinado pela carteira (`Connect Wallet`).
 * MATIC nativo entra como `value` e sai via `unwrapWETH9` no multicall.
 */
export default function UniswapCard() {
  const [tokenIn, setTokenIn] = useState<string>(UNISWAP.usdc);
  const [tokenOut, setTokenOut] = useState<string>(NATIVE_TOKEN);
  const [customIn, setCustomIn] = useState('');
  const [customOut, setCustomOut] = useState('');
  const [amount, setAmount] = useState('');
  const [slippage, setSlippage] = useState('50');
  const [feeChoice, setFeeChoice] = useState<FeeChoice>('auto');

  const [account, setAccount] = useState<string | null>(null);
  const [chainId, setChainId] = useState<number | null>(null);
  const [pool, setPool] = useState<UniswapPool | null>(null);
  const [quote, setQuote] = useState<Quote | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [step, setStep] = useState<Step>('idle');
  const [txs, setTxs] = useState<{ approve: string | null; swap: string } | null>(null);
  const [received, setReceived] = useState<bigint | null>(null);

  const seq = useRef(0);
  const installed = isEvmWalletInstalled();
  const inAddr = customIn.trim() || tokenIn;
  const outAddr = customOut.trim() || tokenOut;
  const slippageBps = Math.min(9_999, Math.max(0, Number.parseFloat(slippage) || 50));
  const onPolygon = chainId === POLYGON_CHAIN_ID;
  const busy = step === 'approving' || step === 'swapping' || step === 'quoting';

  // Conecta / acompanha a wallet (conta e rede).
  useEffect(() => {
    const eth = getEvmProvider() as Eip1193Provider | null;
    if (!eth) return;
    eth.request({ method: 'eth_accounts' })
      .then((accounts) => {
        const list = accounts as string[];
        if (list?.length) setAccount(list[0]);
      })
      .catch(() => undefined);
    eth.request({ method: 'eth_chainId' })
      .then((hex) => setChainId(parseInt(hex as string, 16)))
      .catch(() => undefined);

    const onAccounts = (...args: unknown[]) => setAccount(((args[0] as string[]) ?? [])[0] ?? null);
    const onChain = (...args: unknown[]) => setChainId(parseInt(args[0] as string, 16));
    eth.on?.('accountsChanged', onAccounts);
    eth.on?.('chainChanged', onChain);
    return () => {
      eth.removeListener?.('accountsChanged', onAccounts);
      eth.removeListener?.('chainChanged', onChain);
    };
  }, []);

  const loadQuote = useCallback(async () => {
    const current = ++seq.current;
    const stale = () => current !== seq.current;

    if (!isAddress(inAddr) || !isAddress(outAddr)) {
      setQuote(null);
      setPool(null);
      setError('Informe endereços de token válidos (0x...)');
      return;
    }
    if (sameAddress(wrappedToken(inAddr), wrappedToken(outAddr))) {
      setQuote(null);
      setPool(null);
      setError('Escolha dois tokens diferentes');
      return;
    }

    setStep((prev) => (prev === 'idle' || prev === 'done' ? 'quoting' : prev));
    try {
      const fee = feeChoice === 'auto' ? await detectFeeTier(inAddr, outAddr) : feeChoice;
      if (stale()) return;
      if (fee === null) {
        setPool(null);
        setQuote(null);
        setError('Nenhum pool Uniswap V3 para esse par na Polygon.');
        return;
      }

      const [inMeta, outMeta, poolState] = await Promise.all([
        readPolygonToken(inAddr, account ?? undefined),
        readPolygonToken(outAddr, account ?? undefined),
        readPool(inAddr, outAddr, fee),
      ]);
      if (stale()) return;
      if (!poolState) {
        setPool(null);
        setQuote(null);
        setError(`O par não tem pool na taxa de ${FEE_LABELS[fee] ?? `${fee}`}.`);
        return;
      }

      const amountIn = amount.trim() ? parseUnits(amount, inMeta.decimals) : 0n;
      const amountOut = amountIn > 0n
        ? await quoteExactInputSingle({ tokenIn: inAddr, tokenOut: outAddr, fee, amountIn })
        : 0n;
      if (stale()) return;
      const allowance = account && !isNativeToken(inAddr)
        ? await readRouterAllowance(inAddr, account)
        : 0n;
      if (stale()) return;

      setPool(poolState);
      setError(null);
      setQuote({
        fee,
        amountIn,
        amountOut,
        amountOutMin: applySlippage(amountOut, slippageBps),
        allowance,
        inMeta,
        outMeta,
      });
    } catch (err) {
      if (stale()) return;
      setQuote(null);
      setError(errorMessage(err));
    } finally {
      if (!stale()) setStep((prev) => (prev === 'quoting' ? 'idle' : prev));
    }
  }, [inAddr, outAddr, amount, account, feeChoice, slippageBps]);

  // Recotação com debounce (digitar valor, trocar token/taxa, conectar).
  useEffect(() => {
    const timer = setTimeout(() => { void loadQuote(); }, 350);
    return () => clearTimeout(timer);
  }, [loadQuote]);

  const handleConnect = async () => {
    setError(null);
    try {
      const next = await connectWallet();
      setAccount(next);
      await ensurePolygonChain();
      const eth = getEvmProvider();
      if (eth) setChainId(parseInt((await eth.request({ method: 'eth_chainId' })) as string, 16));
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  const handleSwitchChain = async () => {
    setError(null);
    try {
      await ensurePolygonChain();
      setChainId(POLYGON_CHAIN_ID);
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  const handleMax = () => {
    if (!quote) return;
    setAmount(formatUnits(quote.inMeta.balance, quote.inMeta.decimals, quote.inMeta.decimals));
  };

  const handleSwap = async () => {
    if (!quote) return;
    setError(null);
    setTxs(null);
    setReceived(null);
    try {
      const from = account ?? (await connectWallet());
      setAccount(from);
      await ensurePolygonChain();
      setChainId(POLYGON_CHAIN_ID);

      if (quote.inMeta.balance < quote.amountIn) {
        throw new Error(`Saldo insuficiente de ${quote.inMeta.symbol}`);
      }

      // Recotação imediata: se o preço andou além do slippage, aborta antes de
      // assinar (a tx reverteria e o gas seria perdido).
      const freshOut = await quoteExactInputSingle({
        tokenIn: inAddr,
        tokenOut: outAddr,
        fee: quote.fee,
        amountIn: quote.amountIn,
      });
      if (freshOut < quote.amountOutMin) {
        throw new Error('Preço mudou além do slippage — recote antes de trocar');
      }
      const amountOutMin = applySlippage(freshOut, slippageBps);

      const before = isNativeToken(outAddr) ? 0n : await readPolygonBalance(outAddr, from);

      const result = await executeUniswapSwap(
        {
          from,
          tokenIn: inAddr,
          tokenOut: outAddr,
          fee: quote.fee,
          amountIn: quote.amountIn,
          amountOutMin,
        },
        (next) => setStep(next),
      );
      setTxs({ approve: result.approveTx, swap: result.swapTx });

      // O saldo nativo varia também com o gas, então só medimos ERC-20.
      if (!isNativeToken(outAddr)) {
        const after = await readPolygonBalance(outAddr, from);
        setReceived(after >= before ? after - before : null);
      }
      setStep('done');
      void loadQuote();
    } catch (err) {
      setStep('idle');
      setError(errorMessage(err));
    }
  };

  const needsApproval = quote !== null && quote.allowance < quote.amountIn;
  const canSwap = quote !== null && quote.amountIn > 0n && !busy && onPolygon;
  const buttonLabel =
    step === 'quoting' ? 'Cotando...'
      : step === 'approving' ? 'Aprovando...'
        : step === 'swapping' ? 'Trocando...'
          : needsApproval ? 'Aprovar e trocar'
            : 'Trocar via wallet';

  const priceText = (() => {
    if (!pool || !quote) return null;
    const price = priceTokenInToTokenOut(
      pool,
      inAddr,
      quote.inMeta.decimals,
      quote.outMeta.decimals,
    );
    if (price === null) return null;
    return `1 ${quote.inMeta.symbol} ≈ ${price.toLocaleString('pt-BR', { maximumSignificantDigits: 6 })} ${quote.outMeta.symbol}`;
  })();

  return (
    <div className="bg-kur-bg-card border border-kur-border rounded-xl p-4 sm:p-5">
      <div className="flex flex-wrap items-center justify-between gap-2 mb-3">
        <div>
          <h2 className="text-base sm:text-lg font-semibold text-kur-text">
            Uniswap V3 (Polygon)
          </h2>
          <p className="text-[11px] text-kur-text-muted mt-0.5">
            Pool on-chain + SwapRouter02 · chain {POLYGON_CHAIN_ID}
          </p>
        </div>
        {account ? (
          <div className="flex items-center gap-2">
            <span className="text-[11px] px-2 py-1 rounded bg-kur-accent/10 text-kur-accent font-mono" title={account}>
              {shortAddress(account)}
            </span>
            <span className={`text-[11px] px-2 py-1 rounded ${
              onPolygon ? 'bg-kur-green/10 text-kur-green' : 'bg-kur-orange/10 text-kur-orange'
            }`}>
              {chainId === null ? '—' : onPolygon ? `Polygon (${chainId})` : `outra rede (${chainId})`}
            </span>
            {!onPolygon && (
              <button
                onClick={handleSwitchChain}
                className="text-[11px] px-2 py-1 rounded bg-kur-yellow/10 text-kur-yellow border border-kur-yellow/30 hover:bg-kur-yellow/20"
              >
                Usar Polygon
              </button>
            )}
          </div>
        ) : (
          <button
            onClick={handleConnect}
            className="px-4 py-2 bg-kur-accent/10 text-kur-accent border border-kur-accent/30 rounded-lg hover:bg-kur-accent/20 transition-colors text-sm"
          >
            {installed ? 'Connect Wallet' : 'Instalar carteira EVM'}
          </button>
        )}
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 mb-3">
        <div>
          <label className="block text-xs text-kur-text-muted mb-1 font-medium">
            De {quote ? `(${quote.inMeta.symbol})` : ''}
          </label>
          <select
            value={tokenIn}
            onChange={(e) => { setCustomIn(''); setTokenIn(e.target.value); }}
            className="w-full px-3 py-2.5 bg-kur-bg-hover border border-kur-border rounded-lg text-xs sm:text-sm text-kur-text focus:outline-none focus:border-kur-accent/50"
          >
            {POLYGON_TOKENS.map((token) => (
              <option key={token.address} value={token.address}>{token.symbol}</option>
            ))}
          </select>
          <input
            type="text"
            value={customIn}
            onChange={(e) => setCustomIn(e.target.value.trim())}
            placeholder="0x… (outro token)"
            className="mt-2 w-full px-3 py-2 bg-kur-bg-hover border border-kur-border rounded-lg text-[11px] text-kur-text placeholder-kur-text-muted/50 focus:outline-none focus:border-kur-accent/50 font-mono"
          />
        </div>
        <div>
          <label className="block text-xs text-kur-text-muted mb-1 font-medium">
            Para {quote ? `(${quote.outMeta.symbol})` : ''}
          </label>
          <select
            value={tokenOut}
            onChange={(e) => { setCustomOut(''); setTokenOut(e.target.value); }}
            className="w-full px-3 py-2.5 bg-kur-bg-hover border border-kur-border rounded-lg text-xs sm:text-sm text-kur-text focus:outline-none focus:border-kur-accent/50"
          >
            {POLYGON_TOKENS.map((token) => (
              <option key={token.address} value={token.address}>{token.symbol}</option>
            ))}
          </select>
          <input
            type="text"
            value={customOut}
            onChange={(e) => setCustomOut(e.target.value.trim())}
            placeholder="0x… (outro token)"
            className="mt-2 w-full px-3 py-2 bg-kur-bg-hover border border-kur-border rounded-lg text-[11px] text-kur-text placeholder-kur-text-muted/50 focus:outline-none focus:border-kur-accent/50 font-mono"
          />
        </div>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 mb-4">
        <div>
          <div className="flex items-center justify-between mb-1">
            <label className="text-xs text-kur-text-muted font-medium">Quantidade</label>
            {quote && (
              <button onClick={handleMax} className="text-[11px] text-kur-accent hover:underline">
                saldo: {formatUnits(quote.inMeta.balance, quote.inMeta.decimals, 4)} {quote.inMeta.symbol}
              </button>
            )}
          </div>
          <input
            type="text"
            inputMode="decimal"
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
            placeholder="0.0"
            className="w-full px-3 py-2.5 bg-kur-bg-hover border border-kur-border rounded-lg text-xs sm:text-sm text-kur-text placeholder-kur-text-muted/50 focus:outline-none focus:border-kur-accent/50 font-mono"
          />
        </div>
        <div>
          <label className="block text-xs text-kur-text-muted mb-1 font-medium">Taxa do pool</label>
          <select
            value={String(feeChoice)}
            onChange={(e) => setFeeChoice(e.target.value === 'auto' ? 'auto' : Number(e.target.value))}
            className="w-full px-3 py-2.5 bg-kur-bg-hover border border-kur-border rounded-lg text-xs sm:text-sm text-kur-text focus:outline-none focus:border-kur-accent/50"
          >
            <option value="auto">Auto ({quote ? FEE_LABELS[quote.fee] ?? quote.fee : 'melhor liquidez'})</option>
            {FEE_TIERS.map((fee) => (
              <option key={fee} value={fee}>{FEE_LABELS[fee] ?? `${fee}`}</option>
            ))}
          </select>
        </div>
        <div>
          <label className="block text-xs text-kur-text-muted mb-1 font-medium">Slippage (bps)</label>
          <input
            type="number"
            min={0}
            max={9999}
            value={slippage}
            onChange={(e) => setSlippage(e.target.value)}
            className="w-full px-3 py-2.5 bg-kur-bg-hover border border-kur-border rounded-lg text-xs sm:text-sm text-kur-text focus:outline-none focus:border-kur-accent/50 font-mono"
          />
        </div>
      </div>

      {error && (
        <p className="text-kur-red text-xs sm:text-sm mb-3 bg-kur-red/5 border border-kur-red/20 rounded-lg p-3">{error}</p>
      )}

      {pool && (
        <div className="bg-kur-bg/50 rounded-lg p-3 mb-4 text-xs sm:text-sm space-y-1">
          <div className="flex justify-between gap-2">
            <span className="text-kur-text-muted">Pool</span>
            <span className="text-kur-text font-mono" title={pool.address}>{shortAddress(pool.address)}</span>
          </div>
          <div className="flex justify-between gap-2">
            <span className="text-kur-text-muted">Taxa</span>
            <span className="text-kur-text font-mono">{FEE_LABELS[pool.fee] ?? pool.fee}</span>
          </div>
          <div className="flex justify-between gap-2">
            <span className="text-kur-text-muted">Liquidez ativa</span>
            <span className="text-kur-text font-mono">{pool.liquidity.toString()}</span>
          </div>
          {priceText && (
            <div className="flex justify-between gap-2">
              <span className="text-kur-text-muted">Preço atual</span>
              <span className="text-kur-text font-mono">{priceText}</span>
            </div>
          )}
          {quote && quote.amountIn > 0n && (
            <>
              <div className="flex justify-between gap-2">
                <span className="text-kur-text-muted">Recebe (estimado)</span>
                <span className="text-kur-green font-medium font-mono">
                  {formatUnits(quote.amountOut, quote.outMeta.decimals)} {quote.outMeta.symbol}
                </span>
              </div>
              <div className="flex justify-between gap-2">
                <span className="text-kur-text-muted">Mínimo (slippage {slippageBps / 100}%)</span>
                <span className="text-kur-text font-mono">
                  {formatUnits(quote.amountOutMin, quote.outMeta.decimals)} {quote.outMeta.symbol}
                </span>
              </div>
              {account && (
                <div className="flex justify-between gap-2">
                  <span className="text-kur-text-muted">Allowance p/ o router</span>
                  <span className={`font-mono ${needsApproval ? 'text-kur-yellow' : 'text-kur-green'}`}>
                    {needsApproval ? 'aprovação necessária' : 'ok'}
                  </span>
                </div>
              )}
            </>
          )}
        </div>
      )}

      <button
        onClick={handleSwap}
        disabled={!canSwap}
        className="w-full px-5 py-2.5 bg-kur-yellow/10 text-kur-yellow border border-kur-yellow/30 rounded-lg hover:bg-kur-yellow/20 transition-colors text-sm disabled:opacity-50"
      >
        {!account ? (installed ? 'Connect Wallet' : 'Instalar carteira EVM') : buttonLabel}
      </button>
      {!account && (
        <p className="mt-2 text-[11px] text-kur-text-muted text-center">
          A carteira assina o swap na Polygon — a chave privada nunca sai dela.
        </p>
      )}

      {txs && (
        <div className="mt-3 bg-kur-green/5 border border-kur-green/20 rounded-lg p-3 text-xs sm:text-sm space-y-1">
          {txs.approve && (
            <div className="flex justify-between gap-2">
              <span className="text-kur-text-muted">Approve</span>
              <a
                href={polygonscanTx(txs.approve)}
                target="_blank"
                rel="noreferrer"
                className="text-kur-accent font-mono break-all hover:underline"
              >
                {txs.approve}
              </a>
            </div>
          )}
          <div className="flex justify-between gap-2">
            <span className="text-kur-text-muted">Swap</span>
            <a
              href={polygonscanTx(txs.swap)}
              target="_blank"
              rel="noreferrer"
              className="text-kur-accent font-mono break-all hover:underline"
            >
              {txs.swap}
            </a>
          </div>
          {received !== null && quote && (
            <div className="flex justify-between gap-2">
              <span className="text-kur-text-muted">Recebido on-chain</span>
              <span className="text-kur-green font-medium font-mono">
                {formatUnits(received, quote.outMeta.decimals)} {quote.outMeta.symbol}
              </span>
            </div>
          )}
        </div>
      )}

      <div className="mt-4 p-3 bg-kur-bg-hover rounded-lg text-xs sm:text-sm text-kur-text-muted">
        Leitura do pool e cotação por <code>eth_call</code> no RPC público da Polygon
        (<code>QuoterV2</code>); o swap vai para o <code>SwapRouter02</code>
        {' '}(<code>0x68b3…Fc45</code>) assinado pela carteira. MATIC nativo entra como
        {' '}<code>value</code> e sai via <code>unwrapWETH9</code>. Defina
        {' '}<code>VITE_POLYGON_RPC_URL</code> para usar seu próprio nó.
      </div>
    </div>
  );
}
