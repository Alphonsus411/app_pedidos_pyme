import assert from "node:assert/strict";
import test from "node:test";
import {
  PRIVATE_READ_DISABLED,
  canReadStaffScope,
  prepareStaffOrdersRead,
  readableScopes,
} from "../src/privateOrders.mjs";

const session = {
  subject: "synthetic-operator",
  scopes: [
    { business_slug: "alpha", location_slug: "main", roles: ["read_orders"] },
    { business_slug: "alpha", location_slug: "main", roles: ["read_orders"] },
    { business_slug: "alpha", location_slug: "second", roles: [] },
    { business_slug: "beta", location_slug: "main", roles: ["other_role"] },
    { business_slug: "gamma", location_slug: "main", roles: ["read_orders"] },
  ],
};

test("only readable scopes are selectable; duplicates are removed", () => {
  assert.deepEqual(readableScopes(session), [
    { business_slug: "alpha", location_slug: "main" },
    { business_slug: "gamma", location_slug: "main" },
  ]);
  assert.equal(canReadStaffScope(session, "alpha", "main"), true);
  assert.equal(canReadStaffScope(session, "alpha", "second"), false);
  assert.equal(canReadStaffScope(session, "beta", "main"), false);
  assert.equal(canReadStaffScope(session, "gamma", "main"), true);
});

test("missing or invalid session never offers a selectable private scope", () => {
  for (const payload of [
    null,
    {},
    { subject: "", scopes: session.scopes },
    { subject: "test", scopes: null },
    { subject: "test", scopes: [{ business_slug: "../bad", location_slug: "main", roles: ["read_orders"] }] },
  ]) {
    assert.deepEqual(readableScopes(payload), []);
  }
});

test("an unauthorized or invented business never triggers an HTTP request", async () => {
  let calls = 0;
  const fetchImpl = async () => {
    calls += 1;
    throw new Error("Private request must not start");
  };
  for (const [businessSlug, locationSlug] of [
    ["beta", "main"],
    ["alpha", "second"],
    ["invented", "main"],
    ["alpha", "../admin"],
  ]) {
    assert.deepEqual(
      await prepareStaffOrdersRead({ session, businessSlug, locationSlug, fetchImpl }),
      { state: "forbidden", items: [] },
    );
  }
  assert.equal(calls, 0);
});

test("authorized scope uses same-origin GET without Bearer and preserves empty state", async () => {
  const requests = [];
  const fetchImpl = async (url, options) => {
    requests.push({ url, options });
    return { ok: true, json: async () => ({ items: [] }) };
  };
  const result = await prepareStaffOrdersRead({
    session, businessSlug: "alpha", locationSlug: "main", fetchImpl,
  });
  assert.deepEqual(result, { state: "empty", items: [] });
  assert.deepEqual(requests, [{
    url: "/api/v1/staff/businesses/alpha/locations/main/orders",
    options: {
      method: "GET",
      headers: { Accept: "application/json" },
      credentials: "same-origin",
    },
  }]);
});

test("server 401, 403, 404 and 503 are never converted to authorized data", async () => {
  for (const [status, state] of [
    [401, "session-expired"],
    [403, "forbidden"],
    [404, "forbidden"],
    [503, "unavailable"],
  ]) {
    const result = await prepareStaffOrdersRead({
      session,
      businessSlug: "alpha",
      locationSlug: "main",
      fetchImpl: async () => ({ ok: false, status }),
    });
    assert.deepEqual(result, { state, items: [] });
  }
});

test("valid data, malformed response and network failure map to explicit states", async () => {
  const common = { session, businessSlug: "alpha", locationSlug: "main" };
  const ready = await prepareStaffOrdersRead({
    ...common,
    fetchImpl: async () => ({ ok: true, json: async () => ({ items: [{ id: "synthetic" }] }) }),
  });
  assert.deepEqual(ready, { state: "ready", items: [{ id: "synthetic" }] });
  const malformed = await prepareStaffOrdersRead({
    ...common,
    fetchImpl: async () => ({ ok: true, json: async () => ({ unexpected: true }) }),
  });
  assert.deepEqual(malformed, { state: "error", items: [] });
  const offline = await prepareStaffOrdersRead({
    ...common,
    fetchImpl: async () => { throw new Error("offline"); },
  });
  assert.deepEqual(offline, { state: "error", items: [] });
});

test("private read remains disabled by default in the prototype UI", () => {
  assert.equal(PRIVATE_READ_DISABLED, true);
});
