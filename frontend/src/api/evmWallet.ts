/**
 * Conexão com carteiras EIP-1193 ("Connect Wallet") para a KuramaChain (Fase 6).
 *
 * A EVM da KuramaChain expõe JSON-RPC `eth_*` em `POST /rpc` (chain ID 9090).
 * Aqui só usamos o provider injetado pela wallet (`window.ethereum`), sem
 * dependências novas: a wallet assina localmente e envia via
 * `eth_sendRawTransaction` — o nó nunca precisa custódia de chave.
 *
 * O mesmo provider serve para outras redes EVM (ex.: Polygon/Uniswap), por isso
 * `ensureChain()` e `rpcRequestAt()` são genéricos: quem chama decide a chain e
 * a URL do JSON-RPC.
 */

export interface Eip1193Provider {
  request(args: { method: string; params?: unknown[] | object }): Promise<unknown>;
  on?(event: string, handler: (...args: unknown[]) => void): void;
  removeListener?(event: string, handler: (...args: unknown[]) => void): void;
}

export interface KuramaChainParams {
  chainId: string;
  chainName: string;
  nativeCurrency: { name: string; symbol: string; decimals: number };
  rpcUrls: string[];
  blockExplorerUrls: string[];
}

export const KURAMA_CHAIN_ID = 9090;
export const KURAMA_CHAIN_ID_HEX = '0x' + KURAMA_CHAIN_ID.toString(16);
export const KURAMA_NATIVE_SYMBOL = 'KUR';

/** URL absoluta do JSON-RPC (a wallet não aceita caminho relativo). */
export function kuramaRpcUrl(): string {
  const fromEnv = (import.meta as unknown as { env?: Record<string, string> }).env?.VITE_EVM_RPC_URL;
  if (fromEnv) return fromEnv;
  if (typeof window !== 'undefined') return `${window.location.origin}/rpc`;
  return 'http://localhost:5000/rpc';
}

export function kuramaChainParams(): KuramaChainParams {
  return {
    chainId: KURAMA_CHAIN_ID_HEX,
    chainName: 'KuramaChain',
    nativeCurrency: { name: 'Kurama', symbol: KURAMA_NATIVE_SYMBOL, decimals: 18 },
    rpcUrls: [kuramaRpcUrl()],
    blockExplorerUrls: [
      typeof window !== 'undefined' ? window.location.origin : 'http://localhost:5173',
    ],
  };
}

// ─── Descoberta de carteiras (EIP-6963) ─────────────────────────────
//
// Com mais de uma extensão instalada (ex.: Rabby + MetaMask), só uma consegue
// registrar `window.ethereum` (a outra falha com "Cannot set property ethereum
// ... only a getter"). O EIP-6963 resolve isso: cada extensão anuncia seu
// provider e o dApp escolhe explicitamente qual usar.

export interface Eip6963ProviderInfo {
  uuid: string;
  name: string;
  icon: string;
  rdns: string;
}

interface Eip6963Announcement {
  info: Eip6963ProviderInfo;
  provider: Eip1193Provider;
}

const SELECTED_WALLET_KEY = 'kurama_evm_wallet';
const announcedWallets = new Map<string, Eip6963Announcement>();
let discoveryRegistered = false;

/** Registra o listener EIP-6963 e pede os anúncios (idempotente). */
function ensureDiscovery(): void {
  if (discoveryRegistered || typeof window === 'undefined') return;
  discoveryRegistered = true;
  window.addEventListener('eip6963:announceProvider', ((event: Event) => {
    const detail = (event as CustomEvent<Eip6963Announcement>).detail;
    if (detail?.info?.rdns && detail.provider) {
      announcedWallets.set(detail.info.rdns, detail);
    }
  }) as EventListener);
  window.dispatchEvent(new Event('eip6963:requestProvider'));
}

/** Carteiras EVM anunciadas (Rabby, MetaMask, ...). */
export function listEvmWallets(): Eip6963ProviderInfo[] {
  ensureDiscovery();
  return Array.from(announcedWallets.values()).map((entry) => entry.info);
}

export function selectedEvmWalletRdns(): string {
  if (typeof window === 'undefined') return '';
  try {
    return window.localStorage.getItem(SELECTED_WALLET_KEY) ?? '';
  } catch {
    return '';
  }
}

/** Fixa a carteira usada pelo dApp (persistido no localStorage). */
export function selectEvmWallet(rdns: string): void {
  if (typeof window === 'undefined') return;
  try {
    window.localStorage.setItem(SELECTED_WALLET_KEY, rdns);
  } catch {
    // localStorage indisponível (modo privado): seleção vale só na sessão.
  }
}

/** Carteira EVM ativa (selecionada, ou a única anunciada). */
export function activeEvmWallet(): Eip6963ProviderInfo | null {
  const wallets = listEvmWallets();
  const selected = selectedEvmWalletRdns();
  const bySelection = wallets.find((info) => info.rdns === selected);
  if (bySelection) return bySelection;
  if (wallets.length === 1) return wallets[0];
  return null;
}

/** Provider da carteira ativa, se houver. */
export function getEvmProvider(): Eip1193Provider | null {
  if (typeof window === 'undefined') return null;
  ensureDiscovery();
  const wallets = listEvmWallets();
  const selected = selectedEvmWalletRdns();
  const chosen = announcedWallets.get(selected)
    ?? (wallets.length === 1 ? announcedWallets.get(wallets[0].rdns) : undefined);
  if (chosen) return chosen.provider;
  // Fallback para wallets que ainda não anunciam EIP-6963.
  const eth = (window as unknown as { ethereum?: Eip1193Provider }).ethereum;
  return eth ?? null;
}

export function isEvmWalletInstalled(): boolean {
  return getEvmProvider() !== null;
}

/** Pede contas ao usuário (abre o popup da wallet). */
export async function requestAccounts(provider?: Eip1193Provider): Promise<string[]> {
  const eth = provider ?? getEvmProvider();
  if (!eth) throw new Error('Carteira EVM não encontrada no navegador');
  const accounts = (await eth.request({ method: 'eth_requestAccounts' })) as string[];
  return Array.isArray(accounts) ? accounts : [];
}

export async function getChainId(provider?: Eip1193Provider): Promise<number> {
  const eth = provider ?? getEvmProvider();
  if (!eth) throw new Error('Carteira EVM não encontrada no navegador');
  const hex = (await eth.request({ method: 'eth_chainId' })) as string;
  return parseInt(hex, 16);
}

/**
 * Garante que a wallet está em `chainId`: troca de rede e, se a rede ainda não
 * existe na wallet (erro 4902), adiciona com `wallet_addEthereumChain`.
 *
 * Parameters:
 *   chainId: chain alvo (ex.: 9090 KuramaChain, 137 Polygon).
 *   addParams: parâmetros de `wallet_addEthereumChain` usados quando a wallet
 *     não conhece a rede. Sem eles, um 4902 é propagado.
 */
export async function ensureChain(
  chainId: number,
  addParams?: Pick<KuramaChainParams, 'chainName' | 'nativeCurrency' | 'rpcUrls' | 'blockExplorerUrls'>,
  provider?: Eip1193Provider,
): Promise<void> {
  const eth = provider ?? getEvmProvider();
  if (!eth) throw new Error('Carteira EVM não encontrada no navegador');
  const current = await getChainId(eth);
  if (current === chainId) return;

  const chainIdHex = '0x' + chainId.toString(16);
  try {
    await eth.request({
      method: 'wallet_switchEthereumChain',
      params: [{ chainId: chainIdHex }],
    });
  } catch (error) {
    const code = (error as { code?: number }).code;
    // 4902: rede desconhecida — adiciona e tenta de novo.
    if ((code === 4902 || code === -32603) && addParams) {
      await eth.request({
        method: 'wallet_addEthereumChain',
        params: [{ chainId: chainIdHex, ...addParams }],
      });
      await eth.request({
        method: 'wallet_switchEthereumChain',
        params: [{ chainId: chainIdHex }],
      });
      return;
    }
    throw error;
  }
}

/** Garante que a wallet está na KuramaChain (troca/adiciona a rede). */
export async function ensureKuramaChain(provider?: Eip1193Provider): Promise<void> {
  await ensureChain(KURAMA_CHAIN_ID, kuramaChainParams(), provider);
}

/**
 * Conecta a wallet sem mexer na rede (`eth_requestAccounts`).
 *
 * Use quando o destino pode ser outra chain (ex.: swap na Polygon): quem chama
 * decide depois com `ensureChain()`.
 */
export async function connectWallet(): Promise<string> {
  const accounts = await requestAccounts();
  if (!accounts.length) throw new Error('Nenhuma conta autorizada na carteira');
  return accounts[0];
}

/** Conecta a wallet e já troca/adiciona a KuramaChain. */
export async function connectKuramaWallet(): Promise<string> {
  const eth = getEvmProvider();
  const account = await connectWallet();
  await ensureKuramaChain(eth ?? undefined);
  return account;
}

/** Erro JSON-RPC do nó (usado para diferenciar revert de falha de rede). */
export class RpcError extends Error {
  code?: number;

  constructor(message: string, code?: number) {
    super(message);
    this.name = 'RpcError';
    this.code = code;
  }
}

/** Chamada JSON-RPC `eth_*` em qualquer URL (KuramaChain, Polygon, ...). */
export async function rpcRequestAt<T = unknown>(
  url: string,
  method: string,
  params: unknown[] = [],
): Promise<T> {
  const response = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ jsonrpc: '2.0', id: 1, method, params }),
  });
  if (!response.ok) throw new Error(`RPC ${method}: HTTP ${response.status}`);
  const payload = (await response.json()) as {
    result?: T;
    error?: { code: number; message: string };
  };
  if (payload.error) throw new RpcError(payload.error.message, payload.error.code);
  return payload.result as T;
}

/**
 * Chamada JSON-RPC `eth_*` direto no nó da KuramaChain (`POST /rpc`).
 *
 * É o mesmo endpoint que a wallet usa — o DEX lê estado (pares, reservas,
 * saldos) por aqui e a wallet assina as transações de escrita.
 */
export async function rpcRequest<T = unknown>(method: string, params: unknown[] = []): Promise<T> {
  return rpcRequestAt<T>(kuramaRpcUrl(), method, params);
}

/** Saldo nativo (wei) de um endereço EVM via JSON-RPC do nó. */
export async function getEvmBalance(address: string): Promise<bigint> {
  const result = await rpcRequest<string>('eth_getBalance', [address, 'latest']);
  return BigInt(result ?? '0x0');
}

// ─── Transações assinadas pela wallet ───────────────────────────────

export interface WalletTransactionRequest {
  from: string;
  to: string;
  /** Calldata `0x...` (contratos). */
  data?: string;
  /** Valor em wei (hex). */
  value?: string;
}

/**
 * Pede à wallet para assinar e enviar uma transação (`eth_sendTransaction`).
 *
 * A chave privada nunca sai da wallet: o provider preenche nonce/gas/chainId,
 * assina e manda a tx crua para o nó via `eth_sendRawTransaction`.
 *
 * Returns:
 *   Hash da transação (`0x...`).
 */
export async function sendWalletTransaction(tx: WalletTransactionRequest): Promise<string> {
  const eth = getEvmProvider();
  if (!eth) throw new Error('Carteira EVM não encontrada no navegador');
  const hash = (await eth.request({ method: 'eth_sendTransaction', params: [tx] })) as string;
  if (typeof hash !== 'string' || !hash.startsWith('0x')) {
    throw new Error('A wallet não devolveu o hash da transação');
  }
  return hash;
}

export interface EvmLog {
  address: string;
  topics: string[];
  data: string;
}

export interface EvmReceipt {
  transactionHash: string;
  /** `0x1` = sucesso, `0x0` = revertida. */
  status: string;
  blockNumber: string;
  gasUsed: string;
  logs: EvmLog[];
}

export async function getTransactionReceipt(hash: string): Promise<EvmReceipt | null> {
  return rpcRequest<EvmReceipt | null>('eth_getTransactionReceipt', [hash]);
}

/**
 * Aguarda o recibo e devolve `null` no timeout.
 *
 * O nó sela um bloco por transação (auto_mine), então o recibo costuma chegar
 * no primeiro polling.
 */
export async function waitForTransactionReceipt(
  hash: string,
  timeoutMs = 120_000,
  intervalMs = 1_500,
): Promise<EvmReceipt | null> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const receipt = await getTransactionReceipt(hash);
    if (receipt) return receipt;
    await new Promise((resolve) => setTimeout(resolve, intervalMs));
  }
  return null;
}

export function formatKur(wei: bigint, decimals = 4): string {
  const whole = wei / 10n ** 18n;
  const fraction = (wei % 10n ** 18n).toString().padStart(18, '0').slice(0, decimals);
  return `${whole.toLocaleString('pt-BR')}.${fraction}`;
}

export function shortAddress(address: string): string {
  return address.length > 12 ? `${address.slice(0, 8)}…${address.slice(-4)}` : address;
}
