import { test, expect } from '@playwright/test';

test('Install OIDC Plugin in Jellyfin', async ({ browser }) => {
  const context = await browser.newContext({ storageState: 'auth-state.json' });
  const page = await context.newPage();

  console.log('Navigating to Jellyfin...');
  await page.goto('https://media.researchstack.info/');
  await page.waitForLoadState('networkidle');

  // Wait for login input or home page element to load
  console.log('Checking login state...');
  const loginInput = page.locator('input#txtManualName, input[type="text"]').first();
  const homeElement = page.locator('.skinHeader, #reactRoot').first();

  // Wait up to 10 seconds for either to appear
  try {
    await Promise.race([
      loginInput.waitFor({ state: 'visible', timeout: 8000 }),
      homeElement.waitFor({ state: 'visible', timeout: 8000 })
    ]);
  } catch (err) {
    console.log('Wait timeout, continuing anyway...');
  }

  if (await loginInput.isVisible()) {
    console.log('Login form visible. Logging in manually...');
    await loginInput.fill('admin');
    const passwordInput = page.locator('input#txtManualPassword, input[type="password"]').first();
    await passwordInput.fill('RY03KhsFez73K5va2uUb');
    await page.locator('button[type="submit"], button.button-submit').first().click();
    await page.waitForTimeout(6000);
  }

  console.log('Ensuring we are logged in. URL:', page.url());
  await page.screenshot({ path: 'jellyfin-logged-in-state.png' });

  // Navigate directly to Plugins page
  console.log('Navigating directly to Plugins page...');
  await page.goto('https://media.researchstack.info/web/#/dashboard/plugins');
  await page.waitForLoadState('networkidle');
  await page.waitForTimeout(5000);
  
  console.log('Plugins URL:', page.url());
  await page.screenshot({ path: 'jellyfin-plugins-loaded.png' });

  // Click the "Available" tab using the filtered locator
  console.log('Clicking Available tab...');
  const availableTab = page.locator('button, a, .tabButton, .emby-button, [role="tab"]').filter({ hasText: 'Available' }).first();
  await availableTab.waitFor({ state: 'visible', timeout: 5000 });
  await availableTab.click({ force: true });
  await page.waitForTimeout(4000);
  await page.screenshot({ path: 'jellyfin-plugins-available.png' });

  // Search for OpenID Connect in catalog
  console.log('Searching for OpenID Connect in catalog...');
  const searchInput = page.locator('input[type="search"], input[placeholder*="Search"]').first();
  if (await searchInput.isVisible()) {
    await searchInput.fill('OpenID Connect');
    await page.waitForTimeout(4000);
    await page.screenshot({ path: 'jellyfin-plugins-search-results.png' });
  }

  // Click on the OpenID Connect card
  console.log('Clicking OpenID Connect card...');
  const oidcCard = page.locator('a, .card, .cardHeader').filter({ hasText: 'OpenID Connect' }).first();
  await oidcCard.click({ force: true });
  await page.waitForTimeout(4000);
  await page.screenshot({ path: 'jellyfin-plugin-details.png' });

  // Click Install
  console.log('Clicking Install button...');
  const installBtn = page.locator('button, a, .emby-button').filter({ hasText: 'Install' }).first();
  await installBtn.click({ force: true });
  await page.waitForTimeout(4000);
  await page.screenshot({ path: 'jellyfin-plugin-install-clicked.png' });

  // Handle OK button in modal dialog if any
  const okBtn = page.locator('button, .emby-button').filter({ hasText: 'OK' }).first();
  if (await okBtn.isVisible()) {
    console.log('Clicking OK on dialog...');
    await okBtn.click({ force: true });
    await page.waitForTimeout(3000);
    await page.screenshot({ path: 'jellyfin-plugin-install-confirmed.png' });
  }

  console.log('OIDC Plugin installation completed.');
  await context.close();
});
