import { test, expect } from '@playwright/test';

test('Check Homarr Status', async ({ browser }) => {
  const context = await browser.newContext({ storageState: 'auth-state.json' });
  const page = await context.newPage();

  console.log('Navigating to Homarr...');
  await page.goto('https://www.researchstack.info/');
  await page.waitForLoadState('networkidle');
  await page.waitForTimeout(4000);

  if (page.url().includes('default-provider-authorization-explicit-consent')) {
    await page.locator('button:has-text("Continue"), input[type="submit"]').first().click();
    await page.waitForTimeout(4000);
  }

  await page.screenshot({ path: 'homarr-status.png' });
  console.log('Screenshot saved.');
  console.log('Current URL:', page.url());
  console.log('Page Title:', await page.title());

  const content = await page.evaluate(() => document.body.innerText);
  console.log('Homarr text:', content.slice(0, 1000));

  await context.close();
});
