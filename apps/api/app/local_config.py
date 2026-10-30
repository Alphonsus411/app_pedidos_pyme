"""Composición explícita de la API local desde un archivo JSON de desarrollo."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from apps.api.app.cors import ApiCorsSettings
from apps.api.app.main import create_app
from apps.api.app.public_catalog import PublicCatalogScope, SqlitePublicCatalog
from apps.api.app.public_orders import SqlitePublicOrders
from apps.api.app.staff_auth import StaffGrant, StaffPrincipal, StaffRole, StaticBearerAuthenticator
from apps.api.app.staff_orders import SqliteStaffOrders
from fastapi import FastAPI

from universal_business.domain.shared.errors import InvariantViolationError
from universal_business.domain.shared.value_objects.ids import BusinessId, LocationId, TenantId


class LocalConfigurationError(ValueError):
    """El archivo de composición local no cumple el contrato de desarrollo."""


@dataclass(frozen=True)
class LocalApiConfiguration:
    sqlite_path: str
    scopes: dict[tuple[str, str], PublicCatalogScope]
    credentials: dict[str, StaffPrincipal]
    cors_origins: tuple[str, ...]


def load_local_configuration(path: Path) -> LocalApiConfiguration:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LocalConfigurationError("Local API configuration could not be read") from exc
    if type(value) is not dict or set(value) != {
        "sqlite_path",
        "scopes",
        "staff_credentials",
        "cors_origins",
    }:
        raise LocalConfigurationError("Local API configuration keys are invalid")
    sqlite_path = value["sqlite_path"]
    if not isinstance(sqlite_path, str) or not sqlite_path.strip():
        raise LocalConfigurationError("sqlite_path is required")
    return LocalApiConfiguration(
        sqlite_path=sqlite_path,
        scopes=_parse_scopes(value["scopes"]),
        credentials=_parse_credentials(value["staff_credentials"]),
        cors_origins=_parse_origins(value["cors_origins"]),
    )


def create_local_app(path: Path) -> FastAPI:
    """Compone adaptadores SQLite y credenciales estáticas solo para desarrollo."""
    config = load_local_configuration(path)

    def connect() -> sqlite3.Connection:
        return sqlite3.connect(config.sqlite_path)

    cors_settings = ApiCorsSettings(config.cors_origins) if config.cors_origins else None
    catalog = SqlitePublicCatalog(connect=connect, scopes=config.scopes)
    orders = SqlitePublicOrders(connect=connect, scopes=config.scopes)
    staff_orders = SqliteStaffOrders(connect=connect, scopes=config.scopes)
    authenticator = StaticBearerAuthenticator(config.credentials) if config.credentials else None
    return create_app(
        public_catalog=catalog,
        public_orders=orders,
        cors_settings=cors_settings,
        staff_authenticator=authenticator,
        staff_orders=staff_orders if authenticator is not None else None,
    )


def _parse_scopes(value: Any) -> dict[tuple[str, str], PublicCatalogScope]:
    if type(value) is not list or not value:
        raise LocalConfigurationError("At least one scope is required")
    parsed: dict[tuple[str, str], PublicCatalogScope] = {}
    for item in value:
        if type(item) is not dict or set(item) != {
            "business_slug",
            "location_slug",
            "tenant_id",
            "business_id",
            "location_id",
        }:
            raise LocalConfigurationError("Scope is invalid")
        fields = tuple(item.values())
        if not all(isinstance(field, str) and field.strip() for field in fields):
            raise LocalConfigurationError("Scope fields are invalid")
        key = (item["business_slug"], item["location_slug"])
        if key in parsed:
            raise LocalConfigurationError("Scope is duplicated")
        try:
            parsed[key] = PublicCatalogScope(
                tenant_id=TenantId.from_raw(item["tenant_id"]),
                business_id=BusinessId.from_raw(item["business_id"]),
                location_id=LocationId.from_raw(item["location_id"]),
            )
        except InvariantViolationError as exc:
            raise LocalConfigurationError("Scope identifiers are invalid") from exc
    return parsed


def _parse_credentials(value: Any) -> dict[str, StaffPrincipal]:
    if type(value) is not list:
        raise LocalConfigurationError("staff_credentials must be a list")
    parsed: dict[str, StaffPrincipal] = {}
    for item in value:
        if type(item) is not dict or set(item) != {"token", "subject", "grants"}:
            raise LocalConfigurationError("Staff credential is invalid")
        token, subject, grants = item["token"], item["subject"], item["grants"]
        if not isinstance(token, str) or not token.isascii() or not token or token in parsed:
            raise LocalConfigurationError("Staff token is invalid")
        if not isinstance(subject, str) or not subject.strip() or type(grants) is not list:
            raise LocalConfigurationError("Staff credential fields are invalid")
        parsed[token] = StaffPrincipal(
            subject=subject, grants=tuple(_parse_grant(g) for g in grants)
        )
    return parsed


def _parse_grant(value: Any) -> StaffGrant:
    if type(value) is not dict or set(value) != {"business_slug", "location_slug", "roles"}:
        raise LocalConfigurationError("Staff grant is invalid")
    business_slug, location_slug, roles = (
        value["business_slug"],
        value["location_slug"],
        value["roles"],
    )
    if not all(isinstance(item, str) and item.strip() for item in (business_slug, location_slug)):
        raise LocalConfigurationError("Staff grant scope is invalid")
    if type(roles) is not list or not roles:
        raise LocalConfigurationError("Staff grant roles are invalid")
    try:
        parsed_roles = frozenset(StaffRole(role) for role in roles)
    except ValueError as exc:
        raise LocalConfigurationError("Staff grant role is invalid") from exc
    return StaffGrant(business_slug=business_slug, location_slug=location_slug, roles=parsed_roles)


def _parse_origins(value: Any) -> tuple[str, ...]:
    if type(value) is not list or not all(isinstance(origin, str) for origin in value):
        raise LocalConfigurationError("cors_origins must be a list of strings")
    return tuple(value)
