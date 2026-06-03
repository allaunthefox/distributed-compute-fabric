import { test } from '@playwright/test';
test('Jellyfin full setup via direct port', async ({ page }) => {
  test.setTimeout(300000);
  const BASE = 'http://100.88.57.96:30091';

  // Step 1: Complete Jellyfin Setup Wizard
  console.log('=== Wizard Step 1: Language ===');
  await page.goto(`${BASE}/web/#/wizard/start.html`, { waitUntil: 'networkidle', timeout: 30000 });
  await page.waitForTimeout(3000);
  await page.locator('button.button-submit:visible').first().click();
  await page.waitForTimeout(3000);

  console.log('=== Wizard Step 2: Create Admin ===');
  await page.locator('#txtUsername').fill('admin');
  await page.locator('#txtManualPassword').fill('jellyfin-admin');
  await page.locator('#txtPasswordConfirm').fill('jellyfin-admin');
  await page.locator('button.button-submit:visible').first().click();
  await page.waitForTimeout(3000);

  console.log('=== Wizard Step 3: Libraries ===');
  await page.locator('button.button-submit:visible').first().click();
  await page.waitForTimeout(3000);

  console.log('=== Wizard Step 4: Metadata ===');
  await page.locator('button.button-submit:visible').first().click();
  await page.waitForTimeout(3000);

  console.log('=== Wizard Step 5: Remote Access ===');
  await page.locator('button.button-submit:visible').first().click();
  await page.waitForTimeout(3000);

  console.log('=== Wizard Step 6: Finish ===');
  await page.locator('button.button-submit:visible').first().click();
  await page.waitForTimeout(5000);
  console.log('Wizard complete:', page.url());

  // Step 2: Install OIDC Plugin
  console.log('=== Installing OIDC Plugin ===');
  await page.goto(`${BASE}/web/#/dashboard/plugins/catalog`, { waitUntil: 'networkidle', timeout: 30000 });
  await page.waitForTimeout(5000);

  // Search for OIDC
  const searchInput = page.locator('input[type="text"]').first();
  if (await searchInput.isVisible()) {
    await searchInput.fill('OIDC');
    await page.waitForTimeout(3000);
  }

  // Look for install buttons
  const installBtns = page.locator('button:has-text("Install"):visible');
  const count = await installBtns.count();
  console.log(`Found ${count} install buttons`);
  if (count > 0) {
    await installBtns.first().click();
    await page.waitForTimeout(2000);
    
    // Confirm restart dialog if any
    const confirmBtn = page.locator('button:has-text("Yes"):visible, button:has-text("Restart"):visible, button:has-text("OK"):visible').first();
    if (await confirmBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
      await confirmBtn.click();
    }
    console.log('Plugin install initiated');
  }

  // Wait for Jellyfin to restart
  console.log('Waiting for restart...');
  await page.waitForTimeout(30000);

  // Step 3: Navigate to OIDC plugin settings
  console.log('=== Configuring OIDC Plugin ===');
  await page.goto(`${BASE}/web/#/dashboard/plugins`, { waitUntil: 'networkidle', timeout: 30000 });
  await page.waitForTimeout(5000);
  
  // Find the OIDC plugin in the list
  const oidcLink = page.locator('a:has-text("OIDC"):visible, div.card:has-text("OIDC"):visible').first();
  if (await oidcLink.isVisible({ timeout: 5000 }).catch(() => false)) {
    if ((await oidcLink.evaluate(el => el.tagName)) === 'A') {
      await oidcLink.click();
    } else {
      await oidcLink.locator('a').first().click();
    }
    await page.waitForTimeout(3000);
    
    // Fill OIDC config
    const issuerInput = page.locator('input:visible').first();
    if (await issuerInput.isVisible({ timeout: 3000 }).catch(() => false)) {
      await issuerInput.fill('https://auth.researchstack.info');
      await page.waitForTimeout(500);
    }
    
    // Fill client ID
    const clientIdInput = page.locator('input:visible').nth(1);
    if (await clientIdInput.isVisible({ timeout: 2000 }).catch(() => false)) {
      await clientIdInput.fill('sso-jellyfin');
    }
    
    // Fill client secret
    const secretInput = page.locator('input:visible').nth(2);
    if (await secretInput.isVisible({ timeout: 2000 }).catch(() => false)) {
      await secretInput.fill('fc96e87934f544bef43e5466c929baa73b681c4e5d0aa9fc5cafe6e6a36e2e49');
    }
    
    // Fill callback URL
    const callbackInput = page.locator('input:visible').nth(3);
    if (await callbackInput.isVisible({ timeout: 2000 }).catch(() => false)) {
      await callbackInput.fill('https://media.researchstack.info/sso/OID/redirect');
    }
    
    // Hit Save
    const saveBtn = page.locator('button:has-text("Save"):visible').first();
    if (await saveBtn.isVisible({ timeout: 2000 }).catch(() => false)) {
      await saveBtn.click();
      await page.waitForTimeout(2000);
      console.log('OIDC config saved');
    }
  }

  await page.screenshot({ path: '/tmp/jf-oidc-done.png', fullPage: true });
  console.log('=== Jellyfin setup complete ===');
});
