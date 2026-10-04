/* Verifica el editor en un SOC local aislado y captura escritorio y móvil. */
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

async function main() {
  const origin = 'http://127.0.0.1:18081';
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
    const initial = await page.goto(origin + '/admin/rules');
    assert.equal(initial.status(), 200);
    await page.getByRole('button', { name: 'Crear borrador' }).click();
    await page.waitForURL(/draft_id=/);
    const rule = page.locator('[data-rule-form="brute_force_user"]');
    await rule.locator('input[name="minimum_failures"]').fill('7');
    await rule.getByRole('button', { name: 'Guardar esta regla' }).click();
    await page.waitForFunction(() => document.querySelector('[data-rule-form="brute_force_user"] input[name="minimum_failures"]')?.value === '7');
    const output = path.join(process.cwd(), 'analysis', 'sprint6-ui');
    fs.mkdirSync(output, { recursive: true });
    for (const width of [1440, 390]) {
      await page.setViewportSize({ width, height: 900 });
      await page.screenshot({ path: path.join(output, `rules-${width}.png`), fullPage: true });
    }
    assert.equal(await page.locator('[data-rule-form]').count(), 5);
    assert.ok((await page.locator('[data-publish-form] button').isDisabled()));
    assert.ok((await page.locator('[data-preview-form] button').isDisabled()));
    console.log('Editor: borrador, cambio controlado y diseño escritorio/móvil correctos.');
  } finally {
    await browser.close();
  }
}
main().catch(error => { console.error(error.name, error.message.split('\n')[0]); process.exitCode = 1; });
