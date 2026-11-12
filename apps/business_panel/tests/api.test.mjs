import assert from "node:assert/strict";
import test from "node:test";
import { getPublicCatalog, getStaffOrders, getStaffSession, ApiRequestError } from "../src/api.mjs";

test("public catalogue sends only versioned GET, never bearer or direct DB calls", async () => {
  const calls = [];
  const response = await getPublicCatalog({
    businessSlug: "demo",
    locationSlug: "main",
    fetchImpl: async (url, init) => {
      calls.push({ url, init });
      return { ok: true, json: async () => ({ items: [], next_cursor: null }) };
    },
  });
  assert.deepEqual(response.items, []);
  assert.deepEqual(calls, [{
    url: "/api/v1/public/businesses/demo/locations/main/catalog",
    init: { method: "GET", headers: { Accept: "application/json" }, credentials: "same-origin" },
  }]);
  assert.equal("Authorization" in calls[0].init.headers, false);
});

test("staff client never sends a static token or trusts response without items", async () => {
  const requests = [];
  const fetchImpl = async (url, init) => {
    requests.push({ url, init });
    return { ok: true, json: async () => ({ items: [{ id: "synthetic" }] }) };
  };
  const response = await getStaffOrders({
    businessSlug: "demo", locationSlug: "main", fetchImpl,
  });
  assert.equal(response.items.length, 1);
  assert.equal(requests[0].url, "/api/v1/staff/businesses/demo/locations/main/orders");
  assert.equal(requests[0].init.credentials, "same-origin");
  assert.deepEqual(requests[0].init.headers, { Accept: "application/json" });
});

test("staff denied by API stays denied and never becomes a success", async () => {
  for (const status of [401, 403, 404, 503]) {
    await assert.rejects(
      getStaffOrders({
        businessSlug: "other", locationSlug: "main",
        fetchImpl: async () => ({ ok: false, status }),
      }),
      (error) => error instanceof ApiRequestError && error.status === status,
    );
  }
});

test("rejects invalid or injected slugs without making network requests", async () => {
  let count = 0;
  const fetchImpl = async () => { count += 1; throw Error("unexpected request"); };
  for (const slug of ["", "../admin", "other/../../staff", "UPPER", "demo?admin=true"]) {
    assert.throws(
      () => getPublicCatalog({ businessSlug: slug, locationSlug: "main", fetchImpl }),
      /Ámbito inválido/,
    );
    assert.throws(
      () => getStaffOrders({ businessSlug: "demo", locationSlug: slug, fetchImpl }),
      /Ámbito inválido/,
    );
  }
  assert.equal(count, 0);
});

test("does not accept silently malformed API responses", async () => {
  await assert.rejects(
    getPublicCatalog({
      businessSlug: "demo", locationSlug: "main",
      fetchImpl: async () => ({ ok: true, json: async () => ({ bogus: true }) }),
    }),
    /Respuesta API inválida/,
  );
});

test("staff session contract uses only same-origin cookie transport", async () => {
  const calls = [];
  const session = await getStaffSession({
    fetchImpl: async (url, init) => {
      calls.push({ url, init });
      return {
        ok: true,
        json: async () => ({
          subject: "synthetic-operator",
          scopes: [{ business_slug: "alpha", location_slug: "main", roles: ["read_orders"] }],
        }),
      };
    },
  });
  assert.equal(session.subject, "synthetic-operator");
  assert.deepEqual(calls, [{
    url: "/api/v1/staff/session",
    init: { method: "GET", headers: { Accept: "application/json" }, credentials: "same-origin" },
  }]);
  assert.equal("Authorization" in calls[0].init.headers, false);
});

test("staff session contract fails closed on auth failure and invalid scopes", async () => {
  for (const status of [401, 403, 503]) {
    await assert.rejects(
      getStaffSession({ fetchImpl: async () => ({ ok: false, status }) }),
      (error) => error instanceof ApiRequestError && error.status === status,
    );
  }
  await assert.rejects(
    getStaffSession({
      fetchImpl: async () => ({
        ok: true,
        json: async () => ({
          subject: "synthetic-operator",
          scopes: [{ business_slug: "../other", location_slug: "main", roles: ["read_orders"] }],
        }),
      }),
    }),
    /Respuesta de sesión inválida/,
  );
});
