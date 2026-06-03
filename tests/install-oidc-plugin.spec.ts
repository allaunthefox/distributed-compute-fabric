import { test, expect } from '@playwright/test';

test('Install OIDC Plugin in Jellyfin', async ({ browser }) => {
  const context = await browser.newContext({ storageState: 'auth-state.json' });
  const page = await context.newPage();

  console.log('Navigating to Jellyfin Plugins...');
  await page.goto('https://media.researchstack.info/web/#/dashboard/plugins');
  await page.waitForLoadState('networkidle');
  await page.waitForTimeout(4000);

  // Login if needed
  const usernameInput = page.locator('input[type="text"], input#txtManualName');
  const passwordInput = page.locator('input[type="password"], input#txtManualPassword');

  if (await usernameInput.isVisible()) {
    console.log('Logging in...');
    await usernameInput.fill('admin');
    await passwordInput.fill('RY03KhsFez73K5va2uUb');
    await page.locator('button[type="submit"], button.button-submit').first().click();
    await page.waitForTimeout(6000);
  }

  // Double check we are on plugins page
  if (!page.url().includes('#/dashboard/plugins')) {
    await page.goto('https://media.researchstack.info/web/#/dashboard/plugins');
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(4000);
  }

  console.log('Clicking Available tab...');
  // Find the Available tab pill
  const availableTab = page.locator('a:has-text("Available"), button:has-text("Available"), div:has-text("Available"), span:has-text("Available")').first();
  await availableTab.click({ force: true });
  await page.waitForTimeout(4000);
  await page.screenshot({ path: 'jellyfin-plugins-available.png' });

  // Type in the search box to find OpenID Connect
  console.log('Searching for OpenID Connect in catalog...');
  const searchInput = page.locator('input[type="search"], input[placeholder*="Search"]').first();
  if (await searchInput.isVisible()) {
    await searchInput.fill('OpenID Connect');
    await page.waitForTimeout(3000);
    await page.screenshot({ path: 'jellyfin-plugins-search-results.png' });
  }

  // Click on the OpenID Connect card
  console.log('Clicking OpenID Connect card...');
  const oidcCard = page.locator('a:has-text("OpenID Connect"), .card:has-text("OpenID Connect"), .cardHeader:has-text("OpenID Connect")').first();
  await oidcCard.click({ force: true });
  await page.waitForTimeout(4000);
  await page.screenshot({ path: 'jellyfin-plugin-details.png' });

  // Click Install
  console.log('Clicking Install button...');
  const installBtn = page.locator('button:has-text("Install"), button.button-submit').first();
  await installBtn.click({ force: true });
  await page.waitForTimeout(4000);
  await page.screenshot({ path: 'jellyfin-plugin-install-clicked.png' });

  // Handle OK button in modal dialog if any
  const okBtn = page.locator('button:has-text("OK"), button:has-text("Ok"), button.button-submit').first();
  if (await okBtn.isVisible()) {
    console.log('Clicking OK on dialog...');
    await okBtn.click({ force: true });
    await page.waitForTimeout(3000);
    await page.screenshot({ path: 'jellyfin-plugin-install-confirmed.png' });
  }

  console.log('OIDC Plugin installation completed.');
  await context.close();
});
