# F3.1 — Panel de negocio (base de solo lectura)

Aplicación **React independiente** del motor Python, su repositorio SQLite y
los adaptadores privados. Los únicos datos que solicita la interfaz hoy son
los del **catálogo público** mediante `GET /api/v1/public/.../catalog`.
Incluye un cliente HTTP de lectura para `GET /api/v1/staff/.../orders`,
pero **NO lo ejecuta** hasta que exista un mecanismo de identidad y sesión
apropiado. Nunca almacena ni incrusta los Bearer tokens estáticos del
laboratorio. Un slug sintético (`demo/main`) sirve solo para el catálogo
público, y no otorga permiso alguno.

## Desarrollo local

El backend de pruebas debe estar levantado en http://127.0.0.1:8000 con su
configuración **externa y no versionada**. El proxy local de Vite encamina
`/api` allí. Sin backend compuesto, el catálogo puede mostrar un error;
no se falsea una respuesta de éxito.

```bash
cd apps/business_panel
npm install
npm test
npm run dev
npm run build
```

La aplicación construida requiere que su servidor/reverse proxy redirija
`/api` al backend correspondiente. La UI muestra estados de carga, error
y resultado vacío; no permite crear/modificar pedidos o editar catálogo.

## Límites conocidos

- Sin login, IdP, sesión real, renovación, revocación ni autorización del
  navegador. La lectura staff permanece **bloqueada en la UI** y el adaptador
  no proporciona tokens.
- No hay selección de negocio basada en permisos del usuario, ni gestión de
  pedidos, ni módulos de plataforma.
- La aplicación todavía no ha pasado validación visual, accesibilidad
  exhaustiva ni pruebas E2E contra dos negocios; los tests de contrato HTTP
  usan dobles de `fetch`, no un servidor productivo.
- Nunca publicar archivos de configuración con secretos ni adoptar tokens
  estáticos para la aplicación web. SQLite solo en el prototipo de desarrollo.
- El paquete React no importa `src/universal_business`, modelos Python ni SQL.

Siguiente incremento: comprobar el contrato real de lectura staff y diseñar
una sesión segura en el backend antes de activar su consumo desde la UI.

## Contrato de sesión preparado (F3.2)

El cliente `getStaffSession()` solo lee `GET /api/v1/staff/session` con
`credentials: "same-origin"` y sin token Bearer o IDs de negocio indicados
por el navegador. Valida la estructura recibida y rechaza estados 401/403/503.
No lo usa aún `App.jsx`: faltan identidad/cookies gestionadas por el servidor
y mecanismos de revocación. **No es un login** y no concede acceso privado.

## F3.5 — Preparación de la lectura privada, sin activarla

`src/privateOrders.mjs` prepara el estado de presentación del personal:
`readableScopes(session)` filtra únicamente los ámbitos que declaran
`read_orders`, elimina duplicados y rechaza sesiones malformadas;
`prepareStaffOrdersRead(...)` está diseñado para una futura UI autorizada,
con estados explícitos `ready`, `empty`, `forbidden`, `session-expired`,
`unavailable` y `error`. Sin un ámbito autorizado, ni siquiera inicia
la solicitud HTTP. Cuando se use, el backend **revalidará siempre** la
identidad y permisos; filtrar opciones en React no autoriza accesos.

`App.jsx` muestra la sesión no configurada y un selector **deshabilitado**.
La constante `PRIVATE_READ_DISABLED` permanece activa y la UI **no llama**
a `getStaffSession` ni `getStaffOrders`; no hay autenticación ficticia,
cookies emitidas ni credenciales en el frontend. Las pruebas HTTP con dobles
de `fetch` validan falta de red para ámbitos prohibidos, errores y ausencia
de tokens Bearer. Queda pendiente E2E real con sesiones seguras antes de
habilitar lectura de pedidos. SQLite exclusivamente desarrollo/pruebas.

## F3.7 — Pruebas de navegador Chromium (laboratorio)

Las pruebas `e2e/panel.spec.js` ejecutan la UI React en Chromium mediante
Playwright. Las respuestas del catálogo público se interceptan con datos
sintéticos en el navegador: **no se conecta a un backend real**. Se verifica
el renderizado de catálogo con artículos, estado vacío, error 503, selector
privado deshabilitado, vista móvil y que ninguna petición de la UI se dirija
a `/api/v1/staff`. También se comprueba que las solicitudes públicas
no envíen Authorization y que no haya tokens en cookies ni storage.

```bash
cd apps/business_panel
npm install
npx playwright install chromium
npm run test:e2e
```

La CI instala Chromium con dependencias y ejecuta estas pruebas además de
las comprobaciones JavaScript y la compilación existentes. Este nivel es
**E2E del navegador/UI con API pública simulada**, no E2E con IdP, sesión
productiva, API y base de datos reales. La interfaz privada permanece
inhabilitada. No guarda capturas ni trazas salvo las de fallos de test.

## F3.8 — Chromium con FastAPI y SQLite reales de laboratorio

El comando `npm run test:e2e:real` inicia un servidor FastAPI local con
SQLite temporal y catálogos sintéticos de dos negocios, además de Vite en
127.0.0.1:4175. Chromium consulta la API real mediante el proxy de Vite;
**no intercepta las respuestas HTTP**. Se comprueban catálogo y precios,
separación de negocios, error 404, ausencia de credenciales y acceso privado
inaccesible (503 sin proveedor). La CI instala Python 3.11, dependencias API,
Node 22 y Chromium en un job independiente.

Ejecutar desde la raíz del repositorio tras instalar dependencias Python
`python -m pip install -e ".[api,dev]"` y `uvicorn`, y desde
`apps/business_panel` instalar Node y Chromium antes de llamar al comando.
Es una prueba con backend real **solo local y sintético**, no un despliegue,
no un IdP ni una prueba de acceso privado autorizado. No se habilitan
operaciones staff en el frontend.
