import { test } from '@playwright/test';
test('Homarr full onboard', async ({ page }) => {
  test.setTimeout(120000);
  await page.goto('http://100.88.57.96:30093/', { timeout: 10000, waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(3000);

  // Step 1: Click start
  await page.evaluate(() => {
    document.querySelectorAll('button').forEach(b => {
      if (b.textContent?.includes('Start update process')) b.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });
  });
  await page.waitForTimeout(3000);
  console.log('Step 1 - Start clicked');

  // Check what inputs are available
  const inputs = await page.locator('input').count();
  console.log(`Found ${inputs} inputs`);

  if (inputs > 0) {
    await page.locator('input').nth(0).fill('admin');
    if (inputs > 1) await page.locator('input').nth(1).fill('admin@researchstack.info');
    if (inputs > 2) await page.locator('input').nth(2).fill('homarr-admin');
    console.log('Form filled');
  }

  // Click Continue
  const continueBtn = page.locator('button:has-text("Continue"):visible').first();
  if (await continueBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
    await continueBtn.click({ force: true, noWaitAfter: true });
    await page.waitForTimeout(3000);
    console.log('Continue clicked');
  }

  // Continue clicking "Continue" or "Finish" through remaining steps
  for (let i = 0; i < 10; i++) {
    const btn = page.locator('button:has-text("Continue"):visible, button:has-text("Finish"):visible, button:has-text("Next"):visible').first();
    if (await btn.isVisible({ timeout: 3000 }).catch(() => false)) {
      await btn.click({ force: true, noWaitAfter: true });
      await page.waitForTimeout(3000);
      console.log(`Step ${i+2} clicked, URL: ${page.url()}`);
    } else {
      break;
    }
  }

  console.log('Final URL:', page.url());
  await page.screenshot({ path: '/tmp/homarr-complete.png' });
});
