/** F3.5: modelo de lectura staff sin activación en la interfaz.
 *
 * El contrato de sesión viene exclusivamente de GET /staff/session. Esto es
 * una guarda de presentación, no sustituye los permisos de la API.
 */
import { ApiRequestError, getStaffOrders } from "./api.mjs";

const SLUG = /^[a-z0-9][a-z0-9-]{0,62}$/;
const READ_ORDERS = "read_orders";

function isScope(scope) {
  return scope !== null && typeof scope === "object" &&
    typeof scope.business_slug === "string" && SLUG.test(scope.business_slug) &&
    typeof scope.location_slug === "string" && SLUG.test(scope.location_slug) &&
    Array.isArray(scope.roles) && scope.roles.every((role) => typeof role === "string");
}

export function readableScopes(session) {
  if (!session || typeof session.subject !== "string" || !session.subject.trim() ||
      !Array.isArray(session.scopes) || !session.scopes.every(isScope)) {
    return [];
  }
  const seen = new Set();
  return session.scopes.filter((scope) => {
    if (!scope.roles.includes(READ_ORDERS)) return false;
    const key = `${scope.business_slug}/${scope.location_slug}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  }).map(({ business_slug, location_slug }) => ({ business_slug, location_slug }));
}

export function canReadStaffScope(session, businessSlug, locationSlug) {
  return readableScopes(session).some(
    (scope) => scope.business_slug === businessSlug && scope.location_slug === locationSlug,
  );
}

/** La llamada privada solo será invocada por una futura composición de UI
 * con sesión segura real. Nunca se usa en App.jsx del prototipo actual.
 */
export async function prepareStaffOrdersRead({
  session, businessSlug, locationSlug, fetchImpl,
}) {
  if (!canReadStaffScope(session, businessSlug, locationSlug)) {
    return { state: "forbidden", items: [] };
  }
  try {
    const payload = await getStaffOrders({ businessSlug, locationSlug, fetchImpl });
    return { state: payload.items.length ? "ready" : "empty", items: payload.items };
  } catch (error) {
    if (error instanceof ApiRequestError) {
      if (error.status === 401) return { state: "session-expired", items: [] };
      if (error.status === 403 || error.status === 404) {
        return { state: "forbidden", items: [] };
      }
      if (error.status === 503) return { state: "unavailable", items: [] };
    }
    return { state: "error", items: [] };
  }
}

export const PRIVATE_READ_DISABLED = true;
