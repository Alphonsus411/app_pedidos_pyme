import { useEffect, useState } from "react";
import { ApiRequestError, getPublicCatalog } from "./api.mjs";
import { PRIVATE_READ_DISABLED, readableScopes } from "./privateOrders.mjs";

// Ámbito sintético de la demo: no representa permisos de un trabajador.
const DEMO = { businessSlug: "demo", locationSlug: "main" };

export function App() {
  const [catalog, setCatalog] = useState({ state: "loading", items: [] });

  useEffect(() => {
    const controller = new AbortController();
    // Solo datos de catálogo público. No se solicita /staff sin sesión real.
    getPublicCatalog({
      ...DEMO,
      fetchImpl: (url, options) => fetch(url, { ...options, signal: controller.signal }),
    })
      .then((data) => {
        if (!controller.signal.aborted) setCatalog({ state: "ready", items: data.items });
      })
      .catch((error) => {
        if (!controller.signal.aborted) {
          setCatalog({
            state: "error",
            message: error instanceof ApiRequestError ? error.message : "No se pudo cargar el catálogo",
            items: [],
          });
        }
      });
    return () => controller.abort();
  }, []);

  return (
    <main className="layout">
      <header className="masthead">
        <span className="eyebrow">UNIVERSAL BUSINESS · PROTOTIPO LOCAL</span>
        <h1>Panel de negocio</h1>
        <p>Base de consulta, sin funciones de administración ni identidad productiva.</p>
      </header>

      <PrivateReadiness />


      <section className="panel" aria-labelledby="catalog-title" aria-live="polite">
        <div className="section-heading">
          <h2 id="catalog-title">Vista pública del catálogo</h2>
          <span>Negocio sintético: demo / main</span>
        </div>
        {catalog.state === "loading" && <p role="status">Consultando la API…</p>}
        {catalog.state === "error" && <p role="alert">{catalog.message}</p>}
        {catalog.state === "ready" && catalog.items.length === 0 && (
          <p>No hay artículos públicos para este ámbito.</p>
        )}
        {catalog.state === "ready" && catalog.items.length > 0 && (
          <ul className="catalog">
            {catalog.items.map((item, index) => (
              <li key={item.id ?? index}>
                <strong>{item.name ?? "Artículo sin nombre"}</strong>
                <span>{item.base_price?.amount ?? item.price?.amount ?? "Precio no disponible"}</span>
              </li>
            ))}
          </ul>
        )}
      </section>
      <footer>Consulta únicamente · Sin pagos, pedidos confirmados ni operaciones privadas.</footer>
    </main>
  );
}

/** Preparación visual de sesión/ámbitos, sin peticiones privadas ni sesiones ficticias. */
function PrivateReadiness({ session = null }) {
  const scopes = readableScopes(session);
  const blocked = PRIVATE_READ_DISABLED;
  return (
    <section className="panel" aria-labelledby="identity">
      <h2 id="identity">Acceso privado pendiente</h2>
      <p>
        La API ya exige autorización para consultar pedidos. Todavía no existe
        un inicio de sesión real para este panel, por lo que no se consultan
        pedidos ni se aceptan permisos suministrados desde el navegador.
      </p>
      <p role="status" className="status">Sesión de personal no configurada</p>
      <div className="private-readiness">
        <label htmlFor="private-scope">Negocio y ubicación autorizados</label>
        <select id="private-scope" disabled={blocked || scopes.length === 0} defaultValue="">
          <option value="">Sin ámbitos disponibles</option>
          {scopes.map((scope) => (
            <option
              key={`${scope.business_slug}/${scope.location_slug}`}
              value={`${scope.business_slug}/${scope.location_slug}`}
            >
              {`${scope.business_slug} / ${scope.location_slug}`}
            </option>
          ))}
        </select>
        <p className="private-help">
          La selección y lectura privada se habilitarán únicamente cuando el
          servidor gestione la identidad, la sesión y los permisos reales.
        </p>
      </div>
    </section>
  );
}
