import { test, expect } from '@playwright/test';

test('Dump plugins page HTML', async ({ browser }) => {
  const context = await browser.newContext({ storageState: 'auth-state.json' });
  const page = await context.newPage();

  console.log('Navigating directly to plugins page...');
  await page.goto('https://media.researchstack.info/web/#/dashboard/plugins');
  await page.waitForLoadState('networkidle');
  await page.waitForTimeout(5000);

  const bodyHtml = await page.evaluate(() => document.body.innerHTML);
  console.log('Plugins Body HTML length:', bodyHtml.length);
  // Log the first 4000 characters and look for tab buttons
  console.log('Body HTML:', bodyHtml.slice(0, 4000));
  
  // Let's also look for text "Available" in the HTML string and show surrounding content
  const idx = bodyHtml.indexOf('Available');
  if (idx !== -1) {
    console.log('Found "Available" at index:', idx);
    console.log('Context:', bodyHtml.slice(Math.max(0, idx - 200), idx + 200));
  } else {
    console.log('"Available" text not found in raw innerHTML!');
  }

  await context.close();
});
