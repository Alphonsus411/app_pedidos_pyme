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
