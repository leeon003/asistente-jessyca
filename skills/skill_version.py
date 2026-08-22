"""Módulo de versionado semántico y estados de versión de Skills (skill_version.py - Fase 33).

Proporciona la estructura SemVer formal (MAJOR.MINOR.PATCH), evaluación de restricciones de versión,
clasificación de cambios (bump types) y estados de ciclo de vida para Skills en JESSYCA 3.0.

INVARIANTES:
1. Versionado semántico estricto con soporte para pre-releases y build metadata.
2. Comparación determinista e inmutable.
3. Separación explícita entre Skill ID y Skill Version.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from functools import total_ordering
from typing import Any

# Regex robusto para SemVer 2.0.0
SEMVER_STRICT_REGEX = re.compile(
    r"^(?P<major>0|[1-9]\d*)\.(?P<minor>0|[1-9]\d*)\.(?P<patch>0|[1-9]\d*)"
    r"(?:-(?P<prerelease>[0-9a-zA-Z-]+(?:\.[0-9a-zA-Z-]+)*))?"
    r"(?:\+(?P<buildmetadata>[0-9a-zA-Z-]+(?:\.[0-9a-zA-Z-]+)*))?$"
)


class VersionBumpType(StrEnum):
    """Clasificación del tipo de incremento entre dos versiones SemVer."""

    MAJOR = "MAJOR"
    MINOR = "MINOR"
    PATCH = "PATCH"
    DOWNGRADE = "DOWNGRADE"
    SAME = "SAME"


class SkillLifecycleState(StrEnum):
    """Estados del ciclo de vida y progresión de versiones de una Skill."""

    INSTALLED = "INSTALLED"
    STAGED = "STAGED"
    TESTING = "TESTING"
    ACTIVE = "ACTIVE"
    DEPRECATED = "DEPRECATED"
    ROLLED_BACK = "ROLLED_BACK"
    DISABLED = "DISABLED"


@total_ordering
@dataclass(frozen=True)
class SemVer:
    """Representación formal, inmutable y ordenable de una versión SemVer 2.0.0."""

    major: int
    minor: int
    patch: int
    prerelease: str | None = None
    build: str | None = None

    @classmethod
    def parse(cls, version_str: str) -> SemVer:
        """Parsea una cadena de versión en una instancia SemVer válida."""
        clean = version_str.strip()
        if clean.startswith("v") or clean.startswith("V"):
            clean = clean[1:]

        match = SEMVER_STRICT_REGEX.match(clean)
        if not match:
            # Tolerancia para versiones abreviadas simples (ej: "1.0")
            parts = clean.split(".")
            if len(parts) == 2 and all(p.isdigit() for p in parts):
                return cls(major=int(parts[0]), minor=int(parts[1]), patch=0)
            elif len(parts) == 1 and parts[0].isdigit():
                return cls(major=int(parts[0]), minor=0, patch=0)
            raise ValueError(f"Formato SemVer inválido: '{version_str}'. Debe seguir MAJOR.MINOR.PATCH.")

        gd = match.groupdict()
        return cls(
            major=int(gd["major"]),
            minor=int(gd["minor"]),
            patch=int(gd["patch"]),
            prerelease=gd.get("prerelease"),
            build=gd.get("buildmetadata"),
        )

    def __str__(self) -> str:
        base = f"{self.major}.{self.minor}.{self.patch}"
        if self.prerelease:
            base += f"-{self.prerelease}"
        if self.build:
            base += f"+{self.build}"
        return base

    def __repr__(self) -> str:
        return f"SemVer({self})"

    def _compare_tuple(self) -> tuple[int, int, int, int, str]:
        # Pre-releases have lower precedence than regular releases (1 if no prerelease, 0 if prerelease)
        has_no_pre = 1 if self.prerelease is None else 0
        pre_str = self.prerelease or ""
        return (self.major, self.minor, self.patch, has_no_pre, pre_str)

    def __eq__(self, other: Any) -> bool:
        if not isinstance(other, SemVer):
            if isinstance(other, str):
                try:
                    other = SemVer.parse(other)
                except ValueError:
                    return False
            else:
                return False
        return (self.major, self.minor, self.patch, self.prerelease) == (
            other.major,
            other.minor,
            other.patch,
            other.prerelease,
        )

    def __lt__(self, other: Any) -> bool:
        if not isinstance(other, SemVer):
            if isinstance(other, str):
                try:
                    other = SemVer.parse(other)
                except ValueError:
                    return False
            else:
                return False
        return bool(self._compare_tuple() < other._compare_tuple())

    def is_patch_of(self, other: SemVer | str) -> bool:
        """Indica si esta versión es un incremento PATCH respecto a other (mismo major y minor, patch mayor)."""
        target = other if isinstance(other, SemVer) else SemVer.parse(other)
        return (
            self.major == target.major
            and self.minor == target.minor
            and self.patch > target.patch
        )

    def is_minor_of(self, other: SemVer | str) -> bool:
        """Indica si esta versión es un incremento MINOR respecto a other (mismo major, minor mayor)."""
        target = other if isinstance(other, SemVer) else SemVer.parse(other)
        return self.major == target.major and self.minor > target.minor

    def is_major_of(self, other: SemVer | str) -> bool:
        """Indica si esta versión es un incremento MAJOR respecto a other (major mayor)."""
        target = other if isinstance(other, SemVer) else SemVer.parse(other)
        return self.major > target.major

    def is_downgrade_of(self, other: SemVer | str) -> bool:
        """Indica si esta versión es menor que other."""
        target = other if isinstance(other, SemVer) else SemVer.parse(other)
        return self < target

    def is_same_version(self, other: SemVer | str) -> bool:
        """Indica si ambas versiones son idénticas en major, minor, patch y prerelease."""
        target = other if isinstance(other, SemVer) else SemVer.parse(other)
        return self == target

    def bump_type_from(self, previous: SemVer | str) -> VersionBumpType:
        """Determina el tipo de incremento respecto a una versión previa."""
        prev = previous if isinstance(previous, SemVer) else SemVer.parse(previous)
        if self == prev:
            return VersionBumpType.SAME
        if self < prev:
            return VersionBumpType.DOWNGRADE
        if self.is_major_of(prev):
            return VersionBumpType.MAJOR
        if self.is_minor_of(prev):
            return VersionBumpType.MINOR
        return VersionBumpType.PATCH

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": str(self),
            "major": self.major,
            "minor": self.minor,
            "patch": self.patch,
            "prerelease": self.prerelease,
            "build": self.build,
        }


class SemVerConstraint:
    """Evaluador formal de restricciones de versión SemVer."""

    def __init__(self, raw_constraint: str) -> None:
        self.raw_constraint = raw_constraint.strip()
        self._matchers = self._compile_matchers(self.raw_constraint)

    def matches(self, version: SemVer | str) -> bool:
        """Comprueba si una versión satisface la restricción."""
        v = version if isinstance(version, SemVer) else SemVer.parse(version)
        if not self._matchers:
            return True
        return all(fn(v) for fn in self._matchers)

    def _compile_matchers(self, expr: str) -> list[Any]:
        if not expr or expr in ("*", "any", "latest"):
            return []

        # Separar por comas si hay múltiples cláusulas (ej: ">=1.0.0, <2.0.0")
        clauses = [c.strip() for c in expr.split(",") if c.strip()]
        matchers = []

        for clause in clauses:
            # 1. Caret operator: ^1.2.3 (compatible con 1.x.x >= 1.2.3, no major bump)
            if clause.startswith("^"):
                target = SemVer.parse(clause[1:])
                def make_caret(tgt: SemVer) -> Any:
                    if tgt.major > 0:
                        return lambda v: v >= tgt and v.major == tgt.major
                    elif tgt.minor > 0:
                        return lambda v: v >= tgt and v.major == 0 and v.minor == tgt.minor
                    return lambda v: v == tgt
                matchers.append(make_caret(target))

            # 2. Tilde operator: ~1.2.3 (compatible con 1.2.x >= 1.2.3, no minor bump)
            elif clause.startswith("~"):
                target = SemVer.parse(clause[1:])
                def make_tilde(tgt: SemVer) -> Any:
                    return lambda v: v >= tgt and v.major == tgt.major and v.minor == tgt.minor
                matchers.append(make_tilde(target))

            # 3. >=, <=, >, <, ==
            elif clause.startswith(">="):
                target = SemVer.parse(clause[2:])
                matchers.append(lambda v, tgt=target: v >= tgt)
            elif clause.startswith("<="):
                target = SemVer.parse(clause[2:])
                matchers.append(lambda v, tgt=target: v <= tgt)
            elif clause.startswith(">"):
                target = SemVer.parse(clause[1:])
                matchers.append(lambda v, tgt=target: v > tgt)
            elif clause.startswith("<"):
                target = SemVer.parse(clause[1:])
                matchers.append(lambda v, tgt=target: v < tgt)
            elif clause.startswith("==") or clause.startswith("="):
                eq_part = clause[2:] if clause.startswith("==") else clause[1:]
                target = SemVer.parse(eq_part)
                matchers.append(lambda v, tgt=target: v == tgt)
            else:
                # Default: versión exacta o prefijo
                try:
                    target = SemVer.parse(clause)
                    matchers.append(lambda v, tgt=target: v >= tgt)
                except ValueError:
                    pass

        return matchers
