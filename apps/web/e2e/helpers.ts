import { expect, type Page } from '@playwright/test';

/** Waits until React has hydrated the current document (set by components/providers.tsx). */
export async function hydrated(page: Page): Promise<void> {
  await expect(page.locator('html[data-hydrated="true"]')).toHaveCount(1);
}

/** Opens a URL and waits for hydration. */
export async function open(page: Page, url: string): Promise<void> {
  await page.goto(url);
  await hydrated(page);
}

/** Signs in through the development persona picker (mock adapter / dev IdP). */
export async function signInAs(page: Page, persona: RegExp): Promise<void> {
  await open(page, '/dev/login');
  await page.getByRole('button', { name: persona }).click();
  await expect(page).toHaveURL(/\/feed/);
  await hydrated(page);
}
