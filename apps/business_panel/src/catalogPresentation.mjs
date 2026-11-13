/** Presentación de datos públicos suministrados por la API, sin inventar valores. */

const DECIMAL = /^(?:0|[1-9][0-9]*)(?:\.[0-9]{1,4})?$/;
const CURRENCY = /^[A-Z]{3}$/;

export function displayPrice(item, locale = "es-ES") {
  const price = item?.price ?? item?.base_price;
  const amount = price?.amount;
  const currency = price?.currency;
  if (
    (typeof amount !== "string" && typeof amount !== "number") ||
    !DECIMAL.test(String(amount)) ||
    typeof currency !== "string" ||
    !CURRENCY.test(currency)
  ) {
    return "Precio no disponible";
  }
  const numeric = Number(amount);
  if (!Number.isFinite(numeric) || numeric > Number.MAX_SAFE_INTEGER) {
    return "Precio no disponible";
  }
  try {
    return new Intl.NumberFormat(locale, {
      style: "currency",
      currency,
    }).format(numeric);
  } catch (error) {
    if (error instanceof RangeError) return "Precio no disponible";
    throw error;
  }
}

export function displayDescription(item) {
  const description = item?.description;
  return typeof description === "string" && description.trim() ? description.trim() : null;
}

export function displayAvailability(item) {
  // El contrato público actual no ofrece disponibilidad. Nunca inferirla
  // del hecho de que un artículo figure como activo en el catálogo.
  if (item?.available === true) return "Disponible";
  if (item?.available === false) return "No disponible";
  return null;
}
