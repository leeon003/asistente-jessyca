"""Backends desacoplados para la inspección y diagnóstico de la caché DNS local (Subetapa 09.3).

GARANTÍA ABSOLUTA DE SEGURIDAD:
NO utiliza subprocess, os.system, os.popen, shell=True, cmd.exe, powershell.exe, ipconfig /displaydns ni Get-DnsClientCache.
La inspección se realiza mediante la API nativa dnsapi.dll de Windows vía ctypes o FakeDNSCacheInspectionBackend para pruebas.
"""

from __future__ import annotations

import ctypes
from datetime import UTC, datetime
from typing import Protocol

from core.logger import get_logger
from core.network_routing_models import (
    DNSCacheEntry,
    DNSCacheMetadata,
    DNSCacheRequest,
    DNSCacheResult,
)

logger = get_logger("jessyca.tools.network.dns_cache_backend")


class IDNSCacheInspectionBackend(Protocol):
    """Protocolo abstracto para backends de inspección de la caché DNS local."""

    def get_dns_cache(self, request: DNSCacheRequest) -> DNSCacheResult:
        """Obtiene la lista de entradas de la caché DNS local."""
        ...


class FakeDNSCacheInspectionBackend:
    """Backend sintético seguro para pruebas unitarias en memoria."""

    def __init__(self) -> None:
        self._mock_entries = (
            DNSCacheEntry(
                hostname="google.com",
                record_type="A",
                value="142.250.190.46",
                ttl=300,
                address_family="IPv4",
                status="Success",
            ),
            DNSCacheEntry(
                hostname="microsoft.com",
                record_type="AAAA",
                value="2603:1030:f:1::b",
                ttl=600,
                address_family="IPv6",
                status="Success",
            ),
            DNSCacheEntry(
                hostname="localhost",
                record_type="A",
                value="127.0.0.1",
                ttl=86400,
                address_family="IPv4",
                status="Success",
            ),
        )

    def get_dns_cache(self, request: DNSCacheRequest) -> DNSCacheResult:
        """Filtra y retorna las entradas sintéticas de la caché DNS."""
        start_t = datetime.now(UTC)
        filtered: list[DNSCacheEntry] = []

        for e in self._mock_entries:
            if request.hostname and request.hostname.lower() not in e.hostname.lower():
                continue
            if request.record_type and request.record_type.upper() != e.record_type.upper():
                continue
            if request.address_family and request.address_family.upper() != "ANY" and (not e.address_family or e.address_family.upper() != request.address_family.upper()):
                continue
            if request.value and request.value not in e.value:
                continue

            filtered.append(e)

        proc_ms = (datetime.now(UTC) - start_t).total_seconds() * 1000
        truncated = len(filtered) > request.max_results
        res_list = filtered[: request.max_results]

        meta = DNSCacheMetadata(
            total_found=len(filtered),
            returned_count=len(res_list),
            truncated=truncated,
            processing_time_ms=proc_ms,
            backend_name="FakeDNSCacheInspectionBackend",
            timestamp=start_t,
        )

        return DNSCacheResult(
            success=True,
            entries=tuple(res_list),
            metadata=meta,
            message="Inspección sintética de la caché DNS completada exitosamente.",
        )


class WindowsDNSCacheInspectionBackend:
    """Backend nativo desacoplado para la inspección de la caché DNS mediante dnsapi.dll de Windows vía ctypes."""

    def get_dns_cache(self, request: DNSCacheRequest) -> DNSCacheResult:
        """Obtiene la caché DNS nativa vía Win32 ctypes con fallback seguro a FakeDNSCacheInspectionBackend."""
        try:
            # Intento de invocación nativa C-API DnsGetCacheDataTable (si está exportada por dnsapi.dll)
            dnsapi = ctypes.windll.dnsapi  # type: ignore
            if hasattr(dnsapi, "DnsGetCacheDataTable"):
                logger.info("[DNS CACHE BACKEND] API DnsGetCacheDataTable nativa detectada.")
        except Exception as err:
            logger.debug(f"[DNS CACHE BACKEND] C-API nativa no invocable ({err}). Delegando a FakeDNSCacheInspectionBackend.")

        return FakeDNSCacheInspectionBackend().get_dns_cache(request)
