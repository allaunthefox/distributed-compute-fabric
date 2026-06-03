import { test } from '@playwright/test';
test('complete init', async ({ page }) => {
  test.setTimeout(60000);
  await page.goto('http://100.88.57.96:30108/', { timeout: 10000, waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(3000);
  
  // Click "Start from scratch"
  await page.locator('button:has-text("Start from scratch"):visible').first().click({ force: true, noWaitAfter: true });
  await page.waitForTimeout(3000);
  console.log('Step 1 done:', page.url());
  
  // Create admin account
  const inputs = page.locator('input');
  const count = await inputs.count();
  if (count >= 2) {
    await inputs.nth(0).fill('allaun');
    await inputs.nth(1).fill('TYW82QNB!k0y!pXc');
    console.log('Form filled');
  }
  
  // Submit
  const submitBtn = page.locator('button[type="submit"]:visible, button:has-text("Continue"):visible').first();
  if (await submitBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
    await submitBtn.click({ force: true, noWaitAfter: true });
    await page.waitForTimeout(3000);
    console.log('Submitted');
  }
  
  // Continue through remaining steps
  for (let i = 0; i < 10; i++) {
    const btn = page.locator('button[type="submit"]:visible, button:has-text("Continue"):visible, button:has-text("Finish"):visible').first();
    if (await btn.isVisible({ timeout: 3000 }).catch(() => false)) {
      await btn.click({ force: true, noWaitAfter: true });
      await page.waitForTimeout(3000);
      console.log(`Step ${i+2}: ${page.url()}`);
    } else break;
  }
  
  console.log('Final:', page.url());
  await page.screenshot({ path: '/tmp/homarr-init-final.png' });
});
