import { test, expect } from '@playwright/test';

test('Complete Jellyfin setup wizard with class selectors', async ({ browser }) => {
  const context = await browser.newContext({ storageState: 'auth-state.json' });
  const page = await context.newPage();

  console.log('Navigating to Jellyfin wizard start...');
  await page.goto('https://media.researchstack.info/web/#/wizard/start');
  await page.waitForLoadState('networkidle');
  await page.waitForTimeout(4000);
  
  // Step 1: Display language (default is English)
  console.log('Wizard Step 1: Preferred display language...');
  await page.screenshot({ path: 'jellyfin-wizard-step1.png' });
  await page.locator('.button-submit:visible').first().click();
  await page.waitForTimeout(4000);

  // Step 2: Create Admin account
  console.log('Wizard Step 2: Creating Admin account...');
  await page.screenshot({ path: 'jellyfin-wizard-step2.png' });
  
  const usernameInput = page.locator('input#txtUsername:visible');
  const passwordInput = page.locator('input#txtManualPassword:visible');
  const confirmInput = page.locator('input#txtPasswordConfirm:visible');
  
  await usernameInput.fill('admin');
  await passwordInput.fill('RY03KhsFez73K5va2uUb');
  await confirmInput.fill('RY03KhsFez73K5va2uUb');
  
  await page.screenshot({ path: 'jellyfin-wizard-step2-filled.png' });
  await page.locator('.button-submit:visible').first().click();
  await page.waitForTimeout(4000);

  // Step 3: Set up media libraries
  console.log('Wizard Step 3: Media Libraries...');
  await page.screenshot({ path: 'jellyfin-wizard-step3.png' });
  await page.locator('.button-submit:visible').first().click();
  await page.waitForTimeout(4000);

  // Step 4: Preferred Metadata Language
  console.log('Wizard Step 4: Metadata Language...');
  await page.screenshot({ path: 'jellyfin-wizard-step4.png' });
  await page.locator('.button-submit:visible').first().click();
  await page.waitForTimeout(4000);

  // Step 5: Configure Remote Access
  console.log('Wizard Step 5: Remote Access...');
  await page.screenshot({ path: 'jellyfin-wizard-step5.png' });
  await page.locator('.button-submit:visible').first().click();
  await page.waitForTimeout(4000);

  // Step 6: Finish
  console.log('Wizard Step 6: Finish...');
  await page.screenshot({ path: 'jellyfin-wizard-step6.png' });
  await page.locator('.button-submit:visible').first().click();
  await page.waitForTimeout(8000);

  console.log('Wizard complete. Current URL:', page.url());
  await page.screenshot({ path: 'jellyfin-after-wizard.png' });

  // Log in to Jellyfin
  console.log('Logging in to Jellyfin with new admin account...');
  const userLoginInput = page.locator('input#txtManualName:visible, input[type="text"]:visible').first();
  const passLoginInput = page.locator('input#txtManualPassword:visible, input[type="password"]:visible').first();

  if (await userLoginInput.isVisible()) {
    await userLoginInput.fill('admin');
    await passLoginInput.fill('RY03KhsFez73K5va2uUb');
    await page.locator('button[type="submit"]:visible, .button-submit:visible').first().click();
    await page.waitForTimeout(6000);
  }

  console.log('Home dashboard URL:', page.url());
  await page.screenshot({ path: 'jellyfin-home-dashboard.png' });
  const textContent = await page.evaluate(() => document.body.innerText);
  console.log('Jellyfin main page text:', textContent.slice(0, 1000));

  await context.close();
});
