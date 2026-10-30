"""Punto de entrada opcional para ejecutar una composición local explícita."""

import os
from pathlib import Path

from apps.api.app.local_config import LocalConfigurationError, create_local_app

_CONFIG_PATH = os.environ.get("UNIVERSAL_BUSINESS_API_LOCAL_CONFIG")
if not _CONFIG_PATH:
    raise LocalConfigurationError("UNIVERSAL_BUSINESS_API_LOCAL_CONFIG is required")

app = create_local_app(Path(_CONFIG_PATH))
