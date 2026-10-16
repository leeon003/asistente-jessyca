"""Sistema de configuración tipado basado en Pydantic BaseSettings para Jessyca Windows MCP.

Soporta lectura automática de variables de entorno desde archivos .env y del sistema operativo.
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_ENVIRONMENT = "development"
DEFAULT_LOG_LEVEL = "INFO"
DEFAULT_MCP_SERVER_NAME = "jessyca-windows-mcp"
VALID_MODEL_ROUTER_MODES = ("static", "shadow", "controlled", "experimental")


class EnvironmentMode(StrEnum):
    """Entornos de ejecución de la aplicación."""

    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"
    TESTING = "testing"


class LogLevel(StrEnum):
    """Niveles de registro para el sistema de logging centralizado."""

    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"



class AppSettings(BaseSettings):
    """Modelo de configuración principal de la aplicación."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Entorno y Logging
    ENVIRONMENT: EnvironmentMode = Field(
        default=EnvironmentMode.DEVELOPMENT,
        description="Entorno de ejecución (development, staging, production, testing).",
    )
    LOG_LEVEL: LogLevel = Field(
        default=LogLevel.INFO,
        description="Nivel de logging del sistema centralizado.",
    )
    LOG_FILE_PATH: Path | None = Field(
        default=None,
        description="Ruta personalizada para guardar los archivos de registro.",
    )

    # Feature Flag: Motor Agéntico Autónomo JESSYCA 4.0 (Fase 3: Patrones SAI)
    ENABLE_AUTONOMOUS_AGENT_ENGINE: bool = Field(
        default=True,
        description="Habilita el motor agéntico autónomo (Fase 3: JESSYCA 4.0 con patrones SAI).",
    )

    # Configuración de Auditoría de Seguridad (Subetapa 04.6)
    AUDIT_ENABLED: bool = Field(
        default=True,
        description="Habilita el registro estructurado de auditoría de seguridad.",
    )
    AUDIT_DIRECTORY: Path = Field(
        default=Path("logs/audit"),
        description="Directorio para los archivos de auditoría estructurados (.jsonl).",
    )
    AUDIT_MAX_FILE_SIZE: int = Field(
        default=10485760,  # 10 MB
        description="Tamaño máximo por archivo de auditoría en bytes antes de rotar.",
    )
    AUDIT_BACKUP_COUNT: int = Field(
        default=5,
        description="Cantidad máxima de archivos rotados de auditoría a conservar.",
    )
    AUDIT_FAILURE_MODE: str = Field(
        default="BEST_EFFORT",
        description="Modo de fallo de auditoría (BEST_EFFORT o FAIL_CLOSED).",
    )

    # Configuración MCP Server
    MCP_SERVER_NAME: str = Field(
        default=DEFAULT_MCP_SERVER_NAME,
        description="Nombre identificador del servidor MCP.",
    )
    MCP_SERVER_VERSION: str = Field(
        default="0.5.1",
        description="Versión del servidor MCP.",
    )
    MCP_SERVER_HOST: str = Field(
        default="127.0.0.1",
        description="Host local donde se expone o comunica el servidor MCP.",
    )
    MCP_SERVER_PORT: int = Field(
        default=8000,
        description="Puerto para la comunicación del servidor MCP.",
    )
    MCP_TRANSPORT: str = Field(
        default="stdio",
        description="Mecanismo de transporte MCP por defecto.",
    )
    MCP_DEMO_TRANSPORT: str = Field(
        default="streamable-http",
        description="Mecanismo de transporte MCP para modo DEMO interactivo (streamable-http, sse, http).",
    )
    MCP_EXTERNAL_TRANSPORT: str = Field(
        default="stdio",
        description="Mecanismo de transporte MCP para clientes externos dedicados (stdio).",
    )
    MCP_ENABLED: bool = Field(
        default=True,
        description="Indica si el servidor MCP se encuentra habilitado.",
    )

    # Configuración de JDE Runtime Binding (Fase 1)
    JDE_RUNTIME_MODE: str = Field(
        default="CONTROLLED",
        description="Modo de ejecución del JDE Runtime Binding (SHADOW, CONTROLLED, ACTIVE).",
    )

    # Configuración de ARE (Autonomous Reasoning Engine) Runtime Mode
    ARE_RUNTIME_MODE: str = Field(
        default="CONTROLLED",
        description="Modo de ejecución de ARE (DISABLED, SHADOW, CONTROLLED, ACTIVE).",
    )

    # Configuración de Intent Engine (JESSYCA 4.0 / Patrones SAI)
    INTENT_ENGINE_MODE: str = Field(
        default="legacy",
        description="Modo del motor de intenciones: legacy (regex original), shadow (ejecuta SAI en paralelo para métricas sin alterar flujo), sai (activo con descomposición y catálogo progresivo).",
    )

    # Configuración de Sistema de Archivos Seguro (Subetapa 06.2)
    FILESYSTEM_SANDBOX_ROOT: Path = Field(
        default=Path("sandbox"),
        description="Directorio raíz del sandbox para operaciones de sistema de archivos.",
    )
    FILESYSTEM_MAX_READ_SIZE: int = Field(
        default=5242880,  # 5 MB
        description="Tamaño máximo permitido en bytes para lecturas de archivos.",
    )
    FILESYSTEM_MAX_WRITE_SIZE: int = Field(
        default=10485760,  # 10 MB
        description="Tamaño máximo permitido en bytes para escrituras de archivos.",
    )
    FILESYSTEM_MAX_LIST_ENTRIES: int = Field(
        default=1000,
        description="Cantidad máxima de entradas a listar en un directorio.",
    )

    # Configuración de Gestión de Procesos Segura (Subetapa 06.3)
    PROCESS_MAX_LIST_ENTRIES: int = Field(
        default=1000,
        description="Cantidad máxima de procesos a listar por consulta.",
    )
    PROCESS_QUERY_TIMEOUT: float = Field(
        default=5.0,
        description="Tiempo máximo de espera en segundos para consultas de procesos.",
    )
    PROCESS_TERMINATION_TIMEOUT: float = Field(
        default=5.0,
        description="Tiempo máximo de espera en segundos para la terminación de un proceso.",
    )
    PROCESS_PROTECTED_NAMES: set[str] = Field(
        default_factory=lambda: {
            "system",
            "registry",
            "smss.exe",
            "csrss.exe",
            "wininit.exe",
            "services.exe",
            "lsass.exe",
            "winlogon.exe",
            "svchost.exe",
            "spoolsv.exe",
            "explorer.exe",
        },
        description="Conjunto de nombres de procesos del sistema protegidos contra terminación.",
    )

    # Configuración de Inspección del Registro de Windows (Subetapa 06.4 - READ ONLY)
    REGISTRY_ALLOWED_HIVES: set[str] = Field(
        default_factory=lambda: {"HKEY_CURRENT_USER", "HKEY_LOCAL_MACHINE", "HKCU", "HKLM"},
        description="Hives del Registro de Windows autorizados para lectura.",
    )
    REGISTRY_MAX_DEPTH: int = Field(
        default=10,
        description="Profundidad máxima permitida en las rutas de claves del Registro.",
    )
    REGISTRY_MAX_SUBKEYS: int = Field(
        default=1000,
        description="Cantidad máxima de subclaves a retornar en una consulta.",
    )
    REGISTRY_MAX_VALUES: int = Field(
        default=1000,
        description="Cantidad máxima de valores a retornar en una consulta.",
    )
    REGISTRY_MAX_VALUE_SIZE: int = Field(
        default=1048576,  # 1 MB
        description="Tamaño máximo en bytes permitido para valores binarios del Registro.",
    )
    REGISTRY_QUERY_TIMEOUT: float = Field(
        default=5.0,
        description="Tiempo máximo de espera en segundos para consultas del Registro.",
    )

    # Configuración de Inspección de Servicios de Windows (Subetapa 06.5 - READ ONLY)
    SERVICES_MAX_LIST_ENTRIES: int = Field(
        default=1000,
        description="Cantidad máxima de servicios a retornar por consulta.",
    )
    SERVICES_QUERY_TIMEOUT: float = Field(
        default=5.0,
        description="Tiempo máximo de espera en segundos para consultas de servicios.",
    )
    SERVICES_MAX_DEPENDENCIES: int = Field(
        default=100,
        description="Cantidad máxima de dependencias o dependientes a retornar.",
    )
    SERVICES_MAX_NAME_LENGTH: int = Field(
        default=256,
        description="Longitud máxima permitida para nombres de servicios de Windows.",
    )

    # Configuración de Política de Comandos (Subetapa 07.1 - METADATA ONLY)
    COMMAND_POLICY_ENABLED: bool = Field(
        default=True,
        description="Habilita la evaluación declarativa de políticas de comandos y allowlists.",
    )
    COMMAND_MAX_ARGUMENTS: int = Field(
        default=50,
        description="Cantidad máxima de argumentos permitidos por comando.",
    )
    COMMAND_MAX_ARGUMENT_LENGTH: int = Field(
        default=1024,
        description="Longitud máxima en caracteres permitida por argumento de comando.",
    )
    COMMAND_MAX_TOTAL_LENGTH: int = Field(
        default=4096,
        description="Longitud máxima total en caracteres de la entrada de comando.",
    )

    # Configuración de Fronteras de Seguridad PowerShell y CMD (Subetapa 07.3 - BOUNDARY ONLY)
    POWERSHELL_ALLOWED_EXECUTABLES: set[str] = Field(
        default_factory=lambda: {"powershell.exe", "pwsh.exe", "powershell", "pwsh"},
        description="Ejecutables de PowerShell permitidos por frontera de seguridad.",
    )
    POWERSHELL_FORCE_NO_PROFILE: bool = Field(
        default=True,
        description="Forzar la flag -NoProfile en invocaciones de PowerShell.",
    )
    POWERSHELL_FORCE_NON_INTERACTIVE: bool = Field(
        default=True,
        description="Forzar la flag -NonInteractive en invocaciones de PowerShell.",
    )
    POWERSHELL_MAX_ARGUMENTS: int = Field(
        default=50,
        description="Cantidad máxima de argumentos permitidos para PowerShell.",
    )
    POWERSHELL_MAX_COMMAND_LENGTH: int = Field(
        default=2048,
        description="Longitud máxima en caracteres permitida para invocaciones de PowerShell.",
    )
    CMD_ALLOWED_EXECUTABLES: set[str] = Field(
        default_factory=lambda: {"cmd.exe", "cmd"},
        description="Ejecutables de CMD permitidos por frontera de seguridad.",
    )
    CMD_MAX_ARGUMENTS: int = Field(
        default=50,
        description="Cantidad máxima de argumentos permitidos para CMD.",
    )

    # Configuración de Control de Aplicaciones (Subetapa 11.1 - Application Control Boundary)
    APPLICATION_SINGLE_INSTANCE_ENFORCED: bool = Field(
        default=True,
        description="Enforzar política de instancia única por defecto en aplicaciones que la soporten.",
    )

    # Configuración de Control de Navegador y Política de URLs (Subetapa 11.2 - Browser Control Boundary)
    BROWSER_URL_ALLOWLIST_ENABLED: bool = Field(
        default=True,
        description="Activar política de lista blanca de URLs de navegador (Deny by default).",
    )
    BROWSER_ALLOWED_SCHEMES: set[str] = Field(
        default_factory=lambda: {"http", "https"},
        description="Esquemas de protocolo permitidos para navegación web.",
    )
    BROWSER_BLOCKED_SCHEMES: set[str] = Field(
        default_factory=lambda: {"javascript", "data", "file", "chrome", "edge", "about"},
        description="Esquemas de protocolo estrictamente denegados por seguridad.",
    )
    BROWSER_ALLOWED_DOMAINS: set[str] = Field(
        default_factory=lambda: {
            "youtube.com",
            "www.youtube.com",
            "google.com",
            "www.google.com",
            "github.com",
            "microsoft.com",
            "127.0.0.1",
            "localhost",
            "wikipedia.org",
            "es.wikipedia.org",
            "duckduckgo.com",
            "bing.com",
            "www.bing.com",
            "example.com",
            "httpbin.org",
        },
        description="Dominios web autorizados por defecto para la navegación del agente.",
    )
    BROWSER_PAGE_LOAD_TIMEOUT: float = Field(
        default=10.0,
        description="Tiempo máximo en segundos de espera de carga de página web.",
    )
    BROWSER_SINGLE_INSTANCE_ENFORCED: bool = Field(
        default=True,
        description="Enforzar política de instancia única de navegador en Application Control.",
    )

    # Configuración de Control de Portapapeles (Subetapa 11.3 - Clipboard Control)
    CLIPBOARD_ENABLED: bool = Field(
        default=True,
        description="Habilitar/deshabilitar globalmente el acceso al portapapeles.",
    )
    CLIPBOARD_MAX_SIZE: int = Field(

        default=65536,  # 64 KB
        description="Tamaño máximo en bytes permitido para lectura/escritura en el portapapeles.",
    )

    # Configuración de Secure Plugin Loader (Etapa 14.2)
    PLUGINS_ENABLED: bool = Field(
        default=True,
        description="Habilita o deshabilita globalmente la carga de plugins externos.",
    )
    PLUGINS_DIRECTORY: Path = Field(
        default=Path("plugins"),
        description="Directorio raíz restringido para el almacenamiento y carga exclusiva de plugins.",
    )
    PLUGINS_MAX_LOADED: int = Field(
        default=10,
        description="Cantidad máxima permitida de plugins cargados simultáneamente en memoria.",
    )
    PLUGIN_SANDBOX_TIMEOUT: float = Field(
        default=10.0,
        description="Tiempo límite máximo en segundos para la ejecución acotada de acciones de plugins en el sandbox.",
    )
    PLUGIN_SANDBOX_MAX_MEMORY_MB: int = Field(
        default=256,
        description="Límite máximo de memoria en megabytes asignable al sandbox de un plugin.",
    )


    # Configuración de Registry Write Boundary (Etapa 15.2)
    REGISTRY_WRITE_ENABLED: bool = Field(
        default=False,
        description="Indica si la modificación del Registro de Windows está habilitada (Deshabilitado por defecto).",
    )
    REGISTRY_WRITE_ALLOWLIST: list[str] = Field(
        default_factory=lambda: ["hkcu\\software\\jessyca"],
        description="Lista blanca explícita de rutas de Registro de Windows cuya modificación es permitida previa confirmación.",
    )

    # Configuración de Service Control Boundary (Etapa 15.3)
    SERVICE_WRITE_ENABLED: bool = Field(
        default=False,
        description="Indica si la administración de Servicios de Windows está habilitada (Deshabilitado por defecto).",
    )
    SERVICE_PROTECTED_LIST: list[str] = Field(
        default_factory=lambda: [
            "windefend",
            "rpcss",
            "lsass",
            "eventlog",
            "wuauserv",
            "mpssvc",
            "dhcp",
            "dnscache",
            "lanmanserver",
            "termservice",
            "vmicvss",
            "samss",
            "seclogon",
            "cryptsvc",
        ],
        description="Lista de servicios críticos protegidos del sistema operativo cuya modificación está prohibida.",
    )

    # Configuración de Software Install Boundary (Etapa 15.4)
    SOFTWARE_INSTALL_ENABLED: bool = Field(
        default=False,
        description="Indica si la instalación de software está habilitada (Deshabilitado por defecto).",
    )
    SOFTWARE_INSTALL_SOURCE: str = Field(
        default="winget",
        description="Gestor de paquetes único aprobado para la instalación de software.",
    )
    SOFTWARE_INSTALL_ALLOWLIST: list[str] = Field(
        default_factory=lambda: [
            "git.git",
            "7zip.7zip",
            "python.python.3.11",
            "microsoft.powershell",
            "google.chrome",
            "vscode.vscode",
        ],
        description="Lista blanca explícita de identificadores de paquetes cuya instalación está permitida previa confirmación.",
    )

    # Configuración de Notification Dispatcher (Etapa 13.3)




    NOTIFICATION_RATE_LIMIT_PER_MINUTE: int = Field(
        default=10,
        description="Cantidad máxima permitida de notificaciones despachadas por minuto para prevenir loops infinitos.",
    )
    NOTIFICATION_DEDUP_WINDOW_SECONDS: float = Field(
        default=10.0,
        description="Ventana de tiempo en segundos para suprimir notificaciones duplicadas idénticas.",
    )
    NOTIFICATION_TOAST_ENABLED: bool = Field(
        default=True,
        description="Indica si las notificaciones nativas de Windows (Toast) están habilitadas.",
    )
    NOTIFICATION_VOICE_ENABLED: bool = Field(
        default=True,
        description="Indica si la síntesis de voz mediante edge-tts está habilitada cuando el módulo se encuentra disponible.",
    )

    # Configuración de Local Wake Word (Etapa 13.2)

    WAKE_WORD_ENABLED: bool = Field(
        default=False,
        description="Indica si la detección de palabra de activación (Wake Word) está habilitada por defecto (Deshabilitado por defecto).",
    )
    WAKE_WORD_KEYWORD: str = Field(
        default="jessyca",
        description="Palabra clave o frase de activación local.",
    )
    AUDIO_BUFFER_MAX_SECONDS: float = Field(
        default=5.0,
        description="Límite máximo de tiempo en segundos para el buffer de audio efímero en memoria.",
    )
    AUDIO_SAMPLE_RATE: int = Field(
        default=16000,
        description="Frecuencia de muestreo de audio en Hz para detección local.",
    )

    # Configuración de Task Scheduler (Etapa 13.1)

    SCHEDULER_ENABLED: bool = Field(
        default=True,
        description="Habilita o deshabilita la ejecución autónoma de tareas programadas.",
    )
    SCHEDULER_MAX_CONCURRENT_TASKS: int = Field(
        default=5,
        description="Cantidad máxima de tareas programadas que pueden ejecutarse concurrentemente.",
    )
    SCHEDULER_STORAGE_PATH: Path = Field(
        default=Path("data/scheduled_tasks.json"),
        description="Ruta de almacenamiento persistente local para las definiciones de tareas programadas.",
    )

    # Configuración de Memoria Semántica Vectorial Local (Subetapa 12.1 - Local Vector Store)
    VECTOR_STORE_ENABLED: bool = Field(
        default=True,
        description="Habilitar/deshabilitar la memoria semántica vectorial local.",
    )
    VECTOR_STORE_PATH: Path = Field(
        default=Path("data/vector_store"),
        description="Ruta local del directorio de almacenamiento vectorial.",
    )
    VECTOR_MAX_RESULTS: int = Field(
        default=50,
        description="Cantidad máxima permitida de resultados (top-k) en búsquedas vectoriales.",
    )
    VECTOR_EMBEDDING_MODEL: str = Field(
        default="local-hash",
        description="Nombre del modelo o proveedor de embeddings (local-hash, nomic-embed-text, etc.).",
    )
    VECTOR_STORE_EMBEDDING_DIMENSION: int = Field(
        default=384,
        description="Dimensión de los vectores embedding generados localmente.",
    )
    VECTOR_STORE_MAX_DOCUMENTS: int = Field(
        default=10000,
        description="Cantidad máxima permitida de documentos almacenados en la memoria vectorial.",
    )
    VECTOR_MAX_DOCUMENT_SIZE: int = Field(
        default=65536,  # 64 KB
        description="Tamaño máximo en caracteres/bytes permitido por documento vectorial.",
    )
    VECTOR_MAX_METADATA_ENTRIES: int = Field(
        default=32,
        description="Cantidad máxima de entradas en los metadatos de un documento vectorial.",
    )

    # Configuración de Consolidación y Retención de Memoria (Subetapa 12.3)
    CONSOLIDATION_INTERVAL_HOURS: int = Field(
        default=24,
        description="Intervalo en horas para la ejecución en background del consolidador de memoria.",
    )
    CONSOLIDATION_MIN_SESSION_AGE_DAYS: int = Field(
        default=7,
        description="Edad mínima en días de una sesión inactiva para ser elegible para consolidación.",
    )

    CMD_MAX_COMMAND_LENGTH: int = Field(
        default=2048,
        description="Longitud máxima en caracteres permitida para invocaciones de CMD.",
    )


    # Configuración de Sanitización y Redacción de Salida de Comandos (Subetapa 07.5)
    COMMAND_MAX_OUTPUT_SIZE: int = Field(
        default=1048576,  # 1 MB
        description="Límite máximo total en bytes para la salida combinada de comandos.",
    )
    COMMAND_MAX_STDOUT_SIZE: int = Field(
        default=524288,  # 512 KB
        description="Límite máximo en bytes para stdout.",
    )
    COMMAND_MAX_STDERR_SIZE: int = Field(
        default=524288,  # 512 KB
        description="Límite máximo en bytes para stderr.",
    )
    COMMAND_OUTPUT_REDACTION_ENABLED: bool = Field(
        default=True,
        description="Habilita la detección y redacción automática de secretos en la salida.",
    )
    COMMAND_ANSI_SANITIZATION_ENABLED: bool = Field(
        default=True,
        description="Habilita la eliminación automática de secuencias de escape ANSI.",
    )

    # Configuración de Captura de Escritorio y Visión (Subetapa 08.1)
    DESKTOP_MAX_WIDTH: int = Field(
        default=3840,
        description="Ancho máximo permitido para captura de pantalla en píxeles.",
    )
    DESKTOP_MAX_HEIGHT: int = Field(
        default=2160,
        description="Alto máximo permitido para captura de pantalla en píxeles.",
    )
    DESKTOP_MAX_PIXELS: int = Field(
        default=8294400,  # 3840 * 2160
        description="Cantidad máxima de píxeles totales permitidos por captura de pantalla.",
    )
    DESKTOP_MAX_CAPTURE_BYTES: int = Field(
        default=10485760,  # 10 MB
        description="Tamaño máximo permitido en bytes para la imagen capturada.",
    )
    DESKTOP_CAPTURE_TIMEOUT: float = Field(
        default=5.0,
        description="Tiempo máximo de espera en segundos para la operación de captura.",
    )

    # Configuración del Motor OCR (Subetapa 08.2)
    OCR_ENABLED: bool = Field(
        default=True,
        description="Habilita la capacidad de extracción de texto OCR desde capturas.",
    )
    OCR_MAX_REGIONS: int = Field(
        default=500,
        description="Cantidad máxima de regiones de texto reconocidas por operación OCR.",
    )
    OCR_MAX_TEXT_LENGTH: int = Field(
        default=50000,
        description="Longitud máxima en caracteres permitida para el texto OCR reconocido.",
    )
    OCR_MAX_INPUT_BYTES: int = Field(
        default=10485760,  # 10 MB
        description="Tamaño máximo permitido en bytes para la imagen de entrada a OCR.",
    )
    OCR_TIMEOUT: float = Field(
        default=10.0,
        description="Tiempo máximo de espera en segundos para el procesamiento OCR.",
    )
    OCR_MIN_CONFIDENCE: float = Field(
        default=0.3,
        description="Nivel mínimo de confianza (0.0 - 1.0) para incluir una región reconocible.",
    )
    OCR_MAX_SCREEN_WIDTH: int = Field(
        default=3840,
        description="Ancho máximo permitido de pantalla/región para procesamiento OCR.",
    )
    OCR_MAX_SCREEN_HEIGHT: int = Field(
        default=2160,
        description="Alto máximo permitido de pantalla/región para procesamiento OCR.",
    )

    # Configuración de Inspección de Elementos UI (Subetapa 08.3)
    UI_INSPECTION_ENABLED: bool = Field(
        default=True,
        description="Habilita la capacidad de inspección de elementos visuales UI de Windows.",
    )
    UI_MAX_ELEMENTS: int = Field(
        default=1000,
        description="Cantidad máxima de elementos UI inspeccionados por árbol/solicitud.",
    )
    UI_MAX_TREE_DEPTH: int = Field(
        default=20,
        description="Profundidad máxima del árbol de jerarquía de elementos UI.",
    )
    UI_MAX_TEXT_LENGTH: int = Field(
        default=4096,
        description="Longitud máxima en caracteres permitida para textos de elementos UI.",
    )
    UI_MAX_NAME_LENGTH: int = Field(
        default=1024,
        description="Longitud máxima en caracteres permitida para nombres/títulos de elementos UI.",
    )
    UI_MAX_PROPERTIES: int = Field(
        default=32,
        description="Cantidad máxima de propiedades retenidas por elemento UI.",
    )
    UI_INSPECTION_TIMEOUT: float = Field(
        default=5.0,
        description="Tiempo máximo de espera en segundos para la inspección visual de UI.",
    )

    # Configuración de Frontera de Automatización de Escritorio (Subetapa 08.4)
    DESKTOP_AUTOMATION_ENABLED: bool = Field(
        default=True,
        description="Habilita la ejecución controlada de acciones gráficas sobre el escritorio.",
    )
    DESKTOP_AUTOMATION_TIMEOUT: float = Field(
        default=5.0,
        description="Tiempo máximo de espera en segundos para la ejecución de una acción UI.",
    )
    DESKTOP_AUTOMATION_MAX_ACTIONS: int = Field(
        default=20,
        description="Cantidad máxima de acciones consecutivas permitidas por solicitud.",
    )
    DESKTOP_AUTOMATION_MAX_TEXT_LENGTH: int = Field(
        default=4096,
        description="Longitud máxima en caracteres permitida para escribir texto mediante type_text.",
    )
    DESKTOP_AUTOMATION_MAX_DRAG_DISTANCE: int = Field(
        default=3840,
        description="Distancia máxima permitida en píxeles para operaciones de arrastrar y soltar (drag_and_drop).",
    )
    DESKTOP_AUTOMATION_CLICK_DELAY: float = Field(
        default=0.1,
        description="Retardo mínimo en segundos entre acciones de clic o interacción.",
    )
    DESKTOP_AUTOMATION_FAILSAFE_ENABLED: bool = Field(
        default=True,
        description="Habilita el mecanismo de parada de emergencia y fail-safe para acciones UI.",
    )

    # Configuración de Inspección de Red (Subetapa 09.1)
    NETWORK_ENABLED: bool = Field(
        default=True,
        description="Habilita la capacidad de inspección de diagnóstico de adaptadores de red.",
    )
    NETWORK_MAX_INTERFACES: int = Field(
        default=256,
        description="Cantidad máxima de adaptadores de red retornados por inspección.",
    )
    NETWORK_MAX_IP_ADDRESSES_PER_INTERFACE: int = Field(
        default=64,
        description="Cantidad máxima de direcciones IP retornadas por adaptador.",
    )
    NETWORK_MAX_GATEWAYS_PER_INTERFACE: int = Field(
        default=16,
        description="Cantidad máxima de pasarelas (gateways) retornadas por adaptador.",
    )
    NETWORK_MAX_DNS_SERVERS_PER_INTERFACE: int = Field(
        default=32,
        description="Cantidad máxima de servidores DNS retornados por adaptador.",
    )
    NETWORK_MAX_NAME_LENGTH: int = Field(
        default=256,
        description="Longitud máxima en caracteres permitida para el nombre o filtro de adaptadores de red.",
    )
    NETWORK_MAX_DESCRIPTION_LENGTH: int = Field(
        default=1024,
        description="Longitud máxima en caracteres permitida para la descripción de adaptadores de red.",
    )
    NETWORK_INSPECTION_TIMEOUT: float = Field(
        default=5.0,
        description="Tiempo máximo de espera en segundos para la inspección de red.",
    )
    NETWORK_MAX_TOTAL_RESPONSE_SIZE: int = Field(
        default=1048576,
        description="Tamaño máximo en bytes permitido para la respuesta estructurada de red (1 MB).",
    )

    # Configuración de Inspección de Conexiones de Red y Puertos (Subetapa 09.2)
    NETWORK_CONNECTIONS_ENABLED: bool = Field(
        default=True,
        description="Habilita la capacidad de inspección de diagnóstico de conexiones de red activas y puertos en escucha.",
    )
    NETWORK_MAX_ACTIVE_CONNECTIONS: int = Field(
        default=1000,
        description="Cantidad máxima de conexiones activas retornadas por solicitud de inspección.",
    )
    NETWORK_MAX_LISTENING_PORTS: int = Field(
        default=512,
        description="Cantidad máxima de puertos en escucha retornados por solicitud de inspección.",
    )
    NETWORK_MAX_PROCESS_NAME_LENGTH: int = Field(
        default=256,
        description="Longitud máxima en caracteres permitida para nombres de proceso en conexiones de red.",
    )
    NETWORK_MAX_STATUS_LENGTH: int = Field(
        default=64,
        description="Longitud máxima en caracteres permitida para descripciones de estado de conexiones.",
    )
    NETWORK_MAX_CONNECTION_RESPONSE_SIZE: int = Field(
        default=1048576,
        description="Tamaño máximo en bytes permitido para la respuesta estructurada de conexiones de red (1 MB).",
    )
    NETWORK_CONNECTION_INSPECTION_TIMEOUT: float = Field(
        default=5.0,
        description="Tiempo máximo de espera en segundos para la inspección de conexiones de red.",
    )

    # Configuración de Inspección de Tabla de Ruteo y Caché DNS (Subetapa 09.3)
    NETWORK_ROUTING_ENABLED: bool = Field(
        default=True,
        description="Habilita la inspección de diagnóstico de la tabla de ruteo IP del sistema.",
    )
    NETWORK_MAX_ROUTES: int = Field(
        default=2048,
        description="Cantidad máxima de rutas retornadas por solicitud de inspección.",
    )
    NETWORK_MAX_ROUTE_PREFIX_LENGTH: int = Field(
        default=64,
        description="Longitud máxima en caracteres permitida para la representación de red/prefijo de ruteo.",
    )
    NETWORK_MAX_ROUTE_INTERFACE_LENGTH: int = Field(
        default=256,
        description="Longitud máxima en caracteres permitida para el nombre de interfaz en ruteo.",
    )
    NETWORK_MAX_ROUTE_RESPONSE_SIZE: int = Field(
        default=1048576,
        description="Tamaño máximo en bytes permitido para la respuesta estructurada de ruteo (1 MB).",
    )
    NETWORK_ROUTING_INSPECTION_TIMEOUT: float = Field(
        default=5.0,
        description="Tiempo máximo de espera en segundos para la inspección de ruteo.",
    )

    NETWORK_DNS_CACHE_ENABLED: bool = Field(
        default=True,
        description="Habilita la inspección de diagnóstico de la caché DNS local del sistema.",
    )
    NETWORK_MAX_DNS_CACHE_ENTRIES: int = Field(
        default=4096,
        description="Cantidad máxima de entradas de caché DNS retornadas por solicitud de inspección.",
    )
    NETWORK_MAX_DNS_HOSTNAME_LENGTH: int = Field(
        default=253,
        description="Longitud máxima en caracteres permitida para nombres de host (FQDN) en la caché DNS.",
    )
    NETWORK_MAX_DNS_VALUE_LENGTH: int = Field(
        default=1024,
        description="Longitud máxima en caracteres permitida para valores o registros en la caché DNS.",
    )
    NETWORK_MAX_DNS_RESPONSE_SIZE: int = Field(
        default=1048576,
        description="Tamaño máximo en bytes permitido para la respuesta estructurada de caché DNS (1 MB).",
    )
    NETWORK_DNS_CACHE_INSPECTION_TIMEOUT: float = Field(
        default=5.0,
        description="Tiempo máximo de espera en segundos para la inspección de la caché DNS.",
    )

    # Configuración de Memoria de Sesión Persistente (Subetapa 10.1)
    SESSION_ENABLED: bool = Field(
        default=True,
        description="Habilita la gestión de estado de sesión y memoria persistente.",
    )
    SESSION_MAX_ACTIVE_SESSIONS: int = Field(
        default=100,
        description="Cantidad máxima de sesiones activas simultáneas.",
    )
    SESSION_MAX_MESSAGES: int = Field(
        default=500,
        description="Cantidad máxima de mensajes conservados por sesión.",
    )
    SESSION_MAX_MESSAGE_LENGTH: int = Field(
        default=8192,
        description="Longitud máxima en caracteres permitida por mensaje de sesión.",
    )
    SESSION_MAX_FACTS: int = Field(
        default=200,
        description="Cantidad máxima de hechos o facts de memoria por sesión.",
    )
    SESSION_MAX_PREFERENCES: int = Field(
        default=100,
        description="Cantidad máxima de preferencias de usuario por sesión.",
    )
    SESSION_MAX_CONTEXT_SIZE: int = Field(
        default=1048576,
        description="Tamaño máximo en bytes para la estructura completa de sesión (1 MB).",
    )
    SESSION_MAX_MEMORY_ENTRY_LENGTH: int = Field(
        default=1024,
        description="Longitud máxima en caracteres permitida por entrada individual de memoria.",
    )
    SESSION_TIMEOUT: float = Field(
        default=3600.0,
        description="Tiempo de inactividad en segundos antes de la expiración automática de una sesión.",
    )
    SESSION_PERSISTENCE_ENABLED: bool = Field(
        default=True,
        description="Habilita la persistencia en disco mediante SQLiteSessionStore.",
    )
    SESSION_SQLITE_PATH: str = Field(
        default="data/sessions.db",
        description="Ruta del archivo de base de datos SQLite para persistencia de sesiones.",
    )

    # Configuración de Experience Logger (Fase 57)
    EXPERIENCE_LOGGING_ENABLED: bool = Field(
        default=True,
        description="Habilita el registro estructurado de experiencias para aprendizaje futuro.",
    )
    EXPERIENCE_SQLITE_PATH: str = Field(
        default="data/experiences.db",
        description="Ruta del archivo de base de datos SQLite para persistencia de experiencias.",
    )

    # Configuración de Learning Proposal Engine (Fase 59)
    PROPOSAL_SQLITE_PATH: str = Field(
        default="data/proposals.db",
        description="Ruta del archivo de base de datos SQLite para persistencia de propuestas de aprendizaje.",
    )

    # Configuración de Regression Learning Engine (Fase 61)
    REGRESSION_SQLITE_PATH: str = Field(
        default="data/regressions.db",
        description="Ruta del archivo de base de datos SQLite para persistencia de casos de regresión.",
    )

    # Configuración de Personalization Engine (Fase 62)
    PREFERENCE_SQLITE_PATH: str = Field(
        default="data/preferences.db",
        description="Ruta del archivo de base de datos SQLite para persistencia de preferencias del usuario.",
    )

    # Configuración de Daily Learning Cycle (Fase 63)
    LEARNING_ENABLED: bool = Field(
        default=True,
        description="Habilita globalmente el motor de aprendizaje y automejora de JESSYCA.",
    )
    DAILY_LEARNING_ENABLED: bool = Field(
        default=True,
        description="Habilita la ejecución programada del ciclo diario de aprendizaje.",
    )
    DAILY_LEARNING_TIME: str = Field(
        default="23:00",
        description="Hora del día (formato HH:MM) para ejecutar el ciclo de aprendizaje diario.",
    )
    LEARNING_MAX_PROPOSALS: int = Field(
        default=10,
        description="Límite máximo de propuestas procesadas por ciclo diario.",
    )
    LEARNING_REQUIRE_APPROVAL: bool = Field(
        default=True,
        description="Exige aprobación explícita humana o de política antes de cualquier despliegue.",
    )
    LEARNING_AUTO_DEPLOY: bool = Field(
        default=False,
        description="Despliegue automático de mejoras (DESACTIVADO por defecto por seguridad).",
    )
    LEARNING_MAX_RUNTIME_SEC: float = Field(
        default=300.0,
        description="Tiempo máximo de ejecución en segundos antes de abortar por timeout.",
    )
    LEARNING_MAX_TEST_FAILURES: int = Field(
        default=3,
        description="Umbral de fallos en pruebas antes de activar el Circuit Breaker.",
    )
    DAILY_REPORT_STORAGE_PATH: str = Field(
        default="data/learning_reports/",
        description="Directorio de persistencia de reportes diarios de aprendizaje.",
    )

    # Configuración de Voice Capture, Calibration & Diagnostics (Fase 51.1)
    VOICE_SAMPLE_RATE: int = Field(
        default=16000,
        description="Frecuencia de muestreo en Hz para la captura de audio por voz.",
    )
    VOICE_CHANNELS: int = Field(
        default=1,
        description="Canales de audio para captura (1 = mono, 2 = estéreo).",
    )
    VOICE_CALIBRATION_DURATION_SEC: float = Field(
        default=1.0,
        description="Duración en segundos de la calibración de ruido ambiente al inicio.",
    )
    VOICE_VAD_ENABLED: bool = Field(
        default=True,
        description="Habilita la detección de actividad de voz (VAD) basada en energía e histeresis.",
    )
    VOICE_VAD_START_THRESHOLD: float = Field(
        default=350.0,
        description="Umbral de energía RMS para disparar SPEECH_START (histeresis alta).",
    )
    VOICE_VAD_END_THRESHOLD: float = Field(
        default=200.0,
        description="Umbral de energía RMS para mantener SPEECH_CONTINUE / transicionar a silencio (histeresis baja).",
    )
    VOICE_PRE_ROLL_MS: int = Field(
        default=400,
        description="Ventana de pre-roll en milisegundos conservada antes de la detección de voz.",
    )
    VOICE_POST_ROLL_MS: int = Field(
        default=600,
        description="Ventana de post-roll en milisegundos conservada tras el fin de la detección de voz.",
    )
    VOICE_MIN_SPEECH_MS: int = Field(
        default=300,
        description="Duración mínima de habla en milisegundos para filtrar ruidos o clics.",
    )
    VOICE_MAX_CAPTURE_MS: int = Field(
        default=300000,
        description="Watchdog de seguridad técnica contra micrófono atascado o anomalías (300s). No es el fin normal de habla.",
    )
    VOICE_ADAPTIVE_EOS_ENABLED: bool = Field(
        default=True,
        description="Habilita la detección adaptativa de fin de habla (Adaptive End-of-Speech) guiada por VAD y pausas.",
    )
    VOICE_ADAPTIVE_SILENCE_SHORT_SEC: float = Field(
        default=1.0,
        description="Silencio sostenido requerido para finalizar comandos cortos (<1.2s de habla activa).",
    )
    VOICE_ADAPTIVE_SILENCE_EXTENDED_SEC: float = Field(
        default=1.35,
        description="Silencio sostenido requerido para finalizar intervenciones conversacionales o complejas.",
    )
    VOICE_ADAPTIVE_PAUSE_TOLERANCE_SEC: float = Field(
        default=1.2,
        description="Tolerancia máxima de pausa natural de reflexión antes de interpretar silencio como fin de habla.",
    )
    VOICE_FAILSAFE_WATCHDOG_SEC: float = Field(
        default=300.0,
        description="Watchdog técnico de seguridad contra micrófono/VAD atascado (5 min).",
    )
    VOICE_SILENCE_TIMEOUT_MS: int = Field(
        default=2500,
        description="Tiempo de silencio continuo en milisegundos para marcar el fin del turno de voz.",
    )
    VOICE_STT_PROVIDER: str = Field(
        default="faster-whisper",
        description="Proveedor de transcripción STT ('faster-whisper', 'google' o 'mock').",
    )
    VOICE_FASTER_WHISPER_MODEL: str = Field(
        default="base",
        description="Tamaño del modelo faster-whisper ('tiny', 'base', 'small', 'medium', 'large-v3').",
    )
    VOICE_FASTER_WHISPER_BEAM_SIZE: int = Field(
        default=5,
        description="Tamaño del beam para decodificación de faster-whisper (1=greedy, 3-5=mayor precisión fonética).",
    )
    VOICE_FASTER_WHISPER_PROMPT: str = Field(
        default="Conversación en español con la asistente JESSYCA sobre ciencia, tecnología, aplicaciones y cultura.",
        description="Prompt contextual para guiar el decodificador de faster-whisper en español.",
    )
    VOICE_FASTER_WHISPER_DEVICE: str = Field(
        default="auto",
        description="Dispositivo de inferencia para faster-whisper ('auto', 'cpu', 'cuda').",
    )
    VOICE_FASTER_WHISPER_COMPUTE_TYPE: str = Field(
        default="default",
        description="Tipo de cuantización y cómputo para faster-whisper ('default', 'int8', 'float16').",
    )
    VOICE_STT_LANGUAGE: str = Field(
        default="es",
        description="Idioma predeterminado para el reconocimiento de voz (STT).",
    )
    VOICE_STT_CONFIDENCE_THRESHOLD: float = Field(
        default=0.50,
        description="Umbral mínimo de confianza para aceptar una transcripción STT.",
    )
    VOICE_MAX_EMPTY_RETRIES: int = Field(
        default=5,
        description="Límite máximo de reintentos consecutivos de captura vacía antes de notificar.",
    )
    VOICE_DIAGNOSTICS: bool = Field(
        default=False,
        description="Habilita la telemetría y logging diagnóstico detallado de audio y VAD.",
    )
    VOICE_SAVE_DIAGNOSTIC_AUDIO: bool = Field(
        default=False,
        description="Guarda grabaciones WAV de diagnóstico explícito para inspección técnica (desactivado por defecto).",
    )
    VOICE_DIAGNOSTICS_DIR: str = Field(
        default="logs/voice_diagnostics",
        description="Directorio local para almacenar grabaciones de diagnóstico de audio.",
    )

    # Configuración de Auto-Detección y Prioridad de Micrófono (Fase 51.2)
    VOICE_AUTO_SELECT_MICROPHONE: bool = Field(
        default=True,
        description="Habilita la selección automática del mejor micrófono físico disponible.",
    )
    VOICE_PREFERRED_MICROPHONES: list[str] = Field(
        default_factory=lambda: ["G435", "C270"],
        description="Lista priorizada de identificadores de micrófonos físicos (ej. G435, C270).",
    )
    VOICE_DEFAULT_VOICE: str = Field(
        default="es-PE-CamilaNeural",
        description="Voz neuronal predeterminada para síntesis de voz (Camila Neural).",
    )
    VOICE_TTS_ENGINE: str = Field(
        default="edge-tts",
        description="Motor TTS principal (edge-tts con voz neuronal Camila).",
    )
    VOICE_TTS_RATE: str = Field(
        default="+0%",
        description="Ajuste de velocidad para síntesis de voz (ej. '+0%', '-4%', '+5%').",
    )
    VOICE_TTS_PITCH: str = Field(
        default="+0Hz",
        description="Ajuste de tono para síntesis de voz (ej. '+0Hz', '+2Hz').",
    )
    # Configuración de TTS Providers e Intercambiabilidad (Fase 72)
    VOICE_TTS_PROVIDER: str = Field(
        default="edge-tts",
        description="Proveedor TTS preferido ('edge-tts' o 'pocket-tts').",
    )
    VOICE_TTS_FALLBACK: str = Field(
        default="edge-tts",
        description="Proveedor TTS de respaldo en caso de fallo ('edge-tts').",
    )
    VOICE_POCKET_TTS_VOICE: str = Field(
        default="alba",
        description="Voz base de Pocket TTS ('alba', 'lola', etc.).",
    )
    VOICE_POCKET_TTS_DEVICE: str = Field(
        default="cpu",
        description="Dispositivo de inferencia para Pocket TTS ('cpu' o 'cuda').",
    )
    VOICE_TTS_TIMEOUT_SECONDS: float = Field(
        default=10.0,
        description="Timeout máximo en segundos para la síntesis de voz.",
    )
    # Configuración de Barge-In e Interrupción de Voz (Fase 73)
    VOICE_BARGE_IN_ENABLED: bool = Field(
        default=True,
        description="Habilita la capacidad de interrumpir a JESSYCA mientras habla (Barge-in).",
    )
    VOICE_BARGE_IN_MIN_SPEECH_MS: float = Field(
        default=150.0,
        description="Duración mínima en milisegundos de habla requerida para confirmar interrupción.",
    )
    VOICE_BARGE_IN_ECHO_MARGIN_FACTOR: float = Field(
        default=1.6,
        description="Factor multiplicador sobre el umbral VAD durante la locución de JESSYCA (anti-eco).",
    )
    VOICE_BARGE_IN_COOLDOWN_MS: float = Field(
        default=250.0,
        description="Ventana de enfriamiento inicial en ms al comenzar TTS para ignorar transitorios de altavoz.",
    )

    # Configuración de Detección de Actividad de Voz (VAD) - Integración I1 Silero VAD
    VAD_BACKEND: str = Field(
        default="energy",
        description="Backend VAD activo ('energy' o 'silero'). Conserva 'energy' por defecto.",
    )
    SILERO_VAD_ENABLED: bool = Field(
        default=False,
        description="Habilita el backend Silero VAD opcional basado en ONNX (desactivado por defecto).",
    )
    SILERO_VAD_MODEL_PATH: Path | None = Field(
        default=None,
        description="Ruta personalizada al modelo ONNX de Silero VAD (opcional).",
    )
    SILERO_VAD_THRESHOLD: float = Field(
        default=0.50,
        description="Umbral de probabilidad de voz para inicio de habla en Silero VAD (0.0 a 1.0).",
    )
    SILERO_VAD_NEG_THRESHOLD: float = Field(
        default=0.35,
        description="Umbral de probabilidad de voz para fin de habla en Silero VAD (histeresis).",
    )
    SILERO_VAD_SAMPLE_RATE: int = Field(
        default=16000,
        description="Frecuencia de muestreo requerida por Silero VAD en Hz (16000).",
    )
    SILERO_VAD_WINDOW_SIZE: int = Field(
        default=512,
        description="Tamaño de ventana en muestras para Silero VAD (512 muestras = 32ms a 16kHz).",
    )

    # Configuración de Palabra de Activación (Wake Word) - Integración I5 openWakeWord
    WAKE_WORD_BACKEND: str = Field(
        default="manual",
        description="Backend activo de detección de palabra de activación ('manual' / 'push_to_talk' o 'openwakeword'). Conserva 'manual' por defecto.",
    )
    OPENWAKEWORD_ENABLED: bool = Field(
        default=False,
        description="Habilita el backend openWakeWord acústico opcional (desactivado por defecto).",
    )
    OPENWAKEWORD_MODEL_PATH: Path | None = Field(
        default=None,
        description="Ruta personalizada al modelo ONNX/TFLite de wake word local entrenado para la palabra clave (ej. 'jessyca').",
    )
    OPENWAKEWORD_THRESHOLD: float = Field(
        default=0.60,
        description="Umbral de confianza acústica para activación [0.0 - 1.0].",
    )
    OPENWAKEWORD_COOLDOWN_SECONDS: float = Field(
        default=2.0,
        description="Período de enfriamiento en segundos tras activación para prevenir disparos en ráfaga.",
    )
    OPENWAKEWORD_BUFFER_SECONDS: float = Field(
        default=1.5,
        description="Ventana de buffer de audio temporal en segundos para inferencia acústica.",
    )
    OPENWAKEWORD_TARGET_SAMPLE_RATE: int = Field(
        default=16000,
        description="Frecuencia de muestreo requerida por openWakeWord en Hz (16000).",
    )
    OPENWAKEWORD_FALLBACK_TO_MANUAL: bool = Field(
        default=True,
        description="Realiza fallback transparente a modo manual/push-to-talk si el modelo acústico no está disponible.",
    )

    # Configuración de Navegación y Playwright (Integración I2)
    BROWSER_BACKEND: str = Field(
        default="playwright",
        description="Backend de navegador activo ('playwright', 'windows', 'fake'). Playwright activo por defecto.",
    )
    PLAYWRIGHT_ENABLED: bool = Field(
        default=True,
        description="Habilita el backend Playwright nativo para BrowserSessionManager.",
    )
    PLAYWRIGHT_HEADLESS: bool = Field(
        default=True,
        description="Ejecución en modo headless para Playwright.",
    )
    PLAYWRIGHT_CHANNEL: str = Field(
        default="msedge",
        description="Canal de navegador para Playwright ('msedge', 'chrome', 'chromium'). Conserva 'msedge'.",
    )
    PLAYWRIGHT_USER_DATA_DIR: Path | None = Field(
        default=None,
        description="Ruta a perfil de automatización separado para Playwright (aislado de perfiles personales).",
    )
    PLAYWRIGHT_TIMEOUT_MS: int = Field(
        default=15000,
        description="Tiempo de espera máximo en milisegundos para operaciones de Playwright.",
    )

    # Configuración de Procesamiento Documental y Docling (Integración I3)
    ANYDOC_BACKEND: str = Field(
        default="anydoc",
        description="Backend documental activo ('anydoc', 'docling'). Conserva 'anydoc' por defecto.",
    )
    DOCLING_ENABLED: bool = Field(
        default=False,
        description="Habilita el backend Docling opcional para AnyDoc (desactivado por defecto).",
    )
    DOCLING_OCR_ENABLED: bool = Field(
        default=True,
        description="Habilita OCR local offline mediante RapidOCR en Docling si el documento lo requiere.",
    )
    DOCLING_MAX_PAGES: int = Field(
        default=50,
        description="Límite máximo de páginas a procesar por documento en Docling.",
    )
    DOCLING_TIMEOUT_SECONDS: float = Field(
        default=60.0,
        description="Tiempo máximo de espera en segundos para procesamiento de documentos en Docling.",
    )
    DOCLING_CONCURRENCY_LIMIT: int = Field(
        default=1,
        description="Límite de operaciones concurrentes en Docling para evitar saturación de CPU/memoria.",
    )
    DOCLING_FALLBACK_TO_ANYDOC: bool = Field(
        default=True,
        description="Realiza fallback explícito al backend AnyDoc si Docling no está disponible o falla.",
    )

    # Configuración de Inspección y Automatización UI (Fase I4)
    UI_INSPECTION_BACKEND: str = Field(
        default="uiautomation",
        description="Backend activo de inspección visual UI ('uiautomation', 'pywinauto', 'fake').",
    )
    PYWINAUTO_ENABLED: bool = Field(
        default=False,
        description="Habilita pywinauto como adaptador opcional para inspección/automatización (desactivado por defecto).",
    )
    PYWINAUTO_BACKEND: str = Field(
        default="uia",
        description="Backend tecnológico interno de pywinauto ('uia' o 'win32').",
    )
    PYWINAUTO_ACTION_TIMEOUT: float = Field(
        default=5.0,
        description="Tiempo de espera máximo en segundos para acciones gobernadas ejecutadas vía pywinauto.",
    )
    PYWINAUTO_FALLBACK_TO_UIA: bool = Field(
        default=True,
        description="Realiza fallback automático a uiautomation si pywinauto no está disponible o falla.",
    )

    # Configuración de Context Builder & Memory Retrieval (Subetapa 10.2)
    CONTEXT_ENABLED: bool = Field(
        default=True,
        description="Habilita el motor de construcción de contexto y recuperación de memoria.",
    )
    CONTEXT_MAX_ITEMS: int = Field(
        default=200,
        description="Cantidad máxima de elementos de contexto permitidos por snapshot.",
    )
    CONTEXT_MAX_MESSAGES: int = Field(
        default=50,
        description="Cantidad máxima de mensajes conservados en la construcción del contexto.",
    )
    CONTEXT_MAX_FACTS: int = Field(
        default=50,
        description="Cantidad máxima de hechos o facts incluidos en la construcción del contexto.",
    )
    CONTEXT_MAX_PREFERENCES: int = Field(
        default=50,
        description="Cantidad máxima de preferencias incluidas en la construcción del contexto.",
    )
    CONTEXT_MAX_SECTIONS: int = Field(
        default=10,
        description="Cantidad máxima de secciones estructuradas en el ContextSnapshot.",
    )
    CONTEXT_MAX_ITEM_LENGTH: int = Field(
        default=2048,
        description="Longitud máxima en caracteres permitida por elemento individual de contexto.",
    )
    CONTEXT_MAX_TOTAL_SIZE: int = Field(
        default=524288,
        description="Tamaño máximo en bytes para la estructura completa de ContextSnapshot (512 KB).",
    )
    CONTEXT_RETRIEVAL_TIMEOUT: float = Field(
        default=5.0,
        description="Tiempo máximo de espera en segundos para la construcción y recuperación de contexto.",
    )
    CONTEXT_MAX_QUERY_LENGTH: int = Field(
        default=1024,
        description="Longitud máxima en caracteres permitida para la consulta o filtro de contexto.",
    )

    # Opciones Específicas de Windows
    ENABLE_WINDOWS_NOTIFICATIONS: bool = Field(
        default=True,
        description="Habilita la integración de notificaciones nativas de Windows 10/11.",
    )
    STRICT_WINDOWS_ADMIN_CHECK: bool = Field(
        default=False,
        description="Si es True, exige permisos de administrador al iniciar servicios del sistema.",
    )

    # Configuración de Smart Media Playback ("Jessyca, báilame")
    JESSYCA_DANCE_VIDEO_DIRECTORY: Path = Field(
        default=Path(r"D:\bailes de ia"),
        description="Directorio exclusivo autorizado para vídeos de baile (play_random_video).",
    )
    SUPPORTED_VIDEO_EXTENSIONS: frozenset[str] = Field(
        default_factory=lambda: frozenset({".mp4", ".mkv", ".avi", ".mov", ".webm", ".wmv", ".m4v"}),
        description="Extensiones de archivo de vídeo permitidas (case-insensitive).",
    )

    # Configuración de Mobile API Bridge (JESSYCA 4.0 Core ↔ Mobile)
    MOBILE_API_ENABLED: bool = Field(
        default=True,
        description="Habilita el servidor Mobile API para comunicación con cliente Android.",
    )
    MOBILE_API_HOST: str = Field(
        default="127.0.0.1",
        description="Host de escucha para Mobile API (127.0.0.1 loopback por defecto; configurar a 0.0.0.0 o IP de red para acceso LAN explícito).",
    )
    MOBILE_API_PORT: int = Field(
        default=8765,
        description="Puerto TCP de escucha para Mobile API.",
    )
    MOBILE_API_AUTH_TOKEN: str = Field(
        default="",
        description="Token de autenticación obligatorio para cliente móvil (X-Jessyca-Token). Prohibido valor vacío o desarrollo en ejecución normal.",
    )
    MOBILE_API_TIMEOUT: float = Field(
        default=30.0,
        ge=0.01,
        description="Timeout máximo en segundos para procesamiento de solicitudes móviles.",
    )
    MOBILE_API_CORS_ORIGINS: list[str] = Field(
        default_factory=list,
        description="Lista de orígenes permitidos para CORS en Mobile API. Vacío por defecto (CORS restrictivo/desactivado).",
    )
    MOBILE_API_DOCS_ENABLED: bool = Field(
        default=False,
        description="Determina si se exponen /docs y /openapi.json en Mobile API (falso por defecto en entornos de red).",
    )

    # Configuración de Web Bridge (OpenAI-Compatible Bridge para Open WebUI)
    WEBUI_BRIDGE_ENABLED: bool = Field(
        default=True,
        description="Habilita el servidor Web Bridge OpenAI-Compatible para Open WebUI.",
    )
    WEBUI_BRIDGE_HOST: str = Field(
        default="127.0.0.1",
        description="Host de escucha para Web Bridge (127.0.0.1 loopback por defecto).",
    )
    WEBUI_BRIDGE_PORT: int = Field(
        default=8088,
        description="Puerto TCP de escucha para Web Bridge.",
    )
    WEBUI_BRIDGE_AUTH_TOKEN: str = Field(
        default="",
        description="Token de autenticación Bearer para Web Bridge. Requerido por seguridad.",
    )
    WEBUI_BRIDGE_TIMEOUT: float = Field(
        default=60.0,
        description="Timeout máximo en segundos para procesamiento de solicitudes de Web Bridge.",
    )
    WEBUI_BRIDGE_CORS_ORIGINS: list[str] = Field(
        default_factory=list,
        description="Lista de orígenes permitidos para CORS en WebUI Bridge. Vacío por defecto.",
    )
    WEBUI_BRIDGE_DOCS_ENABLED: bool = Field(
        default=False,
        description="Determina si se exponen /docs y /openapi.json en WebUI Bridge (falso por defecto).",
    )

    # Integraciones Externas (Integration Hub / Adapter Layer)
    INTEGRATIONS_ENABLED: bool = Field(
        default=True,
        description="Habilita o deshabilita globalmente el subsistema de Integration Hub.",
    )
    INTEGRATIONS_ADAPTERS: dict[str, dict[str, Any]] = Field(
        default_factory=lambda: {
            "jarvis": {"enabled": False},
            "are": {"enabled": False},
            "windows_computer_use": {"enabled": False},
            "mobile": {"enabled": False},
        },
        description="Configuración y estado de habilitación de adapters específicos.",
    )

    # Proveedor Experimental Remoto: NVIDIA Nemotron 3 Ultra
    NEMOTRON_ENABLED: bool = Field(
        default=False,
        description="Habilita de forma experimental el proveedor remoto NVIDIA Nemotron 3 Ultra.",
    )
    NEMOTRON_API_KEY: str = Field(
        default="",
        description="API Key de NVIDIA Cloud Functions / NGC para Nemotron. Jamás hardcodear.",
    )
    NEMOTRON_BASE_URL: str = Field(
        default="https://integrate.api.nvidia.com/v1",
        description="Base URL de la API OpenAI-compatible de NVIDIA para inferencia.",
    )
    NEMOTRON_MODEL: str = Field(
        default="nvidia/nemotron-3-ultra-550b-a55b",
        description="Identificador del modelo Nemotron en NVIDIA API Catalog.",
    )
    NEMOTRON_TIMEOUT_SECONDS: float = Field(
        default=30.0,
        description="Timeout total en segundos para la llamada HTTP a Nemotron.",
    )
    NEMOTRON_CONNECT_TIMEOUT_SECONDS: float = Field(
        default=5.0,
        description="Timeout de conexión inicial en segundos.",
    )
    NEMOTRON_MAX_RETRIES: int = Field(
        default=2,
        description="Cantidad máxima de reintentos con backoff para errores transitorios de red.",
    )

    # Router Inteligente (Fase 3: static, shadow, experimental / Fase 5 Controlled)
    MODEL_ROUTER_ENABLED: bool = Field(
        default=False,
        description="Flag maestro de activación del Model Router (False=desactivado, True=enrutamiento controlado activo).",
    )
    MODEL_ROUTER_MODE: str = Field(
        default="shadow",
        description="Modo de operación del router inteligente: static, shadow (por defecto Fase 4), controlled, experimental.",
    )
    ROUTER_CONFIDENCE_THRESHOLD: float = Field(
        default=0.80,
        ge=0.0,
        le=1.0,
        description="Umbral mínimo de confianza para enrutamiento avanzado hacia modelos de alto cómputo (0.0 a 1.0).",
    )
    ROUTER_SHADOW_LOG_FILE: Path = Field(
        default=Path("logs/router_shadow.jsonl"),
        description="Ruta del archivo de registro estructurado para decisiones en shadow mode.",
    )


    @classmethod
    def validate_environment(cls, value: str | EnvironmentMode) -> EnvironmentMode:
        if isinstance(value, EnvironmentMode):
            return value
        if isinstance(value, str):
            try:
                return EnvironmentMode(value.lower())
            except ValueError:
                return EnvironmentMode(DEFAULT_ENVIRONMENT)
        return EnvironmentMode(DEFAULT_ENVIRONMENT)

    @field_validator("LOG_LEVEL", mode="before")
    @classmethod
    def validate_log_level(cls, value: str | LogLevel) -> LogLevel:
        if isinstance(value, LogLevel):
            return value
        if isinstance(value, str):
            try:
                return LogLevel(value.upper())
            except ValueError:
                return LogLevel(DEFAULT_LOG_LEVEL)
        return LogLevel(DEFAULT_LOG_LEVEL)

    @field_validator("JESSYCA_DANCE_VIDEO_DIRECTORY", mode="before")
    @classmethod
    def validate_dance_video_directory(cls, value: str | Path) -> Path:
        if isinstance(value, Path):
            return value
        if isinstance(value, str) and value.strip():
            return Path(value.strip())
        return Path(r"D:\bailes de ia")

    @field_validator("JDE_RUNTIME_MODE", mode="before")
    @classmethod
    def validate_jde_runtime_mode(cls, value: str) -> str:
        cleaned = str(value).strip().upper()
        if cleaned == "ACTIVE":
            raise ValueError(
                "JDE_RUNTIME_MODE 'ACTIVE' está estrictamente prohibido en Fase 1 "
                "(protección contra activación accidental)."
            )
        if cleaned not in ("SHADOW", "CONTROLLED"):
            raise ValueError(
                f"JDE_RUNTIME_MODE inválido: '{value}'. Valores permitidos: SHADOW, CONTROLLED."
            )
        return cleaned

    @field_validator("ARE_RUNTIME_MODE", mode="before")
    @classmethod
    def validate_are_runtime_mode(cls, value: str) -> str:
        cleaned = str(value).strip().upper()
        if cleaned == "ACTIVE":
            raise ValueError(
                "ARE_RUNTIME_MODE 'ACTIVE' está estrictamente prohibido en esta fase "
                "(protección contra activación accidental)."
            )
        if cleaned not in ("DISABLED", "SHADOW", "CONTROLLED"):
            raise ValueError(
                f"ARE_RUNTIME_MODE inválido: '{value}'. Valores permitidos: DISABLED, SHADOW, CONTROLLED."
            )
        return cleaned

    @field_validator("MODEL_ROUTER_MODE", mode="before")
    @classmethod
    def validate_model_router_mode(cls, value: Any) -> str:
        cleaned = str(value).strip().lower()
        if cleaned not in VALID_MODEL_ROUTER_MODES:
            raise ValueError(
                f"MODEL_ROUTER_MODE inválido: '{value}'. "
                f"Valores permitidos: {', '.join(sorted(VALID_MODEL_ROUTER_MODES))}."
            )
        return cleaned

    @field_validator("ROUTER_CONFIDENCE_THRESHOLD", mode="before")
    @classmethod
    def validate_router_confidence_threshold(cls, value: Any) -> float:
        try:
            val = float(value)
        except (ValueError, TypeError) as e:
            raise ValueError(f"ROUTER_CONFIDENCE_THRESHOLD debe ser un número: {value}") from e
        if not (0.0 <= val <= 1.0):
            raise ValueError(
                f"ROUTER_CONFIDENCE_THRESHOLD fuera de rango: {val}. "
                "Debe estar comprendido entre 0.0 y 1.0 inclusive."
            )
        return val

    @field_validator("ROUTER_SHADOW_LOG_FILE", mode="before")
    @classmethod
    def validate_router_shadow_log_file(cls, value: Any) -> Path:
        if not value or not str(value).strip():
            raise ValueError("ROUTER_SHADOW_LOG_FILE no puede estar vacío.")
        return Path(str(value).strip())

    @field_validator("NEMOTRON_TIMEOUT_SECONDS", mode="before")
    @classmethod
    def validate_nemotron_timeout(cls, value: Any) -> float:
        try:
            val = float(value)
        except (ValueError, TypeError) as e:
            raise ValueError(f"NEMOTRON_TIMEOUT_SECONDS debe ser un número: {value}") from e
        if val <= 0:
            raise ValueError(f"NEMOTRON_TIMEOUT_SECONDS debe ser mayor a 0 (obtenido: {val})")
        return val

    @field_validator("NEMOTRON_CONNECT_TIMEOUT_SECONDS", mode="before")
    @classmethod
    def validate_nemotron_connect_timeout(cls, value: Any) -> float:
        try:
            val = float(value)
        except (ValueError, TypeError) as e:
            raise ValueError(f"NEMOTRON_CONNECT_TIMEOUT_SECONDS debe ser un número: {value}") from e
        if val <= 0:
            raise ValueError(f"NEMOTRON_CONNECT_TIMEOUT_SECONDS debe ser mayor a 0 (obtenido: {val})")
        return val

    @field_validator("NEMOTRON_MAX_RETRIES", mode="before")
    @classmethod
    def validate_nemotron_max_retries(cls, value: Any) -> int:
        try:
            val = int(value)
        except (ValueError, TypeError) as e:
            raise ValueError(f"NEMOTRON_MAX_RETRIES debe ser un entero: {value}") from e
        if val < 0:
            raise ValueError(f"NEMOTRON_MAX_RETRIES no puede ser negativo: {val}")
        return val

    @field_validator("VOICE_STT_PROVIDER", mode="before")
    @classmethod
    def validate_stt_provider(cls, value: Any) -> str:
        val = str(value).lower().strip()
        allowed = {"faster-whisper", "google", "mock"}
        if val not in allowed:
            raise ValueError(f"VOICE_STT_PROVIDER '{val}' no es válido. Opciones permitidas: {sorted(allowed)}")
        return val

    @field_validator("VAD_BACKEND", mode="before")
    @classmethod
    def validate_vad_backend(cls, value: Any) -> str:
        if not value:
            return "energy"
        val = str(value).lower().strip()
        allowed = {"energy", "silero"}
        if val not in allowed:
            raise ValueError(f"VAD_BACKEND '{val}' no es válido. Opciones permitidas: {sorted(allowed)}")
        return val

    @field_validator("BROWSER_BACKEND", mode="before")
    @classmethod
    def validate_browser_backend(cls, value: Any) -> str:
        if not value:
            return "windows"
        val = str(value).lower().strip()
        allowed = {"windows", "playwright", "fake"}
        if val not in allowed:
            raise ValueError(f"BROWSER_BACKEND '{val}' no es válido. Opciones permitidas: {sorted(allowed)}")
        return val

    @field_validator("ANYDOC_BACKEND", mode="before")
    @classmethod
    def validate_anydoc_backend(cls, value: Any) -> str:
        if not value:
            return "anydoc"
        val = str(value).lower().strip()
        allowed = {"anydoc", "docling"}
        if val not in allowed:
            raise ValueError(f"ANYDOC_BACKEND '{val}' no es válido. Opciones permitidas: {sorted(allowed)}")
        return val

    @field_validator("INTENT_ENGINE_MODE", mode="before")
    @classmethod
    def validate_intent_engine_mode(cls, value: Any) -> str:
        if not value:
            return "legacy"
        val = str(value).lower().strip()
        allowed = {"legacy", "shadow", "sai"}
        if val not in allowed:
            raise ValueError(f"INTENT_ENGINE_MODE '{val}' no es válido. Opciones permitidas: {sorted(allowed)}")
        return val

    # WhatsApp Personal & Wake-on-LAN (Fase 6)
    WHATSAPP_OWNER_PHONE_JID: str = Field(
        default="51999999999@s.whatsapp.net",
        description="JID o número de teléfono del propietario autorizado para WhatsApp Personal.",
    )
    WHATSAPP_AUTHORIZED_DEVICES: str = Field(
        default="owner-primary-phone",
        description="Lista separada por comas de identificadores de dispositivos móviles autorizados.",
    )
    WHATSAPP_REMOTE_SHARED_SECRET: str = Field(
        default="jessyca-personal-default-secret-2026",
        description="Clave secreta compartida para firma criptográfica HMAC de mensajes remotos.",
    )
    WOL_TARGET_MAC: str = Field(
        default="04-7C-16-6E-B4-70",
        description="Dirección MAC física de la tarjeta de red cableada del host para Wake-on-LAN.",
    )
    WOL_BROADCAST_IP: str = Field(
        default="192.168.1.255",
        description="Dirección IP de broadcast de la subred local para envío del Magic Packet.",
    )
    WOL_PORT: int = Field(
        default=9,
        description="Puerto UDP estándar para Wake-on-LAN (9 ó 7).",
    )

    def get_effective_summary(self) -> dict[str, Any]:
        """Genera un diccionario de la configuración efectiva sanitizada,

        ocultando credenciales, API keys y tokens secretos.
        """
        raw = self.model_dump()
        safe: dict[str, Any] = {}

        sensitive_substrings = (
            "api_key",
            "auth_token",
            "secret",
            "password",
            "credential",
        )
        non_sensitive_exceptions = (
            "keyword",
            "subkeys",
            "token_pattern",
            "max_tokens",
        )

        for k, v in raw.items():
            k_lower = k.lower()
            is_sensitive = any(pat in k_lower for pat in sensitive_substrings) and not any(
                exc in k_lower for exc in non_sensitive_exceptions
            )

            if is_sensitive:
                safe[k] = "[REDACTED]" if v else ""
            elif isinstance(v, Path):
                safe[k] = str(v)
            elif hasattr(v, "value"):
                safe[k] = v.value
            else:
                safe[k] = v

        return safe

