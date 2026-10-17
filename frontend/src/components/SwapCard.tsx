import { useCallback, useEffect, useRef, useState } from 'react';
import {
  KURAMA_CHAIN_ID,
  connectMetaMask,
  ensureKuramaChain,
  getEvmProvider,
  isMetaMaskInstalled,
  sendWalletTransaction,
  shortAddress,
  waitForTransactionReceipt,
} from '../api/metamask';
import {
  applySlippage,
  defaultRouterAddress,
  formatUnits,
  parseUnits,
  quoteAmountOut,
  readAllowance,
  readPair,
  readTokenMeta,
  type PairSides,
  type TokenMeta,
} from '../api/dex';
import {
  decodeSwapExecuted,
  encodeApprove,
  encodeSwapExactTokensForTokens,
  isAddress,
  sameAddress,
} from '../api/evmAbi';

const ROUTER_KEY = 'kur.dex.router';
const TOKEN_IN_KEY = 'kur.dex.tokenIn';
const TOKEN_OUT_KEY = 'kur.dex.tokenOut';

type Step = 'idle' | 'quoting' | 'approving' | 'swapping' | 'done';

interface Quote {
  pair: PairSides;
  inMeta: TokenMeta;
  outMeta: TokenMeta;
  amountIn: bigint;
  amountOut: bigint;
  amountOutMin: bigint;
  allowance: bigint;
}

function stored(key: string): string {
  try {
    return window.localStorage.getItem(key) ?? '';
  } catch {
    return '';
  }
}

function store(key: string, value: string): void {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    /* modo privado: ignora */
  }
}

function errorMessage(err: unknown): string {
  if (err instanceof Error) return err.message;
  const raw = err as { message?: string; data?: { message?: string } };
  return raw?.data?.message || raw?.message || 'Erro inesperado';
}

/**
 * Swap do DEX assinado pela carteira (MetaMask / EIP-1193).
 *
 * O usuário informa o `KurRouter` e os dois tokens ERC-20; o par é descoberto
 * no factory (`getPair`) e as reservas em `getReserves()`. A cotação usa a
 * mesma fórmula do contrato (`x*y=k`, taxa 0,3%). O swap pede `approve` quando
 * a allowance é insuficiente e envia
 * `swapExactTokensForTokens(amountIn, amountOutMin, [in, out], conta)` para a
 * wallet — que assina e transmite via `eth_sendRawTransaction`.
 */
export default function SwapCard() {
  const [router, setRouter] = useState(() => stored(ROUTER_KEY) || defaultRouterAddress());
  const [tokenIn, setTokenIn] = useState(() => stored(TOKEN_IN_KEY));
  const [tokenOut, setTokenOut] = useState(() => stored(TOKEN_OUT_KEY));
  const [amount, setAmount] = useState('');
  const [slippage, setSlippage] = useState('50');

  const [account, setAccount] = useState<string | null>(null);
  const [chainId, setChainId] = useState<number | null>(null);
  const [quote, setQuote] = useState<Quote | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [step, setStep] = useState<Step>('idle');

  const [approveTx, setApproveTx] = useState<string | null>(null);
  const [swapTx, setSwapTx] = useState<string | null>(null);
  const [received, setReceived] = useState<bigint | null>(null);

  const quoteSeq = useRef(0);
  const installed = isMetaMaskInstalled();
  const slippageBps = Math.min(9_999, Math.max(0, Number.parseFloat(slippage) || 50));

  useEffect(() => store(ROUTER_KEY, router), [router]);
  useEffect(() => store(TOKEN_IN_KEY, tokenIn), [tokenIn]);
  useEffect(() => store(TOKEN_OUT_KEY, tokenOut), [tokenOut]);

  // Reconecta silenciosamente + acompanha conta/rede da wallet.
  useEffect(() => {
    const eth = getEvmProvider();
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

    const onAccounts = (...args: unknown[]) => {
      const list = (args[0] as string[]) ?? [];
      setAccount(list[0] ?? null);
    };
    const onChain = (...args: unknown[]) => setChainId(parseInt(args[0] as string, 16));
    eth.on?.('accountsChanged', onAccounts);
    eth.on?.('chainChanged', onChain);
    return () => {
      eth.removeListener?.('accountsChanged', onAccounts);
      eth.removeListener?.('chainChanged', onChain);
    };
  }, []);

  const loadQuote = useCallback(async () => {
    const seq = ++quoteSeq.current;
    const stale = () => seq !== quoteSeq.current;

    if (!isAddress(router)) {
      setQuote(null);
      setError(router.trim() ? 'Endereço do KurRouter inválido' : null);
      return;
    }
    if (!isAddress(tokenIn) || !isAddress(tokenOut)) {
      setQuote(null);
      setError(null);
      return;
    }
    if (sameAddress(tokenIn, tokenOut)) {
      setQuote(null);
      setError('Escolha dois tokens diferentes');
      return;
    }

    setStep((current) => (current === 'idle' || current === 'done' ? 'quoting' : current));
    try {
      const pair = await readPair(router, tokenIn, tokenOut);
      if (stale()) return;
      if (!pair) {
        setQuote(null);
        setError('Esse par ainda não existe no factory — adicione liquidez primeiro.');
        return;
      }
      const [inMeta, outMeta] = await Promise.all([
        readTokenMeta(tokenIn, account ?? undefined),
        readTokenMeta(tokenOut, account ?? undefined),
      ]);
      if (stale()) return;

      const amountIn = amount.trim() ? parseUnits(amount, inMeta.decimals) : 0n;
      const amountOut = quoteAmountOut(amountIn, pair.reserveIn, pair.reserveOut);
      const allowance = account ? await readAllowance(tokenIn, account, router) : 0n;
      if (stale()) return;

      setError(null);
      setQuote({
        pair,
        inMeta,
        outMeta,
        amountIn,
        amountOut,
        amountOutMin: applySlippage(amountOut, slippageBps),
        allowance,
      });
    } catch (err) {
      if (stale()) return;
      setQuote(null);
      setError(errorMessage(err));
    } finally {
      if (!stale()) setStep((current) => (current === 'quoting' ? 'idle' : current));
    }
  }, [router, tokenIn, tokenOut, amount, account, slippageBps]);

  // Recotação com debounce (digitar / trocar token / conectar conta).
  useEffect(() => {
    const timer = setTimeout(() => { void loadQuote(); }, 350);
    return () => clearTimeout(timer);
  }, [loadQuote]);

  const handleConnect = async () => {
    setError(null);
    try {
      const next = await connectMetaMask();
      setAccount(next);
      const eth = getEvmProvider();
      if (eth) setChainId(parseInt((await eth.request({ method: 'eth_chainId' })) as string, 16));
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  const handleSwitchChain = async () => {
    setError(null);
    try {
      await ensureKuramaChain();
      const eth = getEvmProvider();
      if (eth) setChainId(parseInt((await eth.request({ method: 'eth_chainId' })) as string, 16));
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
    setReceived(null);
    setApproveTx(null);
    setSwapTx(null);
    try {
      if (!getEvmProvider()) throw new Error('Instale a MetaMask para assinar o swap');
      const from = await connectMetaMask();
      setAccount(from);

      if (quote.amountIn <= 0n) throw new Error('Informe a quantidade de entrada');
      if (quote.inMeta.balance < quote.amountIn) {
        throw new Error(`Saldo insuficiente de ${quote.inMeta.symbol}`);
      }

      // Recheca o par imediatamente antes de assinar: se o preço andou além do
      // slippage, aborta em vez de mandar uma tx que reverte (gas perdido).
      const fresh = await readPair(router, tokenIn, tokenOut);
      if (!fresh) throw new Error('O par desapareceu do factory');
      const freshOut = quoteAmountOut(quote.amountIn, fresh.reserveIn, fresh.reserveOut);
      if (freshOut < quote.amountOutMin) {
        throw new Error('Preço mudou além do slippage — recote antes de trocar');
      }
      const amountOutMin = applySlippage(freshOut, slippageBps);

      const allowance = await readAllowance(tokenIn, from, router);
      if (allowance < quote.amountIn) {
        setStep('approving');
        const approveHash = await sendWalletTransaction({
          from,
          to: tokenIn,
          data: encodeApprove(router, quote.amountIn),
        });
        setApproveTx(approveHash);
        const approveReceipt = await waitForTransactionReceipt(approveHash);
        if (!approveReceipt) throw new Error('Timeout esperando o approve');
        if (parseInt(approveReceipt.status, 16) !== 1) {
          throw new Error('Approve revertido pela EVM');
        }
      }

      setStep('swapping');
      const swapHash = await sendWalletTransaction({
        from,
        to: router,
        data: encodeSwapExactTokensForTokens(
          quote.amountIn,
          amountOutMin,
          [tokenIn, tokenOut],
          from,
        ),
      });
      setSwapTx(swapHash);
      const receipt = await waitForTransactionReceipt(swapHash);
      if (!receipt) throw new Error('Timeout esperando o recibo do swap');
      if (parseInt(receipt.status, 16) !== 1) {
        throw new Error('Swap revertido (slippage, liquidez ou allowance)');
      }
      setReceived(decodeSwapExecuted(receipt.logs, router) ?? freshOut);
      setStep('done');
      void loadQuote();
    } catch (err) {
      setStep('idle');
      setError(errorMessage(err));
    }
  };

  const needsApproval = quote !== null && quote.allowance < quote.amountIn;
  const busy = step === 'approving' || step === 'swapping';
  const onKuramaChain = chainId === KURAMA_CHAIN_ID;
  const canSwap = quote !== null && quote.amountIn > 0n && !busy && onKuramaChain;
  const buttonLabel =
    step === 'approving' ? 'Aprovando...'
      : step === 'swapping' ? 'Trocando...'
        : needsApproval ? 'Aprovar e trocar'
          : 'Trocar via wallet';

  return (
    <div className="bg-kur-bg-card border border-kur-border rounded-xl p-4 sm:p-5">
      <div className="flex flex-wrap items-center justify-between gap-2 mb-3">
        <h2 className="text-base sm:text-lg font-semibold text-kur-text">Swap (DEX — AMM x*y=k)</h2>
        {account ? (
          <div className="flex items-center gap-2">
            <span className="text-[11px] px-2 py-1 rounded bg-kur-accent/10 text-kur-accent font-mono" title={account}>
              {shortAddress(account)}
            </span>
            <span className={`text-[11px] px-2 py-1 rounded ${
              onKuramaChain ? 'bg-kur-green/10 text-kur-green' : 'bg-kur-orange/10 text-kur-orange'
            }`}>
              {chainId === null ? '—' : onKuramaChain ? `chain ${chainId}` : `outra rede (${chainId})`}
            </span>
            {!onKuramaChain && (
              <button
                onClick={handleSwitchChain}
                className="text-[11px] px-2 py-1 rounded bg-kur-yellow/10 text-kur-yellow border border-kur-yellow/30 hover:bg-kur-yellow/20"
              >
                Usar KuramaChain
              </button>
            )}
          </div>
        ) : (
          <button
            onClick={handleConnect}
            className="px-4 py-2 bg-kur-accent/10 text-kur-accent border border-kur-accent/30 rounded-lg hover:bg-kur-accent/20 transition-colors text-sm"
          >
            {installed ? 'Conectar carteira' : 'Instalar MetaMask'}
          </button>
        )}
      </div>

      <div className="mb-3">
        <label className="block text-xs text-kur-text-muted mb-1 font-medium">KurRouter</label>
        <input
          type="text"
          value={router}
          onChange={(e) => setRouter(e.target.value.trim())}
          placeholder="0x... (endereço do KurRouter)"
          className="w-full px-3 py-2.5 bg-kur-bg-hover border border-kur-border rounded-lg text-xs sm:text-sm text-kur-text placeholder-kur-text-muted/50 focus:outline-none focus:border-kur-accent/50 font-mono"
        />
        <p className="mt-1 text-[11px] text-kur-text-muted">
          O factory e o par saem do router (<code>factory()</code> → <code>getPair()</code>);
          qualquer par ERC-20 criado no <code>KurFactory</code> funciona.
        </p>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 mb-3">
        <div>
          <label className="block text-xs text-kur-text-muted mb-1 font-medium">
            Token de entrada {quote ? `(${quote.inMeta.symbol})` : ''}
          </label>
          <input
            type="text"
            value={tokenIn}
            onChange={(e) => setTokenIn(e.target.value.trim())}
            placeholder="0x... (token ERC-20 de entrada)"
            className="w-full px-3 py-2.5 bg-kur-bg-hover border border-kur-border rounded-lg text-xs sm:text-sm text-kur-text placeholder-kur-text-muted/50 focus:outline-none focus:border-kur-accent/50 font-mono"
          />
        </div>
        <div>
          <label className="block text-xs text-kur-text-muted mb-1 font-medium">
            Token de saída {quote ? `(${quote.outMeta.symbol})` : ''}
          </label>
          <input
            type="text"
            value={tokenOut}
            onChange={(e) => setTokenOut(e.target.value.trim())}
            placeholder="0x... (token ERC-20 de saída)"
            className="w-full px-3 py-2.5 bg-kur-bg-hover border border-kur-border rounded-lg text-xs sm:text-sm text-kur-text placeholder-kur-text-muted/50 focus:outline-none focus:border-kur-accent/50 font-mono"
          />
        </div>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 mb-4">
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

      {quote && (
        <div className="bg-kur-bg/50 rounded-lg p-3 mb-4 text-xs sm:text-sm space-y-1">
          <div className="flex justify-between gap-2">
            <span className="text-kur-text-muted">Par</span>
            <span className="text-kur-text font-mono" title={quote.pair.pair}>{shortAddress(quote.pair.pair)}</span>
          </div>
          <div className="flex justify-between gap-2">
            <span className="text-kur-text-muted">Reservas</span>
            <span className="text-kur-text font-mono">
              {formatUnits(quote.pair.reserveIn, quote.inMeta.decimals, 4)} {quote.inMeta.symbol}
              {' / '}
              {formatUnits(quote.pair.reserveOut, quote.outMeta.decimals, 4)} {quote.outMeta.symbol}
            </span>
          </div>
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
        </div>
      )}

      <button
        onClick={handleSwap}
        disabled={!canSwap}
        className="w-full px-5 py-2.5 bg-kur-yellow/10 text-kur-yellow border border-kur-yellow/30 rounded-lg hover:bg-kur-yellow/20 transition-colors text-sm disabled:opacity-50"
      >
        {step === 'quoting' ? 'Cotando...' : buttonLabel}
      </button>
      {!account && (
        <p className="mt-2 text-[11px] text-kur-text-muted text-center">
          Conecte a carteira para assinar — a chave privada nunca sai dela.
        </p>
      )}

      {(approveTx || swapTx || received !== null) && (
        <div className="mt-3 bg-kur-green/5 border border-kur-green/20 rounded-lg p-3 text-xs sm:text-sm space-y-1">
          {approveTx && (
            <div className="flex justify-between gap-2">
              <span className="text-kur-text-muted">Approve</span>
              <span className="text-kur-text font-mono break-all">{approveTx}</span>
            </div>
          )}
          {swapTx && (
            <div className="flex justify-between gap-2">
              <span className="text-kur-text-muted">Swap</span>
              <span className="text-kur-text font-mono break-all">{swapTx}</span>
            </div>
          )}
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
        A wallet assina <code>approve</code> (quando necessário) e <code>swapExactTokensForTokens</code>
        {' '}do <code>KurRouter</code>; o nó recebe a tx crua em <code>POST /rpc</code>. O valor recebido é lido do
        evento <code>SwapExecuted</code> no recibo. Pares são com tokens ERC-20 (KUR nativo não é ERC-20).
      </div>
    </div>
  );
}
