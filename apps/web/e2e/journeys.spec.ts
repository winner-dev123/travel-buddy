import { expect, test } from '@playwright/test';
import { hydrated, open, signInAs } from './helpers';

/** Brief §30 E2E journeys that the web can run against the mock adapter today. */

test('registration → onboarding → personalized feed', async ({ page }) => {
  const unique = Date.now();
  await open(page, '/register');
  await page.getByLabel('Display name').fill('Robin Traveler');
  await page.getByLabel('Email').fill(`robin.${unique}@example.com`);
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
  await page.getByLabel('Email').fill(`young.${Date.now()}@example.com`);
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

test('a place recommendation needs a destination, and the default destination can be removed', async ({ page }) => {
  await signInAs(page, /Yuki Tanaka/);
  await page.getByRole('button', { name: /Share a moment|Continue your draft/ }).click();
  await page.getByLabel('What’s happening?').fill('Best ramen near the station');
  await page.getByLabel('Type', { exact: true }).selectOption('restaurant_recommendation');
  const publish = page.getByRole('button', { name: 'Publish' });
  await expect(publish).toBeEnabled(); // the browse destination (Tokyo) applies by default

  await page.getByRole('button', { name: 'Remove destination' }).click();
  await expect(page.getByText('This type of post needs a destination. Choose one above.')).toBeVisible();
  await expect(publish).toBeDisabled();

  await page.getByLabel('Type', { exact: true }).selectOption('tip');
  await expect(publish).toBeEnabled(); // a tip may be posted without a location
  await page.getByRole('button', { name: 'Discard draft' }).click();
});

test('blocking from a post, then unblocking in privacy settings', async ({ page }) => {
  // Lucas and the author he blocks are used by no other test: tests run in parallel against one mock server,
  // and a block removes follows both ways, which would reshuffle another persona's feed.
  await signInAs(page, /Lucas Almeida/);
  const article = page.getByRole('article').filter({ hasNotText: /Lucas Almeida|Noah Fischer|Yuki Tanaka|Amelia Clarke/ }).first();
  const labelId = await article.getAttribute('aria-labelledby');
  // textContent, not innerText: post cards use content-visibility: auto, so off-screen text is not rendered.
  const author = ((await page.locator(`[id="${labelId}"]`).textContent()) ?? '').trim();
  expect(author).not.toBe('');
  await article.getByLabel('More actions').click();
  await article.getByRole('button', { name: `Block ${author}`, exact: true }).click();
  await expect(page.getByRole('article', { name: author, exact: true })).toHaveCount(0);

  await page.goto('/settings');
  await hydrated(page);
  const blocked = page.getByRole('list', { name: 'Blocked accounts' });
  await expect(blocked.getByText(author, { exact: true })).toBeVisible();
  await page.getByRole('button', { name: `Unblock ${author}` }).click();
  await expect(page.getByText('You haven’t blocked anyone.')).toBeVisible();
  await page.reload();
  await expect(page.getByText('You haven’t blocked anyone.')).toBeVisible();
});

test('hiding a post from the feed keeps it hidden after a reload', async ({ page }) => {
  await signInAs(page, /Sofia Rossi/); // used by no other test (feedback changes this persona's feed)
  const article = page.getByRole('article').filter({ hasNotText: 'Sofia Rossi' }).first();
  const labelId = await article.getAttribute('aria-labelledby');
  const postId = labelId?.replace(/^post-|-author$/g, '') ?? '';
  expect(postId).not.toBe('');
  await article.getByLabel('More actions').click();
  await article.getByRole('button', { name: 'Hide post' }).click();
  await expect(page.locator(`article[aria-labelledby="${labelId}"]`)).toHaveCount(0);
  await page.reload();
  await hydrated(page);
  await expect(page.getByRole('article').first()).toBeVisible();
  await expect(page.locator(`article[aria-labelledby="${labelId}"]`)).toHaveCount(0);
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
