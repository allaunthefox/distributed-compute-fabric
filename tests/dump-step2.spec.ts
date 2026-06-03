import { test, expect } from '@playwright/test';

test('Dump Step 2 inputs', async ({ browser }) => {
  const context = await browser.newContext({ storageState: 'auth-state.json' });
  const page = await context.newPage();

  console.log('Navigating to wizard start...');
  await page.goto('https://media.researchstack.info/web/#/wizard/start');
  await page.waitForLoadState('networkidle');
  await page.waitForTimeout(4000);

  // Click Next on step 1
  console.log('Clicking Next on step 1...');
  await page.locator('button[type="submit"], button:has-text("Next")').first().click();
  
  // Wait for URL to change to /wizard/user
  console.log('Waiting for wizard/user page...');
  await page.waitForURL('**/wizard/user**');
  await page.waitForTimeout(4000);
  
  console.log('Current URL:', page.url());
  
  // Print all input tags on the page
  const inputs = await page.evaluate(() => {
    return Array.from(document.querySelectorAll('input, select, button')).map(el => ({
      tagName: el.tagName,
      id: el.id,
      type: el.getAttribute('type'),
      className: el.className,
      innerText: (el as HTMLElement).innerText || el.getAttribute('value')
    }));
  });
  console.log('Inputs found:', JSON.stringify(inputs, null, 2));

  await context.close();
});
