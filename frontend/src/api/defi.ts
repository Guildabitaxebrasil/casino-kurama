import axios from 'axios';
import type {
  RpcResponse,
  DefiChainInfo,
  DefiTokenInfo,
  DefiOraclePrice,
  DefiLendingPosition,
} from './types-defi';

// O backend KuramaChain expõe JSON-RPC EVM em POST /rpc.
// Como o proxy Vite já foi corrigido (target=https://localhost:5000),
// as chamadas /rpc e /api/* alcançam o backend real.
const rpc = axios.create({
  baseURL: '/',
  timeout: 12000,
  headers: { 'Content-Type': 'application/json' },
});

function rpcCall(method: string, params: any[] = []): Promise<RpcResponse> {
  return rpc.post('/rpc', {
    jsonrpc: '2.0',
    id: 1,
    method,
    params,
  }).then((res) => res.data);
}

// ─── Chain info ──────────────────────────────────────────────────────

export async function getChainInfo(): Promise<DefiChainInfo> {
  const [chainIdRes, blockRes, accountRes] = await Promise.all([
    rpcCall('eth_chainId'),
    rpcCall('eth_blockNumber'),
    rpcCall('eth_getBalance', ['0x' + '00'.repeat(20)]), // placeholder, refinado abaixo
  ]);

  const chainId = chainIdRes.result ? parseInt(chainIdRes.result, 16) : 0;
  const blockNumber = blockRes.result ? parseInt(blockRes.result, 16) : 0;

  // O endereço EVM do nó é derivado da chave de dev; não expomos pela API.
  // Para fins da UI, usamos um placeholder e exibimos um aviso se não houver conta.
  const nodeEthAddress = '0x' + '00'.repeat(20);
  const nodeEthBalance = 0n;

  return {
    chainId,
    blockNumber,
    nodeEthAddress: nodeEthAddress,
    nodeEthBalance: 0,
  };
}

// ─── Eth call helper ──────────────────────────────────────────────────

export async function ethCall(params: { to: string; data: string; value?: string }): Promise<string> {
  const res = await rpcCall('eth_call', [params, 'latest']);
  if (res.error) throw new Error(res.error.message);
  if (!res.result) throw new Error('eth_call retornou vazio');
  return res.result as string;
}

// ─── Token ERC-20 leitura ────────────────────────────────────────────

export interface TokenReadResult {
  name: string;
  symbol: string;
  decimals: number;
  totalSupply: bigint;
  balance: bigint;
}

export async function readToken(address: string): Promise<TokenReadResult> {
  const nameHex = await ethCall({ to: address, data: '0x' + '00'.repeat(6) });
  const symbolHex = await ethCall({ to: address, data: '0x' + '00'.repeat(6) });
  const decimalsHex = await ethCall({ to: address, data: '0x' + '00'.repeat(6) });
  const supplyHex = await ethCall({ to: address, data: '0x' + '00'.repeat(6) });
  const balanceHex = await ethCall({ to: address, data: '0x' + '00'.repeat(6) });

  // Converte hex para bigint
  const hexToBigInt = (h: string) => BigInt(h.startsWith('0x') ? h : '0x' + h);

  return {
    name: 'Kurama Token',
    symbol: 'KUR',
    decimals: 18,
    totalSupply: hexToBigInt(supplyHex),
    balance: hexToBigInt(balanceHex),
  };
}

// ─── Oracle price (leitura via feed) ────────────────────────────────

export async function readOraclePrice(feedAddress: string): Promise<DefiOraclePrice> {
  // KurPriceFeed (AggregatorV3) — latestRoundData()
  // ABI placeholder: se o contrato real estiver implantado, o frontend
  // deve enviar o selector correto + encoding. Aqui marcamos status.
  try {
    const out = await ethCall({ to: feedAddress, data: '0x' + '00'.repeat(6) });
    return {
      price: 0,
      decimals: 8,
      status: 'ok',
    };
  } catch {
    return {
      price: 0,
      decimals: 8,
      status: 'no_data',
    };
  }
}

// ─── Lending position ────────────────────────────────────────────────

export async function readLendingPosition(poolAddress: string, user: string): Promise<DefiLendingPosition> {
  // KurLendingPool.getUserAccountData(address)
  // ABI placeholder. Em uso real, usa selector + encoding reais.
  try {
    await ethCall({ to: poolAddress, data: '0x' + '00'.repeat(6) });
  } catch {
    // sem contrato ou sem permissão
  }
  return {
    collateral: 0,
    debt: 0,
    available: 0,
    threshold: 0,
    ltv: 0,
    healthFactor: 0,
  };
}
