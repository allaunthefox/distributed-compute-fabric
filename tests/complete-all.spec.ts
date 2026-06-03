import { test, expect } from '@playwright/test';

test('Complete Jellyfin setup + OIDC plugin', async ({ browser }) => {
  const context = await browser.newContext({ ignoreHTTPSErrors: true });
  const page = await context.newPage();

  // Step 1: Complete Jellyfin Setup Wizard
  console.log('=== Starting Jellyfin Setup Wizard ===');
  await page.goto('https://media.researchstack.info/web/#/wizard/start', { waitUntil: 'networkidle' });
  await page.waitForTimeout(3000);

  // Step 1: Language - click Next
  console.log('Step 1: Language');
  await page.locator('.button-submit:visible').first().click();
  await page.waitForTimeout(3000);

  // Step 2: Create admin account
  console.log('Step 2: Create Admin');
  await page.locator('input#txtUsername:visible').fill('admin');
  await page.locator('input#txtManualPassword:visible').fill('jellyfin-admin');
  await page.locator('input#txtPasswordConfirm:visible').fill('jellyfin-admin');
  await page.locator('.button-submit:visible').first().click();
  await page.waitForTimeout(3000);

  // Step 3: Media Libraries - skip
  console.log('Step 3: Libraries');
  await page.locator('.button-submit:visible').first().click();
  await page.waitForTimeout(3000);

  // Step 4: Metadata Language
  console.log('Step 4: Metadata');
  await page.locator('.button-submit:visible').first().click();
  await page.waitForTimeout(3000);

  // Step 5: Remote Access
  console.log('Step 5: Remote Access');
  await page.locator('.button-submit:visible').first().click();
  await page.waitForTimeout(3000);

  // Step 6: Finish
  console.log('Step 6: Finish');
  await page.locator('.button-submit:visible').first().click();
  await page.waitForTimeout(5000);

  console.log('Wizard complete at:', page.url());

  // Step 2: Login
  console.log('=== Logging in ===');
  if (page.url().includes('/login') || page.url().includes('/web')) {
    await page.goto('https://media.researchstack.info/web/#/login.html', { waitUntil: 'networkidle' });
    await page.waitForTimeout(3000);
    const username = page.locator('input#txtUsername:visible');
    const password = page.locator('input#txtPassword:visible');
    if (await username.isVisible()) {
      await username.fill('admin');
      await password.fill('jellyfin-admin');
      await page.locator('.button-submit:visible').first().click();
      await page.waitForTimeout(5000);
    }
  }

  // Step 3: Navigate to Dashboard -> Plugins
  console.log('=== Installing OIDC Plugin ===');
  await page.goto('https://media.researchstack.info/web/#/dashboard/plugins', { waitUntil: 'networkidle' });
  await page.waitForTimeout(5000);

  // Click Catalog tab
  await page.locator('a[href="#/dashboard/plugins/catalog"]:visible').first().click();
  await page.waitForTimeout(3000);

  // Search for OIDC plugin
  console.log('Searching for OIDC plugin...');
  const searchBox = page.locator('input[type="text"]:visible').first();
  if (await searchBox.isVisible()) {
    await searchBox.fill('OIDC');
    await page.waitForTimeout(3000);
  }

  // Install the OIDC plugin
  console.log('Looking for install button...');
  const installButtons = page.locator('button:has-text("Install"):visible');
  const count = await installButtons.count();
  console.log(`Found ${count} install buttons`);
  if (count > 0) {
    await installButtons.first().click();
    await page.waitForTimeout(2000);
  }

  // This might trigger a restart notification
  await page.waitForTimeout(2000);

  console.log('Plugin installation initiated. Jellyfin will restart.');
  
  // Wait for Jellyfin to restart
  console.log('Waiting for Jellyfin restart...');
  await page.waitForTimeout(15000);

  // Try to navigate back and check if plugin is installed
  await page.goto('https://media.researchstack.info/web/#/dashboard/plugins', { waitUntil: 'networkidle' });
  await page.waitForTimeout(5000);
  
  console.log('Current URL:', page.url());
  console.log('=== DONE ===');
});
