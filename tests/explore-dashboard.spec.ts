import { test, expect } from '@playwright/test';

test('Explore Jellyfin Dashboard and find Plugins', async ({ browser }) => {
  const context = await browser.newContext({ storageState: 'auth-state.json' });
  const page = await context.newPage();

  console.log('Navigating to Jellyfin Home...');
  await page.goto('https://media.researchstack.info/');
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

  console.log('Navigating directly to Dashboard...');
  await page.goto('https://media.researchstack.info/web/#/dashboard');
  await page.waitForLoadState('networkidle');
  await page.waitForTimeout(5000);
  await page.screenshot({ path: 'jellyfin-dashboard-direct.png' });

  // Get all links on this page
  const links = await page.evaluate(() => {
    return Array.from(document.querySelectorAll('a')).map(a => ({
      text: a.innerText.trim(),
      href: a.getAttribute('href')
    }));
  });
  console.log('Links on Dashboard page:', links);

  // Let's search for "Plugins" link in the list or click on it
  const pluginsLinkInfo = links.find(l => l.text.includes('Plugins') || (l.href && l.href.includes('plugins')));
  if (pluginsLinkInfo) {
    console.log('Found Plugins link info:', pluginsLinkInfo);
    // Click the actual element
    await page.locator(`a[href="${pluginsLinkInfo.href}"], a:has-text("Plugins")`).first().click();
    await page.waitForTimeout(5000);
    await page.screenshot({ path: 'jellyfin-dashboard-plugins-clicked.png' });
    
    // Check if we are on the plugins page and print details
    const currentUrl = page.url();
    console.log('Plugins Page URL after click:', currentUrl);
    const textContent = await page.evaluate(() => document.body.innerText);
    console.log('Plugins Page text:', textContent.slice(0, 1000));
  } else {
    console.log('Could not find Plugins link on dashboard page');
  }

  await context.close();
});
