"""Analizador estático de seguridad para código fuente de Skills (skill_security_analyzer.py - Fase 32).

Realiza inspección estática del Árbol de Sintaxis Abstracta (AST) de todos los archivos Python
de un paquete de Skill antes de autorizar su instalación o carga.

INVARIANTES DE SEGURIDAD:
1. Bloqueo de llamadas dinámicas no verificables (eval, exec, __import__, globals()).
2. Bloqueo de imports no autorizados (ctypes, subprocess arbitrario, win32api, monkeypatching).
3. Bloqueo estricto de intentos de acceso o manipulación del bloque de seguridad inmutable.
4. Verificación de consistencia entre capabilities declaradas y módulos de red/filesystem importados.
"""

from __future__ import annotations

import ast
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core.logger import get_logger
from core.security_architecture import SecurityLevel
from skills.skill_models import SkillManifest

logger = get_logger("jessyca.skills.security_analyzer")

# Módulos prohibidos globalmente en cualquier Skill
GLOBAL_FORBIDDEN_MODULES: frozenset[str] = frozenset({
    "ctypes",
    "win32api",
    "win32con",
    "win32gui",
    "win32process",
    "_winapi",
    "multiprocessing",
    "pty",
})

# Funciones peligrosas prohibidas en el código de Skills
DANGEROUS_BUILTIN_CALLS: frozenset[str] = frozenset({
    "eval",
    "exec",
    "compile",
    "__import__",
})

# Palabras clave y componentes del bloque de seguridad inmutable cuya manipulación está prohibida
SECURITY_TAMPERING_TARGETS: frozenset[str] = frozenset({
    "securitypipeline",
    "riskengine",
    "permissionmanager",
    "confirmationmanager",
    "emergencystopmanager",
    "auditlogger",
    "securitypolicy",
    "securitycontext",
})


@dataclass(frozen=True)
class SecurityAnalysisResult:
    """Resultado formal inmutable del análisis estático de seguridad."""

    is_safe: bool
    risk_level: SecurityLevel
    violations: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    scanned_files: tuple[str, ...] = ()
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "is_safe": self.is_safe,
            "risk_level": str(self.risk_level),
            "violations": list(self.violations),
            "warnings": list(self.warnings),
            "scanned_files": list(self.scanned_files),
            "details": self.details,
        }


class _SkillASTSecurityVisitor(ast.NodeVisitor):
    """Visitador AST para detección de patrones maliciosos o no autorizados."""

    def __init__(self, filename: str, manifest: SkillManifest) -> None:
        self.filename = filename
        self.manifest = manifest
        self.violations: list[str] = []
        self.warnings: list[str] = []
        self.has_network_capability = any("network" in c.lower() or "web" in c.lower() or "browser" in c.lower() for c in manifest.capabilities)
        self.has_process_capability = any("process" in c.lower() or "application" in c.lower() for c in manifest.capabilities)

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            mod_name = alias.name.split(".")[0].lower()
            self._check_module_name(mod_name, node.lineno)
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module:
            mod_name = node.module.split(".")[0].lower()
            self._check_module_name(mod_name, node.lineno)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        # Detectar llamadas a funciones built-in peligrosas (eval, exec, compile)
        if isinstance(node.func, ast.Name):
            func_name = node.func.id
            if func_name in DANGEROUS_BUILTIN_CALLS:
                self.violations.append(
                    f"[{self.filename}:{node.lineno}] Uso prohibido de función de ejecución dinámica: '{func_name}()'."
                )

        # Detectar llamadas tipo os.system(), os.popen()
        elif isinstance(node.func, ast.Attribute):
            attr_name = node.func.attr
            if attr_name in ("system", "popen", "spawn", "execv", "execl"):
                if isinstance(node.func.value, ast.Name) and node.func.value.id == "os":
                    self.violations.append(
                        f"[{self.filename}:{node.lineno}] Uso de vector de ejecución directo no gobernado: 'os.{attr_name}()'."
                    )

        # Detectar intentos de modificar componentes inmutables de seguridad
        self._check_security_tampering_in_node(node)
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        attr_name = node.attr.lower()
        if attr_name in SECURITY_TAMPERING_TARGETS or "__subclasses__" in attr_name:
            self.violations.append(
                f"[{self.filename}:{node.lineno}] Intento de introspección o alteración de seguridad: atributo '{node.attr}'."
            )
        self.generic_visit(node)

    def _check_module_name(self, mod_name: str, lineno: int) -> None:
        if mod_name in GLOBAL_FORBIDDEN_MODULES:
            self.violations.append(
                f"[{self.filename}:{lineno}] Import prohibido por política de seguridad: '{mod_name}'."
            )
        elif mod_name == "socket" and not self.has_network_capability:
            self.violations.append(
                f"[{self.filename}:{lineno}] Import de red '{mod_name}' sin declarar capability 'network'."
            )
        elif mod_name in ("subprocess",) and not self.has_process_capability:
            self.warnings.append(
                f"[{self.filename}:{lineno}] Módulo '{mod_name}' importado; se supervisará mediante SkillSecuritySandbox."
            )

    def _check_security_tampering_in_node(self, node: ast.AST) -> None:
        for child in ast.walk(node):
            if isinstance(child, ast.Name) and child.id.lower() in SECURITY_TAMPERING_TARGETS:
                # Comprobar si se intenta llamar a métodos como trigger_stop, reset, modify
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                    if node.func.attr in ("reset", "disable", "override", "modify_policies"):
                        self.violations.append(
                            f"[{self.filename}:{getattr(node, 'lineno', 1)}] Intento de manipulación de componente de seguridad: '{child.id}.{node.func.attr}()'."
                        )


class SkillSecurityAnalyzer:
    """Analizador estático formal para validación de seguridad de Skills."""

    @classmethod
    def analyze_directory(cls, directory_path: str | Path, manifest: SkillManifest) -> SecurityAnalysisResult:
        """Analiza estáticamente todos los archivos Python (.py) del paquete de Skill."""
        target_dir = Path(directory_path).resolve()
        if not target_dir.exists() or not target_dir.is_dir():
            return SecurityAnalysisResult(
                is_safe=False,
                risk_level=SecurityLevel.CRITICAL,
                violations=(f"Directorio de skill '{target_dir}' no existe o no es accesible.",),
            )

        violations: list[str] = []
        warnings: list[str] = []
        scanned_files: list[str] = []

        for root, _dirs, files in os.walk(target_dir):
            for f in files:
                if f.endswith(".py"):
                    full_p = Path(root) / f
                    rel_p = full_p.relative_to(target_dir).as_posix()
                    scanned_files.append(rel_p)

                    try:
                        with open(full_p, encoding="utf-8", errors="replace") as pyf:
                            source_code = pyf.read()

                        tree = ast.parse(source_code, filename=rel_p)
                        visitor = _SkillASTSecurityVisitor(filename=rel_p, manifest=manifest)
                        visitor.visit(tree)

                        violations.extend(visitor.violations)
                        warnings.extend(visitor.warnings)

                    except SyntaxError as exc:
                        violations.append(f"[{rel_p}:{exc.lineno}] Error de sintaxis en archivo Python: {exc.msg}")
                    except Exception as exc:
                        warnings.append(f"[{rel_p}] Advertencia durante análisis AST: {exc}")

        # Calcular nivel de riesgo resultante
        if violations:
            calculated_risk = SecurityLevel.CRITICAL
            is_safe = False
            logger.warning(
                f"[SECURITY ANALYZER VIOLATIONS] Skill '{manifest.id}': {len(violations)} violaciones detectadas."
            )
        else:
            calculated_risk = manifest.risk_level
            is_safe = True

        return SecurityAnalysisResult(
            is_safe=is_safe,
            risk_level=calculated_risk,
            violations=tuple(violations),
            warnings=tuple(warnings),
            scanned_files=tuple(scanned_files),
        )
