import axios from 'axios';
import type {
  Block, Transaction, WalletInfo, Stats, MempoolStats,
  ChartDataPoint, NodeInfo, SearchResult, ChainResponse,
  HealthResponse, MineResponse, BalanceResponse
} from './types';

const api = axios.create({
  baseURL: '/',
  timeout: 10000,
  headers: { 'Content-Type': 'application/json' },
});

async function fetchData<T>(url: string, params?: Record<string, any>): Promise<T> {
  const res = await api.get<T>(url, { params });
  return res.data;
}

async function postData<T>(url: string, body: any): Promise<T> {
  const res = await api.post<T>(url, body);
  return res.data;
}

// Chain endpoints
export const getChain = () => fetchData<ChainResponse>('/chain');
export const getBlocksSince = (index: number) => fetchData<ChainResponse>(`/api/chain/since/${index}`);
export const getBlockByIdentifier = (id: string | number) => fetchData<{ block: Block }>(`/api/blocks/${id}`);
export const getAllBlocks = () => fetchData<Block[]>('/api/blocks/all');

// Transaction endpoints
export const getPendingTransactions = () => fetchData<{ transactions: Transaction[] }>('/transactions/pending');
export const getAllTransactions = (params?: { page?: number; per_page?: number; sender?: string; receiver?: string; min_amount?: number; max_amount?: number; block?: number }) =>
  fetchData<{ transactions: Transaction[]; total: number; page: number; per_page: number; total_pages: number }>('/api/transactions', params);
export const createTransaction = (data: { sender: string; receiver: string; amount: number; signature?: string; sender_address?: string; timestamp?: number }) =>
  postData<{ message: string; index: number; transaction: Transaction }>('/transactions/new', data);

// Mining
export const mineBlock = () => fetchData<MineResponse>('/mine');

// Wallet
export const newWallet = () => fetchData<WalletInfo>('/wallet/new');
export const getBalance = (address: string) => fetchData<BalanceResponse>(`/balance/${address}`);

// Network
export const registerNode = (url: string) => postData<{ message: string; total_nodes: number }>('/nodes/register', { node_url: url });
export const resolveConsensus = () => fetchData<{ message: string; chain_replaced: boolean; new_length: number }>('/nodes/resolve');
export const getNodes = () => fetchData<NodeInfo[]>('/api/nodes');
export const syncNodes = () => postData<{ message: string; chain_replaced: boolean }>('/api/nodes/sync', {});

// Stats & Explorer
export const getStats = () => fetchData<Stats>('/stats');
export const getChartData = (limit?: number) => fetchData<ChartDataPoint[]>('/api/chart', { limit });
export const getMempoolStats = () => fetchData<MempoolStats>('/api/mempool');
export const search = (q: string) => fetchData<SearchResult>('/api/search', { q });
export const getHealth = () => fetchData<HealthResponse>('/api/health');
export const validateChain = () => fetchData<{ valid: boolean; errors: string[] }>('/validate');
