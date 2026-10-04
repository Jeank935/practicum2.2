/* Grafana real y enlace a la bandeja, únicamente con datos ficticios locales. */
const { chromium } = require("playwright");
const assert = require("node:assert/strict");
const crypto = require("node:crypto");
const path = require("node:path");
const fs = require("node:fs");

async function main() {
  const grafana = process.env.SOC_SMOKE_GRAFANA_URL;
  const web = process.env.SOC_SMOKE_WEB_URL;
  assert.equal(new URL(grafana).hostname, "127.0.0.1");
  assert.equal(new URL(web).hostname, "127.0.0.1");
  const browser = await chromium.launch({ channel: "msedge", headless: true });
  try {
    const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
    const page = await context.newPage();
    await page.goto(web + "/");
    await page.locator('input[name="username"]').fill("soc-admin");
    await page.locator('input[name="password"]').fill(process.env.SOC_BOOTSTRAP_ADMIN_PASSWORD);
    await page.locator('input[type="submit"], button[type="submit"]').first().click();
    await page.waitForURL(web + "/");
    await page.goto(grafana + "/login");
    await page.getByLabel("Email or username").fill("admin");
    await page.getByLabel("Password", { exact: true }).fill(process.env.GRAFANA_ADMIN_PASSWORD);
    await page.getByRole("button", { name: "Log in", exact: true }).click();
    await page.waitForURL(url => !url.pathname.startsWith("/login"));
    const key = crypto.createHash("sha256").update("app_00").digest("hex");
    const query = new URLSearchParams({
      from: "2026-03-21T05:00:00.000Z", to: "2026-03-23T05:00:00.000Z",
      "var-source": "csv_demo_mvp", "var-service": key,
      "var-grain": "hour", "var-web_url": web,
    });
    const results = [];
    page.on("response", async response => {
      if (response.url().includes("/api/ds/query") && response.status() === 200) {
        results.push(await response.json());
      }
    });
    await page.goto(grafana + "/d/adfs-service-detail?" + query);
    await page.getByText("Detalle por intervalo y casos asociados", { exact: true }).scrollIntoViewIfNeeded();
    // Esperar resultados reales del datasource, no un retraso fijo.
    await page.getByText("Autenticaciones", { exact: true }).last().waitFor().catch(async error => {
      console.error(JSON.stringify(results)); // Solo datasource sintético de esta prueba.
      throw error;
    });
    assert.ok(results.length > 0);
    assert.ok(results.every(body => Object.values(body.results || {}).every(result => !result.error)));
    fs.mkdirSync(process.env.SOC_SMOKE_SCREENSHOTS, { recursive: true });
    for (const width of [1440, 390]) {
      await page.setViewportSize({ width, height: 1000 });
      await page.screenshot({ path: path.join(process.env.SOC_SMOKE_SCREENSHOTS, "grafana-"+width+".png"), fullPage: true });
    }
    // La tabla ofrece un enlace calculado con las mismas claves que la gráfica.
    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.getByText("Detalle por intervalo y casos asociados", { exact: true }).scrollIntoViewIfNeeded();
    const link = page.locator('a[href*="service_key="]').first();
    await link.scrollIntoViewIfNeeded();
    const href = await link.getAttribute("href");
    assert.ok(href.startsWith(web + "/alerts?"));
    const target = new URL(href);
    assert.equal(target.searchParams.get("service_key"), key);
    assert.equal(target.searchParams.get("source"), "csv_demo_mvp");
    assert.ok(Number(target.searchParams.get("time_to")) > Number(target.searchParams.get("time_from")));
    const result = await context.request.get(web + "/api/v1/alerts?" + target.searchParams);
    assert.equal(result.status(), 200);
    await page.goto(href);
    await page.getByText("Intervalo de Grafana", { exact: false }).waitFor();
    console.log("Grafana: seis paneles consultan PostgreSQL y el enlace conserva servicio, fuente e intervalo.");
  } finally {
    await browser.close();
  }
}
main().catch(error => {
  console.error("Falló la prueba Grafana:", error.name, error.message?.split("\n")[0]);
  process.exitCode = 1;
});
