"""Recorrido local de Fripollo con datos ficticios y SQLite temporal."""

from pathlib import Path
from tempfile import TemporaryDirectory

from fripollo_catalog import FRIPOLLO_CATALOG
from sqlite_demo import run_demo


def main():
    print("Fripollo — demostración ficticia")
    print("Carta de ejemplo: Pica pollo clásico — 12,50 EUR")
    print("Pedido de ejemplo: 2 unidades — 25,00 EUR (sin impuestos ni descuentos)")
    with TemporaryDirectory(prefix="fripollo-demo-") as temporary:
        run_demo(
            Path(temporary),
            location_name="Fripollo (ficticio)",
            product_name=FRIPOLLO_CATALOG[0][0],
            product_price=FRIPOLLO_CATALOG[0][1],
            additional_products=FRIPOLLO_CATALOG[1:],
        )
    print("Base temporal eliminada; no se han enviado pedidos ni eventos externos.")


if __name__ == "__main__":
    main()
