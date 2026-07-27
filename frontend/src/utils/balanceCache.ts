/**
 * Cache de saldo no localStorage com TTL (Time-To-Live).
 * Reduz chamadas desnecessarias a API para enderecos ja consultados.
 *
 * Cache por endereco com TTL de 30 segundos.
 * Limpeza automatica de caches expirados.
 */

const BALANCE_CACHE_KEY = 'kurama_balance_cache';
const BALANCE_TTL_MS = 30_000;

interface CachedBalance {
  balance: number;
  timestamp: number;
}

interface BalanceCacheStore {
  [address: string]: CachedBalance;
}

function getCacheStore(): BalanceCacheStore {
  try {
    const raw = localStorage.getItem(BALANCE_CACHE_KEY);
    if (!raw) return {};
    const store = JSON.parse(raw) as BalanceCacheStore;
    const now = Date.now();
    const cleaned: BalanceCacheStore = {};
    for (const [addr, entry] of Object.entries(store)) {
      if (now - entry.timestamp < BALANCE_TTL_MS) {
        cleaned[addr] = entry;
      }
    }
    return cleaned;
  } catch {
    return {};
  }
}

function saveCacheStore(store: BalanceCacheStore): void {
  try {
    localStorage.setItem(BALANCE_CACHE_KEY, JSON.stringify(store));
  } catch {}
}

export function getCachedBalance(address: string): number | null {
  const store = getCacheStore();
  const entry = store[address];
  if (!entry) return null;
  if (Date.now() - entry.timestamp >= BALANCE_TTL_MS) {
    delete store[address];
    saveCacheStore(store);
    return null;
  }
  return entry.balance;
}

export function setCachedBalance(address: string, balance: number): void {
  const store = getCacheStore();
  store[address] = { balance, timestamp: Date.now() };
  saveCacheStore(store);
}

export function clearBalanceCache(address: string): void {
  const store = getCacheStore();
  delete store[address];
  saveCacheStore(store);
}

export function clearAllBalanceCaches(): void {
  try {
    localStorage.removeItem(BALANCE_CACHE_KEY);
  } catch {}
}
