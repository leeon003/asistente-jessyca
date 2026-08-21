"""Capacidades granulares de navegación web (browser_capabilities.py - Fase 14: Browser Agent).

Define las capacidades independientes para BrowserAgent, evitando otorgar permisos totales automáticamente.
"""

from __future__ import annotations

from enum import StrEnum


class BrowserCapability(StrEnum):
    """Capacidades granulares de automatización web."""

    BROWSER_NAVIGATE = "BROWSER_NAVIGATE"
    BROWSER_READ = "BROWSER_READ"
    BROWSER_CLICK = "BROWSER_CLICK"
    BROWSER_TYPE = "BROWSER_TYPE"
    BROWSER_SUBMIT = "BROWSER_SUBMIT"
    BROWSER_BACK = "BROWSER_BACK"
    BROWSER_SCROLL = "BROWSER_SCROLL"


# Perfiles predefinidos de capacidades
READ_ONLY_BROWSER_CAPABILITIES: frozenset[BrowserCapability] = frozenset({
    BrowserCapability.BROWSER_NAVIGATE,
    BrowserCapability.BROWSER_READ,
    BrowserCapability.BROWSER_BACK,
    BrowserCapability.BROWSER_SCROLL,
})

INTERACTIVE_BROWSER_CAPABILITIES: frozenset[BrowserCapability] = frozenset({
    BrowserCapability.BROWSER_NAVIGATE,
    BrowserCapability.BROWSER_READ,
    BrowserCapability.BROWSER_CLICK,
    BrowserCapability.BROWSER_TYPE,
    BrowserCapability.BROWSER_SUBMIT,
    BrowserCapability.BROWSER_BACK,
    BrowserCapability.BROWSER_SCROLL,
})
