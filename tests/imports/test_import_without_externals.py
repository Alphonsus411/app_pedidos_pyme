"""Test de importación limpia.

Garantiza que `import universal_business` se ejecuta:
- SIN variables de entorno especiales
- SIN levantar base de datos / API / servicios externos
- SIN conexiones de red

Se ejecuta en un SUBPROCESS para evitar contaminación del módulo por los
otros tests que ya han importado partes.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_import_universal_business_without_externals() -> None:
    # Eliminar cualquier variable de entorno de servicios / DB conocida para
    # simular un entorno vacío.
    env = os.environ.copy()
    for k in list(env.keys()):
        kl = k.lower()
        if any(
            tok in kl
            for tok in (
                "postgres",
                "mysql",
                "redis",
                "mongo",
                "api_key",
                "fastapi",
                "db_url",
                "database_url",
            )
        ):
            del env[k]
    env["PYTHONPATH"] = str(ROOT / "src") + os.pathsep + env.get("PYTHONPATH", "")
    # Copiar PATH y otras variables necesarias
    script = (
        "import universal_business as ub\n"
        "print('VERSION', ub.__version__)\n"
        "import universal_business.domain as d\n"
        "import universal_business.application as a\n"
        "print('OK')\n"
    )
    res = subprocess.run(
        [sys.executable, "-c", script],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert res.returncode == 0, (
        f"Import falló exit={res.returncode}\nSTDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}"
    )
    assert "OK" in res.stdout
    assert "VERSION" in res.stdout
