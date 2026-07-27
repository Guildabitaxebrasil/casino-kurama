/**
 * Utilitário para armazenar carteiras no localStorage.
 * As carteiras ficam disponíveis entre sessões (persistência local).
 *
 * ATENÇÃO: A chave privada é armazenada no navegador!
 * Isso é aceitável para ambiente de desenvolvimento/educacional.
 * Em produção, a chave privada NUNCA deve ser armazenada no navegador
 * sem criptografia adequada (ex: usar Web Crypto API + senha).
 */

export interface StoredWallet {
  address: string;
  public_key: string;
  private_key_pem: string;
  label: string;
  created_at: number;
}

const STORAGE_KEY = 'kurama_wallets';

export function getStoredWallets(): StoredWallet[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    return JSON.parse(raw) as StoredWallet[];
  } catch {
    return [];
  }
}

export function saveWallet(wallet: StoredWallet): void {
  const wallets = getStoredWallets();
  // Evita duplicatas pelo address
  const exists = wallets.find(w => w.address === wallet.address);
  if (exists) return;
  wallets.push(wallet);
  localStorage.setItem(STORAGE_KEY, JSON.stringify(wallets));
}

export function removeWallet(address: string): void {
  const wallets = getStoredWallets().filter(w => w.address !== address);
  localStorage.setItem(STORAGE_KEY, JSON.stringify(wallets));
}

export function clearWallets(): void {
  localStorage.removeItem(STORAGE_KEY);
}

export function getWalletCount(): number {
  return getStoredWallets().length;
}
