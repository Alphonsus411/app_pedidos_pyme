import React, { useEffect, useRef, useState } from "react";
import { ApiRequestError, getPublicCatalog } from "./api.mjs";
import { displayAvailability, displayDescription, displayPrice } from "./catalogPresentation.mjs";
import { PRIVATE_READ_DISABLED, readableScopes } from "./privateOrders.mjs";

// Ámbito sintético de la demo: no representa permisos de un trabajador.
const DEMO = { businessSlug: "demo", locationSlug: "main" };

export function App() {
  const [catalog, setCatalog] = useState({ state: "loading", items: [], nextCursor: null });
  const [loadingMore, setLoadingMore] = useState(false);
  const [pageError, setPageError] = useState(null);
  const [pageAnnouncement, setPageAnnouncement] = useState("");
  const [selectedItemId, setSelectedItemId] = useState(null);
  const pageRequest = useRef(null);

  useEffect(() => {
    const controller = new AbortController();
    // Solo datos de catálogo público. No se solicita /staff sin sesión real.
    getPublicCatalog({
      ...DEMO,
      fetchImpl: (url, options) => fetch(url, { ...options, signal: controller.signal }),
    })
      .then((data) => {
        if (!controller.signal.aborted) {
          setCatalog({ state: "ready", items: data.items, nextCursor: data.next_cursor ?? null });
        }
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
    return () => {
      controller.abort();
      pageRequest.current?.abort();
    };
  }, []);

  async function loadMore() {
    if (catalog.state !== "ready" || !catalog.nextCursor || loadingMore) return;
    const controller = new AbortController();
    pageRequest.current = controller;
    setLoadingMore(true);
    setPageError(null);
    setPageAnnouncement("Cargando más artículos…");
    try {
      const data = await getPublicCatalog({
        ...DEMO,
        cursor: catalog.nextCursor,
        fetchImpl: (url, options) => fetch(url, { ...options, signal: controller.signal }),
      });
      if (controller.signal.aborted) return;
      setPageAnnouncement(`${data.items.length} artículos recibidos de la API.`);
      setCatalog((previous) => {
        const seen = new Set(previous.items.map((item) => item.id));
        const newItems = data.items.filter((item) => !seen.has(item.id));
        return {
          state: "ready",
          items: [...previous.items, ...newItems],
          nextCursor: data.next_cursor ?? null,
        };
      });
    } catch (error) {
      if (!controller.signal.aborted) {
        setPageError(error instanceof ApiRequestError ? error.message : "No se pudo cargar la siguiente página");
        setPageAnnouncement("");
      }
    } finally {
      if (!controller.signal.aborted) setLoadingMore(false);
      if (pageRequest.current === controller) pageRequest.current = null;
    }
  }

  return (
    <main className="layout">
      <header className="masthead">
        <span className="eyebrow">UNIVERSAL BUSINESS · PROTOTIPO LOCAL</span>
        <h1>Panel de negocio</h1>
        <p>Base de consulta, sin funciones de administración ni identidad productiva.</p>
      </header>

      <PrivateReadiness />


      <section className="panel" aria-labelledby="catalog-title">
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
                {typeof item.id === "string" && (
                  <button type="button" onClick={() => setSelectedItemId((current) => current === item.id ? null : item.id)} aria-expanded={selectedItemId === item.id} aria-controls={`catalog-detail-${index}`}>
                    {selectedItemId === item.id ? "Ocultar detalle" : "Ver detalle"}
                  </button>
                )}
                {displayDescription(item) && <p className="catalog-description">{displayDescription(item)}</p>}
                <span>{displayPrice(item)}</span>
                {displayAvailability(item) && <small className="catalog-availability">{displayAvailability(item)}</small>}
                {selectedItemId === item.id && typeof item.id === "string" && (
                  <section id={`catalog-detail-${index}`} aria-label={`Detalle de ${item.name ?? "artículo"}`} className="catalog-detail">
                    <h3>{item.name ?? "Artículo sin nombre"}</h3>
                    {displayDescription(item) && <p>{displayDescription(item)}</p>}
                    <p>{displayPrice(item)}</p>
                    {displayAvailability(item) && <p>{displayAvailability(item)}</p>}
                  </section>
                )}
              </li>
            ))}
          </ul>
        )}
        {catalog.state === "ready" && catalog.nextCursor && (
          <button type="button" onClick={loadMore} aria-disabled={loadingMore} aria-busy={loadingMore}>
            {loadingMore ? "Cargando más artículos…" : "Cargar más artículos"}
          </button>
        )}
        <p role="status" aria-live="polite" aria-atomic="true" className="catalog-page-status">{pageAnnouncement}</p>
        {pageError && <p role="alert">{pageError}</p>}
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
