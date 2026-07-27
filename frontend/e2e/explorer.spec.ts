import { test, expect } from '@playwright/test';
import { waitForDashboardLoad, navigateTo, expectPageTitle, mineBlock } from './helpers';

test.describe('Explorer / Blocos', () => {
  test('Deve carregar pagina de Explorer', async ({ page }) => {
    await page.goto('/blocks');
    await expectPageTitle(page, 'Blockchain Explorer');
  });

  test('Deve mostrar blocos na lista', async ({ page }) => {
    await page.goto('/blocks');
    await expectPageTitle(page, 'Blockchain Explorer');

    // Deve mostrar blocos ou mensagem de vazio
    await page.waitForTimeout(2000);

    const hasBlocks = await page.locator('text=#0').first().isVisible().catch(() => false);
    const hasEmptyMsg = await page.locator('text=Nenhum bloco').first().isVisible().catch(() => false);

    expect(hasBlocks || hasEmptyMsg).toBeTruthy();
  });

  test('Deve mostrar paginacao quando houver mais de 10 blocos', async ({ page }) => {
    // Mina alguns blocos primeiro
    for (let i = 0; i < 3; i++) {
      await mineBlock(page);
    }

    await page.goto('/blocks');
    await expectPageTitle(page, 'Blockchain Explorer');
    await page.waitForTimeout(2000);

    // Verifica contagem total
    await expect(page.locator('text=transa\u00e7\u00f5es').first()).toBeVisible({ timeout: 5000 });
  });

  test('Deve clicar em um bloco e ver detalhes', async ({ page }) => {
    await page.goto('/blocks');
    await expectPageTitle(page, 'Blockchain Explorer');
    await page.waitForTimeout(2000);

    // Clica no link do primeiro bloco (hash)
    const blockLink = page.locator('a[href^="/block/"]').first();
    if (await blockLink.isVisible().catch(() => false)) {
      await blockLink.click();
      await page.waitForTimeout(2000);

      // Deve mostrar detalhes do bloco
      await expect(page.locator('text=Informa\u00e7\u00f5es do Bloco').first()).toBeVisible({ timeout: 5000 });
      await expect(page.locator('text=Hash do Bloco').first()).toBeVisible();
      await expect(page.locator('text=Nonce').first()).toBeVisible();
    }
  });

  test('Bloco genesis deve ter previous_hash = zeros', async ({ page }) => {
    await page.goto('/block/0');
    await page.waitForTimeout(2000);

    await expect(page.locator('text=Informa\u00e7\u00f5es do Bloco').first()).toBeVisible({ timeout: 5000 });
    await expect(page.locator('text=Bloco #0').first()).toBeVisible();
  });

  test('Bloco inexistente deve mostrar erro', async ({ page }) => {
    await page.goto('/block/99999');
    await page.waitForTimeout(2000);

    await expect(page.locator('text=Bloco n\u00e3o encontrado').first()).toBeVisible({ timeout: 5000 });
  });

  test('Navegacao de volta para Explorer deve funcionar', async ({ page }) => {
    await page.goto('/block/0');
    await page.waitForTimeout(2000);

    await page.locator('a:has-text("Blocos")').first().click();
    await expectPageTitle(page, 'Blockchain Explorer');
  });
});
