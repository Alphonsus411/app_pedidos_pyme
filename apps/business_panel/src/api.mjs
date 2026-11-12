/** Cliente HTTP del panel, independiente del núcleo Python y de SQLite. */

const SLUG = /^[a-z0-9][a-z0-9-]{0,62}$/;

function locationPath(businessSlug, locationSlug) {
  if (!SLUG.test(businessSlug) || !SLUG.test(locationSlug)) {
    throw new Error("Ámbito inválido");
  }
  return `/api/v1/public/businesses/${businessSlug}/locations/${locationSlug}`;
}

export class ApiRequestError extends Error {
  constructor(status) {
    super(status === 401 ? "Sesión requerida" : status === 403 ? "Sin autorización" : "No se pudo consultar la API");
    this.name = "ApiRequestError";
    this.status = status;
  }
}

async function readJson(fetchImpl, path) {
  // Sin token de desarrollo, almacenamiento local, cabeceras de identidad ni acceso a SQLite.
  const response = await fetchImpl(path, {
    method: "GET",
    headers: { Accept: "application/json" },
    credentials: "same-origin",
  });
  if (!response.ok) throw new ApiRequestError(response.status);
  const result = await response.json();
  if (!result || !Array.isArray(result.items)) throw new Error("Respuesta API inválida");
  return result;
}

export function getPublicCatalog({ businessSlug, locationSlug, fetchImpl = fetch }) {
  return readJson(fetchImpl, `${locationPath(businessSlug, locationSlug)}/catalog`);
}

/** Preparado como contrato, pero NO se invoca desde la UI sin sesión gestionada. */
export function getStaffOrders({ businessSlug, locationSlug, fetchImpl = fetch }) {
  if (!SLUG.test(businessSlug) || !SLUG.test(locationSlug)) {
    throw new Error("Ámbito inválido");
  }
  return readJson(
    fetchImpl,
    `/api/v1/staff/businesses/${businessSlug}/locations/${locationSlug}/orders`,
  );
}
