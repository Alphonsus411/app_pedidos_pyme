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


# ============================================================================
# Gate 0.2 — Application Layer architectural guards
# Nota: AT-10 (App ⊬ Infrastructure) ya lo cubre AT-7
#       AT-14 (Infra skeleton-only) cubierto por AT-8
#       AT-15 (API skeleton-only) cubierto por AT-8
#       AT-16 (Verticals sin lógica sectorial) cubierto por AT-8
# ============================================================================


API_DIR = SRC / "api"
VERTICALS_DIR = SRC / "verticals"

FORBIDDEN_APP_IMPORTS_AT11 = {"universal_business.api"}
FORBIDDEN_APP_IMPORTS_AT12 = {"universal_business.verticals"}

FORBIDDEN_APP_FRAMEWORKS_AT13 = (
    # Web frameworks
    "fastapi",
    "starlette",
    "flask",
    "django",
    "tornado",
    # ORM / DB drivers
    "sqlalchemy",
    "alembic",
    "psycopg",
    "psycopg2",
    "asyncpg",
    "sqlite3",
    "mysql",
    "mariadb",
    "tortoise",
    "ormar",
    # Message brokers / task queues
    "redis",
    "celery",
    "kafka",
    "pika",
    "rabbitmq",
    # AI SDKs
    "openai",
    "anthropic",
    "google.generativeai",
    "gemini",
    "openrouter",
    # Payment gateways
    "stripe",
    "paypal",
    "mercadopago",
    # Notifications / push
    "twilio",
    "firebase",
    "whatsapp",
    # Frontend
    "react",
    "vue",
    "angular",
    "jinja2",
    # DI frameworks
    "injector",
    "dependency_injector",
    "lagom",
)


def _imports_in_module_simple(
    root_module_parts: tuple[str, ...], import_chain: tuple[str, ...]
) -> bool:
    """True si la cadena de import comienza por el módulo raiz."""
    if len(import_chain) < len(root_module_parts):
        return False
    return import_chain[: len(root_module_parts)] == root_module_parts


def _is_protocol_or_abstract(obj: object) -> bool:
    """Devuelve True si la clase es un Protocol o una ABC con métodos abstractos."""
    if not inspect.isclass(obj):
        return False
    # Protocol detection: tiene __protocol_attrs__ o Protocol en MRO
    has_protocol_marker = hasattr(obj, "__protocol_attrs__")
    has_protocol_mro = any(getattr(base, "__name__", None) == "Protocol" for base in obj.__mro__)
    if has_protocol_marker or has_protocol_mro:
        return True
    # ABC detection: tiene __abstractmethods__ no vacío
    abstract = getattr(obj, "__abstractmethods__", set())
    if abstract:
        return True
    return False


def test_at11_application_cannot_import_api() -> None:
    """AT-11: Application layer NO puede importar módulos de API."""
    api_parts = ("universal_business", "api")
    violations: list[str] = []
    for py_file in iter_python_files(APPLICATION_DIR):
        rel = py_file.relative_to(ROOT).as_posix()
        for lineno, mod in collect_imports(py_file):
            chain = tuple(mod.split("."))
            if _imports_in_module_simple(api_parts, chain):
                violations.append(f"{rel}:{lineno} -> {mod}")
    assert not violations, "AT-11 FAIL Application importa API. Violaciones:\n  " + "\n  ".join(
        violations
    )


def test_at12_application_cannot_import_verticals() -> None:
    """AT-12: Application layer NO puede importar verticales concretos."""
    vert_parts = ("universal_business", "verticals")
    violations: list[str] = []
    for py_file in iter_python_files(APPLICATION_DIR):
        rel = py_file.relative_to(ROOT).as_posix()
        for lineno, mod in collect_imports(py_file):
            chain = tuple(mod.split("."))
            if _imports_in_module_simple(vert_parts, chain):
                violations.append(f"{rel}:{lineno} -> {mod}")
    assert not violations, (
        "AT-12 FAIL Application importa verticales. Violaciones:\n  " + "\n  ".join(violations)
    )


def test_at13_application_cannot_import_external_frameworks_or_sdk() -> None:
    """AT-13: Application no puede importar frameworks/SDK externos prohibidos.

    Cubre: web frameworks, ORM/DB drivers, brokers/task queues, AI SDKs,
    pasarelas de pago, notificaciones push y DI frameworks.
    """
    violations: list[str] = []
    for py_file in iter_python_files(APPLICATION_DIR):
        rel = py_file.relative_to(ROOT).as_posix()
        for lineno, mod in collect_imports(py_file):
            head = mod.split(".")[0]
            if head in FORBIDDEN_APP_FRAMEWORKS_AT13:
                violations.append(f"{rel}:{lineno} -> {mod}")
        # También detectamos ocurrencias de identificador por si alguien usa alias raros
        for _lineno, ident in collect_identifier_occurrences(
            py_file, FORBIDDEN_APP_FRAMEWORKS_AT13
        ):
            # Excluimos comentarios/docstrings comprobando el source no trivial:
            # Para evitar falsos positivos con nombres en strings o comentarios,
            # solo aplicamos cuando el import real coincide (loop anterior).
            # Este loop es defensivo y preparado para checks adicionales en
            # entregas futuras. (No-op en Gate 0.2.)
            del ident
    assert not violations, (
        "AT-13 FAIL Application importa frameworks/SDK externos. Violaciones:\n  "
        + "\n  ".join(violations)
    )


def test_at17_core_ports_are_abstractions_without_concrete_implementation() -> None:
    """AT-17: UnitOfWork, IdempotencyStore y EventPublisher deben ser
    Protocol / ABC sin implementación concreta en el core (src/application).

    Importamos los 3 símbolos desde application y validamos que sean
    Protocol o ABC. Validamos también que dentro de application/ no haya
    una subclase concreta (no-Protocol, no-abstract) que los implemente
    dentro del propio módulo application.
    """
    import sys

    if str(SRC.parent) not in sys.path:
        sys.path.insert(0, str(SRC.parent))

    from universal_business.application import UnitOfWork
    from universal_business.application.events.publisher import EventPublisher
    from universal_business.application.idempotency import IdempotencyStore

    symbols: list[tuple[str, type]] = [
        ("UnitOfWork", UnitOfWork),
        ("IdempotencyStore", IdempotencyStore),
        ("EventPublisher", EventPublisher),
    ]
    for name, cls in symbols:
        assert _is_protocol_or_abstract(cls), (
            f"AT-17 FAIL {name}: debe ser Protocol o ABC. {type(cls)} attrs={dir(cls)}"
        )

    # Aseguramos que en application/** no existan implementaciones concretas
    # que sean subclases de estos ports sin ser Protocol/ABC.
    app_modules: list[str] = []
    for py_file in iter_python_files(APPLICATION_DIR):
        mod = "universal_business." + ".".join(list(py_file.relative_to(SRC).with_suffix("").parts))
        app_modules.append(mod)
        __import__(mod)

    concrete_violations: list[str] = []
    port_classes = [cls for _n, cls in symbols]
    for mod_name in app_modules:
        module = sys.modules[mod_name]
        for attr in dir(module):
            if attr.startswith("_"):
                continue
            obj = getattr(module, attr, None)
            if not inspect.isclass(obj):
                continue
            # Es una subclase concreta (no abstract, no protocol) de algún port?
            is_sub = any(issubclass(obj, pc) for pc in port_classes if obj is not pc)
            if not is_sub:
                continue
            if _is_protocol_or_abstract(obj):
                continue
            concrete_violations.append(f"{mod_name}.{attr}")
    assert not concrete_violations, (
        "AT-17 FAIL Implementaciones concretas de ports core encontradas en application:\n  "
        + "\n  ".join(concrete_violations)
    )


# ============================================================================
# Gate 0.3 — Fase 2: Catalog + Resources architectural guards
# AT-18, AT-19, AT-21, AT-22
# ============================================================================

CATALOG_DOMAIN_DIR = SRC / "domain" / "catalog"
RESOURCES_DOMAIN_DIR = SRC / "domain" / "resources"
CATALOG_APPLICATION_DIR = APPLICATION_DIR / "catalog"
RESOURCES_APPLICATION_DIR = APPLICATION_DIR / "resources"
CATALOG_PORTS = CATALOG_DOMAIN_DIR / "ports.py"
RESOURCES_PORTS = RESOURCES_DOMAIN_DIR / "ports.py"


def test_at18_catalog_resources_domain_no_application_imports() -> None:
    """AT-18: Los módulos de dominio catalog/resources NO deben importar nada
    desde application (la flecha de dependencia va application -> domain,
    nunca al revés).
    """
    target_dirs = [CATALOG_DOMAIN_DIR, RESOURCES_DOMAIN_DIR]
    violations: list[str] = []
    app_parts_1 = ("universal_business", "application")
    app_parts_2 = ("src", "universal_business", "application")
    for py_file in iter_python_files(*target_dirs):
        rel = py_file.relative_to(ROOT).as_posix()
        for lineno, mod in collect_imports(py_file):
            chain = tuple(mod.split("."))
            if _imports_in_module_simple(app_parts_1, chain) or _imports_in_module_simple(
                app_parts_2, chain
            ):
                violations.append(f"{rel}:{lineno} -> {mod}")
    assert not violations, (
        "AT-18 FAIL Dominio catalog/resources importa application. Violaciones:\n  "
        + "\n  ".join(violations)
    )


def test_at19_application_catalog_resources_no_infra_api_verticals() -> None:
    """AT-19: application.catalog y application.resources NO deben importar
    infrastructure, api ni verticals. La capa de aplicación solo habla con
    domain + módulos propios de application.
    """
    target_dirs = [CATALOG_APPLICATION_DIR, RESOURCES_APPLICATION_DIR]
    violations: list[str] = []
    forbidden_roots = [
        ("universal_business", "infrastructure"),
        ("universal_business", "api"),
        ("universal_business", "verticals"),
    ]
    for py_file in iter_python_files(*target_dirs):
        rel = py_file.relative_to(ROOT).as_posix()
        for lineno, mod in collect_imports(py_file):
            chain = tuple(mod.split("."))
            for root in forbidden_roots:
                if _imports_in_module_simple(root, chain):
                    violations.append(f"{rel}:{lineno} -> {mod}")
                    break
    assert not violations, (
        "AT-19 FAIL application.catalog/resources importa infra/api/verticals. "
        "Violaciones:\n  " + "\n  ".join(violations)
    )


def test_at21_catalog_resources_ports_are_protocols_and_no_concrete_repos_in_handlers() -> None:
    """AT-21: Los nuevos repositorios de catalog/resources siguen el patrón
    Protocol typing:

    1. Todas las clases I*Repository en domain/*/ports.py deben ser Protocol
       subclasses (sub-typing estructural, no implementaciones).
    2. En application/*/handlers.py NO debe haber una definición concreta
       `class XxxRepository(object)` o similar; los handlers solo usan
       los Protocol via dependency injection (importados desde dominio).
    """
    import sys

    if str(SRC.parent) not in sys.path:
        sys.path.insert(0, str(SRC.parent))

    violations: list[str] = []

    # ---- Parte 1: ports de dominio son Protocol ----
    port_files = [CATALOG_PORTS, RESOURCES_PORTS]
    for port_py in port_files:
        if not port_py.exists():
            continue
        module_name = "universal_business." + ".".join(
            list(port_py.relative_to(SRC).with_suffix("").parts)
        )
        __import__(module_name)
        module = sys.modules[module_name]
        for name in dir(module):
            if not name.startswith("I"):
                continue
            obj = getattr(module, name)
            if not inspect.isclass(obj):
                continue
            if not _is_protocol_or_abstract(obj):
                violations.append(
                    f"{port_py.relative_to(ROOT).as_posix()}: clase {name} no es Protocol/ABC"
                )

    # ---- Parte 2: handlers de application no definen repos concretos ----
    handler_files = [
        CATALOG_APPLICATION_DIR / "handlers.py",
        RESOURCES_APPLICATION_DIR / "handlers.py",
    ]
    for handler_py in handler_files:
        if not handler_py.exists():
            continue
        rel = handler_py.relative_to(ROOT).as_posix()
        source = handler_py.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(handler_py))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            cls_name = node.name
            if "Repository" not in cls_name:
                continue
            # Es una clase concreta? Protocol/ABC se importan, no se definen aquí.
            # Para conservadurismo: cualquier clase *Repository definida dentro
            # de handlers.py es una violación.
            violations.append(
                f"{rel}:{node.lineno}: definición concreta de repositorio prohibida: {cls_name}"
            )

    assert not violations, (
        "AT-21 FAIL ports/repos de catalog/resources violan patrón Protocol. "
        "Violaciones:\n  " + "\n  ".join(violations)
    )


def _collect_repo_protocol_params_from_ast(ports_py: Path):
    """Parse AST de un ports.py y devuelve tuplas:
    (protocol_name, method_name, [param_names], lineno)
    para cada método (excepto __init__ y dunders) de clases I*Protocol.

    Usamos AST (no inspect) para detectar también parámetros positional-only
    y keyword-only con exactitud de firma fuente.
    """
    results = []
    if not ports_py.exists():
        return results
    source = ports_py.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(ports_py))
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        if not node.name.startswith("I"):
            continue
        for item in node.body:
            if not isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            mname = item.name
            if mname.startswith("_"):
                continue
            # param names: positional-only + regular + keyword-only (sin self/cls)
            args = item.args
            param_names: list[str] = []
            # positional-only
            for a in args.posonlyargs:
                param_names.append(a.arg)
            # regular args
            for a in args.args:
                param_names.append(a.arg)
            # keyword-only
            for a in args.kwonlyargs:
                param_names.append(a.arg)
            # quitar self/cls del principio si aparece
            if param_names and param_names[0] in {"self", "cls"}:
                param_names = param_names[1:]
            results.append((node.name, mname, param_names, ports_py, item.lineno))
    return results


def test_at22_catalog_resources_scoped_methods_require_tenant_and_business() -> None:
    """AT-22: Métodos de repositorios scoped (todos salvo save()) deben
    contener ambos parámetros explícitos: tenant_id y business_id.

    Excepción: save() no requiere estos parámetros (recibe la entity que
    ya contiene ambos).
    """
    violations: list[str] = []
    for ports_py in [CATALOG_PORTS, RESOURCES_PORTS]:
        if not ports_py.exists():
            continue
        rel = ports_py.relative_to(ROOT).as_posix()
        for (
            proto_name,
            method_name,
            param_names,
            _path,
            lineno,
        ) in _collect_repo_protocol_params_from_ast(ports_py):
            if method_name == "save":
                continue
            has_tenant = "tenant_id" in param_names
            has_business = "business_id" in param_names
            if not (has_tenant and has_business):
                missing = []
                if not has_tenant:
                    missing.append("tenant_id")
                if not has_business:
                    missing.append("business_id")
                violations.append(
                    f"{rel}:{lineno} {proto_name}.{method_name}() "
                    f"falta parámetro(s): {', '.join(missing)}. Params: {param_names}"
                )
    assert not violations, (
        "AT-22 FAIL métodos scoped de repositorios catalog/resources "
        "requieren tenant_id + business_id. Violaciones:\n  " + "\n  ".join(violations)
    )
