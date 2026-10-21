/**
 * Ponte com os pools Uniswap V3 na Polygon (chain 137).
 *
 * Tudo roda no navegador, sem SDK novo:
 *   • leitura  → `eth_call` em um RPC público da Polygon (factory, pool, ERC-20);
 *   • cotação  → `QuoterV2.quoteExactInputSingle` (staticcall, não gasta gas);
 *   • swap     → `SwapRouter02`, assinado pela carteira EIP-1193 (a chave nunca
 *                sai da wallet; o front só monta o calldata).
 *
 * Endereços conferidos na documentação oficial de deployments da Uniswap V3
 * (Polygon): factory, QuoterV2, SwapRouter02 e WMATIC.
 */
import {
  SELECTORS,
  decodeAddress,
  decodeTokenString,
  decodeUint,
  decodeWord,
  encodeAddress,
  isAddress,
  isZeroAddress,
  sameAddress,
  word,
} from './evmAbi';
import { formatUnits, parseUnits } from './dex';
import {
  RpcError,
  ensureChain,
  getEvmProvider,
  rpcRequestAt,
  sendWalletTransaction,
  waitForTransactionReceipt,
  type KuramaChainParams,
} from './evmWallet';

export { formatUnits, parseUnits };

// ─── Rede ───────────────────────────────────────────────────────────

export const POLYGON_CHAIN_ID = 137;

/** Parâmetros para `wallet_addEthereumChain` quando a wallet não tem Polygon. */
/**
 * RPC público padrão da Polygon.
 *
 * `polygon-rpc.com` (o mais citado) passou a exigir API key e devolve 401, por
 * isso o padrão é o nó público da PublicNode; a ordem de fallback está em
 * `polygonRpcUrls()`.
 */
const DEFAULT_POLYGON_RPC = 'https://polygon-bor-rpc.publicnode.com';
const FALLBACK_POLYGON_RPCS = ['https://1rpc.io/matic', 'https://polygon.drpc.org'];

export const POLYGON_CHAIN_PARAMS: Pick<
  KuramaChainParams,
  'chainName' | 'nativeCurrency' | 'rpcUrls' | 'blockExplorerUrls'
> = {
  chainName: 'Polygon',
  nativeCurrency: { name: 'POL', symbol: 'POL', decimals: 18 },
  rpcUrls: [DEFAULT_POLYGON_RPC],
  blockExplorerUrls: ['https://polygonscan.com'],
};

/** URLs de JSON-RPC da Polygon (env primeiro, depois RPCs públicos). */
export function polygonRpcUrls(): string[] {
  const fromEnv = (import.meta as unknown as { env?: Record<string, string> }).env
    ?.VITE_POLYGON_RPC_URL;
  return Array.from(
    new Set([fromEnv, DEFAULT_POLYGON_RPC, ...FALLBACK_POLYGON_RPCS].filter(Boolean) as string[]),
  );
}

function errorMessage(err: unknown): string {
  if (err instanceof Error) return err.message;
  const raw = err as { message?: string };
  return raw?.message || 'erro desconhecido';
}

/**
 * `eth_*` na Polygon, tentando o próximo RPC quando a URL falha.
 *
 * Um erro JSON-RPC (revert do contrato) **não** rotaciona de RPC: o resultado
 * seria o mesmo e o usuário esperaria três timeouts.
 */
export async function polygonRpc<T = unknown>(method: string, params: unknown[] = []): Promise<T> {
  let lastError: unknown = null;
  for (const url of polygonRpcUrls()) {
    try {
      return await rpcRequestAt<T>(url, method, params);
    } catch (err) {
      if (err instanceof RpcError) throw err;
      lastError = err;
    }
  }
  throw new Error(`RPC Polygon (${method}): ${errorMessage(lastError)}`);
}

/** `eth_call` cru na Polygon. */
export async function ethCallPolygon(to: string, data: string): Promise<string> {
  const result = await polygonRpc<string>('eth_call', [{ to, data }, 'latest']);
  if (!result || result === '0x') throw new Error(`eth_call vazio em ${to}`);
  return result;
}

/** Troca a wallet para a Polygon (adiciona a rede se necessário). */
export async function ensurePolygonChain(): Promise<void> {
  if (!getEvmProvider()) throw new Error('Carteira EVM não encontrada no navegador');
  await ensureChain(POLYGON_CHAIN_ID, POLYGON_CHAIN_PARAMS);
}

// ─── Contratos e tokens (Polygon mainnet) ───────────────────────────

export const UNISWAP = {
  /** UniswapV3Factory */
  factory: '0x1F98431c8aD98523631AE4a59f267346ea31F984',
  /** SwapRouter02 */
  router02: '0x68b3465833fb72A70ecDF485E0e4C7bD8665Fc45',
  /** QuoterV2 */
  quoterV2: '0x61fFE014bA17989E743c5F6cB21bF9697530B21e',
  /** WMATIC (wrapped native da Polygon) */
  wmatic: '0x0d500B1d8E8eF31E21C99d1Db9A6444d3ADf1270',
  usdc: '0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359',
  usdcE: '0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174',
  usdt: '0xc2132D05D31c914a87C6611C10748AEb04B58e8F',
  dai: '0x8f3Cf7ad23Cd3CaDbD9735AFf958023239c6A063',
  weth: '0x7ceB23fD6bC0adD59E62ac25578270cFf1b9f619',
  wbtc: '0x1BFD67037B42Cf73acF2047067bd4F2C47D9BfD6',
} as const;

/**
 * Endereço-sentinela para o MATIC nativo (convenção dos agregadores).
 *
 * No swap ele é trocado por WMATIC; a diferença é que a entrada vai como
 * `value` da transação e a saída passa por `unwrapWETH9`.
 */
export const NATIVE_TOKEN = '0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE';

export function isNativeToken(address: string): boolean {
  return sameAddress(address, NATIVE_TOKEN);
}

/** Endereço ERC-20 equivalente (MATIC nativo → WMATIC). */
export function wrappedToken(address: string): string {
  return isNativeToken(address) ? UNISWAP.wmatic : address;
}

export interface PolygonTokenOption {
  symbol: string;
  address: string;
  decimals: number;
}

/** Tokens oferecidos no seletor do card (Polygon). */
export const POLYGON_TOKENS: PolygonTokenOption[] = [
  { symbol: 'MATIC', address: NATIVE_TOKEN, decimals: 18 },
  { symbol: 'WMATIC', address: UNISWAP.wmatic, decimals: 18 },
  { symbol: 'USDC', address: UNISWAP.usdc, decimals: 6 },
  { symbol: 'USDC.e', address: UNISWAP.usdcE, decimals: 6 },
  { symbol: 'USDT', address: UNISWAP.usdt, decimals: 6 },
  { symbol: 'DAI', address: UNISWAP.dai, decimals: 18 },
  { symbol: 'WETH', address: UNISWAP.weth, decimals: 18 },
  { symbol: 'WBTC', address: UNISWAP.wbtc, decimals: 8 },
];

/** Busca a metadata padrão de um token da lista (undefined se for custom). */
export function knownToken(address: string): PolygonTokenOption | undefined {
  return POLYGON_TOKENS.find((token) => sameAddress(token.address, address));
}

// ─── Seletores ABI (Uniswap V3) ─────────────────────────────────────

const UNISWAP_SELECTORS = {
  /** UniswapV3Factory.getPool(address,address,uint24) */
  getPool: '0x1698ee82',
  /** UniswapV3Pool.slot0() */
  slot0: '0x3850c7bd',
  /** UniswapV3Pool.liquidity() */
  liquidity: '0x1a686502',
  /** QuoterV2.quoteExactInputSingle((address,address,uint256,uint24,uint160)) */
  quoteExactInputSingle: '0xc6a5026a',
  /** SwapRouter02.exactInputSingle((address,address,uint24,address,uint256,uint256,uint160)) */
  exactInputSingle: '0x04e45aaf',
  /** SwapRouter02.unwrapWETH9(uint256,address) */
  unwrapWETH9: '0x49404b7c',
  /** SwapRouter02.multicall(bytes[]) */
  multicall: '0xac9650d8',
} as const;

/** Taxas (em centésimos de bp) dos pools Uniswap V3. */
export const FEE_TIERS = [100, 500, 3000, 10000] as const;
export type FeeTier = (typeof FEE_TIERS)[number];

function strip0x(value: string): string {
  return value.startsWith('0x') || value.startsWith('0X') ? value.slice(2) : value;
}

/** `getPool(tokenA, tokenB, fee)` com os endereços ordenados como o factory exige. */
export function encodeGetPool(tokenA: string, tokenB: string, fee: number): string {
  const [a, b] = [tokenA, tokenB].sort((x, y) => x.toLowerCase().localeCompare(y.toLowerCase()));
  return UNISWAP_SELECTORS.getPool + encodeAddress(a) + encodeAddress(b) + word(fee);
}

/** Parâmetros de `SwapRouter02.exactInputSingle` (7 campos estáticos). */
export interface ExactInputSingleParams {
  tokenIn: string;
  tokenOut: string;
  fee: number;
  recipient: string;
  amountIn: bigint;
  amountOutMinimum: bigint;
  /** 0 = sem limite de preço (padrão). */
  sqrtPriceLimitX96?: bigint;
}

export function encodeExactInputSingle(params: ExactInputSingleParams): string {
  return (
    UNISWAP_SELECTORS.exactInputSingle +
    encodeAddress(params.tokenIn) +
    encodeAddress(params.tokenOut) +
    word(params.fee) +
    encodeAddress(params.recipient) +
    word(params.amountIn) +
    word(params.amountOutMinimum) +
    word(params.sqrtPriceLimitX96 ?? 0n)
  );
}

/** `unwrapWETH9(amountMinimum, recipient)` — MATIC nativo na saída. */
export function encodeUnwrapWETH9(amountMinimum: bigint, recipient: string): string {
  return UNISWAP_SELECTORS.unwrapWETH9 + word(amountMinimum) + encodeAddress(recipient);
}

/** `multicall(bytes[])` — cada chamada interna vem com tamanho + padding. */
export function encodeMulticall(calls: string[]): string {
  if (!calls.length) throw new Error('multicall sem chamadas');
  const bodies = calls.map((call) => strip0x(call));
  const elements = bodies.map(
    (body) => word(BigInt(body.length / 2)) + body.padEnd(Math.ceil(body.length / 64) * 64, '0'),
  );

  let running = bodies.length * 32;
  const offsets = elements.map((element) => {
    const offset = word(BigInt(running));
    running += element.length / 2;
    return offset;
  });

  return UNISWAP_SELECTORS.multicall + word(32) + word(bodies.length) + offsets.join('') + elements.join('');
}

// ─── Pool ───────────────────────────────────────────────────────────

export interface UniswapPool {
  address: string;
  token0: string;
  token1: string;
  fee: number;
  /** Preço atual como sqrt(price) * 2^96. */
  sqrtPriceX96: bigint;
  tick: number;
  /** Liquidez ativa na faixa atual (uint128). */
  liquidity: bigint;
}

/** Endereço do pool `tokenA/tokenB` nessa taxa (null quando não existe). */
export async function findPool(tokenA: string, tokenB: string, fee: number): Promise<string | null> {
  const a = wrappedToken(tokenA);
  const b = wrappedToken(tokenB);
  if (!isAddress(a) || !isAddress(b)) throw new Error('Endereço de token inválido');
  const out = await ethCallPolygon(UNISWAP.factory, encodeGetPool(a, b, fee));
  const pool = decodeAddress(out);
  return isZeroAddress(pool) ? null : pool;
}

/** Lê `slot0` + `liquidity` do pool. */
export async function readPoolState(pool: string, fee: number): Promise<UniswapPool> {
  const [slot0, liquidityOut, token0Out, token1Out] = await Promise.all([
    ethCallPolygon(pool, UNISWAP_SELECTORS.slot0),
    ethCallPolygon(pool, UNISWAP_SELECTORS.liquidity),
    ethCallPolygon(pool, SELECTORS.token0),
    ethCallPolygon(pool, SELECTORS.token1),
  ]);
  const sqrtPriceX96 = decodeUint(slot0, 0);
  const rawTick = decodeWord(slot0, 1);
  const tick = Number(rawTick >= 1n << 255n ? rawTick - (1n << 256n) : rawTick);

  return {
    address: pool.toLowerCase(),
    token0: decodeAddress(token0Out),
    token1: decodeAddress(token1Out),
    fee,
    sqrtPriceX96,
    tick,
    liquidity: decodeUint(liquidityOut, 0),
  };
}

/** Lê o pool (null quando não existe). */
export async function readPool(
  tokenA: string,
  tokenB: string,
  fee: number,
): Promise<UniswapPool | null> {
  const pool = await findPool(tokenA, tokenB, fee);
  if (!pool) return null;
  return readPoolState(pool, fee);
}

/**
 * Descobre a taxa do pool com mais liquidez entre `tokenA` e `tokenB`.
 *
 * Returns:
 *   `null` quando não há nenhum pool criado para o par.
 */
export async function detectFeeTier(tokenA: string, tokenB: string): Promise<number | null> {
  const found = await Promise.all(
    FEE_TIERS.map(async (fee) => ({ fee, pool: await findPool(tokenA, tokenB, fee) })),
  );
  const existing = found.flatMap((entry) =>
    entry.pool ? [{ fee: entry.fee as number, pool: entry.pool }] : [],
  );
  if (!existing.length) return null;

  const states = await Promise.all(
    existing.map(async (entry) => {
      try {
        return { fee: entry.fee, liquidity: (await readPoolState(entry.pool, entry.fee)).liquidity };
      } catch {
        return { fee: entry.fee, liquidity: 0n };
      }
    }),
  );
  states.sort((a, b) => (a.liquidity === b.liquidity ? 0 : a.liquidity > b.liquidity ? -1 : 1));
  return states[0].fee;
}

/** Preço de 1 token0 em token1 (float, só para exibição). */
export function poolPrice(pool: UniswapPool, decimals0: number, decimals1: number): number {
  const sqrtPrice = Number(pool.sqrtPriceX96) / 2 ** 96;
  return sqrtPrice * sqrtPrice * 10 ** (decimals0 - decimals1);
}

/**
 * Preço de 1 `tokenIn` em `tokenOut` (float, só para exibição).
 *
 * `slot0` dá o preço de token0 em token1; quando a entrada é o token1 o valor
 * precisa ser invertido — senão a UI mostra o par de cabeça para baixo.
 */
export function priceTokenInToTokenOut(
  pool: UniswapPool,
  tokenIn: string,
  decimalsIn: number,
  decimalsOut: number,
): number | null {
  const inIsToken0 = sameAddress(pool.token0, wrappedToken(tokenIn));
  const outPerIn = inIsToken0
    ? poolPrice(pool, decimalsIn, decimalsOut)
    : poolPrice(pool, decimalsOut, decimalsIn);
  if (!Number.isFinite(outPerIn) || outPerIn <= 0) return null;
  return inIsToken0 ? outPerIn : 1 / outPerIn;
}

// ─── Tokens (leitura) ───────────────────────────────────────────────

export interface PolygonToken {
  address: string;
  symbol: string;
  decimals: number;
  /** Saldo do dono (0n quando nenhum dono foi informado). */
  balance: bigint;
}

/** Saldo nativo (wei) de um endereço na Polygon. */
export async function readPolygonBalance(token: string, owner: string): Promise<bigint> {
  if (isNativeToken(token)) {
    const hex = await polygonRpc<string>('eth_getBalance', [owner, 'latest']);
    return BigInt(hex ?? '0x0');
  }
  if (!isAddress(token)) throw new Error(`Token inválido: ${token}`);
  const out = await ethCallPolygon(token, SELECTORS.balanceOf + encodeAddress(owner));
  return decodeUint(out, 0);
}

/** Lê `symbol()`, `decimals()` e (opcional) `balanceOf(owner)` na Polygon. */
export async function readPolygonToken(token: string, owner?: string): Promise<PolygonToken> {
  if (isNativeToken(token)) {
    return {
      address: NATIVE_TOKEN,
      symbol: 'MATIC',
      decimals: 18,
      balance: owner ? await readPolygonBalance(token, owner) : 0n,
    };
  }
  if (!isAddress(token)) throw new Error(`Token inválido: ${token}`);

  const [symbolOut, decimalsOut, balance] = await Promise.all([
    ethCallPolygon(token, SELECTORS.symbol).catch(() => ''),
    ethCallPolygon(token, SELECTORS.decimals),
    owner ? readPolygonBalance(token, owner) : Promise.resolve(0n),
  ]);
  const known = knownToken(token);

  return {
    address: token.toLowerCase(),
    symbol: known?.symbol || (symbolOut ? decodeTokenString(symbolOut) : '?') || '?',
    decimals: Number(decodeUint(decimalsOut)),
    balance,
  };
}

/** Allowance ERC-20 do dono para o SwapRouter02. */
export async function readRouterAllowance(token: string, owner: string): Promise<bigint> {
  if (isNativeToken(token)) return 0n;
  const out = await ethCallPolygon(
    token,
    SELECTORS.allowance + encodeAddress(owner) + encodeAddress(UNISWAP.router02),
  );
  return decodeUint(out, 0);
}

// ─── Cotação ────────────────────────────────────────────────────────

export interface QuoteRequest {
  tokenIn: string;
  tokenOut: string;
  fee: number;
  amountIn: bigint;
}

/**
 * Cotação exata via `QuoterV2` (single pool).
 *
 * Reverte quando o pool não existe ou não tem liquidez para o tamanho — o
 * chamador trata como "sem rota".
 */
export async function quoteExactInputSingle(request: QuoteRequest): Promise<bigint> {
  if (request.amountIn <= 0n) return 0n;
  const data =
    UNISWAP_SELECTORS.quoteExactInputSingle +
    encodeAddress(wrappedToken(request.tokenIn)) +
    encodeAddress(wrappedToken(request.tokenOut)) +
    word(request.amountIn) +
    word(request.fee) +
    word(0n);
  const out = await ethCallPolygon(UNISWAP.quoterV2, data);
  return decodeUint(out, 0);
}

/** Aplica a tolerância de slippage (bps) no mínimo aceito. */
export function applySlippage(amountOut: bigint, slippageBps: number): bigint {
  const bps = BigInt(Math.min(9_999, Math.max(0, Math.round(slippageBps))));
  return (amountOut * (10_000n - bps)) / 10_000n;
}

// ─── Swap (escrita assinada pela carteira) ──────────────────────────

export interface UniswapSwapRequest {
  from: string;
  tokenIn: string;
  tokenOut: string;
  fee: number;
  amountIn: bigint;
  amountOutMin: bigint;
}

export interface UniswapSwapCall {
  to: string;
  data: string;
  /** Valor em wei (hex) — só quando a entrada é MATIC nativo. */
  value?: string;
}

/**
 * Monta o calldata do swap no `SwapRouter02`.
 *
 *   ERC-20 → ERC-20 : `exactInputSingle` direto para o usuário
 *   MATIC  → ERC-20 : `exactInputSingle` com `value` (o router faz o wrap)
 *   *      → MATIC  : `multicall([exactInputSingle(recipient=router), unwrapWETH9])`
 */
export function buildSwapCall(request: UniswapSwapRequest): UniswapSwapCall {
  const nativeIn = isNativeToken(request.tokenIn);
  const nativeOut = isNativeToken(request.tokenOut);
  if (nativeIn && nativeOut) throw new Error('Entrada e saída não podem ser MATIC nativo');
  if (sameAddress(wrappedToken(request.tokenIn), wrappedToken(request.tokenOut))) {
    throw new Error('Escolha dois tokens diferentes');
  }

  const inner = encodeExactInputSingle({
    tokenIn: wrappedToken(request.tokenIn),
    tokenOut: wrappedToken(request.tokenOut),
    fee: request.fee,
    // Saída nativa: o router recebe o WMATIC e devolve MATIC via unwrapWETH9.
    recipient: nativeOut ? UNISWAP.router02 : request.from,
    amountIn: request.amountIn,
    // O mínimo é comparado no unwrapWETH9 quando a saída é nativa.
    amountOutMinimum: nativeOut ? 0n : request.amountOutMin,
  });

  const data = nativeOut
    ? encodeMulticall([inner, encodeUnwrapWETH9(request.amountOutMin, request.from)])
    : inner;

  return {
    to: UNISWAP.router02,
    data,
    ...(nativeIn ? { value: '0x' + request.amountIn.toString(16) } : {}),
  };
}

/** Pede `approve` do token de entrada para o SwapRouter02. */
export async function approveRouter(token: string, from: string, amount: bigint): Promise<string> {
  if (isNativeToken(token)) throw new Error('MATIC nativo não precisa de approve');
  return sendWalletTransaction({
    from,
    to: token,
    data: SELECTORS.approve + encodeAddress(UNISWAP.router02) + word(amount),
  });
}

export type UniswapSwapStep = 'approving' | 'swapping';

/**
 * Executa o swap: approve (se preciso) → swap → espera os recibos.
 *
 * Parameters:
 *   request: dados do swap já com `amountOutMin` calculado.
 *   onStep: callback de progresso (`approving`/`swapping`).
 *
 * Returns:
 *   `{ approveTx, swapTx }` — hashes das transações enviadas.
 */
export async function executeUniswapSwap(
  request: UniswapSwapRequest,
  onStep?: (step: UniswapSwapStep) => void,
): Promise<{ approveTx: string | null; swapTx: string }> {
  if (!getEvmProvider()) throw new Error('Carteira EVM não encontrada no navegador');
  if (request.amountIn <= 0n) throw new Error('Informe a quantidade de entrada');

  let approveTx: string | null = null;
  if (!isNativeToken(request.tokenIn)) {
    const allowance = await readRouterAllowance(request.tokenIn, request.from);
    if (allowance < request.amountIn) {
      onStep?.('approving');
      approveTx = await approveRouter(request.tokenIn, request.from, request.amountIn);
      const approveReceipt = await waitForTransactionReceipt(approveTx);
      if (!approveReceipt) throw new Error('Timeout esperando o approve');
      if (parseInt(approveReceipt.status, 16) !== 1) throw new Error('Approve revertido na Polygon');
    }
  }

  onStep?.('swapping');
  const call = buildSwapCall(request);
  const swapTx = await sendWalletTransaction({
    from: request.from,
    to: call.to,
    data: call.data,
    value: call.value,
  });
  const receipt = await waitForTransactionReceipt(swapTx);
  if (!receipt) throw new Error('Timeout esperando o recibo do swap');
  if (parseInt(receipt.status, 16) !== 1) {
    throw new Error('Swap revertido na Polygon (slippage ou liquidez)');
  }
  return { approveTx, swapTx };
}

/** Link do Polygonscan para uma transação. */
export function polygonscanTx(hash: string): string {
  return `https://polygonscan.com/tx/${hash}`;
}
