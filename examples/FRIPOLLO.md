# Fripollo: demostración local ficticia

Ejemplo de un restaurante de pica pollo dominicano. Todos los datos y precios son inventados y deben revisarse con el futuro cliente. No representa a ningún negocio real.

Desde la raíz del repositorio, con Python 3.11 o posterior:

```bash
python -m pip install -e .
python examples/fripollo_demo.py
```

El ejemplo crea una base SQLite temporal, registra seis productos ficticios en el catálogo, crea un pedido de dos unidades y lo confirma. También crea y confirma una reserva ficticia; reabre la base para comprobar ambos estados y procesa seis eventos con un publicador simulado. Al terminar, elimina la base temporal.

No hay interfaz conectada ni se envían pedidos, reservas o mensajes. No se cobran pagos y las políticas de descuentos, impuestos y transición son ejemplos limitados; no constituyen políticas reales ni autorización. No usar datos reales. La integración del frontend requiere una interfaz de API, autenticación y autorización, validación de extremo a extremo y decisiones del negocio.
