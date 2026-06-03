import { test, expect } from '@playwright/test';

test('Complete Jellyfin setup wizard with forced clicks', async ({ browser }) => {
  const context = await browser.newContext({ storageState: 'auth-state.json' });
  const page = await context.newPage();

  console.log('Navigating to Jellyfin...');
  await page.goto('https://media.researchstack.info/');
  await page.waitForLoadState('networkidle');
  await page.waitForTimeout(4000);

  console.log('URL at start:', page.url());
  await page.screenshot({ path: 'jellyfin-wizard-v3-start.png' });

  // If we are on the login page instead of the wizard, go to wizard
  if (page.url().includes('login')) {
    console.log('Redirecting to wizard start manually...');
    await page.goto('https://media.researchstack.info/web/#/wizard/start');
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(4000);
  }

  // Step 1: Language
  console.log('Step 1 URL:', page.url());
  await page.screenshot({ path: 'jellyfin-wizard-v3-step1.png' });
  await page.locator('.button-submit:visible').first().click({ force: true });
  await page.waitForTimeout(4000);

  // Step 2: Create User
  console.log('Step 2 URL:', page.url());
  await page.screenshot({ path: 'jellyfin-wizard-v3-step2.png' });
  
  const usernameInput = page.locator('input#txtUsername:visible');
  const passwordInput = page.locator('input#txtManualPassword:visible');
  const confirmInput = page.locator('input#txtPasswordConfirm:visible');
  
  await usernameInput.fill('admin');
  await passwordInput.fill('RY03KhsFez73K5va2uUb');
  await confirmInput.fill('RY03KhsFez73K5va2uUb');
  
  await page.screenshot({ path: 'jellyfin-wizard-v3-step2-filled.png' });
  await page.locator('.button-submit:visible').first().click({ force: true });
  await page.waitForTimeout(4000);

  // Step 3: Libraries
  console.log('Step 3 URL:', page.url());
  await page.screenshot({ path: 'jellyfin-wizard-v3-step3.png' });
  await page.locator('.button-submit:visible').first().click({ force: true });
  await page.waitForTimeout(4000);

  // Step 4: Metadata Language
  console.log('Step 4 URL:', page.url());
  await page.screenshot({ path: 'jellyfin-wizard-v3-step4.png' });
  await page.locator('.button-submit:visible').first().click({ force: true });
  await page.waitForTimeout(4000);

  // Step 5: Remote Access
  console.log('Step 5 URL:', page.url());
  await page.screenshot({ path: 'jellyfin-wizard-v3-step5.png' });
  await page.locator('.button-submit:visible').first().click({ force: true });
  await page.waitForTimeout(4000);

  // Step 6: Finish
  console.log('Step 6 URL:', page.url());
  await page.screenshot({ path: 'jellyfin-wizard-v3-step6.png' });
  
  const finishBtn = page.locator('button:has-text("Finish"):visible, .button-submit:visible').first();
  await finishBtn.click({ force: true });
  await page.waitForTimeout(8000);

  console.log('After wizard URL:', page.url());
  await page.screenshot({ path: 'jellyfin-wizard-v3-finished.png' });

  // Log in
  const userLoginInput = page.locator('input#txtManualName:visible, input[type="text"]:visible').first();
  const passLoginInput = page.locator('input#txtManualPassword:visible, input[type="password"]:visible').first();

  if (await userLoginInput.isVisible()) {
    console.log('Logging in manually to verify...');
    await userLoginInput.fill('admin');
    await passLoginInput.fill('RY03KhsFez73K5va2uUb');
    await page.locator('button[type="submit"]:visible, .button-submit:visible').first().click({ force: true });
    await page.waitForTimeout(6000);
    console.log('Logged in home URL:', page.url());
    await page.screenshot({ path: 'jellyfin-wizard-v3-home.png' });
  }

  await context.close();
});
