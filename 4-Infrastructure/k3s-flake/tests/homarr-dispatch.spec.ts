import { test } from '@playwright/test';
test('homarr dispatch', async ({ page }) => {
  test.setTimeout(20000);
  await page.goto('http://100.88.57.96:30093/', { timeout: 10000, waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(4000);
  
  // Try clicking via JavaScript dispatch
  await page.evaluate(() => {
    const buttons = document.querySelectorAll('button');
    for (const btn of buttons) {
      if (btn.textContent?.includes('Start update process')) {
        btn.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }));
        return;
      }
    }
  });
  await page.waitForTimeout(5000);
  console.log('URL:', page.url());
  
  // Check for new buttons
  const btns = await page.locator('button').all();
  for (const b of btns) {
    const text = await b.textContent();
    if (await b.isVisible()) console.log(`  "${text?.trim().substring(0,40)}"`);
  }
});
