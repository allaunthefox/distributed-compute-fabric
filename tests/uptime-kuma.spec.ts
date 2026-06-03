import { test, expect } from '@playwright/test';

test('Configure Uptime Kuma Admin', async ({ browser }) => {
  const context = await browser.newContext({ storageState: 'auth-state.json' });
  const page = await context.newPage();

  console.log('Navigating to Uptime Kuma...');
  await page.goto('https://uptime.researchstack.info/');
  await page.waitForLoadState('networkidle');
  await page.waitForTimeout(4000);

  if (page.url().includes('default-provider-authorization-explicit-consent')) {
    await page.locator('button:has-text("Continue"), input[type="submit"]').first().click();
    await page.waitForTimeout(4000);
  }

  console.log('Current URL:', page.url());

  if (page.url().includes('/setup')) {
    console.log('Filling setup wizard form...');
    
    const usernameInput = page.locator('#floatingInput');
    await expect(usernameInput).toBeVisible();
    await usernameInput.fill('admin');

    const passwordInput = page.locator('#floatingPassword');
    await passwordInput.fill('RY03KhsFez73K5va2uUb');

    const repeatInput = page.locator('#repeat');
    await repeatInput.fill('RY03KhsFez73K5va2uUb');

    // Click Create
    console.log('Clicking Create...');
    const createBtn = page.locator('button[type="submit"]');
    await createBtn.click();
    await page.waitForTimeout(5000);
  } else {
    console.log('Already past setup page.');
  }

  await page.screenshot({ path: 'uptime-kuma-dashboard.png' });
  console.log('Final page URL:', page.url());
  console.log('Final page title:', await page.title());
  
  await context.close();
});
