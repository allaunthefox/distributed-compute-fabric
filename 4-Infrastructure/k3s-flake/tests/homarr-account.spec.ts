import { test } from '@playwright/test';
test('homarr account form', async ({ page }) => {
  test.setTimeout(20000);
  await page.goto('http://100.88.57.96:30093/', { timeout: 10000, waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(3000);
  
  // Navigate to account creation
  await page.evaluate(() => {
    document.querySelectorAll('button').forEach(b => {
      if (b.textContent?.includes('Start update process')) b.click();
    });
  });
  await page.waitForTimeout(4000);
  
  // Dump all inputs and their labels
  const inputs = await page.locator('input, select, textarea').all();
  console.log(`Found ${inputs.length} inputs`);
  for (const inp of inputs) {
    const id = await inp.getAttribute('id');
    const name = await inp.getAttribute('name');
    const placeholder = await inp.getAttribute('placeholder');
    const type = await inp.getAttribute('type');
    const label = await page.locator(`label[for="${id}"]`).textContent().catch(() => '');
    console.log(`  id=${id} type=${type} name=${name} placeholder=${placeholder} label=${label}`);
  }
  
  // Also check what elements with role and text
  const texts = await page.locator('h1,h2,h3,p,label,span').all();
  for (const el of texts) {
    const text = await el.textContent();
    if (text?.trim() && text.trim().length > 2 && text.trim().length < 100) {
      console.log(`Text: "${text.trim()}"`);
    }
  }
});
