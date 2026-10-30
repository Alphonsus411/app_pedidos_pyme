"""La demostración de Fripollo usa el núcleo y SQLite sin datos reales."""

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path


def test_fripollo_demo_flow_persists_fictional_offering_and_confirmed_order(tmp_path):
    root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(root / "examples"))
    try:
        from sqlite_demo import run_demo

        run_demo(
            tmp_path,
            location_name="Fripollo (ficticio)",
            product_name="Pica pollo clásico",
            product_price="12.50",
        )
    finally:
        sys.path.pop(0)
    with sqlite3.connect(tmp_path / "prototype.db") as connection:
        name, payload = connection.execute("SELECT name, payload FROM offerings").fetchone()
        status, order_payload = connection.execute("SELECT status, payload FROM orders").fetchone()
        assert name == "Pica pollo clásico"
        assert json.loads(payload)["price"]["amount"] == "12.5000"
        assert status == "confirmed"
        line = json.loads(order_payload)["lines"][0]
        assert line["name"] == name
        assert line["quantity"] == "2"
        assert line["unit_price"]["amount"] == "12.5000"
        assert connection.execute("SELECT status FROM reservations").fetchone() == ("confirmed",)


def test_fripollo_demo_runs_and_cleans_temporary_database(tmp_path):
    root = Path(__file__).resolve().parents[2]
    env = dict(os.environ, PYTHONPATH=str(root / "src"), TMPDIR=str(tmp_path))
    run = subprocess.run(
        [sys.executable, str(root / "examples" / "fripollo_demo.py")],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    assert "Fripollo — demostración ficticia" in run.stdout
    assert "Pedido: confirmed" in run.stdout
    assert "Reserva: confirmed" in run.stdout
    assert "Eventos procesados en simulación: 6" in run.stdout
    assert list(tmp_path.iterdir()) == []
