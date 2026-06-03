import { test, expect } from '@playwright/test';

test('Check Jellyfin with auth-state', async ({ browser }) => {
  const context = await browser.newContext({ storageState: 'auth-state.json' });
  const page = await context.newPage();

  console.log('Navigating to Jellyfin...');
  await page.goto('https://media.researchstack.info/');
  await page.waitForLoadState('networkidle');
  await page.waitForTimeout(6000);

  console.log('Current URL:', page.url());
  await page.screenshot({ path: 'jellyfin-check-initial.png' });

  // If on consent page
  if (page.url().includes('consent') || page.url().includes('authorize')) {
    console.log('On consent/authorize page. Clicking Continue/Submit...');
    const btn = page.locator('button:has-text("Continue"), button:has-text("Authorize"), input[type="submit"]').first();
    if (await btn.isVisible()) {
      await btn.click();
      await page.waitForTimeout(6000);
      console.log('Clicked. New URL:', page.url());
      await page.screenshot({ path: 'jellyfin-check-after-consent.png' });
    }
  }

  const textContent = await page.evaluate(() => document.body.innerText);
  console.log('Jellyfin body text:', textContent.slice(0, 1000));
  
  await context.close();
});
