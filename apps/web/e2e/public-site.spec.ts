import AxeBuilder from '@axe-core/playwright';
import { expect, test } from '@playwright/test';
import { open, signInAs } from './helpers';

test.describe('public website', () => {
  test('homepage hero, search → destination page @mobile', async ({ page }) => {
    await open(page, '/');
    await expect(page.getByRole('heading', { level: 1 })).toContainText('Explore the World.');
    await expect(page.getByRole('note')).toContainText('Mock data');

    const search = page.getByRole('combobox', { name: 'Search destinations' });
    await search.fill('lisb');
    await page.getByRole('option', { name: /Lisbon/ }).click();
    await expect(page).toHaveURL(/\/destinations\/portugal\/lisbon$/);
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('Lisbon');
  });

  test('destination page has canonical, hreflang alternates and structured data', async ({ page }) => {
    await page.goto('/destinations/brazil/rio-de-janeiro');
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('Rio de Janeiro');
    await expect(page.locator('link[rel="canonical"]')).toHaveAttribute('href', /\/destinations\/brazil\/rio-de-janeiro$/);
    for (const lang of ['en', 'es', 'pt-BR', 'fr', 'de', 'x-default']) {
      await expect(page.locator(`link[rel="alternate"][hreflang="${lang}"]`)).toHaveCount(1);
    }
    const types = await page.locator('script[type="application/ld+json"]').evaluateAll((nodes) =>
      nodes.flatMap((n) => [JSON.parse(n.textContent ?? '[]')].flat().map((x: { '@type': string }) => x['@type'])),
    );
    expect(types).toEqual(expect.arrayContaining(['TouristDestination', 'BreadcrumbList', 'FAQPage']));
  });

  test('localized pages use localized destination names', async ({ page }) => {
    await page.goto('/pt-br/destinations/japan/tokyo');
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('Tóquio');
    await expect(page.locator('html')).toHaveAttribute('lang', 'pt-BR');
  });

  test('public stories never include private or followers-only posts', async ({ page }) => {
    await page.goto('/stories');
    await expect(page.getByRole('article').first()).toBeVisible();
    const text = await page.locator('main').innerText();
    expect(text).not.toContain('reef-safe sunscreen');
    expect(text).not.toContain('Ilha Grande');
  });

  test('home and destination pages have no serious accessibility violations', async ({ page }) => {
    for (const path of ['/', '/destinations/brazil/rio-de-janeiro', '/login']) {
      await page.goto(path);
      const results = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21aa']).analyze();
      const serious = results.violations.filter((v) => v.impact === 'serious' || v.impact === 'critical');
      expect(serious.map((v) => `${path}: ${v.id} → ${v.nodes.map((n) => n.target.join(' ')).join(' | ')}`)).toEqual([]);
    }
  });
});

test.describe('access control', () => {
  test('traveler routes redirect anonymous visitors to login', async ({ page }) => {
    await page.goto('/feed');
    await expect(page).toHaveURL(/\/login\?next=%2Ffeed/);
  });

  test('admin is not revealed to non-staff (404)', async ({ page, context }) => {
    await signInAs(page, /Amelia Clarke/);
    const response = await page.goto('/admin');
    expect(response?.status()).toBe(404);
    await context.clearCookies();
  });

  test('private areas are noindex', async ({ request }) => {
    const response = await request.get('/login');
    expect(response.headers()['x-robots-tag']).toContain('noindex');
    expect(response.headers()['content-security-policy']).toContain("'nonce-");
  });

  test('BFF never proxies token-bearing auth endpoints and enforces CSRF', async ({ request }) => {
    expect((await request.post('/api/v1/auth/login', { data: {} })).status()).toBe(404);
    expect((await request.post('/api/v1/posts', { data: {} })).status()).toBe(403);
  });
});
