import { test } from '@playwright/test';
test('Debug Jellyfin wizard', async ({ page }) => {
  test.setTimeout(60000);
  await page.goto('https://media.researchstack.info/web/#/wizard/start.html', { waitUntil: 'networkidle', timeout: 30000 });
  await page.waitForTimeout(5000);
  await page.screenshot({ path: '/tmp/jf-wizard-debug.png', fullPage: true });
  
  // Dump all buttons
  const buttons = page.locator('button');
  const count = await buttons.count();
  console.log(`Found ${count} buttons`);
  for (let i = 0; i < count; i++) {
    const text = await buttons.nth(i).textContent();
    const visible = await buttons.nth(i).isVisible();
    console.log(`  Button ${i}: text="${text?.trim()}" visible=${visible}`);
  }
  
  // Dump the page title
  console.log('Title:', await page.title());
  console.log('URL:', page.url());
});
