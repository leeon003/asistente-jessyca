"""Capabilities integradas declarativas (Built-in Declarative Capabilities - Subetapa 06.1).

Proporciona únicamente las definiciones de metadatos declarativos para las futuras herramientas
de Jessyca Windows MCP.

GARANTÍA ABSOLUTA DE SEGURIDAD:
Este archivo contiene ÚNICAMENTE METADATOS DECLARATIVOS.
NO ejecuta herramientas reales de Windows, NO invoca subprocess, NO invoca PowerShell,
NO invoca CMD, NO invoca ctypes ni APIs del sistema operativo.
"""

from __future__ import annotations

from core.capabilities import (
    CapabilityDecision,
    CapabilityOperation,
    CapabilityRiskLevel,
    CapabilitySource,
    CapabilityStatus,
    ToolCapability,
)
from core.capability_registry import ICapabilityRegistry, get_capability_registry
from core.logger import get_logger

logger = get_logger("jessyca.core.builtin_capabilities")


def get_builtin_capabilities() -> list[ToolCapability]:
    """Retorna las definiciones declarativas integradas de capacidades para herramientas Windows."""
    capabilities: list[ToolCapability] = [
        # 1. Herramientas de Archivos (windows.files)
        ToolCapability(
            capability_id="cap_windows_files_v1",
            tool_name="windows.files",
            display_name="Windows File System Capability",
            description="Metadatos declarativos para operaciones seguras en el sistema de archivos de Windows.",
            version="1.0.0",
            source=CapabilitySource.BUILTIN,
            status=CapabilityStatus.ENABLED,
            is_immutable=True,
            operations=(
                CapabilityOperation(
                    operation_id="op_files_list",
                    name="list_directory",
                    description="Listar contenido de directorios.",
                    risk_level=CapabilityRiskLevel.SAFE,
                    decision=CapabilityDecision.ALLOW,
                ),
                CapabilityOperation(
                    operation_id="op_files_read",
                    name="read_file",
                    description="Leer contenido de un archivo.",
                    risk_level=CapabilityRiskLevel.SAFE,
                    decision=CapabilityDecision.ALLOW,
                ),
                CapabilityOperation(
                    operation_id="op_files_write",
                    name="write_file",
                    description="Escribir contenido en un archivo.",
                    risk_level=CapabilityRiskLevel.WARNING,
                    decision=CapabilityDecision.REQUIRE_CONFIRMATION,
                    requires_confirmation=True,
                ),
                CapabilityOperation(
                    operation_id="op_files_delete",
                    name="delete_file",
                    description="Eliminar un archivo del sistema.",
                    risk_level=CapabilityRiskLevel.DANGEROUS,
                    decision=CapabilityDecision.REQUIRE_CONFIRMATION,
                    requires_confirmation=True,
                ),
            ),
        ),
        # 2. Herramientas de Procesos (windows.process)
        ToolCapability(
            capability_id="cap_windows_process_v1",
            tool_name="windows.process",
            display_name="Windows Process Capability",
            description="Metadatos declarativos para inspección y gestión de procesos en Windows.",
            version="1.0.0",
            source=CapabilitySource.BUILTIN,
            status=CapabilityStatus.ENABLED,
            is_immutable=True,
            operations=(
                CapabilityOperation(
                    operation_id="op_process_list",
                    name="list_processes",
                    description="Listar procesos activos.",
                    risk_level=CapabilityRiskLevel.SAFE,
                    decision=CapabilityDecision.ALLOW,
                ),
                CapabilityOperation(
                    operation_id="op_process_info",
                    name="get_process_info",
                    description="Obtener detalles de un proceso.",
                    risk_level=CapabilityRiskLevel.SAFE,
                    decision=CapabilityDecision.ALLOW,
                ),
                CapabilityOperation(
                    operation_id="op_process_kill",
                    name="terminate_process",
                    description="Terminar un proceso activo.",
                    risk_level=CapabilityRiskLevel.DANGEROUS,
                    decision=CapabilityDecision.REQUIRE_CONFIRMATION,
                    requires_confirmation=True,
                ),
            ),
        ),
        # 3. Herramientas de Registro (windows.registry)
        ToolCapability(
            capability_id="cap_windows_registry_v1",
            tool_name="windows.registry",
            display_name="Windows Registry Capability",
            description="Metadatos declarativos para la inspección y modificación del registro de Windows.",
            version="1.0.0",
            source=CapabilitySource.BUILTIN,
            status=CapabilityStatus.ENABLED,
            is_immutable=True,
            operations=(
                CapabilityOperation(
                    operation_id="op_registry_read",
                    name="read_registry",
                    description="Leer clave del registro.",
                    risk_level=CapabilityRiskLevel.SAFE,
                    decision=CapabilityDecision.ALLOW,
                ),
                CapabilityOperation(
                    operation_id="op_registry_write",
                    name="write_registry",
                    description="Escribir o modificar clave del registro.",
                    risk_level=CapabilityRiskLevel.DANGEROUS,
                    decision=CapabilityDecision.REQUIRE_CONFIRMATION,
                    requires_confirmation=True,
                ),
            ),
        ),
        # 4. Herramientas de Servicios (windows.services)
        ToolCapability(
            capability_id="cap_windows_services_v1",
            tool_name="windows.services",
            display_name="Windows Services Capability",
            description="Metadatos declarativos para inspección de servicios del sistema Windows.",
            version="1.0.0",
            source=CapabilitySource.BUILTIN,
            status=CapabilityStatus.ENABLED,
            is_immutable=True,
            operations=(
                CapabilityOperation(
                    operation_id="op_services_list",
                    name="list_services",
                    description="Listar servicios de Windows.",
                    risk_level=CapabilityRiskLevel.SAFE,
                    decision=CapabilityDecision.ALLOW,
                ),
                CapabilityOperation(
                    operation_id="op_services_status",
                    name="get_service_status",
                    description="Obtener estado de un servicio.",
                    risk_level=CapabilityRiskLevel.SAFE,
                    decision=CapabilityDecision.ALLOW,
                ),
                CapabilityOperation(
                    operation_id="op_services_restart",
                    name="restart_service",
                    description="Reiniciar un servicio del sistema.",
                    risk_level=CapabilityRiskLevel.DANGEROUS,
                    decision=CapabilityDecision.REQUIRE_CONFIRMATION,
                    requires_confirmation=True,
                ),
            ),
        ),
        # 5. Herramientas de Shell (windows.shell)
        ToolCapability(
            capability_id="cap_windows_shell_v1",
            tool_name="windows.shell",
            display_name="Windows Shell Execution Capability",
            description="Metadatos declarativos para comandos shell. Clasificado como CRITICAL / DENY.",
            version="1.0.0",
            source=CapabilitySource.BUILTIN,
            status=CapabilityStatus.ENABLED,
            is_immutable=True,
            operations=(
                CapabilityOperation(
                    operation_id="op_shell_evaluate",
                    name="evaluate_command",
                    description="Evaluación declarativa de políticas de comandos shell sin ejecución.",
                    risk_level=CapabilityRiskLevel.SAFE,
                    decision=CapabilityDecision.ALLOW,
                ),
                CapabilityOperation(
                    operation_id="op_shell_exec",
                    name="execute_command",
                    description="Ejecución de línea de comandos shell.",
                    risk_level=CapabilityRiskLevel.CRITICAL,
                    decision=CapabilityDecision.REQUIRE_ELEVATED_AUTHORIZATION,
                    requires_elevation=True,
                    requires_confirmation=True,
                ),
            ),
        ),
        # 6. Herramientas de Escritorio (windows.desktop)
        ToolCapability(
            capability_id="cap_windows_desktop_v1",
            tool_name="windows.desktop",
            display_name="Windows Desktop Capability",
            description="Metadatos declarativos para automatización e inspección del escritorio.",
            version="1.0.0",
            source=CapabilitySource.BUILTIN,
            status=CapabilityStatus.ENABLED,
            is_immutable=True,
            operations=(
                CapabilityOperation(
                    operation_id="op_desktop_window",
                    name="get_active_window",
                    description="Obtener nombre de la ventana activa.",
                    risk_level=CapabilityRiskLevel.SAFE,
                    decision=CapabilityDecision.ALLOW,
                ),
                CapabilityOperation(
                    operation_id="op_desktop_screenshot",
                    name="take_screenshot",
                    description="Capturar pantalla del escritorio.",
                    risk_level=CapabilityRiskLevel.WARNING,
                    decision=CapabilityDecision.REQUIRE_CONFIRMATION,
                    requires_confirmation=True,
                ),
                CapabilityOperation(
                    operation_id="op_desktop_ocr",
                    name="ocr_screen",
                    description="Extracción segura de texto OCR desde regiones del escritorio.",
                    risk_level=CapabilityRiskLevel.WARNING,
                    decision=CapabilityDecision.REQUIRE_CONFIRMATION,
                    requires_confirmation=True,
                ),
                CapabilityOperation(
                    operation_id="op_desktop_inspect_ui",
                    name="inspect_ui_element",
                    description="Inspección visual segura de elementos UI y jerarquía del escritorio.",
                    risk_level=CapabilityRiskLevel.WARNING,
                    decision=CapabilityDecision.REQUIRE_CONFIRMATION,
                    requires_confirmation=True,
                ),
                CapabilityOperation(
                    operation_id="op_desktop_click",
                    name="click_element",
                    description="Ejecución de clic controlado sobre un elemento UI del escritorio.",
                    risk_level=CapabilityRiskLevel.DANGEROUS,
                    decision=CapabilityDecision.REQUIRE_CONFIRMATION,
                    requires_confirmation=True,
                ),
                CapabilityOperation(
                    operation_id="op_desktop_type",
                    name="type_text",
                    description="Escritura controlada de texto sobre un campo o elemento UI del escritorio.",
                    risk_level=CapabilityRiskLevel.DANGEROUS,
                    decision=CapabilityDecision.REQUIRE_CONFIRMATION,
                    requires_confirmation=True,
                ),
                CapabilityOperation(
                    operation_id="op_desktop_focus",
                    name="focus_window",
                    description="Enfoque y activación de una ventana del escritorio.",
                    risk_level=CapabilityRiskLevel.WARNING,
                    decision=CapabilityDecision.REQUIRE_CONFIRMATION,
                    requires_confirmation=True,
                ),
                CapabilityOperation(
                    operation_id="op_desktop_drag_drop",
                    name="drag_and_drop",
                    description="Operación acotada de arrastrar y soltar entre coordenadas de pantalla.",
                    risk_level=CapabilityRiskLevel.DANGEROUS,
                    decision=CapabilityDecision.REQUIRE_CONFIRMATION,
                    requires_confirmation=True,
                ),
            ),
        ),
        Capability(
            tool_name="windows.network",
            description="Inspección segura de diagnóstico de adaptadores e interfaces de red en Windows.",
            category=CapabilityCategory.SYSTEM,
            risk_level=CapabilityRiskLevel.SAFE,
            operations=(
                CapabilityOperation(
                    operation_id="op_net_get_interfaces",
                    name="get_network_interfaces",
                    description="Inspección de diagnóstico de adaptadores, IPs, pasarelas y DNS de red en Windows.",
                    risk_level=CapabilityRiskLevel.SAFE,
                    decision=CapabilityDecision.ALLOW,
                    requires_confirmation=False,
                ),
                CapabilityOperation(
                    operation_id="op_net_get_active_connections",
                    name="get_active_connections",
                    description="Inspección de diagnóstico de conexiones de red activas (TCP/UDP).",
                    risk_level=CapabilityRiskLevel.SAFE,
                    decision=CapabilityDecision.ALLOW,
                    requires_confirmation=False,
                ),
                CapabilityOperation(
                    operation_id="op_net_get_listening_ports",
                    name="get_listening_ports",
                    description="Inspección de diagnóstico de puertos en escucha y sockets bindados.",
                    risk_level=CapabilityRiskLevel.SAFE,
                    decision=CapabilityDecision.ALLOW,
                    requires_confirmation=False,
                ),
                CapabilityOperation(
                    operation_id="op_net_get_routing_table",
                    name="get_routing_table",
                    description="Inspección de diagnóstico de la tabla de ruteo IP del sistema.",
                    risk_level=CapabilityRiskLevel.SAFE,
                    decision=CapabilityDecision.ALLOW,
                    requires_confirmation=False,
                ),
                CapabilityOperation(
                    operation_id="op_net_get_dns_cache",
                    name="get_dns_cache",
                    description="Inspección de diagnóstico de la caché DNS local del sistema.",
                    risk_level=CapabilityRiskLevel.SAFE,
                    decision=CapabilityDecision.ALLOW,
                    requires_confirmation=False,
                ),
            ),
        ),
    ]

    return capabilities


def register_builtin_capabilities(registry: ICapabilityRegistry | None = None) -> None:
    """Registra todas las capabilities integradas declarativas en el CapabilityRegistry."""
    target_registry = registry or get_capability_registry()
    for cap in get_builtin_capabilities():
        if not target_registry.has_tool(cap.tool_name):
            target_registry.register(cap)
    logger.info("Capabilities integradas declarativas registradas en el CapabilityRegistry.")
