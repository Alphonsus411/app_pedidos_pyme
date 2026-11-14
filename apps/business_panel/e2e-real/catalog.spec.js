import { expect, test } from "@playwright/test";

const FIRST = "/api/v1/public/businesses/demo/locations/main/catalog";
const SECOND = "/api/v1/public/businesses/second/locations/main/catalog";

test("Chromium renders real FastAPI / SQLite catalogue without private calls", async ({ page }) => {
  const apiRequests = [];
  page.on("request", (request) => {
    const path = new URL(request.url()).pathname;
    if (path.startsWith("/api/")) {
      apiRequests.push({
        path,
        method: request.method(),
        authorization: request.headers()["authorization"],
      });
    }
  });

  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Panel de negocio" })).toBeVisible();
  await expect(page.getByText("Artículo sintético F3.8")).toBeVisible();
  await expect(page.getByText(/12,50\s*€/)).toBeVisible();
  await expect(page.getByLabel("Negocio y ubicación autorizados")).toBeDisabled();
  await expect(page.getByText("Sesión de personal no configurada")).toBeVisible();
  // React StrictMode puede efectuar dos GET legítimos en desarrollo.
  expect(apiRequests.length).toBeGreaterThan(0);
  expect(apiRequests.every(
    (request) => request.path === FIRST && request.method === "GET" &&
      request.authorization === undefined,
  )).toBe(true);
  expect(await page.context().cookies()).toEqual([]);
  expect(await page.evaluate(() => Object.keys(localStorage))).toEqual([]);
  expect(await page.evaluate(() => Object.keys(sessionStorage))).toEqual([]);
});

test("two synthetic businesses stay isolated in real HTTP API via browser fetch", async ({ page }) => {
  await page.goto("/");
  const result = await page.evaluate(async (paths) => {
    const responses = await Promise.all(paths.map(async (path) => {
      const response = await fetch(path, { credentials: "same-origin" });
      return { status: response.status, body: await response.json() };
    }));
    return responses;
  }, [FIRST, SECOND, "/api/v1/public/businesses/demo/locations/unknown/catalog"]);
  expect(result.map((x) => x.status)).toEqual([200, 200, 404]);
  expect(result[0].body.items).toHaveLength(50);
  expect(result[0].body.items.map((x) => x.name)).toContain("Artículo sintético F3.8");
  expect(typeof result[0].body.next_cursor).toBe("string");
  expect(result[1].body.items.map((x) => x.name)).toEqual(["Artículo exclusivo segundo negocio"]);
  expect(result[0].body.items[0].name).not.toEqual(result[1].body.items[0].name);
  expect(result[0].body.items[0]).not.toHaveProperty("tenant_id");
  expect(result[1].body.items[0]).not.toHaveProperty("business_id");
  await expect(page.getByLabel("Negocio y ubicación autorizados")).toBeDisabled();
});

test("real FastAPI cursor loads page two in Chromium without private requests", async ({ page }) => {
  const calls = [];
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (url.pathname.startsWith("/api/")) {
      calls.push({
        path: url.pathname,
        search: url.search,
        method: request.method(),
        authorization: request.headers()["authorization"],
      });
    }
  });
  await page.goto("/");
  await expect(page.getByText("Artículo sintético F3.8")).toBeVisible();
  await expect(page.locator(".catalog li")).toHaveCount(50);
  await page.getByRole("button", { name: "Cargar más artículos" }).click();
  await expect(page.locator(".catalog li")).toHaveCount(51);
  await expect(page.getByText("Artículo sintético adicional 50")).toBeVisible();
  await expect(page.getByRole("button", { name: "Cargar más artículos" })).toHaveCount(0);
  await expect(page.getByLabel("Negocio y ubicación autorizados")).toBeDisabled();
  const publicCalls = calls.filter((call) => call.path === FIRST);
  expect(publicCalls.some((call) => call.search.startsWith("?cursor="))).toBe(true);
  expect(calls.every((call) => call.path === FIRST && call.method === "GET"
    && call.authorization === undefined)).toBe(true);
});

test("private API remains disabled and inaccessible without credentials", async ({ page }) => {
  await page.goto("/");
  const result = await page.evaluate(async () => {
    const session = await fetch("/api/v1/staff/session", { credentials: "same-origin" });
    const orders = await fetch(
      "/api/v1/staff/businesses/demo/locations/main/orders",
      { credentials: "same-origin" },
    );
    return { session: session.status, orders: orders.status };
  });
  expect(result).toEqual({ session: 503, orders: 503 });
  await expect(page.getByLabel("Negocio y ubicación autorizados")).toBeDisabled();
});


test("real API item detail expands without another request or private access", async ({ page }) => {
  const calls = [];
  page.on("request", (request) => {
    const path = new URL(request.url()).pathname;
    if (path.startsWith("/api/")) {
      calls.push({ path, method: request.method(), authorization: request.headers()["authorization"] });
    }
  });
  await page.goto("/");
  const item = page.locator(".catalog li").filter({ hasText: "Artículo sintético F3.8" });
  await expect(item).toHaveCount(1);
  await item.getByRole("button", { name: "Ver detalle" }).click();
  const detail = item.getByRole("region", { name: "Detalle de Artículo sintético F3.8" });
  await expect(detail).toBeVisible();
  await expect(detail.getByText(/12,50\s*€/)).toBeVisible();
  await expect(detail.getByText("Disponible", { exact: true })).toHaveCount(0);
  const countAfterOpen = calls.length;
  await item.getByRole("button", { name: "Ocultar detalle" }).click();
  await expect(detail).toHaveCount(0);
  expect(calls).toHaveLength(countAfterOpen);
  expect(calls.length).toBeGreaterThan(0);
  expect(calls.every((call) => call.path === FIRST && call.method === "GET"
    && call.authorization === undefined)).toBe(true);
  await expect(page.getByLabel("Negocio y ubicación autorizados")).toBeDisabled();
  expect(await page.evaluate(() => Object.keys(localStorage))).toEqual([]);
});
