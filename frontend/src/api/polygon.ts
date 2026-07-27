/**
 * API Client para rede Polygon (ERC-20 USDT).
 * Endpoints: /api/polygon/*
 */
import axios from 'axios';

const api = axios.create({
  baseURL: '/',
  timeout: 15000,
  headers: { 'Content-Type': 'application/json' },
});

// ─── Types ──────────────────────────────────────────────────────

export interface PolygonNetworkInfo {
  network: string;
  chain_id: number | null;
  rpc_url: string;
  usdt_contract: string;
  explorer_url: string;
  connected: boolean;
  block_number: number | null;
}

export interface PolygonBalance {
  address: string;
  matic: number;
  usdt: number;
  network: string;
  error?: string;
}

export interface PolygonTransaction {
  tx_id: string;
  from: string;
  to: string;
  amount: number;
  block: number;
  confirmations: number;
  timestamp: number;
}

export interface PolygonTransactionsResponse {
  address: string;
  network: string;
  transactions: PolygonTransaction[];
  total: number;
  error?: string;
}

// ─── API Functions ──────────────────────────────────────────────

/**
 * Obtém informações da rede Polygon configurada.
 */
export async function getPolygonInfo(): Promise<PolygonNetworkInfo> {
  const res = await api.get<PolygonNetworkInfo>('/api/polygon/info');
  return res.data;
}

/**
 * Consulta saldo MATIC + USDT de um endereço Polygon.
 */
export async function getPolygonBalance(address: string): Promise<PolygonBalance> {
  const res = await api.get<PolygonBalance>('/api/polygon/balance', {
    params: { address }
  });
  return res.data;
}

/**
 * Consulta transações USDT recebidas por um endereço.
 */
export async function getPolygonTransactions(
  address: string,
  minConfirmations: number = 1,
  limit: number = 50
): Promise<PolygonTransactionsResponse> {
  const res = await api.get<PolygonTransactionsResponse>('/api/polygon/transactions', {
    params: { address, min_confirmations: minConfirmations, limit }
  });
  return res.data;
}

/**
 * Obtém detalhes de uma transação Polygon.
 */
export async function getPolygonTxInfo(txId: string) {
  const res = await api.get(`/api/polygon/tx/${txId}`);
  return res.data;
}

// ─── Network Helper ─────────────────────────────────────────────

/**
 * Retorna URL do explorer para uma transação.
 */
export function getPolygonExplorerUrl(network: string, type: 'tx' | 'address', value: string): string {
  const base = network === 'mainnet'
    ? 'https://polygonscan.com'
    : 'https://amoy.polygonscan.com';
  return `${base}/${type}/${value}`;
}
