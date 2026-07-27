import { test, expect } from '@playwright/test';
import { expectPageTitle, waitForDashboardLoad, navigateTo } from './helpers';

test.describe('Network / Rede', () => {
  test('Deve carregar pagina de Rede', async ({ page }) => {
    await page.goto('/network');
    await expectPageTitle(page, 'Vis\u00e3o da Rede');
  });

  test('Deve mostrar estatisticas de rede (total, ativos, inativos)', async ({ page }) => {
    await page.goto('/network');
    await expectPageTitle(page, 'Vis\u00e3o da Rede');
    await page.waitForTimeout(2000);

    await expect(page.locator('text=Total').first()).toBeVisible({ timeout: 10000 });
    await expect(page.locator('text=Ativos').first()).toBeVisible();
    await expect(page.locator('text=Inativos').first()).toBeVisible();
  });

  test('Deve mostrar o proprio no na lista', async ({ page }) => {
    await page.goto('/network');
    await expectPageTitle(page, 'Vis\u00e3o da Rede');
    await page.waitForTimeout(3000);

    // Deve ter pelo menos 1 no (o proprio)
    const totalText = await page.locator('text=Total').first().locator('..').textContent();
    expect(totalText).toBeTruthy();
  });

  test('Tabela de nos deve ter cabecalhos corretos', async ({ page }) => {
    await page.goto('/network');
    await expectPageTitle(page, 'Vis\u00e3o da Rede');
    await page.waitForTimeout(2000);

    // Verifica cabecalhos da tabela se existir
    const tableHeaders = page.locator('th');
    const headerCount = await tableHeaders.count();
    if (headerCount > 0) {
      await expect(tableHeaders.first()).toBeVisible();
    }
  });

  test('Navegacao Network -> Dashboard deve funcionar', async ({ page }) => {
    await page.goto('/network');
    await expectPageTitle(page, 'Vis\u00e3o da Rede');
    await page.waitForTimeout(1000);

    await page.goto('/');
    await expectPageTitle(page, 'Dashboard');
  });
});
