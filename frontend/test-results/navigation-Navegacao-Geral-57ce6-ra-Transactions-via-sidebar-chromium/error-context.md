# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: navigation.spec.ts >> Navegacao Geral >> Deve navegar para Transactions via sidebar
- Location: e2e\navigation.spec.ts:18:3

# Error details

```
Error: expect(locator).toBeVisible() failed

Locator: locator('text=Blocos').first()
Expected: visible
Timeout: 15000ms
Error: element(s) not found

Call log:
  - Expect "toBeVisible" with timeout 15000ms
  - waiting for locator('text=Blocos').first()

```

```yaml
- complementary:
  - text: K
  - heading "Kurama Chain" [level=1]
  - paragraph: Blockchain Explorer
  - navigation:
    - link "📊 Dashboard":
      - /url: /
    - link "🔗 Explorer":
      - /url: /blocks
    - link "💳 Transactions":
      - /url: /transactions
    - link "🌐 Network":
      - /url: /network
    - link "👛 Wallet":
      - /url: /wallet
  - paragraph: v1.0.0 — Kurama Chain
- banner:
  - img
  - textbox "Buscar blocos, transações ou endereços..."
  - button "💸 Enviar"
  - text: Live
- main:
  - paragraph: Erro ao carregar dados da blockchain
  - paragraph: Request failed with status code 500
  - button "Tentar novamente"
```

# Test source

```ts
  1  | import { Page, expect } from '@playwright/test';
  2  | 
  3  | /**
  4  |  * Aguarda o Dashboard carregar completamente (stat cards + grafico).
  5  |  */
  6  | export async function waitForDashboardLoad(page: Page) {
  7  |   // Aguarda os stat cards aparecerem
> 8  |   await expect(page.locator('text=Blocos').first()).toBeVisible({ timeout: 15000 });
     |                                                     ^ Error: expect(locator).toBeVisible() failed
  9  |   await expect(page.locator('text=Transa\u00e7\u00f5es').first()).toBeVisible({ timeout: 5000 });
  10 |   await expect(page.locator('text=Supply').first()).toBeVisible({ timeout: 5000 });
  11 |   await expect(page.locator('text=Dificuldade').first()).toBeVisible({ timeout: 5000 });
  12 |   // Aguarda o grafico ou mensagem de dados insuficientes
  13 |   await page.waitForTimeout(1000);
  14 | }
  15 | 
  16 | /**
  17 |  * Gera uma carteira via API e retorna o endereco.
  18 |  */
  19 | export async function generateWallet(page: Page): Promise<string> {
  20 |   const response = await page.request.post('http://localhost:5000/wallet/new', {
  21 |     data: {},
  22 |   });
  23 |   expect(response.status()).toBe(200);
  24 |   const body = await response.json();
  25 |   return body.address;
  26 | }
  27 | 
  28 | /**
  29 |  * Mina um bloco via API e retorna a resposta.
  30 |  */
  31 | export async function mineBlock(page: Page, minerAddress?: string) {
  32 |   const response = await page.request.post('http://localhost:5000/mine', {
  33 |     data: minerAddress ? { miner_address: minerAddress } : {},
  34 |   });
  35 |   return response;
  36 | }
  37 | 
  38 | /**
  39 |  * Verifica se a pagina atual tem um titulo correspondente.
  40 |  */
  41 | export async function expectPageTitle(page: Page, title: string) {
  42 |   await expect(page.locator('h1').filter({ hasText: title }).first()).toBeVisible({ timeout: 10000 });
  43 | }
  44 | 
  45 | /**
  46 |  * Navega para uma pagina via sidebar e verifica se carregou.
  47 |  */
  48 | export async function navigateTo(page: Page, label: string) {
  49 |   // No desktop, o sidebar fica visivel
  50 |   await page.locator('a', { hasText: label }).first().click();
  51 |   await page.waitForLoadState('networkidle');
  52 | }
  53 | 
  54 | /**
  55 |  * Verifica se NAO ha erros no console.
  56 |  */
  57 | export function getConsoleErrors(errors: string[]): string[] {
  58 |   return errors.filter(msg => msg.includes('Failed to load') || msg.includes('Unexpected token'));
  59 | }
  60 | 
```