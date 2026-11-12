import { useEffect, useState } from "react";
import { ApiRequestError, getPublicCatalog } from "./api.mjs";

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

      <section className="panel" aria-labelledby="identity">
        <h2 id="identity">Acceso privado pendiente</h2>
        <p>
          La API ya exige autorización para consultar pedidos. Esta interfaz no almacena
          tokens, no simula sesiones ni habilita consultas privadas hasta disponer
          de un mecanismo de identidad y sesión validado.
        </p>
        <span className="status">Gestión de pedidos deshabilitada</span>
      </section>

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
