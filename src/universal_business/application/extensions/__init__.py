"""Extensiones verticales (ADR-005).

El Universal Business Core es **agnóstico de vertical**. Los nombres sectoriales,
las reglas específicas de cada negocio viven fuera de
``src/universal_business/domain`` y ``src/universal_business/application``.

Este módulo define la **puerta mínima** para registrar extensiones sin
que el core conozca las implementaciones.

## Dirección de dependencias

Siempre::

    verticals/<sector>/  -->  application/  -->  domain/

Jamás al revés. La capa aplicación **no importa** ningún módulo de
``verticals/*``. Los ``VerticalExtension`` se instancian en el Host, CLI,
o punto de entrada de infraestructura y se registran con un registry
ligero.

## Qué NO es

No es un plugin system con autodiscovery, hooks complejos, lifecycle events
avanzados o DI. Gate 0.2 solo deja la puerta abierta mediante un Protocol
mínimo y un registry sencillo.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class VerticalExtension(Protocol):
    """Contrato mínimo que debe implementar una extensión vertical.

    Attributes
    ----------
    name:
        Identificador textual corto, no vacío. Recomendado snake_case
        (p. ej. ``"sector_uno"``, ``"vertical_concreto_dos"``).

    Methods
    -------
    register(context):
        Hook de registro. ``context`` es un objeto sencillo que puede
        exponer funciones tipo ``register_command_handler``,
        ``register_domain_event_handler``, etc. En Gate 0.2 exponemos
        un ``VerticalRegistry`` dataclass mínimo sin dependencias.
    """

    @property
    def name(self) -> str:  # pragma: no cover - Protocol
        ...

    def register(self, context: VerticalRegistry, /) -> None:  # pragma: no cover - Protocol
        ...


@dataclass
class VerticalRegistry:
    """Registro simple de extensiones (no hay lógica acoplada al core).

    Encapsula una lista ``extensions`` y un mapping ``metadata`` para
    comunicar configuración sencilla al Host / punto de entrada. En Gate
    0.2 el registry NO sabe de commands/events; es un placeholder que
    las fases siguientes ampliarán sin ruptura.
    """

    extensions: list[VerticalExtension] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def register(self, extension: VerticalExtension, /) -> None:
        """Añade *extension* al registry y llama a ``extension.register(self)``.

        Se acepta una sola vez por name; la segunda llamada es no-op para
        evitar dobles registros.
        """
        if not isinstance(extension, VerticalExtension):  # runtime-check via Protocol
            raise TypeError(
                f"VerticalRegistry.register: expected VerticalExtension Protocol, "
                f"got {type(extension).__name__}"
            )
        name = extension.name
        if not name or not isinstance(name, str):
            raise ValueError("VerticalRegistry.register: extension.name debe ser str no vacío")
        if any(registered.name == name for registered in self.extensions):
            return  # no-op idempotente
        self.extensions.append(extension)
        extension.register(self)

    def names(self) -> tuple[str, ...]:
        """Devuelve los nombres de extensiones registradas, en orden."""
        return tuple(e.name for e in self.extensions)

    def sorted(self) -> Iterable[VerticalExtension]:
        """Devuelve iterable ordenado por ``name`` (determinismo para tests)."""
        return sorted(self.extensions, key=lambda e: e.name)


__all__ = [
    "VerticalExtension",
    "VerticalRegistry",
]
