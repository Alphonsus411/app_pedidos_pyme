"""La demostración se puede ejecutar en un proceso limpio."""

import os
import subprocess
import sys
from pathlib import Path


def test_demo_runs_with_ephemeral_database(tmp_path):
    root = Path(__file__).resolve().parents[2]
    env = dict(
        os.environ,
        PYTHONPATH=str(root / "src"),
        TMPDIR=str(tmp_path),
        TEMP=str(tmp_path),
        TMP=str(tmp_path),
    )
    run = subprocess.run(
        [sys.executable, str(root / "examples" / "sqlite_demo.py")],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    assert "Pedido: confirmed" in run.stdout
    assert "Reserva: confirmed" in run.stdout
    assert "Eventos procesados en simulación: 6" in run.stdout
    assert list(tmp_path.iterdir()) == []
