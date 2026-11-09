import { expect, test } from '@playwright/test';
import { hydrated, open, signInAs } from './helpers';

/** Brief §30 E2E journeys that the web can run against the mock adapter today. */

test('registration → onboarding → personalized feed', async ({ page }) => {
  const unique = Date.now();
  await open(page, '/register');
  await page.getByLabel('Display name').fill('Robin Traveler');
  await page.getByLabel('Email').fill(`robin.${unique}@example.test`);
  await page.getByLabel('Date of birth').fill('1994-05-17');
  await page.getByRole('checkbox').check();
  await page.getByRole('button', { name: 'Create account' }).click();

  await expect(page).toHaveURL(/\/onboarding/);
  await hydrated(page);
  await expect(page.getByText('Step 1 of 7')).toBeVisible();
  await page.getByRole('button', { name: 'Continue' }).click(); // profile (name prefilled)
  await page.getByRole('button', { name: 'Skip' }).click(); // language
  await page.getByRole('button', { name: 'Photography' }).click(); // interests
  await page.getByRole('button', { name: 'Continue' }).click();
  await page.getByRole('button', { name: 'Skip' }).click(); // home country
  await page.getByRole('combobox', { name: 'Search a destination' }).fill('tok');
  await page.getByRole('option', { name: /Tokyo/ }).click();
  await expect(page.getByText('Your feed will focus on Tokyo.')).toBeVisible();
  await page.getByRole('button', { name: 'Continue' }).click();
  await page.getByRole('button', { name: 'Skip' }).click(); // location (never prompted silently)
  // Discovery step: off by default.
  await expect(page.getByRole('switch')).toHaveAttribute('aria-checked', 'false');
  await page.getByRole('button', { name: 'Start exploring' }).click();

  await expect(page).toHaveURL(/\/feed/);
  await hydrated(page);
  await expect(page.getByText('Showing Tokyo · your selected destination')).toBeVisible();
  await expect(page.getByRole('article').first()).toBeVisible();
});

test('underage registration is rejected before an account is created', async ({ page }) => {
  await open(page, '/register');
  await page.getByLabel('Display name').fill('Young Person');
  await page.getByLabel('Email').fill(`young.${Date.now()}@example.test`);
  await page.getByLabel('Date of birth').fill('2012-01-01');
  await page.getByRole('checkbox').check();
  await page.getByRole('button', { name: 'Create account' }).click();
  await expect(page.getByText('You must be at least 18 years old to join.')).toBeVisible();
  await expect(page).toHaveURL(/\/register/);
});

test('publishing a travel post', async ({ page }) => {
  await signInAs(page, /Yuki Tanaka/);
  await expect(page.getByText(/Showing Tokyo/)).toBeVisible();

  const text = `Matcha tasting in Asakusa ${Date.now()}`;
  await page.getByRole('button', { name: /Share a moment|Continue your draft/ }).click();
  await page.getByLabel('What’s happening?').fill(text);
  await expect(page.getByLabel('Who can see this?')).toHaveValue('followers');
  await page.getByRole('button', { name: 'Publish' }).click();

  await expect(page.getByRole('dialog')).toBeHidden();
  await expect(page.getByText(text)).toBeVisible();
});

test('reacting to a post is optimistic and persisted', async ({ page }) => {
  await signInAs(page, /Noah Fischer/);
  const first = page.getByRole('article').first();
  const like = first.getByRole('button', { name: 'Like' });
  const before = Number((await like.innerText()).replace(/\D/g, ''));
  await like.click();
  await expect(first.getByRole('button', { name: 'Remove like' })).toHaveAttribute('aria-pressed', 'true');
  await page.reload();
  await hydrated(page);
  await expect(page.getByRole('article').first().getByRole('button', { name: 'Remove like' })).toBeVisible();
  const after = Number((await page.getByRole('article').first().getByRole('button', { name: 'Remove like' }).innerText()).replace(/\D/g, ''));
  expect(after).toBeGreaterThanOrEqual(before);
});
