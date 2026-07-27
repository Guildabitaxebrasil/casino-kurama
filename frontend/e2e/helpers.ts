import { Page, expect } from '@playwright/test';

/**
 * Aguarda o Dashboard carregar completamente (stat cards + grafico).
 */
export async function waitForDashboardLoad(page: Page) {
  // Aguarda os stat cards aparecerem
  await expect(page.locator('text=Blocos').first()).toBeVisible({ timeout: 15000 });
  await expect(page.locator('text=Transa\u00e7\u00f5es').first()).toBeVisible({ timeout: 5000 });
  await expect(page.locator('text=Supply').first()).toBeVisible({ timeout: 5000 });
  await expect(page.locator('text=Dificuldade').first()).toBeVisible({ timeout: 5000 });
  // Aguarda o grafico ou mensagem de dados insuficientes
  await page.waitForTimeout(1000);
}

/**
 * Gera uma carteira via API e retorna o endereco.
 */
export async function generateWallet(page: Page): Promise<string> {
  const response = await page.request.post('http://localhost:5000/wallet/new', {
    data: {},
  });
  expect(response.status()).toBe(200);
  const body = await response.json();
  return body.address;
}

/**
 * Mina um bloco via API e retorna a resposta.
 */
export async function mineBlock(page: Page, minerAddress?: string) {
  const response = await page.request.post('http://localhost:5000/mine', {
    data: minerAddress ? { miner_address: minerAddress } : {},
  });
  return response;
}

/**
 * Verifica se a pagina atual tem um titulo correspondente.
 */
export async function expectPageTitle(page: Page, title: string) {
  await expect(page.locator('h1').filter({ hasText: title }).first()).toBeVisible({ timeout: 10000 });
}

/**
 * Navega para uma pagina via sidebar e verifica se carregou.
 */
export async function navigateTo(page: Page, label: string) {
  // No desktop, o sidebar fica visivel
  await page.locator('a', { hasText: label }).first().click();
  await page.waitForLoadState('networkidle');
}

/**
 * Verifica se NAO ha erros no console.
 */
export function getConsoleErrors(errors: string[]): string[] {
  return errors.filter(msg => msg.includes('Failed to load') || msg.includes('Unexpected token'));
}
