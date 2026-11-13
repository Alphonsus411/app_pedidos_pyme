import test from "node:test";
import assert from "node:assert/strict";
import {
  displayAvailability,
  displayDescription,
  displayPrice,
} from "../src/catalogPresentation.mjs";

test("formats API currency using es-ES and ISO currency code", () => {
  const eur = displayPrice({ price: { amount: "12.5000", currency: "EUR" } });
  assert.match(eur, /12,50/);
  assert.match(eur, /€/);
  const usd = displayPrice({ price: { amount: "4.25", currency: "USD" } });
  assert.match(usd, /4,25/);
  assert.match(usd, /US\$/);
  const yen = displayPrice({ price: { amount: "500", currency: "JPY" } });
  assert.match(yen, /500/);
  assert.match(yen, /JPY/);
});

test("fails closed on missing, incomplete and malformed price", () => {
  for (const item of [
    {}, { price: null }, { price: { amount: "12.50" } },
    { price: { amount: "12.50", currency: "INVALID" } },
    { price: { amount: "-3.50", currency: "EUR" } },
    { price: { amount: "NaN", currency: "EUR" } },
    { price: { amount: "Infinity", currency: "EUR" } },
    { price: { amount: "9999999999999999999999999", currency: "EUR" } },
  ]) {
    assert.equal(displayPrice(item), "Precio no disponible");
  }
});

test("uses the public price field and handles the legacy alias only when absent", () => {
  assert.match(displayPrice({ base_price: { amount: "3.25", currency: "EUR" } }), /3,25/);
  assert.equal(displayPrice({ price: null, base_price: { amount: "3.25", currency: "EUR" } }).includes("3,25"), true);
});

test("shows only API-supplied optional descriptions and availability", () => {
  assert.equal(displayDescription({ description: "  Artículo de prueba  " }), "Artículo de prueba");
  assert.equal(displayDescription({ description: "  " }), null);
  assert.equal(displayDescription({}), null);
  assert.equal(displayAvailability({ available: true }), "Disponible");
  assert.equal(displayAvailability({ available: false }), "No disponible");
  assert.equal(displayAvailability({ available: "false" }), null);
  assert.equal(displayAvailability({ status: "active" }), null);
  assert.equal(displayAvailability({}), null);
});
