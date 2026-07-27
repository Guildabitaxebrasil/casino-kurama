import { test, expect } from '@playwright/test';
import { expectPageTitle, waitForDashboardLoad, generateWallet } from './helpers';

test.describe('Wallet / Carteira', () => {
  test('Deve carregar pagina de Carteira', async ({ page }) => {
    await page.goto('/wallet');
    await expectPageTitle(page, 'Carteira');
  });

  test('Deve mostrar input de endereco e botoes', async ({ page }) => {
    await page.goto('/wallet');
    await expectPageTitle(page, 'Carteira');

    await expect(page.locator('input[placeholder*="Digite um endere\u00e7o"]').first()).toBeVisible({ timeout: 5000 });
    await expect(page.locator('button:has-text("Consultar")').first()).toBeVisible();
    await expect(page.locator('button:has-text("Gerar Carteira")').first()).toBeVisible();
  });

  test('Deve gerar uma nova carteira', async ({ page }) => {
    await page.goto('/wallet');
    await expectPageTitle(page, 'Carteira');

    // Clica em Gerar Carteira
    await page.locator('button:has-text("Gerar Carteira")').first().click();
    await page.waitForTimeout(3000);

    // Verifica se mostra a nova carteira
    await expect(page.locator('text=Nova Carteira Gerada').first()).toBeVisible({ timeout: 10000 });
    await expect(page.locator('text=Chave Privada').first()).toBeVisible();
  });

  test('Deve consultar saldo de um endereco valido', async ({ page }) => {
    // Gera uma carteira via API
    const address = await generateWallet(page);

    await page.goto('/wallet');
    await expectPageTitle(page, 'Carteira');

    // Digita o endereco
    await page.locator('input[placeholder*="Digite um endere\u00e7o"]').first().fill(address);
    await page.locator('button:has-text("Consultar")').first().click();

    // Aguarda resultado
    await page.waitForTimeout(3000);

    // Verifica se mostra saldo (pode ser 0)
    await expect(page.locator('text=KUR').first()).toBeVisible({ timeout: 10000 });
  });

  test('Deve mostrar saldo 0 para endereco valido sem transacoes', async ({ page }) => {
    const address = await generateWallet(page);

    await page.goto('/wallet');
    await expectPageTitle(page, 'Carteira');

    await page.locator('input[placeholder*="Digite um endere\u00e7o"]').first().fill(address);
    await page.locator('button:has-text("Consultar")').first().click();
    await page.waitForTimeout(3000);

    // Saldo deve ser 0.00
    await expect(page.locator('text=0.00').first()).toBeVisible({ timeout: 10000 });
  });

  test('Nao deve mostrar erros de console na Wallet', async ({ page }) => {
    const errors: string[] = [];
    page.on('console', (msg) => {
      if (msg.type() === 'error') errors.push(msg.text());
    });

    await page.goto('/wallet');
    await expectPageTitle(page, 'Carteira');
    await page.waitForTimeout(2000);

    const criticalErrors = errors.filter(e =>
      e.includes('Failed to load') ||
      e.includes('Unexpected token') ||
      e.includes('is not defined')
    );
    expect(criticalErrors).toEqual([]);
  });
});
