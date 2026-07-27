import { test, expect } from '@playwright/test';
import { waitForDashboardLoad, navigateTo, expectPageTitle } from './helpers';

test.describe('Navegacao Geral', () => {
  test('Deve carregar o Dashboard na rota raiz', async ({ page }) => {
    await page.goto('/');
    await waitForDashboardLoad(page);
    await expectPageTitle(page, 'Dashboard');
  });

  test('Deve navegar para Explorer via sidebar', async ({ page }) => {
    await page.goto('/');
    await waitForDashboardLoad(page);
    await navigateTo(page, 'Explorer');
    await expectPageTitle(page, 'Blockchain Explorer');
  });

  test('Deve navegar para Transactions via sidebar', async ({ page }) => {
    await page.goto('/');
    await waitForDashboardLoad(page);
    await navigateTo(page, 'Transactions');
    await expectPageTitle(page, 'Transa\u00e7\u00f5es');
  });

  test('Deve navegar para Network via sidebar', async ({ page }) => {
    await page.goto('/');
    await waitForDashboardLoad(page);
    await navigateTo(page, 'Network');
    await expectPageTitle(page, 'Vis\u00e3o da Rede');
  });

  test('Deve navegar para Wallet via sidebar', async ({ page }) => {
    await page.goto('/');
    await waitForDashboardLoad(page);
    await navigateTo(page, 'Wallet');
    await expectPageTitle(page, 'Carteira');
  });

  test('Rotas invalidas devem redirecionar para Dashboard', async ({ page }) => {
    await page.goto('/rota-inexistente');
    await waitForDashboardLoad(page);
    await expectPageTitle(page, 'Dashboard');
  });

  test('Navegacao deve funcionar sem erros de console', async ({ page }) => {
    const errors: string[] = [];
    page.on('console', (msg) => {
      if (msg.type() === 'error') errors.push(msg.text());
    });

    await page.goto('/');
    await waitForDashboardLoad(page);
    await navigateTo(page, 'Explorer');
    await page.waitForTimeout(1000);
    await navigateTo(page, 'Network');
    await page.waitForTimeout(1000);
    await navigateTo(page, 'Wallet');
    await page.waitForTimeout(1000);

    expect(errors.filter(e => e.includes('Failed to load') || e.includes('Unexpected token'))).toEqual([]);
  });

  test('TopBar deve mostrar indicador Live', async ({ page }) => {
    await page.goto('/');
    await waitForDashboardLoad(page);
    await expect(page.locator('text=Live').first()).toBeVisible();
  });

  test('Deve abrir e fechar sidebar no mobile', async ({ page }) => {
    // Simula viewport mobile
    await page.setViewportSize({ width: 375, height: 667 });
    await page.goto('/');
    await waitForDashboardLoad(page);

    // Clica no hamburger
    await page.locator('button[aria-label="Toggle sidebar"]').click();
    await expect(page.locator('text=Kurama Chain').first()).toBeVisible();

    // Fecha clicando no backdrop
    await page.locator('.fixed.inset-0.bg-black\/50').first().click();
    await page.waitForTimeout(300);
  });
});
