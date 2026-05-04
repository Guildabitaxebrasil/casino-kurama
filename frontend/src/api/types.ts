export interface Block {
  index: number;
  timestamp: number;
  previous_hash: string;
  hash: string;
  merkle_root: string;
  nonce: number;
  difficulty: number;
  transactions: Transaction[];
}

export interface Transaction {
  transaction_id: string;
  sender: string;
  receiver: string;
  amount: number;
  timestamp: number;
  signature: string | null;
  sender_address: string | null;
}

export interface WalletInfo {
  address: string;
  public_key_pem: string;
  private_key_pem: string;
}

export interface Stats {
  total_blocks: number;
  total_transactions: number;
  total_nodes: number;
  active_nodes: number;
  pending_transactions: number;
  difficulty: number;
  reward: number;
  block_time: number;
  node_id: string;
  chain_size: number;
}

export interface MempoolStats {
  total: number;
  min_value: number;
  max_value: number;
  avg_value: number;
  oldest_tx: number;
  coinbase_count: number;
  transactions: Transaction[];
}

export interface ChartDataPoint {
  block: number;
  timestamp: number;
  transactions: number;
  cumulativeTx: number;
  difficulty: number;
}

export interface NodeInfo {
  id: string;
  url: string;
  active: boolean;
  chain_length: number;
  pending_tx?: number;
  last_seen: number;
  latency_ms: number | null;
  difficulty?: number;
}

export interface SearchResultBlock {
  index: number;
  hash: string;
  timestamp: number;
  tx_count: number;
}

export interface SearchResultTx {
  id: string;
  amount: number;
  block_index: number;
  sender: string;
  receiver: string;
}

export interface SearchResult {
  blocks: SearchResultBlock[] | Block[];
  transactions: SearchResultTx[] | Transaction[];
  addresses: string[];
}

export interface TransactionFilter {
  sender?: string;
  receiver?: string;
  min_amount?: number;
  max_amount?: number;
  block?: number;
  page?: number;
  per_page?: number;
}

export interface ApiResponse<T> {
  data: T | null;
  error: string | null;
  loading: boolean;
}

export interface ChainResponse {
  chain: Block[];
  length: number;
  pending_transactions: Transaction[];
  node_id: string;
  difficulty: number;
}

export interface HealthResponse {
  status: string;
  node_id: string;
  chain_length: number;
  pending: number;
  uptime: number;
}

export interface MineResponse {
  message: string;
  block: Block;
  proof: number;
}

export interface BalanceResponse {
  address: string;
  balance: number;
  pending_received: number;
  pending_sent: number;
}

// Type aliases for backward compatibility
export type BlockData = Block;
export type TransactionData = Transaction;
