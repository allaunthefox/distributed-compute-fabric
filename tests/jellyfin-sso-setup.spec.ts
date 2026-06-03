import { test } from '@playwright/test';
test('Jellyfin SSO-Auth plugin install + configure', async ({ page }) => {
  test.setTimeout(300000);
  const BASE = 'http://100.88.57.96:30091';

  // Step 1: Login to Jellyfin
  console.log('=== Logging in ===');
  await page.goto(`${BASE}/web/#/login.html`, { waitUntil: 'networkidle', timeout: 30000 });
  await page.waitForTimeout(3000);
  await page.locator('#txtUsername').fill('admin');
  await page.locator('#txtPassword').fill('jellyfin-admin');
  await page.locator('.button-submit:visible').first().click();
  await page.waitForTimeout(5000);
  console.log('Logged in:', page.url());

  // Step 2: Navigate to Plugins -> Repositories
  console.log('=== Adding SSO-Auth repository ===');
  await page.goto(`${BASE}/web/#/dashboard/plugins/repositories`, { waitUntil: 'networkidle', timeout: 30000 });
  await page.waitForTimeout(5000);

  // Click "+" to add repository
  const addBtn = page.locator('button:has-text("+"):visible, .button-add:visible, button[title*="Add"]:visible').first();
  if (await addBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
    await addBtn.click();
    await page.waitForTimeout(2000);
  }

  // Fill repository form
  const inputs = page.locator('input:visible');
  const inputCount = await inputs.count();
  console.log(`Found ${inputCount} visible inputs`);
  if (inputCount >= 2) {
    await inputs.nth(0).fill('SSO-Auth');
    await inputs.nth(1).fill('https://raw.githubusercontent.com/9p4/jellyfin-plugin-sso/manifest-release/manifest.json');
    console.log('Repository form filled');
  }
  
  // Click Save
  const saveBtn = page.locator('button:has-text("Save"):visible, .button-submit:visible').first();
  if (await saveBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
    await saveBtn.click();
    await page.waitForTimeout(3000);
    console.log('Repository saved');
  }

  // Step 3: Go to Catalog and install SSO-Auth
  console.log('=== Installing SSO-Auth plugin ===');
  await page.goto(`${BASE}/web/#/dashboard/plugins/catalog`, { waitUntil: 'networkidle', timeout: 30000 });
  await page.waitForTimeout(5000);

  // Search for SSO
  const search = page.locator('input[type="text"]:visible').first();
  if (await search.isVisible({ timeout: 3000 }).catch(() => false)) {
    await search.fill('SSO');
    await page.waitForTimeout(3000);
  }

  // Look for install button
  const installBtn = page.locator('button:has-text("Install"):visible').first();
  if (await installBtn.isVisible({ timeout: 5000 }).catch(() => false)) {
    await installBtn.click();
    await page.waitForTimeout(2000);
    console.log('Install clicked');
  }

  // Handle restart dialog
  const confirmBtn = page.locator('button:has-text("Yes"):visible, button:has-text("Restart"):visible').first();
  if (await confirmBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
    await confirmBtn.click();
    console.log('Restart confirmed');
  }

  // Wait for Jellyfin to restart
  console.log('Waiting for restart...');
  await page.waitForTimeout(30000);

  // Step 4: Configure SSO-Auth plugin
  console.log('=== Configuring SSO-Auth plugin ===');
  await page.goto(`${BASE}/web/#/login.html`, { waitUntil: 'networkidle', timeout: 30000 });
  await page.waitForTimeout(3000);
  if (await page.locator('#txtUsername').isVisible({ timeout: 3000 }).catch(() => false)) {
    await page.locator('#txtUsername').fill('admin');
    await page.locator('#txtPassword').fill('jellyfin-admin');
    await page.locator('.button-submit:visible').first().click();
    await page.waitForTimeout(5000);
  }

  // Go to SSO-Auth plugin settings
  await page.goto(`${BASE}/web/#/dashboard/plugins`, { waitUntil: 'networkidle', timeout: 30000 });
  await page.waitForTimeout(5000);

  // Find SSO-Auth plugin and click it
  const ssoLink = page.locator('a:has-text("SSO Authentication"):visible, .card:has-text("SSO Authentication"):visible').first();
  if (await ssoLink.isVisible({ timeout: 5000 }).catch(() => false)) {
    // Click the settings button (three dots)
    const settingsBtn = page.locator('button[title*="Settings"]:visible, button[aria-label*="Settings"]:visible').first();
    if (await settingsBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
      await settingsBtn.click();
      await page.waitForTimeout(2000);
    } else {
      await ssoLink.click();
      await page.waitForTimeout(3000);
    }
  }

  // Fill OIDC configuration
  const configInputs = page.locator('input:visible, textarea:visible');
  const configCount = await configInputs.count();
  console.log(`Found ${configCount} config inputs`);

  // Fill fields by label or placeholder
  const allFields = [
    { label: 'Name of OID Provider', value: 'authentik' },
    { label: 'OID Endpoint', value: 'https://auth.researchstack.info/application/o/jellyfin/.well-known/openid-configuration' },
    { label: 'OpenID Client ID', value: 'sso-jellyfin' },
    { label: 'OID Secret', value: 'fc96e87934f544bef43e5466c929baa73b681c4e5d0aa9fc5cafe6e6a36e2e49' },
  ];

  for (const field of allFields) {
    const labelEl = page.locator(`label:has-text("${field.label}"):visible`);
    if (await labelEl.isVisible({ timeout: 2000 }).catch(() => false)) {
      const forAttr = await labelEl.getAttribute('for');
      if (forAttr) {
        await page.locator(`#${forAttr}`).fill(field.value);
      } else {
        const input = labelEl.locator('..').locator('input, textarea').first();
        if (await input.isVisible({ timeout: 1000 }).catch(() => false)) {
          await input.fill(field.value);
        }
      }
    }
  }

  // Check Enable checkbox
  const enableCheck = page.locator('input[type="checkbox"]:visible').first();
  if (await enableCheck.isVisible({ timeout: 2000 }).catch(() => false)) {
    await enableCheck.check();
  }

  // Check Enable Authorization by Plugin
  const authCheck = page.locator('input[type="checkbox"]:visible').nth(1);
  if (await authCheck.isVisible({ timeout: 2000 }).catch(() => false)) {
    await authCheck.check();
  }

  // Save
  const saveConfigBtn = page.locator('button:has-text("Save"):visible').first();
  if (await saveConfigBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
    await saveConfigBtn.click();
    await page.waitForTimeout(3000);
    console.log('SSO config saved');
  }

  await page.screenshot({ path: '/tmp/jf-sso-done.png', fullPage: true });
  console.log('=== Jellyfin SSO setup complete ===');
});
