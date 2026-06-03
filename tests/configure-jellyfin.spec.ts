import { test, expect } from '@playwright/test';

test('Log in to Jellyfin and configure OIDC plugin', async ({ browser }) => {
  const context = await browser.newContext({ storageState: 'auth-state.json' });
  const page = await context.newPage();

  console.log('Navigating to Jellyfin...');
  await page.goto('https://media.researchstack.info/');
  await page.waitForLoadState('networkidle');
  await page.waitForTimeout(4000);

  console.log('Current URL:', page.url());

  // Fill Jellyfin login details
  const usernameInput = page.locator('input[type="text"], input#txtManualName');
  const passwordInput = page.locator('input[type="password"], input#txtManualPassword');

  if (await usernameInput.isVisible()) {
    console.log('Logging into Jellyfin manually...');
    await usernameInput.fill('admin');
    await passwordInput.fill('RY03KhsFez73K5va2uUb');
    await page.locator('button[type="submit"], button.button-submit').first().click();
    await page.waitForTimeout(6000);
  }

  console.log('Logged in. URL:', page.url());
  await page.screenshot({ path: 'jellyfin-home.png' });

  // Navigate directly to Plugins page
  console.log('Navigating directly to Plugins page...');
  await page.goto('https://media.researchstack.info/web/#/plugins.html');
  await page.waitForLoadState('networkidle');
  await page.waitForTimeout(5000);
  console.log('Plugins URL:', page.url());
  await page.screenshot({ path: 'jellyfin-plugins.png' });

  const textContent = await page.evaluate(() => document.body.innerText);
  console.log('Plugins page text:', textContent.slice(0, 1000));

  if (textContent.includes('OpenID Connect')) {
    console.log('OIDC Plugin is already installed!');
  } else {
    console.log('OIDC Plugin not found in installed list. Navigating to Catalog...');
    // Click on Catalog tab
    const catalogTab = page.locator('button:has-text("Catalog"), a:has-text("Catalog"), [role="tab"]:has-text("Catalog")').first();
    await catalogTab.click();
    await page.waitForTimeout(5000);
    await page.screenshot({ path: 'jellyfin-catalog.png' });

    // Search for OIDC or look at the list
    console.log('Searching for OpenID Connect in catalog...');
    const oidcLink = page.locator('a:has-text("OpenID Connect"), [role="button"]:has-text("OpenID Connect")').first();
    if (await oidcLink.isVisible()) {
      await oidcLink.click();
      await page.waitForTimeout(4000);
      await page.screenshot({ path: 'jellyfin-plugin-details.png' });

      // Click Install
      const installBtn = page.locator('button:has-text("Install"), button.button-submit').first();
      await installBtn.click();
      await page.waitForTimeout(4000);

      // Handle OK button in modal dialog if any
      const okBtn = page.locator('button:has-text("OK")').first();
      if (await okBtn.isVisible()) {
        await okBtn.click();
        await page.waitForTimeout(2000);
      }
      console.log('OIDC Plugin installation triggered. Need to restart pod!');
      
      // Let's exit the test and let the runner restart the pod
      await context.close();
      return;
    } else {
      console.log('Could not find OpenID Connect in catalog.');
      await context.close();
      throw new Error('OIDC Plugin not found in catalog');
    }
  }

  // If we reach here, OIDC plugin is installed. Let's configure it.
  console.log('Navigating to OIDC configuration page...');
  // Click on "OpenID Connect" plugin row/link in the installed list
  const oidcConfigLink = page.locator('a:has-text("OpenID Connect"), [role="button"]:has-text("OpenID Connect")').first();
  await oidcConfigLink.click();
  await page.waitForTimeout(5000);
  console.log('OIDC Configuration URL:', page.url());
  await page.screenshot({ path: 'jellyfin-oidc-config-initial.png' });

  // In the OpenID Connect settings form, fill in values:
  // Enabled checkbox, Client ID, Client Secret, OIDC Authority
  // Let's inspect the input fields
  console.log('Filling OIDC config fields...');
  
  // Let's log all input fields on the page to see what's there
  const inputs = await page.evaluate(() => {
    return Array.from(document.querySelectorAll('input, select, textarea')).map(el => ({
      id: el.id,
      name: el.getAttribute('name'),
      type: el.getAttribute('type'),
      value: (el as HTMLInputElement).value,
      label: el.labels?.[0]?.innerText || ''
    }));
  });
  console.log('Found form inputs:', inputs);

  // Enabled checkbox: usually has an id or label containing "Enable" or "Enabled"
  const enabledCheckbox = page.locator('input[type="checkbox"], input#chkEnableOpenId').first();
  const isChecked = await enabledCheckbox.isChecked();
  if (!isChecked) {
    await enabledCheckbox.click();
  }

  // OIDC Authority / Issuer
  const authorityInput = page.locator('input[label*="Authority"], input[id*="Authority"], input[name*="Authority"], input[placeholder*="Authority"]').first();
  if (await authorityInput.isVisible()) {
    await authorityInput.fill('https://auth.researchstack.info/application/o/jellyfin/');
  } else {
    // Try by index or other attributes
    const firstTextInput = page.locator('input[type="text"]').first();
    await firstTextInput.fill('https://auth.researchstack.info/application/o/jellyfin/');
  }

  // Client ID
  const clientIdInput = page.locator('input[label*="Client ID"], input[id*="ClientId"], input[name*="ClientId"]').first();
  if (await clientIdInput.isVisible()) {
    await clientIdInput.fill('sso-jellyfin');
  }

  // Client Secret
  const clientSecretInput = page.locator('input[label*="Secret"], input[id*="Secret"], input[name*="Secret"]').first();
  if (await clientSecretInput.isVisible()) {
    await clientSecretInput.fill('fc96e87934f544bef43e5466c929baa73b681c4e5d0aa9fc5cafe6e6a36e2e49');
  }

  await page.screenshot({ path: 'jellyfin-oidc-config-filled.png' });

  // Click Save
  const saveBtn = page.locator('button[type="submit"], button:has-text("Save"), button.button-submit').first();
  await saveBtn.click();
  await page.waitForTimeout(4000);
  await page.screenshot({ path: 'jellyfin-oidc-config-saved.png' });
  console.log('OIDC Configuration saved.');

  await context.close();
});
