# API local del prototipo

Adaptador HTTP independiente del núcleo. Por ahora expone únicamente
GET /health; no abre SQLite, no ofrece catálogo, ni autentica usuarios.

Instalación local desde la raíz del repositorio:

    python -m pip install -e ".[api,dev]"
    uvicorn apps.api.app.main:app --reload

Las rutas de catálogo y pedidos se incorporarán solo con composición explícita,
contratos de error e idempotencia, y pruebas de aislamiento entre negocios.
