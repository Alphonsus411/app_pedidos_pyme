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

export function getPublicCatalog({ businessSlug, locationSlug, cursor = null, fetchImpl = fetch }) {
  const path = `${locationPath(businessSlug, locationSlug)}/catalog`;
  if (cursor === null) return readJson(fetchImpl, path);
  // The cursor comes from the API response; never treat it as a URL or scope.
  if (typeof cursor !== "string" || !/^[A-Za-z0-9_-]{1,512}$/.test(cursor)) {
    throw new Error("Cursor de catálogo inválido");
  }
  return readJson(fetchImpl, `${path}?cursor=${encodeURIComponent(cursor)}`);
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

/** Descubrimiento de ámbito desde sesión HTTP gestionada por el servidor.
 * Solo contrato; la UI no lo invoca hasta componer un IdP/sesión real.
 */
export async function getStaffSession({ fetchImpl = fetch } = {}) {
  const response = await fetchImpl("/api/v1/staff/session", {
    method: "GET",
    headers: { Accept: "application/json" },
    credentials: "same-origin",
  });
  if (!response.ok) throw new ApiRequestError(response.status);
  const payload = await response.json();
  if (
    !payload ||
    typeof payload.subject !== "string" ||
    !Array.isArray(payload.scopes) ||
    !payload.scopes.every(
      (scope) =>
        scope &&
        typeof scope.business_slug === "string" &&
        SLUG.test(scope.business_slug) &&
        typeof scope.location_slug === "string" &&
        SLUG.test(scope.location_slug) &&
        Array.isArray(scope.roles) &&
        scope.roles.every((role) => typeof role === "string"),
    )
  ) {
    throw new Error("Respuesta de sesión inválida");
  }
  return payload;
}
