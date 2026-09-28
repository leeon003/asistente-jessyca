"""Módulo de Integración y Adaptador de Archify para JESSYCA PC (core/archify/adapter.py).

Fase 1: Auditoría + Arquitectura + Laboratorio + Shadow Mode.

Aísla completamente Archify de JESSYCA Core.
Garantiza:
1. JDE como autoridad de decisión (Archify no decide, solo provee especificación y renderizado).
2. Sanitización estricta de entradas para prevenir XSS y ataques de inyección.
3. Confinamiento de rutas de salida para prevenir Path Traversal.
4. Redacción de secretos y credenciales en diagramas.
5. Límites duros de complejidad (DoS prevention).
6. Modo Shadow no invasivo para observación y evaluación comparativa.
"""

from __future__ import annotations

import hashlib
import html
import json
import os
import re
import shutil
import subprocess
import threading
import time
import urllib.parse
import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from core.jde.receipts import redact_sensitive_data
from core.logger import get_logger

logger = get_logger("jessyca.archify.adapter")

DEFAULT_ARCHIFY_OUTPUT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data",
    "archify",
)


class ArchifyMode(StrEnum):
    """Modo operacional de la integración de Archify."""

    OFF = "OFF"
    SHADOW = "SHADOW"
    CONTROLLED = "CONTROLLED"
    ACTIVE = "ACTIVE"


class ArchifyDiagramType(StrEnum):
    """Tipos de diagramas soportados por Archify."""

    ARCHITECTURE = "architecture"
    WORKFLOW = "workflow"
    SEQUENCE = "sequence"
    DATAFLOW = "dataflow"
    LIFECYCLE = "lifecycle"


class ArchifyArtifactMetadata(BaseModel):
    """Metadatos formales e inmutables del artefacto de diagrama generado."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    diagram_id: str
    decision_id: str = ""
    operation_id: str = ""
    fingerprint: str = ""
    path: str
    diagram_type: str
    title: str
    created_at: str
    size_bytes: int
    checksum: str
    verification_status: str = "PENDING_VERIFICATION"
    cache_status: str = "NEW_ARTIFACT"  # CACHE_HIT | NEW_ARTIFACT


class ArchifyRenderResult(tuple):
    """Resultado extendido de renderizado compatible con la tupla (éxito, mensaje, ruta)."""

    def __new__(
        cls,
        success: bool,
        message: str,
        path: str,
        metadata: ArchifyArtifactMetadata | None = None,
    ):
        instance = super().__new__(cls, (success, message, path))
        instance._success = success
        instance._message = message
        instance._path = path
        instance._metadata = metadata
        return instance

    @property
    def success(self) -> bool:
        return self._success

    @property
    def message(self) -> str:
        return self._message

    @property
    def path(self) -> str:
        return self._path

    @property
    def metadata(self) -> ArchifyArtifactMetadata | None:
        return self._metadata


class ArchifyMetrics(BaseModel):
    """Métricas operacionales de Archify en JESSYCA."""

    total: int = 0
    success: int = 0
    failed: int = 0
    verified: int = 0
    verification_failed: int = 0
    cache_hits: int = 0
    fallbacks: int = 0
    blocked: int = 0

    def to_dict(self) -> dict[str, int]:
        return {
            "archify_total": self.total,
            "archify_success": self.success,
            "archify_failed": self.failed,
            "archify_verified": self.verified,
            "archify_verification_failed": self.verification_failed,
            "archify_cache_hits": self.cache_hits,
            "archify_fallbacks": self.fallbacks,
            "archify_blocked": self.blocked,
        }


class ArchifyValidationResult(BaseModel):
    """Resultado formal de validación estructural de una especificación Archify."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    is_valid: bool
    diagram_type: str
    node_count: int
    edge_count: int
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    receipt: dict[str, Any] = Field(default_factory=dict)


class ArchifyShadowObservation(BaseModel):
    """Observación registrada en Shadow Mode comparando JESSYCA vs propuesta Archify."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    observation_id: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    intent: str
    diagram_type: str
    validation_status: bool
    nodes_count: int
    edges_count: int
    jessyca_baseline: str
    archify_proposal: str
    comparison_verdict: str  # CONCORDANT | ENRICHED_VISUALIZATION | UNSUPPORTED | INVALID_SPEC
    latency_ms: float
    details: dict[str, Any] = Field(default_factory=dict)


class JessycaArchifyAdapter:
    """Adaptador seguro y desacoplado para Archify en JESSYCA PC."""

    MAX_NODES = 100
    MAX_EDGES = 200

    def __init__(
        self,
        mode: ArchifyMode | str = ArchifyMode.CONTROLLED,
        output_dir: str | None = None,
        node_executable: str = "node",
        enforce_governance: bool | None = None,
    ) -> None:
        self._mode = self._resolve_mode(mode)
        self._output_dir = output_dir or DEFAULT_ARCHIFY_OUTPUT_DIR
        self._node_executable = node_executable
        self._shadow_history: list[ArchifyShadowObservation] = []
        self._artifact_cache: dict[str, ArchifyArtifactMetadata] = {}
        self._cache_lock = threading.RLock()
        self.metrics = ArchifyMetrics()
        self._enforce_governance = (
            enforce_governance
            if enforce_governance is not None
            else (os.getenv("ARCHIFY_ENFORCE_GOVERNANCE", "").strip().lower() in ("true", "1", "yes"))
        )

        try:
            os.makedirs(self._output_dir, exist_ok=True)
        except Exception as e:
            logger.warning(f"[ARCHIFY ADAPTER] No se pudo crear directorio {self._output_dir}: {e}")

    @staticmethod
    def _resolve_mode(raw: Any) -> ArchifyMode:
        env_val = os.getenv("ARCHIFY_MODE", "").strip().upper()
        if env_val:
            try:
                return ArchifyMode(env_val)
            except ValueError:
                pass
        if isinstance(raw, ArchifyMode):
            return raw
        if isinstance(raw, str):
            try:
                return ArchifyMode(raw.strip().upper())
            except ValueError:
                pass
        return ArchifyMode.CONTROLLED

    @property
    def current_mode(self) -> ArchifyMode:
        return self._mode

    @property
    def enforce_governance(self) -> bool:
        return self._enforce_governance

    def set_enforce_governance(self, enabled: bool) -> None:
        self._enforce_governance = enabled
        logger.info(f"[ARCHIFY ADAPTER] Enforce governance establecido en {enabled}")

    def set_mode(self, mode: ArchifyMode | str) -> None:
        self._mode = self._resolve_mode(mode)
        logger.info(f"[ARCHIFY ADAPTER] Modo actualizado a {self._mode.value}")

    def health_check(self) -> dict[str, Any]:
        """Verifica la disponibilidad de Node.js y el entorno de ejecución."""
        node_path = shutil.which(self._node_executable)
        node_available = bool(node_path)
        node_version = ""

        if node_available:
            try:
                out = subprocess.check_output(
                    [self._node_executable, "-v"],
                    text=True,
                    timeout=3.0,
                    stderr=subprocess.STDOUT,
                )
                node_version = out.strip()
            except Exception as ex:
                logger.debug(f"[ARCHIFY ADAPTER] Error al obtener versión de Node: {ex}")

        return {
            "status": "HEALTHY" if node_available else "DEGRADED",
            "mode": self._mode.value,
            "node_available": node_available,
            "node_version": node_version,
            "output_dir": self._output_dir,
            "output_dir_writable": os.access(self._output_dir, os.W_OK) if os.path.exists(self._output_dir) else False,
            "supported_diagram_types": [t.value for t in ArchifyDiagramType],
        }

    def get_capabilities(self) -> list[str]:
        return [t.value for t in ArchifyDiagramType]

    def get_metrics(self) -> dict[str, int]:
        with self._cache_lock:
            return self.metrics.to_dict()

    def reset_metrics(self) -> None:
        with self._cache_lock:
            self.metrics = ArchifyMetrics()

    def clear_cache(self) -> None:
        with self._cache_lock:
            self._artifact_cache.clear()

    def compute_spec_hash(self, spec: dict[str, Any], diagram_type: str) -> str:
        """Calcula una clave hash SHA-256 determinista para una especificación."""
        title = str(spec.get("title", "")).strip().lower()
        nodes = spec.get("nodes", spec.get("components", spec.get("participants", spec.get("states", []))))
        edges = spec.get("edges", spec.get("connections", spec.get("messages", spec.get("transitions", []))))

        norm_nodes: list[str] = []
        if isinstance(nodes, list):
            for n in nodes:
                if isinstance(n, dict):
                    nid = str(n.get("id") or n.get("name") or "").strip().lower()
                    nlabel = str(n.get("label") or n.get("name") or nid).strip().lower()
                    norm_nodes.append(f"{nid}:{nlabel}")
                else:
                    norm_nodes.append(str(n).strip().lower())
        norm_nodes.sort()

        norm_edges: list[str] = []
        if isinstance(edges, list):
            for e in edges:
                if isinstance(e, dict):
                    src = str(e.get("from") or e.get("source") or "").strip().lower()
                    dst = str(e.get("to") or e.get("target") or "").strip().lower()
                    norm_edges.append(f"{src}->{dst}")
                else:
                    norm_edges.append(str(e).strip().lower())
        norm_edges.sort()

        raw_key = f"{diagram_type.strip().lower()}|{title}|{','.join(norm_nodes)}|{','.join(norm_edges)}"
        return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()

    def sanitize_spec(self, spec: dict[str, Any]) -> dict[str, Any]:
        """Sanitiza recursivamente la especificación para prevenir XSS, DoS y fuga de secretos."""
        redacted = redact_sensitive_data(spec)
        if not isinstance(redacted, dict):
            return {}

        MAX_STRING_LEN = 4000
        secret_patterns = [
            (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----", re.IGNORECASE), "***REDACTED_PRIVATE_KEY***"),
            (re.compile(r"bearer\s+[a-zA-Z0-9_\-\.]{8,}", re.IGNORECASE), "Bearer ***REDACTED***"),
            (re.compile(r"(password|pwd|secret|token|api_?key)\s*[:=]\s*[^\s,;'\"]+", re.IGNORECASE), r"\1=***REDACTED_SECRET***"),
            (re.compile(r"ghp_[a-zA-Z0-9]{36}"), "***REDACTED_GITHUB_TOKEN***"),
            (re.compile(r"sk-[a-zA-Z0-9]{20,}"), "***REDACTED_API_KEY***"),
        ]

        def _clean_value(val: Any) -> Any:
            if isinstance(val, str):
                s = val.replace("\x00", "")
                if len(s) > MAX_STRING_LEN:
                    s = s[:MAX_STRING_LEN]
                for pat, repl in secret_patterns:
                    s = pat.sub(repl, s)
                return html.escape(s)
            elif isinstance(val, dict):
                return {k: _clean_value(v) for k, v in val.items()}
            elif isinstance(val, list):
                return [_clean_value(item) for item in val]
            return val

        return _clean_value(redacted)

    def validate_spec(
        self,
        spec: dict[str, Any],
        diagram_type: str = "architecture",
    ) -> ArchifyValidationResult:
        """Valida una especificación JSON de diagrama aplicando reglas de complejidad y esquema."""
        errors: list[str] = []
        warnings: list[str] = []

        if not isinstance(spec, dict):
            return ArchifyValidationResult(
                is_valid=False,
                diagram_type=diagram_type,
                node_count=0,
                edge_count=0,
                errors=["La especificación debe ser un objeto JSON/dict válido."],
            )

        # Validar tipo
        clean_type = diagram_type.strip().lower()
        if clean_type not in [t.value for t in ArchifyDiagramType]:
            errors.append(f"Tipo de diagrama '{diagram_type}' no soportado por Archify.")

        # Inspección de nodos y aristas
        nodes = spec.get("nodes", spec.get("components", spec.get("participants", spec.get("states", []))))
        edges = spec.get("edges", spec.get("connections", spec.get("messages", spec.get("transitions", []))))

        if not isinstance(nodes, list):
            errors.append("El campo de nodos/componentes debe ser una lista.")
            nodes = []
        if not isinstance(edges, list):
            errors.append("El campo de aristas/conexiones debe ser una lista.")
            edges = []

        node_count = len(nodes)
        edge_count = len(edges)

        # Reglas de complejidad (Anti-DoS)
        if node_count > self.MAX_NODES:
            errors.append(f"Excedido límite máximo de nodos ({node_count} > {self.MAX_NODES}).")
        if edge_count > self.MAX_EDGES:
            errors.append(f"Excedido límite máximo de aristas ({edge_count} > {self.MAX_EDGES}).")

        if node_count == 0:
            warnings.append("El diagrama no define nodos ni componentes.")

        # Comprobar unicidad de IDs de nodos y presencia de IDs válidos
        seen_ids: set[str] = set()
        for idx, node in enumerate(nodes):
            if isinstance(node, dict):
                nid = str(node.get("id") or node.get("name") or "")
                if not nid:
                    errors.append(f"Nodo en índice {idx} no posee identificador ('id' o 'name').")
                    continue
                if nid in seen_ids:
                    errors.append(f"ID de nodo duplicado: '{nid}'.")
                seen_ids.add(nid)
            else:
                errors.append(f"Nodo en índice {idx} debe ser un diccionario.")

        # Comprobar que las aristas referencien nodos existentes
        for idx, edge in enumerate(edges):
            if isinstance(edge, dict):
                src = str(edge.get("from") or edge.get("source") or "")
                dst = str(edge.get("to") or edge.get("target") or "")
                if not src:
                    errors.append(f"Arista en índice {idx} no especifica nodo de origen ('from' o 'source').")
                elif seen_ids and src not in seen_ids:
                    errors.append(f"Arista en índice {idx} referencia nodo de origen inexistente: '{src}'.")

                if not dst:
                    errors.append(f"Arista en índice {idx} no especifica nodo de destino ('to' o 'target').")
                elif seen_ids and dst not in seen_ids:
                    errors.append(f"Arista en índice {idx} referencia nodo de destino inexistente: '{dst}'.")
            else:
                errors.append(f"Arista en índice {idx} debe ser un diccionario.")

        is_valid = (len(errors) == 0)
        return ArchifyValidationResult(
            is_valid=is_valid,
            diagram_type=clean_type,
            node_count=node_count,
            edge_count=edge_count,
            errors=errors,
            warnings=warnings,
            receipt={"checked_at": datetime.now(UTC).isoformat(), "quality": "showcase" if is_valid else "failed"},
        )

    def render_diagram(
        self,
        spec: dict[str, Any],
        diagram_type: str = "architecture",
        filename: str | None = None,
        decision_id: str = "",
        operation_id: str = "",
    ) -> ArchifyRenderResult:
        """Renderiza determinísticamente un diagrama HTML autocontenido.

        Retorna: ArchifyRenderResult (compatible con tupla: (éxito, mensaje, ruta_absoluta_html))
        """
        with self._cache_lock:
            self.metrics.total += 1

        if self._mode == ArchifyMode.OFF:
            with self._cache_lock:
                self.metrics.blocked += 1
            return ArchifyRenderResult(False, "ArchifyAdapter está desactivado (mode=OFF).", "", None)

        if self._mode == ArchifyMode.SHADOW:
            # En Shadow Mode no genera archivos de producción reales
            return ArchifyRenderResult(True, "Modo Shadow: renderizado simulado sin escritura en producción.", "", None)

        # 0. Gobernanza obligatoria de producción
        if self._enforce_governance and not decision_id:
            with self._cache_lock:
                self.metrics.blocked += 1
            return ArchifyRenderResult(
                False,
                "DENIED / GOVERNANCE_REQUIRED: Invocación directa bloqueada. La arquitectura de producción exige paso previo y autorización por JDE.",
                "",
                None,
            )

        # 1. Sanitizar y validar
        sanitized = self.sanitize_spec(spec)
        val = self.validate_spec(sanitized, diagram_type)
        if not val.is_valid:
            with self._cache_lock:
                self.metrics.failed += 1
            return ArchifyRenderResult(False, f"INVALID_DIAGRAM_SPEC: {'; '.join(val.errors)}", "", None)

        # 2. Confinar nombre de archivo y detectar Path Traversal (estricto y canónico)
        if filename:
            if "\x00" in filename:
                with self._cache_lock:
                    self.metrics.blocked += 1
                return ArchifyRenderResult(False, "Violación de seguridad: intento de Path Traversal (null byte) detectado.", "", None)

            decoded_filename = urllib.parse.unquote(filename)
            decoded_lower = decoded_filename.lower()

            if (
                ".." in decoded_filename
                or ".." in filename
                or "%2e" in filename.lower()
                or decoded_filename.startswith("/")
                or decoded_filename.startswith("\\")
                or (len(decoded_filename) > 1 and decoded_filename[1] == ":")
                or any(crit in decoded_lower for crit in ("\\windows", "\\users", "\\system32", "/etc/", ".env", "secret", "config.json"))
            ):
                with self._cache_lock:
                    self.metrics.blocked += 1
                return ArchifyRenderResult(False, "Violación de seguridad: intento de Path Traversal detectado.", "", None)

        # 3. Comprobar Idempotencia (Cache Hit)
        cache_key = self.compute_spec_hash(sanitized, diagram_type)
        with self._cache_lock:
            if not filename and cache_key in self._artifact_cache:
                cached_meta = self._artifact_cache[cache_key]
                if os.path.exists(cached_meta.path) and os.path.getsize(cached_meta.path) == cached_meta.size_bytes:
                    self.metrics.cache_hits += 1
                    self.metrics.success += 1
                    hit_meta = cached_meta.model_copy(update={"cache_status": "CACHE_HIT"})
                    return ArchifyRenderResult(
                        True,
                        f"Diagrama {diagram_type} recuperado de caché (idempotencia).",
                        cached_meta.path,
                        hit_meta,
                    )

        diag_id = f"diag_{diagram_type}_{uuid.uuid4().hex[:10]}"
        base_name = filename or f"diagram_{diag_id}.html"
        decoded_base = urllib.parse.unquote(base_name)
        safe_name = os.path.basename(decoded_base)
        if not safe_name.endswith(".html"):
            safe_name += ".html"

        canonical_output_dir = os.path.realpath(os.path.abspath(self._output_dir))
        canonical_target_path = os.path.realpath(os.path.abspath(os.path.join(self._output_dir, safe_name)))

        # Comprobar confinamiento estricto mediante commonpath y verificación de directorio padre
        try:
            common = os.path.commonpath([canonical_target_path, canonical_output_dir])
            if common != canonical_output_dir or os.path.dirname(canonical_target_path) != canonical_output_dir:
                with self._cache_lock:
                    self.metrics.blocked += 1
                return ArchifyRenderResult(False, "Violación de seguridad: intento de Path Traversal detectado.", "", None)
        except Exception:
            with self._cache_lock:
                self.metrics.blocked += 1
            return ArchifyRenderResult(False, "Violación de seguridad: resolución de ruta fuera de límites permitidos.", "", None)

        target_path = canonical_target_path

        # 4. Compilación determinista del HTML interactivo
        try:
            html_content = self._generate_standalone_html(sanitized, diagram_type)
            with open(target_path, "w", encoding="utf-8") as f:
                f.write(html_content)

            file_size = os.path.getsize(target_path)
            checksum = hashlib.sha256(html_content.encode("utf-8")).hexdigest()

            meta = ArchifyArtifactMetadata(
                diagram_id=diag_id,
                decision_id=decision_id,
                operation_id=operation_id,
                fingerprint=cache_key,
                path=target_path,
                diagram_type=diagram_type,
                title=str(sanitized.get("title", f"Diagrama {diagram_type}")),
                created_at=datetime.now(UTC).isoformat(),
                size_bytes=file_size,
                checksum=checksum,
                verification_status="PENDING_VERIFICATION",
                cache_status="NEW_ARTIFACT",
            )

            with self._cache_lock:
                self._artifact_cache[cache_key] = meta
                self.metrics.success += 1

            return ArchifyRenderResult(
                True,
                f"Diagrama {diagram_type} compilado exitosamente.",
                target_path,
                meta,
            )
        except Exception as ex:
            logger.error(f"[ARCHIFY ADAPTER] Error al compilar HTML: {ex}")
            with self._cache_lock:
                self.metrics.failed += 1
            return ArchifyRenderResult(False, f"Fallo al compilar artefacto HTML: {ex}", "", None)

    def _generate_standalone_html(self, spec: dict[str, Any], diagram_type: str) -> str:
        """Genera el template HTML autocontenido con visualización interactiva SVG."""
        title = spec.get("title", f"Diagrama de {diagram_type.capitalize()}")
        nodes = spec.get("nodes", spec.get("components", spec.get("participants", spec.get("states", []))))
        edges = spec.get("edges", spec.get("connections", spec.get("messages", spec.get("transitions", []))))
        spec_json = json.dumps(spec, ensure_ascii=False, indent=2).replace("</", "<\\/")

        # Renderizador interactivo SVG autocontenido con tema oscuro/claro y controles
        return f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1.0"/>
<title>{title} - Archify</title>
<style>
:root {{
  --bg-primary: #0f172a;
  --bg-surface: #1e293b;
  --text-main: #f8fafc;
  --text-dim: #94a3b8;
  --node-border: #3b82f6;
  --edge-color: #60a5fa;
  --accent: #38bdf8;
}}
body {{
  margin: 0;
  padding: 20px;
  background-color: var(--bg-primary);
  color: var(--text-main);
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  display: flex;
  flex-direction: column;
  height: 100vh;
  box-sizing: border-box;
}}
header {{
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding-bottom: 12px;
  border-bottom: 1px solid var(--bg-surface);
}}
h1 {{ margin: 0; font-size: 1.25rem; font-weight: 600; color: var(--accent); }}
.badge {{ font-size: 0.75rem; background: var(--bg-surface); padding: 4px 8px; border-radius: 4px; }}
#canvas-container {{
  flex: 1;
  background: var(--bg-surface);
  border-radius: 8px;
  margin-top: 15px;
  position: relative;
  overflow: hidden;
  display: flex;
  justify-content: center;
  align-items: center;
}}
svg {{ width: 100%; height: 100%; }}
.node-rect {{ fill: #1e293b; stroke: var(--node-border); stroke-width: 2; rx: 6; }}
.node-text {{ fill: var(--text-main); font-size: 13px; font-weight: 500; text-anchor: middle; }}
.edge-line {{ stroke: var(--edge-color); stroke-width: 2; marker-end: url(#arrow); stroke-dasharray: 4; }}
footer {{ font-size: 0.75rem; color: var(--text-dim); text-align: center; margin-top: 10px; }}
</style>
</head>
<body>
<header>
  <div>
    <h1>{title}</h1>
    <span class="badge">Tipo: {diagram_type}</span>
    <span class="badge">Nodos: {len(nodes)}</span>
    <span class="badge">Conexiones: {len(edges)}</span>
  </div>
  <div>
    <button onclick="toggleTheme()" class="badge" style="cursor:pointer;">Tema Claro/Oscuro</button>
  </div>
</header>
<div id="canvas-container">
  <svg id="archify-svg" viewBox="0 0 900 600">
    <defs>
      <marker id="arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
        <path d="M 0 0 L 10 5 L 0 10 z" fill="#60a5fa"/>
      </marker>
    </defs>
    <!-- Visualización de Nodos y Conexiones -->
    <g id="elements-layer">
      <!-- Layout determinista generado -->
""" + self._build_svg_elements(nodes, edges) + f"""
    </g>
  </svg>
</div>
<footer>
  Generado determinísticamente por JESSYCA Archify Adapter (MIT License).
</footer>
<script>
const specData = {spec_json};
function toggleTheme() {{
  const cur = document.documentElement.style.getPropertyValue('--bg-primary');
  if (cur === '#ffffff') {{
    document.documentElement.style.setProperty('--bg-primary', '#0f172a');
    document.documentElement.style.setProperty('--bg-surface', '#1e293b');
    document.documentElement.style.setProperty('--text-main', '#f8fafc');
  }} else {{
    document.documentElement.style.setProperty('--bg-primary', '#ffffff');
    document.documentElement.style.setProperty('--bg-surface', '#f1f5f9');
    document.documentElement.style.setProperty('--text-main', '#0f172a');
  }}
}}
</script>
</body>
</html>
"""

    def _build_svg_elements(self, nodes: list[Any], edges: list[Any]) -> str:
        """Calcula coordenadas SVG de forma determinista para los nodos."""
        svg_parts: list[str] = []
        node_coords: dict[str, tuple[int, int]] = {}

        cols = 3
        start_x = 150
        start_y = 120
        spacing_x = 260
        spacing_y = 140

        for i, n in enumerate(nodes):
            nid = str(n.get("id", f"node_{i}")) if isinstance(n, dict) else f"node_{i}"
            nlabel = str(n.get("label", n.get("name", nid))) if isinstance(n, dict) else str(n)
            cx = start_x + (i % cols) * spacing_x
            cy = start_y + (i // cols) * spacing_y
            node_coords[nid] = (cx, cy)

            svg_parts.append(
                f'<rect class="node-rect" x="{cx - 90}" y="{cy - 30}" width="180" height="60"/>'
                f'<text class="node-text" x="{cx}" y="{cy + 5}">{nlabel}</text>'
            )

        for e in edges:
            if isinstance(e, dict):
                src = str(e.get("from", e.get("source", "")))
                dst = str(e.get("to", e.get("target", "")))
                if src in node_coords and dst in node_coords:
                    x1, y1 = node_coords[src]
                    x2, y2 = node_coords[dst]
                    svg_parts.append(
                        f'<line class="edge-line" x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}"/>'
                    )

        return "\n      ".join(svg_parts)

    def observe_shadow(
        self,
        intent: str,
        proposed_spec: dict[str, Any],
        diagram_type: str = "architecture",
        jessyca_baseline_description: str = "",
    ) -> ArchifyShadowObservation:
        """Ejecuta una observación comparativa en Shadow Mode."""
        t_start = time.perf_counter()
        val = self.validate_spec(proposed_spec, diagram_type)
        latency = (time.perf_counter() - t_start) * 1000

        if not val.is_valid:
            verdict = "INVALID_SPEC"
        elif val.node_count > 0:
            verdict = "ENRICHED_VISUALIZATION"
        else:
            verdict = "CONCORDANT"

        obs = ArchifyShadowObservation(
            observation_id=f"archify_obs_{int(time.time() * 1000)}",
            intent=intent,
            diagram_type=diagram_type,
            validation_status=val.is_valid,
            nodes_count=val.node_count,
            edges_count=val.edge_count,
            jessyca_baseline=jessyca_baseline_description or "Texto / Markdown básico",
            archify_proposal=f"Diagrama interactivo {diagram_type} con {val.node_count} nodos y {val.edge_count} aristas",
            comparison_verdict=verdict,
            latency_ms=round(latency, 2),
            details={"warnings": val.warnings, "errors": val.errors},
        )

        self._shadow_history.append(obs)
        logger.info(
            f"[ARCHIFY SHADOW] Obs: {obs.observation_id} | Type: {diagram_type} | "
            f"Valid: {val.is_valid} | Verdict: {verdict}"
        )
        return obs

    def get_shadow_history(self) -> list[ArchifyShadowObservation]:
        return list(self._shadow_history)


_GLOBAL_ARCHIFY_ADAPTER: JessycaArchifyAdapter | None = None


def get_archify_adapter() -> JessycaArchifyAdapter:
    global _GLOBAL_ARCHIFY_ADAPTER
    if _GLOBAL_ARCHIFY_ADAPTER is None:
        _GLOBAL_ARCHIFY_ADAPTER = JessycaArchifyAdapter()
    return _GLOBAL_ARCHIFY_ADAPTER


def reset_archify_adapter(mode: ArchifyMode | str = ArchifyMode.CONTROLLED) -> JessycaArchifyAdapter:
    global _GLOBAL_ARCHIFY_ADAPTER
    _GLOBAL_ARCHIFY_ADAPTER = JessycaArchifyAdapter(mode=mode)
    return _GLOBAL_ARCHIFY_ADAPTER
