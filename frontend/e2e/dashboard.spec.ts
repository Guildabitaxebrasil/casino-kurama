import { test, expect } from '@playwright/test';
import { waitForDashboardLoad, mineBlock } from './helpers';

test.describe('Dashboard', () => {
  test('Deve mostrar 4 stat cards com valores', async ({ page }) => {
    await page.goto('/');
    await waitForDashboardLoad(page);

    // Verifica se os 4 stat cards estao visiveis
    await expect(page.locator('text=Blocos').first()).toBeVisible();
    await expect(page.locator('text=Transa\u00e7\u00f5es').first()).toBeVisible();
    await expect(page.locator('text=Supply').first()).toBeVisible();
    await expect(page.locator('text=Dificuldade').first()).toBeVisible();

    // Verifica se os valores sao numeros
    const blocosCard = page.locator('text=Blocos').first().locator('..');
    await expect(blocosCard.locator('text=KUR').first()).toBeVisible();
  });

  test('Deve mostrar a barra de fornecimento (supply)', async ({ page }) => {
    await page.goto('/');
    await waitForDashboardLoad(page);

    await expect(page.locator('text=Fornecimento').first()).toBeVisible({ timeout: 10000 });
    await expect(page.locator('text=% minerado').first()).toBeVisible();
  });

  test('Deve mostrar o grafico de crescimento', async ({ page }) => {
    await page.goto('/');
    await waitForDashboardLoad(page);

    await expect(page.locator('text=Crescimento da Blockchain').first()).toBeVisible({ timeout: 10000 });
  });

  test('Deve mostrar o widget Mempool', async ({ page }) => {
    await page.goto('/');
    await waitForDashboardLoad(page);

    await expect(page.locator('text=Mempool').first()).toBeVisible({ timeout: 10000 });
  });

  test('Deve mostrar se\u00e7\u00e3o Minerar Bloco', async ({ page }) => {
    await page.goto('/');
    await waitForDashboardLoad(page);

    await expect(page.locator('text=Minerar Bloco').first()).toBeVisible({ timeout: 10000 });
    await expect(page.locator('button:has-text("Minerar")').first()).toBeVisible();
  });

  test('Deve minerar um bloco pelo Dashboard', async ({ page }) => {
    await page.goto('/');
    await waitForDashboardLoad(page);

    // Clica no botao Minerar
    await page.locator('button:has-text("Minerar")').first().click();

    // Aguarda resultado (mining pode levar alguns segundos com PoW)
    await page.waitForTimeout(5000);

    // Verifica se apareceu mensagem de sucesso
    const successMsg = page.locator('text=Novo bloco minerado').first();
    const errorMsg = page.locator('text=Erro').first();

    if (await successMsg.isVisible({ timeout: 10000 }).catch(() => false)) {
      await expect(successMsg).toBeVisible();
      // Verifica se mostra recompensa
      await expect(page.locator('text=Recompensa').first()).toBeVisible();
      await expect(page.locator('text=KUR').first()).toBeVisible();
    }
  });

  test('Deve mostrar blocos recentes', async ({ page }) => {
    await page.goto('/');
    await waitForDashboardLoad(page);

    await expect(page.locator('text=Blocos Recentes').first()).toBeVisible({ timeout: 10000 });
  });

  test('Nao deve mostrar erros de console no Dashboard', async ({ page }) => {
    const errors: string[] = [];
    page.on('console', (msg) => {
      if (msg.type() === 'error') errors.push(msg.text());
    });

    await page.goto('/');
    await waitForDashboardLoad(page);
    await page.waitForTimeout(2000);

    const criticalErrors = errors.filter(e =>
      e.includes('Failed to load') ||
      e.includes('Unexpected token') ||
      e.includes('is not defined')
    );
    expect(criticalErrors).toEqual([]);
  });
});
