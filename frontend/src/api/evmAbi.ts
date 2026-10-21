/**
 * ABI mínimo do DEX da KuramaChain, sem dependências novas.
 *
 * O bundle não traz ethers.js/web3.js: os seletores de 4 bytes e os tópicos de
 * evento são `keccak256(assinatura)` calculados uma vez aqui, e a codificação
 * ABI usada pelo swap (`uint256`, `address`, `address[]`) é feita à mão.
 *
 * Fluxo de um swap assinado pela carteira:
 *
 *   approve(router, amountIn)                        → no token de entrada
 *   swapExactTokensForTokens(amountIn, amountOutMin,
 *                            [tokenIn, tokenOut], to) → no KurRouter
 */

/** Seletores de função (`keccak256(sig)[:4]`). */
export const SELECTORS = {
  /** KurRouter.factory() */
  factory: '0xc45a0155',
  /** KurFactory.getPair(address,address) */
  getPair: '0xe6a43905',
  /** KurPair.getReserves() → (uint112, uint112, uint32) */
  getReserves: '0x0902f1ac',
  /** KurPair.token0() / UniswapV3Pool.token0() */
  token0: '0x0dfe1681',
  /** UniswapV3Pool.token1() */
  token1: '0xd21220a7',
  decimals: '0x313ce567',
  symbol: '0x95d89b41',
  name: '0x06fdde03',
  totalSupply: '0x18160ddd',
  balanceOf: '0x70a08231',
  allowance: '0xdd62ed3e',
  approve: '0x095ea7b3',
  /** KurRouter.swapExactTokensForTokens(uint256,uint256,address[],address) */
  swapExactTokensForTokens: '0x472b43f3',
} as const;

/** Tópicos de evento (`keccak256(assinatura)` completo). */
export const TOPICS = {
  /** KurRouter.SwapExecuted(address indexed sender, address tokenIn, address tokenOut, uint256 amountIn, uint256 amountOut) */
  swapExecuted: '0x764f0dc063c06f32d89a3f3af80c0db4be8a090901f589a478b447e0a51f09f1',
  /** KurPair.Swap(address indexed sender, uint256 amount0In, uint256 amount1In, uint256 amount0Out, uint256 amount1Out, address indexed to) */
  pairSwap: '0xd78ad95fa46c994b6551d0da85fc275fe613ce37657fb8d5e3d130840159d822',
} as const;

const WORD_HEX = 64;
const ZERO_ADDRESS = '0x' + '00'.repeat(20);

function strip0x(value: string): string {
  return value.startsWith('0x') || value.startsWith('0X') ? value.slice(2) : value;
}

/** Endereço hex válido (20 bytes)? */
export function isAddress(value: string): boolean {
  return /^0x[0-9a-fA-F]{40}$/.test(value.trim());
}

/** Compara endereços sem depender de checksum/caixa. */
export function sameAddress(a: string, b: string): boolean {
  return a.toLowerCase() === b.toLowerCase();
}

export function isZeroAddress(value: string): boolean {
  return sameAddress(value, ZERO_ADDRESS);
}

/** Palavra ABI de 32 bytes (hex sem `0x`). */
export function word(value: bigint | number | string): string {
  const big = typeof value === 'bigint' ? value : BigInt(value);
  if (big < 0n) throw new Error('Valor ABI negativo não suportado');
  const hex = big.toString(16);
  if (hex.length > WORD_HEX) throw new Error('Valor maior que uint256');
  return hex.padStart(WORD_HEX, '0');
}

/** `address` como palavra ABI (hex sem `0x`). */
export function encodeAddress(address: string): string {
  const body = strip0x(address.trim());
  if (body.length !== 40 || !/^[0-9a-fA-F]{40}$/.test(body)) {
    throw new Error(`Endereço inválido: ${address}`);
  }
  return body.toLowerCase().padStart(WORD_HEX, '0');
}

/** `approve(address spender, uint256 value)` no token de entrada. */
export function encodeApprove(spender: string, amount: bigint): string {
  return SELECTORS.approve + encodeAddress(spender) + word(amount);
}

/** `getPair(address,address)` no factory. */
export function encodeGetPair(tokenA: string, tokenB: string): string {
  return SELECTORS.getPair + encodeAddress(tokenA) + encodeAddress(tokenB);
}

/**
 * `swapExactTokensForTokens(uint256,uint256,address[],address)`.
 *
 * Layout: 3 palavras estáticas + offset do array (0x80) e a palavra `to`;
 * o array vem depois: tamanho (2) + tokenIn + tokenOut.
 */
export function encodeSwapExactTokensForTokens(
  amountIn: bigint,
  amountOutMin: bigint,
  path: [string, string],
  to: string,
): string {
  const head = word(amountIn) + word(amountOutMin) + word(4 * 32) + encodeAddress(to);
  const tail = word(path.length) + path.map((token) => encodeAddress(token)).join('');
  return SELECTORS.swapExactTokensForTokens + head + tail;
}

/** Lê a `word` do retorno ABI (hex com ou sem `0x`). */
export function decodeWord(data: string, index = 0): bigint {
  const body = strip0x(data);
  const start = index * WORD_HEX;
  if (start + WORD_HEX > body.length) throw new Error('Retorno ABI curto');
  return BigInt('0x' + body.slice(start, start + WORD_HEX));
}

export function decodeUint(data: string, index = 0): bigint {
  return decodeWord(data, index);
}

/** Lê um `address` (últimos 20 bytes da palavra). */
export function decodeAddress(data: string, index = 0): string {
  const body = strip0x(data);
  const start = index * WORD_HEX;
  const slice = body.slice(start + 24, start + WORD_HEX);
  if (slice.length !== 40) throw new Error('Retorno ABI curto (address)');
  return '0x' + slice.toLowerCase();
}

/** Lê uma `string` dinâmica (offset + tamanho + bytes). */
export function decodeString(data: string): string {
  const body = strip0x(data);
  if (body.length < WORD_HEX) return '';
  const offset = Number(decodeWord(body, 0)) * 2;
  const length = Number(decodeWord(body.slice(offset), 0)) * 2;
  if (length === 0) return '';
  return hexToUtf8(body.slice(offset + WORD_HEX, offset + WORD_HEX + length));
}

/**
 * Lê `symbol()`/`name()` tolerando ERC-20 legado, que devolve `bytes32` em vez
 * de `string`.
 */
export function decodeTokenString(data: string): string {
  const body = strip0x(data);
  if (body.length === WORD_HEX) return hexToUtf8(body);
  return decodeString(data);
}

function hexToUtf8(hex: string): string {
  let out = '';
  for (let i = 0; i + 1 < hex.length; i += 2) {
    const code = parseInt(hex.slice(i, i + 2), 16);
    if (code === 0) break;
    out += String.fromCharCode(code);
  }
  return out;
}

/**
 * `amountOut` do evento `SwapExecuted` do KurRouter no recibo.
 *
 * Non-indexed: `(tokenIn, tokenOut, amountIn, amountOut)` — 4 palavras.
 */
export function decodeSwapExecuted(
  logs: Array<{ address: string; topics: string[]; data: string }> | undefined,
  router: string,
): bigint | null {
  if (!logs) return null;
  for (const log of logs) {
    if (!sameAddress(log.address, router)) continue;
    if (log.topics?.[0]?.toLowerCase() !== TOPICS.swapExecuted) continue;
    try {
      return decodeWord(log.data, 3);
    } catch {
      return null;
    }
  }
  return null;
}
