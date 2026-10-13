/* Verifica el editor en un SOC local aislado y captura escritorio y móvil. */
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

async function main() {
  const origin = 'http://127.0.0.1:18081';
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, timezoneId: 'America/Guayaquil' });
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    const initial = await page.goto(origin + '/admin/rules');
    assert.equal(initial.status(), 200);
    await page.getByRole('button', { name: 'Crear borrador' }).click();
    await page.waitForURL(/draft_id=/);
    await page.waitForSelector('.rules-enhanced');
    const rule = page.locator('[data-rule-form="brute_force_user"]');
    await rule.locator('input[name="minimum_failures"]').fill('7');
    assert.equal(await page.locator('[data-unsaved-indicator]').isVisible(), true);
    assert.equal(await rule.locator('.rules-field.is-changed').count(), 1);
    const saved = page.waitForResponse(response => response.request().method() === 'PATCH');
    const reloaded = page.waitForEvent('load');
    await rule.getByRole('button', { name: 'Guardar esta regla' }).click();
    assert.equal((await saved).status(), 200);
    await reloaded;
    assert.equal(await rule.locator('input[name="minimum_failures"]').inputValue(), '7');
    assert.equal(await page.locator('[data-unsaved-indicator]').isVisible(), false);
    const output = path.join(process.cwd(), 'analysis', 'rules-ui');
    fs.mkdirSync(output, { recursive: true });
    for (const width of [1440, 390]) {
      await page.setViewportSize({ width, height: 1000 });
      assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), `Desbordamiento a ${width}px`);
      await page.screenshot({ path: path.join(output, `rules-${width}.png`), fullPage: true });
      if (width < 520) await page.locator('[data-rule-picker]').selectOption('scoring');
      else await page.locator('[data-rule-select="scoring"]').click();
      assert.equal(await page.locator('[data-rule-panel="scoring"]').isVisible(), true);
      await page.locator('[data-rule-panel="scoring"]').screenshot({ path: path.join(output, `scoring-${width}.png`) });
      if (width < 520) await page.locator('[data-rule-picker]').selectOption('brute_force_user');
      else await page.locator('[data-rule-select="brute_force_user"]').click();
    }
    assert.equal(await page.locator('[data-rule-form]').count(), 5);
    assert.ok((await page.locator('[data-publish-form] button').isDisabled()));
    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.locator('[data-rule-select="password_spraying_ip"]').click();
    const spraying = page.locator('[data-rule-form="password_spraying_ip"]');
    await spraying.locator('input[name="base_risk"]').fill('66');
    await page.route('**/drafts/*/rules/password_spraying_ip', route => route.abort());
    await spraying.getByRole('button', { name: 'Guardar esta regla' }).click();
    await page.locator('#rules-message.is-error').waitFor();
    assert.ok((await page.locator('#rules-message').textContent()).includes('vuelve a intentarlo'));
    assert.equal(await spraying.locator('input[name="base_risk"]').inputValue(), '66');
    assert.equal(await spraying.getByRole('button').isEnabled(), true);
    await page.unroute('**/drafts/*/rules/password_spraying_ip');
    const secondLoad = page.waitForEvent('load');
    await spraying.getByRole('button', { name: 'Guardar esta regla' }).click();
    await secondLoad;
    assert.equal(await page.locator('[data-rule-panel="password_spraying_ip"]').isVisible(), true);
    assert.ok(page.url().endsWith('#rule-password_spraying_ip'));
    const scoring = page.locator('[data-scoring-form]');
    await page.locator('[data-rule-select="scoring"]').click();
    await scoring.locator('[name="severity_high"]').fill('30');
    assert.equal(await scoring.locator('[name="severity_critical"]').evaluate(input => input.validity.valid), false);
    await scoring.locator('[name="severity_high"]').fill('65');
    const previewForm = page.locator('[data-preview-form]');
    if (await previewForm.getByRole('button').isEnabled()) {
      const comparison = page.waitForResponse(response => response.url().endsWith('/preview'));
      const comparedLoad = page.waitForEvent('load');
      await previewForm.getByRole('button').click();
      const response = await comparison;
      assert.equal(response.status(), 200);
      await comparedLoad;
      assert.equal(await page.locator('.rules-result').isVisible(), true);
      assert.equal(await page.locator('[data-publish-form] button').isEnabled(), true);
      await page.locator('.rules-review-layout').screenshot({ path: path.join(output, 'comparison-1440.png') });
    }
    assert.deepEqual(errors, []);
    console.log('Editor verificado: escritorio/móvil sin desbordamiento; navegación, guardado, rangos, error de conexión y simulación. Solo base sintética.');
  } finally {
    await browser.close();
  }
}
main().catch(error => { console.error(error.name, error.message.split('\n')[0]); process.exitCode = 1; });
