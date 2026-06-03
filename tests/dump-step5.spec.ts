import { test, expect } from '@playwright/test';

test('Dump Step 5 inputs', async ({ browser }) => {
  const context = await browser.newContext({ storageState: 'auth-state.json' });
  const page = await context.newPage();

  console.log('Navigating to wizard start...');
  await page.goto('https://media.researchstack.info/web/#/wizard/start');
  await page.waitForLoadState('networkidle');
  await page.waitForTimeout(3000);

  // Step 1 -> Step 2
  await page.locator('.button-submit:visible').first().click();
  await page.waitForTimeout(3000);
  
  // Step 2 -> Step 3
  await page.locator('input#txtUsername:visible').fill('admin');
  await page.locator('input#txtManualPassword:visible').fill('RY03KhsFez73K5va2uUb');
  await page.locator('input#txtPasswordConfirm:visible').fill('RY03KhsFez73K5va2uUb');
  await page.locator('.button-submit:visible').first().click();
  await page.waitForTimeout(3000);
  
  // Step 3 -> Step 4
  await page.locator('.button-submit:visible').first().click();
  await page.waitForTimeout(3000);

  // Step 4 -> Step 5
  await page.locator('.button-submit:visible').first().click();
  await page.waitForTimeout(3000);
  
  console.log('Current URL:', page.url());
  await page.screenshot({ path: 'jellyfin-wizard-step5-debug.png' });
  
  // Print all visible input/button tags on the page
  const inputs = await page.evaluate(() => {
    return Array.from(document.querySelectorAll('input, select, button')).map(el => ({
      tagName: el.tagName,
      id: el.id,
      type: el.getAttribute('type'),
      className: el.className,
      innerText: (el as HTMLElement).innerText || el.getAttribute('value'),
      isVisible: (el as HTMLElement).offsetWidth > 0 && (el as HTMLElement).offsetHeight > 0
    }));
  });
  console.log('Inputs found in Step 5:', JSON.stringify(inputs, null, 2));

  await context.close();
});
