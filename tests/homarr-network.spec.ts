import { test } from '@playwright/test';
test('homarr network', async ({ page }) => {
  test.setTimeout(20000);
  
  // Listen for API requests
  const requests: string[] = [];
  page.on('request', req => {
    if (req.url().includes('/api')) requests.push(req.url() + ' ' + req.method());
  });
  
  await page.goto('http://100.88.57.96:30093/', { timeout: 10000, waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(3000);
  
  const btn = page.locator('button:has-text("Start update process"):visible').first();
  await btn.click({ force: true, noWaitAfter: true });
  await page.waitForTimeout(5000);
  
  console.log('Requests:', requests.join('\n  '));
  console.log('URL:', page.url());
});
