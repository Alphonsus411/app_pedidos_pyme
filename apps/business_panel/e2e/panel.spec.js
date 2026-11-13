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

test("renders explicit public description and availability without inventing metadata", async ({ page }) => {
  const requests = await watchApi(page, {
    items: [
      {
        id: "described", name: "Artículo descrito",
        description: "Descripción proporcionada por la API",
        price: { amount: "12.5000", currency: "EUR" },
        available: false,
      },
      { id: "unknown", name: "Artículo sin metadatos de precio" },
    ],
    next_cursor: null,
  });
  await page.goto("/");
  await expect(page.getByText("Descripción proporcionada por la API")).toBeVisible();
  await expect(page.getByText(/12,50\\s*€/)).toBeVisible();
  await expect(page.getByText("No disponible")).toBeVisible();
  await expect(page.getByText("Precio no disponible")).toBeVisible();
  await expect(page.getByText("Disponible", { exact: true })).toHaveCount(0);
  await expect(page.getByLabel("Negocio y ubicación autorizados")).toBeDisabled();
  assertOnlyPublicCatalog(requests);
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

test("loads a second public catalog page without contacting private endpoints", async ({ page }) => {
  const calls = [];
  const first = "/api/v1/public/businesses/demo/locations/main/catalog";
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    calls.push({ path: url.pathname + url.search, method: request.method(), headers: await request.allHeaders() });
    if (url.pathname !== first) {
      await route.fulfill({ status: 418, body: "{}" });
      return;
    }
    const second = url.searchParams.get("cursor") === "bmV4dC1wYWdl";
    const payload = second
      ? { items: [{ id: "second", name: "Segundo artículo", price: { amount: "4.25" } }], next_cursor: null }
      : { items: [{ id: "first", name: "Primer artículo", price: { amount: "2.50" } }], next_cursor: "bmV4dC1wYWdl" };
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(payload) });
  });
  await page.goto("/");
  await expect(page.getByText("Primer artículo")).toBeVisible();
  await page.getByRole("button", { name: "Cargar más artículos" }).click();
  await expect(page.getByText("Segundo artículo")).toBeVisible();
  await expect(page.getByRole("button", { name: "Cargar más artículos" })).toHaveCount(0);
  await expect(page.getByLabel("Negocio y ubicación autorizados")).toBeDisabled();
  const paths = calls.map((item) => item.path);
  // React StrictMode can mount the initial public read twice in development.
  expect(paths.filter((path) => path === first).length).toBeGreaterThanOrEqual(1);
  expect(paths.filter((path) => path === first).length).toBeLessThanOrEqual(2);
  expect(paths.filter((path) => path === first + "?cursor=bmV4dC1wYWdl")).toHaveLength(1);
  expect(paths.every((path) => path === first || path === first + "?cursor=bmV4dC1wYWdl")).toBe(true);
  expect(calls.every((item) => item.method === "GET" && !("authorization" in item.headers))).toBe(true);
});

test("pagination errors preserve loaded public items and keep private UI locked", async ({ page }) => {
  const first = "/api/v1/public/businesses/demo/locations/main/catalog";
  await page.route("**/api/v1/**", async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname !== first) {
      await route.fulfill({ status: 418, body: "{}" });
      return;
    }
    if (url.search) {
      await route.fulfill({ status: 503, contentType: "application/json", body: "{}" });
      return;
    }
    await route.fulfill({
      status: 200, contentType: "application/json",
      body: JSON.stringify({ items: [{ id: "first", name: "Artículo conservado" }], next_cursor: "bmV4dA" }),
    });
  });
  await page.goto("/");
  await expect(page.getByText("Artículo conservado")).toBeVisible();
  await page.getByRole("button", { name: "Cargar más artículos" }).click();
  await expect(page.getByRole("alert")).toContainText("No se pudo consultar la API");
  await expect(page.getByText("Artículo conservado")).toBeVisible();
  await expect(page.getByLabel("Negocio y ubicación autorizados")).toBeDisabled();
});
