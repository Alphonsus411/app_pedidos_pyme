import { expect, test } from "@playwright/test";

async function watchApi(page, response = { items: [], next_cursor: null }) {
  const requests = [];
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    requests.push({
      path: new URL(request.url()).pathname,
      method: request.method(),
      headers: await request.allHeaders(),
    });
    if (new URL(request.url()).pathname === "/api/v1/public/businesses/demo/locations/main/catalog") {
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(response) });
    } else {
      await route.fulfill({ status: 418, contentType: "application/json", body: "{}" });
    }
  });
  return requests;
}

function assertOnlyPublicCatalog(requests) {
  expect(requests.length).toBeGreaterThan(0);
  expect(requests.every((item) => (
    item.path === "/api/v1/public/businesses/demo/locations/main/catalog" &&
    item.method === "GET" &&
    !("authorization" in item.headers)
  ))).toBe(true);
}

test("rendered catalog and disabled staff controls use public GET only", async ({ page }) => {
  const requests = await watchApi(page, {
    items: [{ id: "item-synthetic", name: "Artículo sintético", base_price: { amount: "12.50", currency: "EUR" } }],
    next_cursor: null,
  });
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Panel de negocio" })).toBeVisible();
  await expect(page.getByText("Artículo sintético")).toBeVisible();
  await expect(page.getByLabel("Negocio y ubicación autorizados")).toBeDisabled();
  await expect(page.getByText("Sesión de personal no configurada")).toBeVisible();
  assertOnlyPublicCatalog(requests);
  expect(await page.evaluate(() => Object.keys(localStorage))).toEqual([]);
  expect(await page.evaluate(() => Object.keys(sessionStorage))).toEqual([]);
  expect(await page.context().cookies()).toEqual([]);
});

test("empty public catalog never unlocks staff access", async ({ page }) => {
  const requests = await watchApi(page);
  await page.goto("/");
  await expect(page.getByText("No hay artículos públicos para este ámbito.")).toBeVisible();
  await expect(page.getByLabel("Negocio y ubicación autorizados")).toBeDisabled();
  assertOnlyPublicCatalog(requests);
});

test("public catalog server error is visible and never triggers staff requests", async ({ page }) => {
  const requests = [];
  await page.route("**/api/v1/**", async (route) => {
    requests.push(new URL(route.request().url()).pathname);
    if (new URL(route.request().url()).pathname.endsWith("/catalog")) {
      await route.fulfill({ status: 503, contentType: "application/json", body: "{}" });
    } else {
      await route.fulfill({ status: 418, body: "unexpected private request" });
    }
  });
  await page.goto("/");
  await expect(page.getByRole("alert")).toContainText("No se pudo consultar la API");
  await expect(page.getByLabel("Negocio y ubicación autorizados")).toBeDisabled();
  expect(requests.length).toBeGreaterThan(0);
  expect(requests.every((path) => path === "/api/v1/public/businesses/demo/locations/main/catalog")).toBe(true);
});

test("mobile viewport keeps private selector disabled", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  const requests = await watchApi(page);
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Panel de negocio" })).toBeVisible();
  await expect(page.getByLabel("Negocio y ubicación autorizados")).toBeDisabled();
  assertOnlyPublicCatalog(requests);
});
