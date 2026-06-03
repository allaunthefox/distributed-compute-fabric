import { test, expect } from '@playwright/test';

test('Dump Jellyfin Home page HTML', async ({ browser }) => {
  const context = await browser.newContext({ storageState: 'auth-state.json' });
  const page = await context.newPage();

  console.log('Navigating to Jellyfin...');
  await page.goto('https://media.researchstack.info/');
  await page.waitForLoadState('networkidle');
  await page.waitForTimeout(4000);

  // Login
  const usernameInput = page.locator('input[type="text"], input#txtManualName');
  const passwordInput = page.locator('input[type="password"], input#txtManualPassword');

  if (await usernameInput.isVisible()) {
    console.log('Logging in...');
    await usernameInput.fill('admin');
    await passwordInput.fill('RY03KhsFez73K5va2uUb');
    await page.locator('button[type="submit"], button.button-submit').first().click();
    await page.waitForTimeout(6000);
  }

  // Dump HTML of body
  const bodyHtml = await page.evaluate(() => document.body.innerHTML);
  console.log('Body HTML length:', bodyHtml.length);
  // Log a subset of body HTML where headers or buttons are
  console.log('Header/Buttons HTML:', bodyHtml.slice(0, 3000));

  await context.close();
});
