import { test, expect } from '@playwright/test';

test('Dump Jellyfin wizard Step 2 HTML', async ({ browser }) => {
  const context = await browser.newContext({ storageState: 'auth-state.json' });
  const page = await context.newPage();

  console.log('Navigating to Jellyfin wizard start...');
  await page.goto('https://media.researchstack.info/web/#/wizard/start');
  await page.waitForLoadState('networkidle');
  await page.waitForTimeout(4000);

  // Click Next to go to Step 2
  await page.locator('button:has-text("Next")').first().click();
  await page.waitForTimeout(4000);

  console.log('At Step 2. URL:', page.url());

  // Dump form HTML
  const formHtml = await page.evaluate(() => {
    const form = document.querySelector('form');
    return form ? form.innerHTML : 'Form not found';
  });
  console.log('--- Form HTML Start ---');
  console.log(formHtml);
  console.log('--- Form HTML End ---');

  await context.close();
});
