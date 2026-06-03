import { test } from '@playwright/test';
test('Homarr wizard', async ({ page }) => {
  test.setTimeout(60000);
  await page.goto('http://100.88.57.96:30093/', { timeout: 10000, waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(4000);

  // Step 1: Start update
  await page.evaluate(() => {
    document.querySelectorAll('button').forEach(b => {
      if (b.textContent?.trim() === 'Start update process') b.click();
    });
  });
  await page.waitForTimeout(5000);

  // Step 2: Fill account form with valid password
  await page.locator('input[type="text"]').first().fill('admin');
  const pwInputs = page.locator('input[type="password"]');
  await pwInputs.nth(0).fill('Admin123!');
  await pwInputs.nth(1).fill('Admin123!');
  await page.waitForTimeout(1000);

  // Click Continue
  await page.locator('button:has-text("Continue"):visible').first().click({ force: true, noWaitAfter: true });
  await page.waitForTimeout(5000);
  console.log('Step 1 done, URL:', page.url());

  // Keep clicking Continue/Finish through remaining steps
  for (let step = 2; step <= 10; step++) {
    const btn = page.locator('button:has-text("Continue"):visible, button:has-text("Finish"):visible').first();
    if (await btn.isVisible({ timeout: 3000 }).catch(() => false)) {
      await btn.click({ force: true, noWaitAfter: true });
      await page.waitForTimeout(3000);
      console.log(`Step ${step}: ${page.url()}`);
    } else {
      console.log(`No more buttons at step ${step}`);
      break;
    }
  }

  await page.screenshot({ path: '/tmp/homarr-final.png' });
  console.log('Final URL:', page.url());

  // Check if we got redirected away from onboard
  if (!page.url().includes('onboard')) {
    console.log('SUCCESS: Onboard completed!');
  }
});
