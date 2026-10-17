export interface EthChainIdResult {
  chainId: number;
}

export interface EthBlockNumberResult {
  blockNumber: number;
}

export interface EthBalanceResult {
  balance: string; // wei hex
}

export interface RpcRequest {
  address?: string;
  data?: string; // hex
  value?: string; // wei hex
  to?: string;
}

export interface RpcCallParams {
  to: string;
  data: string;
  value?: string;
}

export interface RpcResponse {
  jsonrpc: '2.0';
  id: number;
  result?: any;
  error?: { code: number; message: string };
}

export interface DefiChainInfo {
  chainId: number;
  blockNumber: number;
  nodeEthAddress: string;
  nodeEthBalance: number; // wei
}

export interface DefiTokenInfo {
  name: string;
  symbol: string;
  decimals: number;
  totalSupply: string;
  balance: string;
}

export interface DefiOraclePrice {
  price: number; // units (e.g. 8 decimals)
  decimals: number;
  updatedAt?: number;
  status: 'ok' | 'stale' | 'no_data';
}

export interface DefiLendingPosition {
  collateral: number;
  debt: number;
  available: number;
  threshold: number;
  ltv: number;
  healthFactor: number;
}

export interface DefiLendingActions {
  depositToken?: string;
  borrowToken?: string;
  poolAddress?: string;
  priceOracleAddress?: string;
}
