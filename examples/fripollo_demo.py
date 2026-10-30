"""Recorrido local de Fripollo con datos ficticios y SQLite temporal."""

from pathlib import Path
from tempfile import TemporaryDirectory

from sqlite_demo import run_demo


def main():
    print("Fripollo — demostración ficticia")
    print("Carta de ejemplo: Pica pollo clásico — 12,50 EUR")
    print("Pedido de ejemplo: 2 unidades — 25,00 EUR (sin impuestos ni descuentos)")
    with TemporaryDirectory(prefix="fripollo-demo-") as temporary:
        run_demo(
            Path(temporary),
            location_name="Fripollo (ficticio)",
            product_name="Pica pollo clásico",
            product_price="12.50",
        )
    print("Base temporal eliminada; no se han enviado pedidos ni eventos externos.")


if __name__ == "__main__":
    main()
