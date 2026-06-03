import { test, expect } from '@playwright/test';

test('Dump Step 3 inputs', async ({ browser }) => {
  const context = await browser.newContext({ storageState: 'auth-state.json' });
  const page = await context.newPage();

  console.log('Navigating to wizard start...');
  await page.goto('https://media.researchstack.info/web/#/wizard/start');
  await page.waitForLoadState('networkidle');
  await page.waitForTimeout(3000);

  // Click Next on step 1
  console.log('Clicking Next on step 1...');
  await page.locator('button[type="submit"]:visible, button:has-text("Next"):visible').click();
  await page.waitForTimeout(3000);
  
  // Fill Step 2
  console.log('Filling Step 2...');
  await page.locator('input#txtUsername:visible').fill('admin');
  await page.locator('input#txtManualPassword:visible').fill('RY03KhsFez73K5va2uUb');
  await page.locator('input#txtPasswordConfirm:visible').fill('RY03KhsFez73K5va2uUb');
  
  // Click Next on step 2
  console.log('Clicking Next on step 2...');
  await page.locator('button[type="submit"]:visible, button:has-text("Next"):visible').click();
  await page.waitForTimeout(3000);
  
  console.log('Waiting for wizard/library page...');
  await page.waitForURL('**/wizard/library**');
  await page.waitForTimeout(4000);
  
  console.log('Current URL:', page.url());
  await page.screenshot({ path: 'jellyfin-wizard-step3-debug.png' });
  
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
  console.log('Inputs found in Step 3:', JSON.stringify(inputs, null, 2));

  await context.close();
});
