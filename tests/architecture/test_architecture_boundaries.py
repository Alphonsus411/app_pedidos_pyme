"""Tests arquitectónicos. Protegen los límites de las capas.

Implementados con AST + pathlib (stdlib), sin dependencias externas.
AT-1…AT-9 según plan Gate 0.1-RC1.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src" / "universal_business"
CORE_DIRS = [SRC / "domain", SRC / "application"]
DOMAIN_DIR = SRC / "domain"
APPLICATION_DIR = SRC / "application"

FORBIDDEN_IMPORTS_FROM_DOMAIN = {
    # Infrastructure layer modules
    "universal_business.infrastructure",
    # API layer modules
    "universal_business.api",
    # Runtime dependencies (exclusiones absolutas Entrega 0.1)
    "fastapi",
    "starlette",
    "sqlalchemy",
    "alembic",
    "psycopg",
    "psycopg2",
    "asyncpg",
    "sqlmodel",
    # Redis / Celery / Kafka / MQ / LLM / Firebase
    "redis",
    "celery",
    "kafka",
    "pika",
    "firebase_admin",
    "openai",
    "anthropic",
    "google",
    "stripe",
    # Framework UI
    "react",
    # ORMs misc
    "django",
    "tortoise",
    "ormar",
}

# Nombres sectoriales prohibidos dentro del CORE (domain + application)
FORBIDDEN_VERTICAL_NAMES = [
    "picapol",  # catches picapollo / PicaPollo / _pica_pollo variants
    "piezapollo",
    "pollo_",
    "combopica",
    "restaurant",  # Restaurante/Restaurant mesa restaurante etc.
    "restaurante",
    "mesarestaurante",
    "peluqueria",
    "peluquero",
    "peluqu",  # catches spanish english
    "clinic",
    "clinica",
    "hotel",
    "barber",
    "barbero",
    "barberia",
]


# Métodos de repositorio que deben requerir tenant_id explícito (keyword-only o parámetro)
# cuando la entidad es tenant-scoped.
# Excepción: ITenantRepository (todos sus métodos) no es tenant-scoped; el repo
# de Tenant es el límite superior SaaS y opera sobre tenants directamente.
TENANT_READ_METHODS = {
    "get",
    "list",
    "list_by_tenant",
    "list_by_business",
    "list_by_location",
    "list_by_customer",
    "list_by_order",
    "list_for_resource_in_range",
    "list_for_customer",
    "list_rules_for_resource",
    "list_blocks",
    "search",
    "get_by_external_ref",
}
# Repositorios que NO son tenant-scoped y se excluyen del check AT-9 global.
PORTS_EXCLUDE_FROM_TENANCY: set[str] = {"ITenantRepository"}


def iter_python_files(*roots: Path) -> list[Path]:
    out: list[Path] = []
    for r in roots:
        if not r.exists():
            continue
        for p in r.rglob("*.py"):
            if "__pycache__" in p.parts:
                continue
            out.append(p)
    return out


def collect_imports(path: Path) -> list[tuple[int, str]]:
    """Devuelve (linea, nombre-modulo-importado) para todos los imports en path."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    results: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                results.append((node.lineno, alias.name))
        elif isinstance(node, ast.ImportFrom):
            if node.level and node.module:
                # relative: ignora por ahora (módulos internos OK, pero evaluamos nombres)
                results.append((node.lineno, node.module))
            elif node.module:
                results.append((node.lineno, node.module))
    return results


def collect_identifier_occurrences(path: Path, names: list[str]) -> list[tuple[int, str]]:
    """Inspecciona el código fuente buscando ocurrencias case-insensitive de `names`."""
    text = path.read_text(encoding="utf-8").lower()
    found: list[tuple[int, str]] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        for token in names:
            if token.lower() in line:
                found.append((lineno, token))
    return found


# ============================================================================
# AT-1 a AT-5: imports prohibidos desde dominio
# ============================================================================

DOMAIN_FILES = iter_python_files(DOMAIN_DIR)


@pytest.mark.parametrize("pyfile", DOMAIN_FILES, ids=lambda p: str(p.relative_to(ROOT)))
class TestDomainBoundaryImports:
    def test_at1_domain_does_not_import_infrastructure_or_api(self, pyfile: Path) -> None:
        for lineno, mod in collect_imports(pyfile):
            assert not mod.startswith("universal_business.infrastructure"), (
                f"AT-1 FAIL {pyfile}:{lineno} -> importa {mod!r} (infrastructure)"
            )
            assert not mod.startswith("universal_business.api"), (
                f"AT-1 FAIL {pyfile}:{lineno} -> importa {mod!r} (api)"
            )

    def test_at2_domain_does_not_import_verticals(self, pyfile: Path) -> None:
        for lineno, mod in collect_imports(pyfile):
            assert not mod.startswith("universal_business.verticals"), (
                f"AT-2 FAIL {pyfile}:{lineno} -> importa verticals: {mod!r}"
            )

    def test_at3_domain_no_fastapi_starlette(self, pyfile: Path) -> None:
        for lineno, mod in collect_imports(pyfile):
            bad = {"fastapi", "starlette"}
            for b in bad:
                assert b not in mod.split("."), f"AT-3 FAIL {pyfile}:{lineno} -> importa {mod!r}"

    def test_at4_domain_no_sqlalchemy_or_orm(self, pyfile: Path) -> None:
        forbidden_orms = {
            "sqlalchemy",
            "alembic",
            "psycopg",
            "psycopg2",
            "asyncpg",
            "sqlmodel",
            "django",
        }
        for lineno, mod in collect_imports(pyfile):
            head = mod.split(".")[0]
            assert head not in forbidden_orms, (
                f"AT-4 FAIL {pyfile}:{lineno} -> importa {mod!r} (ORM/DB driver)"
            )

    def test_at5_domain_no_external_services(self, pyfile: Path) -> None:
        forbidden = {
            "redis",
            "celery",
            "kafka",
            "pika",
            "firebase_admin",
            "openai",
            "anthropic",
            "stripe",
            "twilio",
            "react",
        }
        for lineno, mod in collect_imports(pyfile):
            head = mod.split(".")[0]
            assert head not in forbidden, (
                f"AT-5 FAIL {pyfile}:{lineno} -> importa {mod!r} (servicio externo)"
            )


# ============================================================================
# AT-6: nombres verticales prohibidos en core (domain + application)
# ============================================================================

CORE_FILES = iter_python_files(*CORE_DIRS)


@pytest.mark.parametrize("pyfile", CORE_FILES, ids=lambda p: str(p.relative_to(ROOT)))
def test_at6_core_no_vertical_specific_names(pyfile: Path) -> None:
    hits = collect_identifier_occurrences(pyfile, FORBIDDEN_VERTICAL_NAMES)
    assert not hits, f"AT-6 FAIL {pyfile}: nombres verticales encontrados: " + ", ".join(
        f"{tok}@{ln}" for ln, tok in hits
    )


# ============================================================================
# AT-7: Application no debe importar infrastructure (dirección de flecha correcta)
# ============================================================================

APP_FILES = iter_python_files(APPLICATION_DIR)


@pytest.mark.parametrize("pyfile", APP_FILES, ids=lambda p: str(p.relative_to(ROOT)))
def test_at7_application_does_not_import_infrastructure(pyfile: Path) -> None:
    for lineno, mod in collect_imports(pyfile):
        assert not mod.startswith("universal_business.infrastructure"), (
            f"AT-7 FAIL {pyfile}:{lineno} -> application importa infrastructure"
        )


# ============================================================================
# AT-8: Infrastructure / api / verticals sin implementación prematura
# ============================================================================


@pytest.mark.parametrize(
    "layer",
    [SRC / "infrastructure", SRC / "api", SRC / "verticals"],
    ids=["infra", "api", "verticals"],
)
def test_at8_layers_are_skeleton_only(layer: Path) -> None:
    for pyfile in iter_python_files(layer):
        content = [ln for ln in pyfile.read_text(encoding="utf-8").splitlines() if ln.strip()]
        # Permitir archivos con poco código (docstring + from __future__ + pass)
        assert len(content) <= 15, (
            f"AT-8 FAIL: implementación prematura en {pyfile.relative_to(ROOT)} "
            f"con {len(content)} líneas no vacías. Entrega 0.1 solo acepta esqueletos."
        )


# ============================================================================
# AT-9: Repository ports tenant-scoped NO permiten acceso sin tenant explícito.
# ============================================================================


def collect_repository_protocols(domain_dir: Path):
    """Inspecciona dinámicamente cada Protocol definido en domain/**/ports.py y
    devuelve (protocol_name, method_name, signature, port_path) para cada método
    de lectura/listado/search.
    """
    import sys

    if str(SRC.parent) not in sys.path:
        sys.path.insert(0, str(SRC.parent))

    results = []
    for port_py in sorted(domain_dir.rglob("ports.py")):
        rel = port_py.relative_to(ROOT)
        rel.with_suffix("").as_posix().replace("/", ".")
        # import module from src universal_business
        module_name = "universal_business." + ".".join(
            list(port_py.relative_to(SRC).with_suffix("").parts)
        )
        __import__(module_name)
        module = sys.modules[module_name]
        for name in dir(module):
            obj = getattr(module, name)
            if not name.startswith("I"):
                continue
            if not inspect.isclass(obj):
                continue
            # Es Protocol? Los protocols tienen __init_subclass__ con protocol hook.
            if not hasattr(obj, "__protocol_attrs__") and not any(
                b.__name__ == "Protocol" for b in obj.__mro__
            ):
                continue
            for method_name in dir(obj):
                if method_name.startswith("_"):
                    continue
                fn = getattr(obj, method_name, None)
                if fn is None or not callable(fn):
                    continue
                if method_name not in TENANT_READ_METHODS:
                    continue
                try:
                    sig = inspect.signature(fn)
                except (TypeError, ValueError):
                    continue
                results.append((name, method_name, sig, str(rel)))
    return results


REPO_PROTOCOL_METHODS = collect_repository_protocols(DOMAIN_DIR)


@pytest.mark.parametrize(
    "proto_method",
    REPO_PROTOCOL_METHODS,
    ids=lambda pm: f"{pm[0]}.{pm[1]} ({pm[3]})",
)
def test_at9_repository_port_method_has_tenant_id_param_explicit(
    proto_method: tuple[str, str, inspect.Signature, str],
) -> None:
    """AT-9: firmas de repositorios tenant-scoped deben contener `tenant_id`.

    Regla de excepción: repositorios enumerados en PORTS_EXCLUDE_FROM_TENANCY
    (actualmente solo ITenantRepository) no son tenant-scoped: operan sobre
    el límite superior SaaS y sus métodos no requieren parámetro tenant_id.
    """
    proto_name, method_name, sig, _path = proto_method
    if proto_name in PORTS_EXCLUDE_FROM_TENANCY:
        return
    params = sig.parameters
    assert "tenant_id" in params, (
        f"AT-9 FAIL {proto_name}.{method_name}: falta parámetro tenant_id explícito. Params: {list(params)}"
    )
