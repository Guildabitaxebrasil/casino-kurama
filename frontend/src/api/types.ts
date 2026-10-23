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
  fee: number;
  timestamp: number;
  signature: string | null;
  sender_address: string | null;
  nonce?: string;
  /** Hash da tx EVM que creditou este envio para um destino 0x... */
  evm_tx_hash?: string | null;
}

export interface WalletInfo {
  address: string;
  public_key_pem: string;
  private_key_pem: string;
}

export interface Stats {
  blocks: number;
  total_transactions: number;
  pending_transactions: number;
  difficulty: number;
  reward: number;
  node_id: string;
  peer_nodes: string[];
  chain_valid: boolean;
  total_supply: number;
  supply_cap: number;
  remaining_supply: number;
  percent_mined: number;
  token_name: string;
  token_symbol: string;
  /** Timestamp (s) do último bloco. */
  last_block_timestamp?: number | null;
  /** Alvo de segundos por bloco (600 = 10 min). */
  target_block_time?: number;
  /** Timestamp (s) em que o próximo bloco pode ser minerado. */
  next_block_at?: number | null;
}

export interface MempoolStats {
  total: number;
  min_value: number;
  max_value: number;
  avg_value: number;
  oldest_tx: number;
  coinbase_count: number;
  total_fees: number;
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
  node_id: string;
  url: string;
  active: boolean;
  blocks: number;
  latency_ms: number | null;
  is_self?: boolean;
  difficulty?: number;
}

export interface NodesResponse {
  nodes: NodeInfo[];
  total: number;
  active: number;
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
  base_reward: number;
  fee_reward: number;
  total_reward: number;
  miner_address: string;
  miner_balance?: number;
  difficulty: number;
  supply: SupplyResponse;
}

export interface SupplyResponse {
  token_name: string;
  token_symbol: string;
  total_supply: number;
  supply_cap: number;
  remaining_supply: number;
  percent_mined: number;
  blocks_mined: number;
  initial_reward?: number;
  current_block_reward?: number;
  halving_interval?: number;
}

export interface BalanceResponse {
  address: string;
  balance: number;
  transactions_count: number;
  transactions: Transaction[];
}

// Type aliases for backward compatibility
export type BlockData = Block;
export type TransactionData = Transaction;
