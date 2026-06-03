import { test, expect } from '@playwright/test';

test('Check Jellyfin wizard', async ({ browser }) => {
  const context = await browser.newContext({ storageState: 'auth-state.json' });
  const page = await context.newPage();

  console.log('Navigating to Jellyfin wizard...');
  await page.goto('https://media.researchstack.info/web/#/wizardstart.html');
  await page.waitForLoadState('networkidle');
  await page.waitForTimeout(6000);

  console.log('URL:', page.url());
  await page.screenshot({ path: 'jellyfin-wizard.png' });

  const textContent = await page.evaluate(() => document.body.innerText);
  console.log('Jellyfin text:', textContent.slice(0, 1000));
  
  await context.close();
});
