"""tests/test_config_effective_phase06.py

Pruebas exhaustivas para la Fase 06 — Configuración única y efectiva:
1. Ausencia absoluta de declaraciones duplicadas en AppSettings.
2. Valores por defecto correctos (seguridad y modo shadow/desactivado).
3. Overrides válidos (parámetros directos, variables de entorno, recarga).
4. Rechazo y validación de valores inválidos (modos no soportados, rangos fuera de límite, strings vacíos).
5. Resumen de configuración efectiva sanitizado (get_effective_summary sin fuga de secretos).
6. Resolución homogénea y consistente entre diferentes rutas de inicio e inicialización de componentes.
7. Preservación de retrocompatibilidad y nombres públicos del módulo de configuración.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from config.manager import ConfigManager, get_effective_summary, get_settings
from config.settings import VALID_MODEL_ROUTER_MODES, AppSettings
from core.llm.experimental_router import ExperimentalRouter, RouterMode, get_experimental_router
from core.llm.model_registry import ModelRegistry
from core.llm.nemotron_provider import NemotronProvider


# ══════════════════════════════════════════════════════════════════
# 1. AUSENCIA DE DUPLICADOS EN AppSettings
# ══════════════════════════════════════════════════════════════════


def test_no_duplicate_declarations_in_app_settings() -> None:
    """Verifica mediante inspección AST que AppSettings no tiene declaraciones duplicadas."""
    settings_file = Path("config/settings.py")
    assert settings_file.exists(), "config/settings.py debe existir"

    with open(settings_file, "r", encoding="utf-8") as f:
        tree = ast.parse(f.read())

    app_settings_class = None
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "AppSettings":
            app_settings_class = node
            break

    assert app_settings_class is not None, "Clase AppSettings no encontrada en settings.py"

    field_counts: dict[str, int] = {}
    for item in app_settings_class.body:
        if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
            name = item.target.id
            field_counts[name] = field_counts.get(name, 0) + 1

    duplicates = {name: count for name, count in field_counts.items() if count > 1}
    assert not duplicates, f"Se encontraron campos duplicados en AppSettings: {duplicates}"

    # Verificación explícita de los 5 campos corregidos en la Fase 06
    repaired_fields = [
        "MODEL_ROUTER_ENABLED",
        "MODEL_ROUTER_MODE",
        "ROUTER_CONFIDENCE_THRESHOLD",
        "ROUTER_SHADOW_LOG_FILE",
        "NEMOTRON_ENABLED",
    ]
    for field_name in repaired_fields:
        assert field_counts.get(field_name) == 1, (
            f"El campo '{field_name}' debe declararse exactamente una vez (encontrado: {field_counts.get(field_name)})"
        )


# ══════════════════════════════════════════════════════════════════
# 2. VALORES POR DEFECTO Y CONSERVACIÓN DE MODO SHADOW / DESACTIVADO
# ══════════════════════════════════════════════════════════════════


def test_default_values_safety_and_shadow(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verifica que por defecto el router inteligente y la nube remota están estrictamente desactivados."""
    # Limpiar variables de entorno para probar defaults puros
    for env_k in [
        "MODEL_ROUTER_ENABLED",
        "MODEL_ROUTER_MODE",
        "ROUTER_CONFIDENCE_THRESHOLD",
        "ROUTER_SHADOW_LOG_FILE",
        "NEMOTRON_ENABLED",
        "NEMOTRON_API_KEY",
        "NEMOTRON_TIMEOUT_SECONDS",
        "NEMOTRON_CONNECT_TIMEOUT_SECONDS",
        "NEMOTRON_MAX_RETRIES",
    ]:
        monkeypatch.delenv(env_k, raising=False)

    settings = AppSettings()

    # Router inteligente: desactivado y en shadow
    assert settings.MODEL_ROUTER_ENABLED is False
    assert settings.MODEL_ROUTER_MODE == "shadow"
    assert settings.ROUTER_CONFIDENCE_THRESHOLD == 0.80
    assert settings.ROUTER_SHADOW_LOG_FILE == Path("logs/router_shadow.jsonl")

    # Proveedor remoto Nemotron: desactivado y seguro
    assert settings.NEMOTRON_ENABLED is False
    assert settings.NEMOTRON_API_KEY == ""
    assert settings.NEMOTRON_BASE_URL == "https://integrate.api.nvidia.com/v1"
    assert settings.NEMOTRON_MODEL == "nvidia/nemotron-3-ultra-550b-a55b"
    assert settings.NEMOTRON_TIMEOUT_SECONDS == 30.0
    assert settings.NEMOTRON_CONNECT_TIMEOUT_SECONDS == 5.0
    assert settings.NEMOTRON_MAX_RETRIES == 2


# ══════════════════════════════════════════════════════════════════
# 3. OVERRIDES VÁLIDOS (CONSTRUCTOR Y VARIABLES DE ENTORNO)
# ══════════════════════════════════════════════════════════════════


@pytest.mark.parametrize(
    "mode,expected",
    [
        ("static", "static"),
        ("shadow", "shadow"),
        ("controlled", "controlled"),
        ("experimental", "experimental"),
        ("STATIC", "static"),
        ("  Controlled  ", "controlled"),
    ],
)
def test_valid_router_mode_overrides(mode: str, expected: str) -> None:
    """Verifica que todos los modos válidos sean aceptados y normalizados a minúsculas."""
    settings = AppSettings(MODEL_ROUTER_MODE=mode)
    assert settings.MODEL_ROUTER_MODE == expected


@pytest.mark.parametrize("threshold", [0.0, 0.5, 0.80, 0.99, 1.0, "0.75", "1.0"])
def test_valid_router_confidence_threshold_overrides(threshold: Any) -> None:
    """Verifica que umbrales en el rango [0.0, 1.0] sean aceptados."""
    settings = AppSettings(ROUTER_CONFIDENCE_THRESHOLD=threshold)
    assert settings.ROUTER_CONFIDENCE_THRESHOLD == float(threshold)


def test_valid_environment_variables_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verifica que las variables de entorno sobrescriban adecuadamente los defaults."""
    monkeypatch.setenv("MODEL_ROUTER_ENABLED", "true")
    monkeypatch.setenv("MODEL_ROUTER_MODE", "controlled")
    monkeypatch.setenv("ROUTER_CONFIDENCE_THRESHOLD", "0.85")
    monkeypatch.setenv("ROUTER_SHADOW_LOG_FILE", "custom_logs/shadow.jsonl")
    monkeypatch.setenv("NEMOTRON_ENABLED", "true")
    monkeypatch.setenv("NEMOTRON_TIMEOUT_SECONDS", "45.5")
    monkeypatch.setenv("NEMOTRON_CONNECT_TIMEOUT_SECONDS", "10.0")
    monkeypatch.setenv("NEMOTRON_MAX_RETRIES", "5")

    settings = AppSettings()
    assert settings.MODEL_ROUTER_ENABLED is True
    assert settings.MODEL_ROUTER_MODE == "controlled"
    assert settings.ROUTER_CONFIDENCE_THRESHOLD == 0.85
    assert settings.ROUTER_SHADOW_LOG_FILE == Path("custom_logs/shadow.jsonl")
    assert settings.NEMOTRON_ENABLED is True
    assert settings.NEMOTRON_TIMEOUT_SECONDS == 45.5
    assert settings.NEMOTRON_CONNECT_TIMEOUT_SECONDS == 10.0
    assert settings.NEMOTRON_MAX_RETRIES == 5


# ══════════════════════════════════════════════════════════════════
# 4. RECHAZO DE VALORES INVÁLIDOS (VALIDACIONES ROBUSTAS)
# ══════════════════════════════════════════════════════════════════


@pytest.mark.parametrize("invalid_mode", ["invalid", "active", "dynamic", "auto", ""])
def test_invalid_router_mode_rejected(invalid_mode: str) -> None:
    """Verifica que modos no soportados levanten ValidationError."""
    with pytest.raises(ValidationError) as exc_info:
        AppSettings(MODEL_ROUTER_MODE=invalid_mode)
    assert "MODEL_ROUTER_MODE inválido" in str(exc_info.value)


@pytest.mark.parametrize("invalid_threshold", [-0.1, -1.0, 1.01, 2.0, "not_number", None])
def test_invalid_router_confidence_threshold_rejected(invalid_threshold: Any) -> None:
    """Verifica que umbrales fuera de [0.0, 1.0] o no numéricos levanten ValidationError."""
    with pytest.raises(ValidationError):
        AppSettings(ROUTER_CONFIDENCE_THRESHOLD=invalid_threshold)


@pytest.mark.parametrize("invalid_timeout", [0.0, -1.0, -10.0, "bad_timeout"])
def test_invalid_nemotron_timeouts_rejected(invalid_timeout: Any) -> None:
    """Verifica que timeouts no positivos levanten ValidationError."""
    with pytest.raises(ValidationError):
        AppSettings(NEMOTRON_TIMEOUT_SECONDS=invalid_timeout)

    with pytest.raises(ValidationError):
        AppSettings(NEMOTRON_CONNECT_TIMEOUT_SECONDS=invalid_timeout)


@pytest.mark.parametrize("invalid_retries", [-1, -5, "bad_retries"])
def test_invalid_nemotron_retries_rejected(invalid_retries: Any) -> None:
    """Verifica que reintentos negativos o no enteros levanten ValidationError."""
    with pytest.raises(ValidationError):
        AppSettings(NEMOTRON_MAX_RETRIES=invalid_retries)


@pytest.mark.parametrize("invalid_path", ["", "   "])
def test_invalid_router_shadow_log_file_rejected(invalid_path: str) -> None:
    """Verifica que rutas vacías para log shadow levanten ValidationError."""
    with pytest.raises(ValidationError):
        AppSettings(ROUTER_SHADOW_LOG_FILE=invalid_path)


# ══════════════════════════════════════════════════════════════════
# 5. RESUMEN DE CONFIGURACIÓN EFECTIVA Y SANITIZACIÓN DE SECRETOS
# ══════════════════════════════════════════════════════════════════


def test_effective_summary_masks_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verifica que get_effective_summary oculte tokens y credenciales pero preserve flags públicos."""
    settings = AppSettings(
        NEMOTRON_API_KEY="nvapi-super-secret-production-key",
        MOBILE_API_AUTH_TOKEN="mobile-auth-token-secret-999",
        WEBUI_BRIDGE_AUTH_TOKEN="webui-token-secret-888",
    )

    summary = settings.get_effective_summary()

    # Credenciales deben estar redactadas
    assert summary["NEMOTRON_API_KEY"] == "[REDACTED]"
    assert summary["MOBILE_API_AUTH_TOKEN"] == "[REDACTED]"
    assert summary["WEBUI_BRIDGE_AUTH_TOKEN"] == "[REDACTED]"

    # Campos no sensibles no deben ser redactados
    assert summary["MODEL_ROUTER_MODE"] == "shadow"
    assert summary["MODEL_ROUTER_ENABLED"] is False
    assert summary["ROUTER_CONFIDENCE_THRESHOLD"] == 0.80
    assert summary["WAKE_WORD_KEYWORD"] == "jessyca"
    assert summary["REGISTRY_MAX_SUBKEYS"] == 1000
    assert summary["ENVIRONMENT"] == "development"
    assert summary["LOG_LEVEL"] == "INFO"


def test_effective_summary_empty_credentials_safe() -> None:
    """Verifica que credenciales vacías no se muestren como [REDACTED] ni filtren datos erróneos."""
    settings = AppSettings(
        NEMOTRON_API_KEY="",
        MOBILE_API_AUTH_TOKEN="",
        WEBUI_BRIDGE_AUTH_TOKEN="",
    )
    summary = settings.get_effective_summary()
    assert summary["NEMOTRON_API_KEY"] == ""
    assert summary["MOBILE_API_AUTH_TOKEN"] == ""
    assert summary["WEBUI_BRIDGE_AUTH_TOKEN"] == ""


def test_config_manager_effective_summary_integration() -> None:
    """Verifica que ConfigManager expone get_effective_summary directamente y mediante helper."""
    manager = ConfigManager()
    summary1 = manager.get_effective_summary()
    summary2 = get_effective_summary()

    assert isinstance(summary1, dict)
    assert isinstance(summary2, dict)
    assert summary1["MODEL_ROUTER_MODE"] == summary2["MODEL_ROUTER_MODE"]
    assert "NEMOTRON_API_KEY" in summary1


# ══════════════════════════════════════════════════════════════════
# 6. HOMOGENEIDAD ENTRE RUTAS DE INICIO (RESOLUCIÓN CONSISTENTE)
# ══════════════════════════════════════════════════════════════════


def test_startup_routes_resolve_identically_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verifica que sin variables de entorno, todas las rutas de inicio resuelvan idéntico."""
    for env_k in [
        "MODEL_ROUTER_ENABLED",
        "MODEL_ROUTER_MODE",
        "ROUTER_CONFIDENCE_THRESHOLD",
        "NEMOTRON_ENABLED",
    ]:
        monkeypatch.delenv(env_k, raising=False)

    # Ruta A: ConfigManager / get_settings
    settings = get_settings()

    # Ruta B: ExperimentalRouter
    router = ExperimentalRouter()

    # Ruta C: NemotronProvider
    nemotron = NemotronProvider()

    # Ruta D: ModelRegistry
    registry = ModelRegistry(load_defaults=True)

    # Comprobación de consistencia total
    assert settings.MODEL_ROUTER_MODE == "shadow"
    assert router.mode == RouterMode.SHADOW

    assert settings.MODEL_ROUTER_ENABLED is False
    assert router.is_enabled() is False

    assert settings.ROUTER_CONFIDENCE_THRESHOLD == 0.80
    assert router.confidence_threshold == 0.80

    assert settings.NEMOTRON_ENABLED is False
    assert nemotron.enabled is False
    assert router.is_nemotron_enabled() is False
    assert registry.get("nvidia/nemotron-3-ultra-550b-a55b").enabled is False


def test_startup_routes_resolve_identically_with_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verifica que con variables de entorno, todas las rutas resuelvan unívocamente al override."""
    monkeypatch.setenv("MODEL_ROUTER_MODE", "controlled")
    monkeypatch.setenv("MODEL_ROUTER_ENABLED", "true")
    monkeypatch.setenv("ROUTER_CONFIDENCE_THRESHOLD", "0.85")
    monkeypatch.setenv("NEMOTRON_ENABLED", "true")

    # Forzar recarga de settings
    settings = ConfigManager().reload()

    router = ExperimentalRouter()
    nemotron = NemotronProvider()
    registry = ModelRegistry(load_defaults=True)

    assert settings.MODEL_ROUTER_MODE == "controlled"
    assert router.mode == RouterMode.CONTROLLED

    assert settings.MODEL_ROUTER_ENABLED is True
    assert router.is_enabled() is True

    assert settings.ROUTER_CONFIDENCE_THRESHOLD == 0.85
    assert router.confidence_threshold == 0.85

    assert settings.NEMOTRON_ENABLED is True
    assert nemotron.enabled is True
    assert router.is_nemotron_enabled() is True
    assert registry.get("nvidia/nemotron-3-ultra-550b-a55b").enabled is True


# ══════════════════════════════════════════════════════════════════
# 7. COMPATIBILIDAD PÚBLICA Y CONSTANTES
# ══════════════════════════════════════════════════════════════════


def test_public_names_and_compatibility() -> None:
    """Verifica que no se alteraron los nombres públicos de la configuración."""
    import config

    assert hasattr(config, "AppSettings")
    assert hasattr(config, "ConfigManager")
    assert hasattr(config, "get_settings")
    assert hasattr(config, "get_effective_summary")

    assert set(VALID_MODEL_ROUTER_MODES) == {"static", "shadow", "controlled", "experimental"}
