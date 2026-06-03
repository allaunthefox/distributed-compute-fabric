import { test, expect } from '@playwright/test';

test('Explore Authentik Sidebar and find Outposts', async ({ browser }) => {
  const context = await browser.newContext();
  const page = await context.newPage();

  console.log('Navigating to Authentik admin home...');
  await page.goto('https://auth.researchstack.info/if/admin/#/home');
  await page.waitForLoadState('networkidle');
  await page.waitForTimeout(4000);

  // Login
  const loginInput = page.locator('input[placeholder*="Username"], input[name="uid"], input[type="text"]').first();
  if (await loginInput.isVisible()) {
    console.log('Logging in...');
    await loginInput.fill('akadmin');
    const continueBtn = page.locator('button:has-text("Log in"), button:has-text("Continue"), input[type="submit"]').first();
    await continueBtn.click();
    await page.waitForTimeout(2000);
    const passwordInput = page.locator('input[name="password"], input[type="password"]').first();
    await passwordInput.fill('authentik');
    await continueBtn.click();
    await page.waitForTimeout(6000);
  }

  await page.screenshot({ path: 'authentik-admin-home.png' });

  // Click on "Applications" on the sidebar
  // Let's locate the navigation element. Authentik admin panel uses web components, so let's pierce the shadow DOM.
  // We can click the text "Applications" or find the navigation item.
  console.log('Clicking Applications sidebar group...');
  const appsGroup = page.locator('span:has-text("Applications"), a:has-text("Applications"), div:has-text("Applications")').first();
  await appsGroup.click();
  await page.waitForTimeout(2000);
  await page.screenshot({ path: 'authentik-sidebar-expanded.png' });

  // Let's print out all links on the page (including shadow DOM if possible)
  const links = await page.evaluate(() => {
    // Helper to recursively find elements including in shadow roots
    function getElements(root: Element | ShadowRoot): string[] {
      const results: string[] = [];
      const anchors = root.querySelectorAll('a');
      anchors.forEach(a => {
        results.push(`${a.textContent?.trim()} -> ${a.getAttribute('href')}`);
      });
      const all = root.querySelectorAll('*');
      all.forEach(el => {
        if (el.shadowRoot) {
          results.push(...getElements(el.shadowRoot));
        }
      });
      return results;
    }
    return getElements(document.body);
  });

  console.log('All links found:', links);

  // Let's find one that looks like outposts and navigate to it
  const outpostLink = links.find(l => l.toLowerCase().includes('outpost'));
  console.log('Outpost link found:', outpostLink);

  await context.close();
});
