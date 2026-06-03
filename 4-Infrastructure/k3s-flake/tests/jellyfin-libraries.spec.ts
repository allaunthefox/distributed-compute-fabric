import { test } from '@playwright/test';
test('Jellyfin add media libraries', async ({ page }) => {
  test.setTimeout(120000);
  const BASE = 'http://100.88.57.96:30091';

  // Login
  await page.goto(`${BASE}/web/`, { timeout: 10000 });
  await page.waitForTimeout(2000);
  await page.locator('#txtUsername').fill('admin');
  await page.locator('#txtPassword').fill('jellyfin-admin');
  await page.locator('.button-submit').first().click();
  await page.waitForTimeout(3000);

  // Navigate to library setup using hash
  await page.evaluate(() => { window.location.hash = '#/dashboard/library'; });
  await page.waitForTimeout(3000);

  // Click "Add Media Library"
  const addBtn = page.locator('button:has-text("Add Media Library"):visible, button:has-text("+"):visible').first();
  if (await addBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
    await addBtn.click();
    await page.waitForTimeout(2000);
  }

  // Define libraries to add
  const libraries = [
    { name: 'Movies', path: '/media/movies', type: 'Movies' },
    { name: 'TV Shows', path: '/media/tv', type: 'TV Shows' },
    { name: 'Music', path: '/media/music', type: 'Music' },
  ];

  for (const lib of libraries) {
    console.log(`Adding library: ${lib.name}`);

    // Select content type
    const typeSelect = page.locator('select:visible').first();
    if (await typeSelect.isVisible({ timeout: 2000 }).catch(() => false)) {
      await typeSelect.selectOption(lib.type);
      await page.waitForTimeout(500);
    }

    // Fill display name
    const nameInput = page.locator('input:visible').first();
    if (await nameInput.isVisible({ timeout: 2000 }).catch(() => false)) {
      await nameInput.fill(lib.name);
    }

    // Add folder path
    const pathInput = page.locator('input:visible').nth(1);
    if (await pathInput.isVisible({ timeout: 2000 }).catch(() => false)) {
      await pathInput.fill(lib.path);
      await page.waitForTimeout(500);
    }

    // Click OK
    const okBtn = page.locator('button:has-text("OK"):visible').first();
    if (await okBtn.isVisible({ timeout: 2000 }).catch(() => false)) {
      await okBtn.click();
      await page.waitForTimeout(3000);
      console.log(`  ${lib.name} added`);
    }

    // Click "Add Media Library" again for next one
    const idx = libraries.indexOf(lib);
    if (idx < libraries.length - 1) {
      const nextBtn = page.locator('button:has-text("Add Media Library"):visible').first();
      if (await nextBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
        await nextBtn.click();
        await page.waitForTimeout(2000);
      }
    }
  }

  await page.screenshot({ path: '/tmp/jf-libraries-done.png', fullPage: true });
  console.log('All libraries added');
});
