import { test } from '@playwright/test';
test('Homarr complete setup', async ({ page }) => {
  test.setTimeout(120000);

  // Step 1: Load page
  await page.goto('http://100.88.57.96:30093/', { timeout: 10000, waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(3000);

  // Step 2: Click "Start update process"
  await page.evaluate(() => {
    document.querySelectorAll('button').forEach(b => {
      if (b.textContent?.includes('Start update process')) b.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });
  });
  await page.waitForTimeout(5000);

  // Step 3: Fill account form
  await page.locator('input[type="text"]').first().fill('admin');
  const passwordInputs = page.locator('input[type="password"]');
  await passwordInputs.nth(0).fill('homarr-admin');
  await passwordInputs.nth(1).fill('homarr-admin');
  await page.waitForTimeout(500);

  // Click Continue
  await page.locator('button:has-text("Continue"):visible').first().click({ force: true, noWaitAfter: true });
  await page.waitForTimeout(3000);
  console.log('Account created');

  // Step 4: Continue through remaining steps
  for (let i = 0; i < 15; i++) {
    const btn = page.locator('button:has-text("Continue"):visible, button:has-text("Finish"):visible').first();
    if (await btn.isVisible({ timeout: 3000 }).catch(() => false)) {
      await btn.click({ force: true, noWaitAfter: true });
      await page.waitForTimeout(2000);
      console.log(`Step ${i + 2}: ${page.url()}`);
    } else {
      console.log(`No more buttons at step ${i + 2}`);
      break;
    }
  }

  console.log('Final URL:', page.url());
  await page.screenshot({ path: '/tmp/homarr-complete.png' });
});
