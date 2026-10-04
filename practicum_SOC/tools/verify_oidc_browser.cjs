/* Prueba OIDC con un navegador real: no altera cookies Secure de Keycloak. */
const { chromium } = require("playwright");
const assert = require("node:assert/strict");

async function main() {
  const origin = process.env.SOC_SMOKE_WEB_URL || "http://127.0.0.1:8000";
  const provider = process.env.SOC_SMOKE_IDP_URL || "http://127.0.0.1:18080";
  assert.equal(new URL(origin).hostname, "127.0.0.1");
  assert.equal(new URL(provider).hostname, "127.0.0.1");
  const browser = await chromium.launch({
    channel: process.env.SOC_BROWSER_CHANNEL || "msedge",
    headless: true,
  });
  try {
    const sessions = {};
    for (const [username, passwordKey, role] of [
      ["soc-admin", "SOC_BOOTSTRAP_ADMIN_PASSWORD", "administrator"],
      ["soc-analyst", "SOC_BOOTSTRAP_ANALYST_PASSWORD", "analyst"],
    ]) {
      assert.ok(process.env[passwordKey], "Falta contraseña de prueba");
      const context = await browser.newContext();
      const page = await context.newPage();
      await page.goto(origin + "/");
      await page.waitForURL(provider + "/**");
      await page.locator('input[name="username"]').fill(username);
      await page.locator('input[name="password"]').fill(process.env[passwordKey]);
      await page.locator('input[type="submit"], button[type="submit"]').first().click();
      await page.waitForURL(origin + "/", { timeout: 30000 });
      const response = await context.request.get(origin + "/auth/me");
      assert.equal(response.status(), 200);
      const user = await response.json();
      assert.equal(user.role, role);
      sessions[role] = { context, page, user };
      console.log("Login OIDC real correcto:", role);
    }
    const { administrator: admin, analyst } = sessions;
    assert.equal((await analyst.page.goto(origin + "/admin/rules")).status(), 403);
    assert.equal((await admin.page.goto(origin + "/admin/rules")).status(), 200);
    await admin.page.getByRole("button", { name: "Crear borrador" }).click();
    await admin.page.waitForURL(url => url.pathname === "/admin/rules" && url.searchParams.has("draft_id"));
    console.log("Reglas versionadas: administrador crea borrador; analista no accede.");
    for (const route of ["/alerts?page_size=3&severity=high", "/services?page_size=3&window_days=0"]) {
      await analyst.page.goto(origin + route);
      assert.equal(await analyst.page.locator('a[rel="next"]').count(), 1);
      await analyst.page.locator('a[rel="next"]').click();
      await analyst.page.waitForURL(url => url.searchParams.has("cursor"));
      const secondPage = analyst.page.url();
      if (route.startsWith("/alerts")) {
        await analyst.page.locator(".table-link").first().click();
        await analyst.page.locator(".back-link").click();
        assert.equal(analyst.page.url(), secondPage);
        assert.equal(await analyst.page.locator('select[name="severity"]').inputValue(), "high");
      }
      await analyst.page.locator('a[rel="prev"]').click();
      await analyst.page.waitForLoadState("domcontentloaded");
      assert.match(await analyst.page.locator(".pagination").innerText(), /Página 1/);
    }
    const api = await analyst.context.request.get(origin + "/api/v1/alerts?page_size=3");
    assert.equal(api.status(), 200);
    assert.equal((await api.json()).data.length, 3);
    assert.equal((await analyst.context.request.get(origin + "/api/v1/alerts?page_size=101")).status(), 422);
    const snapshot = await analyst.context.request.get(origin + "/api/v1/dashboard/snapshot");
    assert.equal(snapshot.status(), 200);
    assert.equal(typeof (await snapshot.json()).operational.revision, "string");
    assert.equal((await analyst.context.request.get(origin + "/api/v1/operations/metrics")).status(), 403);
    const operations = await admin.context.request.get(origin + "/api/v1/operations/metrics");
    assert.equal(operations.status(), 200);
    assert.ok((await operations.json()).technical.database_bytes > 0);
    console.log("API y navegación paginada con filtros y regreso correctos.");
    if (process.env.SOC_SMOKE_SCREENSHOTS) {
      const fs = require("node:fs");
      const path = require("node:path");
      fs.mkdirSync(process.env.SOC_SMOKE_SCREENSHOTS, { recursive: true });
      for (const width of [1440, 390]) {
        await analyst.page.setViewportSize({ width, height: 1000 });
        for (const route of ["alerts", "services"]) {
          await analyst.page.goto(origin + "/" + route + "?page_size=3");
          await analyst.page.screenshot({
            path: path.join(process.env.SOC_SMOKE_SCREENSHOTS, route + "-" + width + ".png"),
            fullPage: true,
          });
        }
      }
      console.log("Capturas sintéticas de escritorio y móvil guardadas.");
    }
    assert.equal((await analyst.context.request.get(origin + "/admin/users")).status(), 403);
    assert.equal((await admin.context.request.get(origin + "/admin/users")).status(), 200);
    assert.equal((await analyst.context.request.get(origin + "/admin/configuration")).status(), 403);
    assert.equal((await admin.context.request.get(origin + "/admin/configuration")).status(), 200);
    if (process.env.SOC_SMOKE_MUTATIONS === "yes") {
      const headers = { "X-CSRF-Token": admin.user.csrf_token };
      const revoke = await admin.context.request.patch(
        origin + "/admin/users/" + analyst.user.user_id,
        { headers, data: { role: "analyst", enabled: false } },
      );
      assert.equal(revoke.status(), 200);
      assert.equal((await analyst.context.request.get(origin + "/auth/me")).status(), 401);
    }
    const logout = await admin.context.request.post(origin + "/auth/logout", {
      headers: { "X-CSRF-Token": admin.user.csrf_token },
    });
    assert.equal(logout.status(), 200);
    assert.equal((await admin.context.request.get(origin + "/auth/me")).status(), 401);
    console.log("Permisos y cierre de sesión correctos.");
  } finally {
    await browser.close();
  }
}

main().catch((error) => {
  // No imprimir URLs de callback, cookies ni valores de credenciales.
  console.error("Falló la prueba de navegador:", error.name);
  process.exitCode = 1;
});
