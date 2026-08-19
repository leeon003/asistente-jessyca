"""Módulo de tokens de cancelación para retrocompatibilidad.

Exporta CancellationToken.
"""

from __future__ import annotations

from core.emergency_stop import CancellationToken

__all__ = ["CancellationToken"]
