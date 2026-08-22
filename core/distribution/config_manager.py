"""Gestor de Configuraciones Segregadas y Migración de Esquemas (config_manager.py - Fase 46).

Segrega estrictamente los dominios de configuración:
- User Config: Preferencias, idioma, tema, atajos
- System Config: Rutas base, puertos, timeouts, logging
- Model Config: Context window, temperatura, límites de VRAM
- Skill Config: Skills habilitadas, políticas de sandbox, permisos
- Agent Config: Presupuestos de agentes, colaboración, iteraciones
- Security Config: Umbrales de riesgo, retención de auditoría, UAC

Incluye motor de migración de esquemas para actualizaciones de producto seguras.
"""

from __future__ import annotations

import copy
import json
import threading
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from core.logger import get_logger

logger = get_logger("jessyca.distribution.config")


@dataclass
class UserConfig:
    """Configuración y preferencias del usuario."""

    language: str = "es"
    theme: str = "dark"
    enable_voice: bool = True
    enable_wake_word: bool = True
    wake_word_keyword: str = "jessyca"
    voice_feedback_volume: float = 0.85
    shortcuts_enabled: bool = True


@dataclass
class SystemConfig:
    """Configuración del sistema base y runtime."""

    app_name: str = "JESSYCA 3.0"
    base_install_path: str = "C:\\Program Files\\JESSYCA"
    data_dir: str = "C:\\Users\\PC\\AppData\\Local\\JESSYCA"
    server_port: int = 8000
    log_level: str = "INFO"
    global_timeout_seconds: float = 30.0
    auto_start_with_windows: bool = False


@dataclass
class ModelConfig:
    """Configuración de inferencia LLM local."""

    default_fast_model: str = "llama3.2:3b"
    default_complex_model: str = "qwen2.5-coder:7b"
    context_window_tokens: int = 8192
    temperature: float = 0.2
    max_vram_usage_mb: float = 12288.0
    enable_smart_routing: bool = True


@dataclass
class SkillConfig:
    """Configuración de Skills locales y permisos."""

    auto_update_skills: bool = False
    enforce_signature_check: bool = True
    sandbox_isolation_level: str = "STRICT"
    marketplace_trust_verification: bool = True
    enabled_skills: list[str] = field(default_factory=lambda: [
        "windows.apps@1.0.0",
        "files.search@1.0.0",
        "browser.search@1.0.0",
        "research_skill_pipeline@1.0.0",
    ])


@dataclass
class AgentConfig:
    """Configuración de colaboración y orquestación de agentes."""

    max_agent_iterations: int = 10
    agent_budget_timeout_seconds: float = 60.0
    enable_multi_agent_collaboration: bool = True
    default_coordinator: str = "SystemCoordinator4"


@dataclass
class SecurityConfig:
    """Configuración de políticas de seguridad, riesgo y auditoría."""

    require_confirmation_for_destructive_actions: bool = True
    risk_threshold_warning: str = "WARNING"
    risk_threshold_critical: str = "CRITICAL"
    audit_log_retention_days: int = 90
    allow_unattended_execution: bool = False
    emergency_stop_enabled: bool = True


@dataclass
class ProductUnifiedConfig:
    """Contenedor unificado de todas las configuraciones segregadas."""

    schema_version: str = "1.0.0"
    user: UserConfig = field(default_factory=UserConfig)
    system: SystemConfig = field(default_factory=SystemConfig)
    model: ModelConfig = field(default_factory=ModelConfig)
    skill: SkillConfig = field(default_factory=SkillConfig)
    agent: AgentConfig = field(default_factory=AgentConfig)
    security: SecurityConfig = field(default_factory=SecurityConfig)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "user": asdict(self.user),
            "system": asdict(self.system),
            "model": asdict(self.model),
            "skill": asdict(self.skill),
            "agent": asdict(self.agent),
            "security": asdict(self.security),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ProductUnifiedConfig:
        cfg = cls(schema_version=data.get("schema_version", "1.0.0"))
        if "user" in data:
            cfg.user = UserConfig(**{k: v for k, v in data["user"].items() if k in UserConfig.__dataclass_fields__})
        if "system" in data:
            cfg.system = SystemConfig(**{k: v for k, v in data["system"].items() if k in SystemConfig.__dataclass_fields__})
        if "model" in data:
            cfg.model = ModelConfig(**{k: v for k, v in data["model"].items() if k in ModelConfig.__dataclass_fields__})
        if "skill" in data:
            cfg.skill = SkillConfig(**{k: v for k, v in data["skill"].items() if k in SkillConfig.__dataclass_fields__})
        if "agent" in data:
            cfg.agent = AgentConfig(**{k: v for k, v in data["agent"].items() if k in AgentConfig.__dataclass_fields__})
        if "security" in data:
            cfg.security = SecurityConfig(**{k: v for k, v in data["security"].items() if k in SecurityConfig.__dataclass_fields__})
        return cfg


class ProductConfigManager:
    """Administrador para persistencia, carga y migración de configuraciones."""

    def __init__(self, config_file_path: str | Path | None = None) -> None:
        self.config_path = Path(config_file_path) if config_file_path else None
        self._current_config = ProductUnifiedConfig()
        self._lock = threading.RLock()

    def get_config(self) -> ProductUnifiedConfig:
        with self._lock:
            return copy.deepcopy(self._current_config)

    def update_config(self, new_config: ProductUnifiedConfig) -> None:
        with self._lock:
            self._current_config = copy.deepcopy(new_config)
            if self.config_path:
                self.save_to_disk(self.config_path)

    def save_to_disk(self, target_path: Path) -> bool:
        """Guarda la configuración segregada en un archivo JSON formateado."""
        with self._lock:
            try:
                target_path.parent.mkdir(parents=True, exist_ok=True)
                with open(target_path, "w", encoding="utf-8") as f:
                    json.dump(self._current_config.to_dict(), f, indent=2, ensure_ascii=False)
                return True
            except Exception as ex:
                logger.error(f"[CONFIG SAVE ERROR] No se pudo guardar configuración en {target_path}: {ex}")
                return False

    def load_from_disk(self, source_path: Path) -> bool:
        """Carga y migra si es necesario la configuración desde disco."""
        with self._lock:
            try:
                if not source_path.exists():
                    return False
                with open(source_path, encoding="utf-8") as f:
                    data = json.load(f)

                # Ejecutar migración automática si la versión del esquema es anterior
                migrated_data = self.migrate_schema(data, target_version="1.0.0")
                self._current_config = ProductUnifiedConfig.from_dict(migrated_data)
                return True
            except Exception as ex:
                logger.error(f"[CONFIG LOAD ERROR] Error cargando configuración desde {source_path}: {ex}")
                return False

    @staticmethod
    def migrate_schema(data: dict[str, Any], target_version: str = "1.0.0") -> dict[str, Any]:
        """Aplica transformaciones de migración de esquema paso a paso."""
        current_version = data.get("schema_version", "0.9.0")
        migrated = copy.deepcopy(data)

        if current_version == "0.9.0":
            logger.info("[CONFIG MIGRATION] Migrando esquema 0.9.0 -> 1.0.0...")
            # Migración: segregar campos planos en dominios formales
            if "language" in migrated and "user" not in migrated:
                migrated["user"] = {"language": migrated.pop("language")}
            if "server_port" in migrated and "system" not in migrated:
                migrated["system"] = {"server_port": migrated.pop("server_port")}
            migrated["schema_version"] = "1.0.0"

        return migrated
