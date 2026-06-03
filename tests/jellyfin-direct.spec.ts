import { test } from '@playwright/test';
test('Jellyfin wizard + OIDC via direct port', async ({ page }) => {
  test.setTimeout(180000);
  
  // Bypass Caddy forward_auth by going to Jellyfin directly
  console.log('=== Connecting to Jellyfin directly ===');
  await page.goto('http://100.88.57.96:30091/web/#/wizard/start.html', { waitUntil: 'networkidle', timeout: 30000 });
  await page.waitForTimeout(5000);
  
  console.log('URL:', page.url());
  console.log('Title:', await page.title());
  
  // Check if we're on the wizard
  const pageContent = await page.textContent('body');
  if (pageContent?.includes('wizard') || pageContent?.includes('Welcome')) {
    console.log('Wizard page detected');
  }
  
  // Dump all visible elements
  const buttons = await page.locator('button, .button-submit, [class*="button"]').all();
  console.log(`Found ${buttons.length} clickable elements`);
  for (const btn of buttons) {
    if (await btn.isVisible()) {
      console.log(`  Visible: "${await btn.textContent()}" tag=${await btn.evaluate(el => el.tagName)} class=${await btn.evaluate(el => el.className)}`);
    }
  }
  
  await page.screenshot({ path: '/tmp/jf-wizard-start.png', fullPage: true });
  
  // Try clicking next/submit
  const nextBtn = page.locator('button:has-text("Next"), .button-submit:visible, button[type="submit"]').first();
  if (await nextBtn.isVisible({ timeout: 2000 }).catch(() => false)) {
    await nextBtn.click();
    await page.waitForTimeout(3000);
    await page.screenshot({ path: '/tmp/jf-wizard-step2.png', fullPage: true });
    console.log('Clicked Next. URL:', page.url());
  }
});
