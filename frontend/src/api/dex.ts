/**
 * DEX da KuramaChain no frontend: leitura de pares/reservas e cotação AMM.
 *
 * Funciona para **qualquer par ERC-20** que exista no `KurFactory`: o par é
 * descoberto por `getPair(tokenIn, tokenOut)` a partir do `KurRouter`
 * informado (o factory é lido on-chain em `router.factory()`).
 *
 * Só leitura aqui — a escrita (approve + swap) é assinada pela wallet em
 * `metamask.ts`/`SwapCard`.
 */
import {
  SELECTORS,
  decodeAddress,
  decodeTokenString,
  decodeUint,
  encodeAddress,
  encodeGetPair,
  isAddress,
  isZeroAddress,
  sameAddress,
} from './evmAbi';
import { rpcRequest } from './metamask';

/** `eth_call` cru (`0x...`). Lança se a chamada reverter/sem código. */
export async function ethCall(to: string, data: string): Promise<string> {
  const result = await rpcRequest<string>('eth_call', [{ to, data }, 'latest']);
  if (!result || result === '0x') throw new Error(`eth_call vazio em ${to}`);
  return result;
}

/** `factory()` do router (endereço do KurFactory). */
export async function readRouterFactory(router: string): Promise<string> {
  if (!isAddress(router)) throw new Error('Endereço do router inválido');
  const factory = decodeAddress(await ethCall(router, SELECTORS.factory));
  if (isZeroAddress(factory)) throw new Error('Router sem factory (contrato errado?)');
  return factory;
}

export interface TokenMeta {
  address: string;
  symbol: string;
  decimals: number;
  /** Saldo do dono (0n quando nenhum dono foi informado). */
  balance: bigint;
}

/** Lê `symbol()`, `decimals()` e (opcional) `balanceOf(owner)` de um ERC-20. */
export async function readTokenMeta(token: string, owner?: string): Promise<TokenMeta> {
  if (!isAddress(token)) throw new Error(`Token inválido: ${token}`);
  const [symbolHex, decimalsHex, balanceHex] = await Promise.all([
    ethCall(token, SELECTORS.symbol).catch(() => SELECTORS.symbol),
    ethCall(token, SELECTORS.decimals),
    owner ? ethCall(token, SELECTORS.balanceOf + encodeAddress(owner)) : Promise.resolve<null>(null),
  ]);
  const symbol = symbolHex === SELECTORS.symbol ? '?' : decodeTokenString(symbolHex);
  return {
    address: token,
    symbol: symbol || '?',
    decimals: Number(decodeUint(decimalsHex)),
    balance: balanceHex ? decodeUint(balanceHex) : 0n,
  };
}

export async function readAllowance(token: string, owner: string, spender: string): Promise<bigint> {
  const data = SELECTORS.allowance + encodeAddress(owner) + encodeAddress(spender);
  return decodeUint(await ethCall(token, data));
}

export interface PairSides {
  /** Endereço do KurFactory usado na consulta. */
  factory: string;
  /** Endereço do KurPair (``0x000...0`` → par não existe). */
  pair: string;
  token0: string;
  reserve0: bigint;
  reserve1: bigint;
  /** Reservas já orientadas para o swap `tokenIn → tokenOut`. */
  reserveIn: bigint;
  reserveOut: bigint;
  /** Timestamp do último sync do par (uint32). */
  blockTimestampLast: number;
}

/**
 * Descobre o par `tokenIn/tokenOut` e lê as reservas.
 *
 * Returns:
 *   `null` quando o factory ainda não criou o par (precisa de liquidez).
 */
export async function readPair(
  router: string,
  tokenIn: string,
  tokenOut: string,
): Promise<PairSides | null> {
  if (!isAddress(tokenIn) || !isAddress(tokenOut)) throw new Error('Endereços de token inválidos');
  if (sameAddress(tokenIn, tokenOut)) throw new Error('Escolha dois tokens diferentes');

  const factory = await readRouterFactory(router);
  const pair = decodeAddress(await ethCall(factory, encodeGetPair(tokenIn, tokenOut)));
  if (isZeroAddress(pair)) return null;

  const [token0, reserves] = await Promise.all([
    ethCall(pair, SELECTORS.token0).then((out) => decodeAddress(out)),
    ethCall(pair, SELECTORS.getReserves),
  ]);
  const reserve0 = decodeUint(reserves, 0);
  const reserve1 = decodeUint(reserves, 1);
  const blockTimestampLast = Number(decodeUint(reserves, 2));
  const inIsToken0 = sameAddress(tokenIn, token0);

  return {
    factory,
    pair,
    token0,
    reserve0,
    reserve1,
    reserveIn: inIsToken0 ? reserve0 : reserve1,
    reserveOut: inIsToken0 ? reserve1 : reserve0,
    blockTimestampLast,
  };
}

/** Cotação do `KurRouter`/`KurPair`: `x*y=k` com taxa de 0,3%. */
export function quoteAmountOut(amountIn: bigint, reserveIn: bigint, reserveOut: bigint): bigint {
  if (amountIn <= 0n) return 0n;
  if (reserveIn <= 0n || reserveOut <= 0n) return 0n;
  const amountInWithFee = amountIn * 997n;
  return (amountInWithFee * reserveOut) / (reserveIn * 1000n + amountInWithFee);
}

/** Aplica a tolerância de slippage (bps) no mínimo aceito. */
export function applySlippage(amountOut: bigint, slippageBps: number): bigint {
  const bps = BigInt(Math.min(9_999, Math.max(0, Math.round(slippageBps))));
  return (amountOut * (10_000n - bps)) / 10_000n;
}

/** `"1.5"` + decimals → wei, sem passar por float. */
export function parseUnits(value: string, decimals: number): bigint {
  const clean = value.trim().replace(',', '.');
  if (!/^\d*\.?\d*$/.test(clean) || clean === '' || clean === '.') {
    throw new Error('Quantidade inválida');
  }
  const [whole, fraction = ''] = clean.split('.');
  if (fraction.length > decimals) {
    throw new Error(`Máximo de ${decimals} casas decimais`);
  }
  const digits = ((whole || '0') + fraction.padEnd(decimals, '0')).replace(/^0+(?=\d)/, '');
  return BigInt(digits);
}

/** wei → string legível (`maxFraction` casas, zeros à direita removidos). */
export function formatUnits(value: bigint, decimals: number, maxFraction = 6): string {
  const negative = value < 0n;
  const abs = negative ? -value : value;
  const base = 10n ** BigInt(decimals);
  const whole = abs / base;
  const fraction = (abs % base)
    .toString()
    .padStart(decimals, '0')
    .slice(0, maxFraction)
    .replace(/0+$/, '');
  return `${negative ? '-' : ''}${whole.toString()}${fraction ? `.${fraction}` : ''}`;
}

/** Router default da build (`VITE_KUR_ROUTER`), se configurado. */
export function defaultRouterAddress(): string {
  const fromEnv = import.meta.env.VITE_KUR_ROUTER;
  return typeof fromEnv === 'string' ? fromEnv.trim() : '';
}
