# Auditoría de Consolidación: Jarvis Adapter vs Native Windows Skills

## Fecha de Auditoría: 2026-09-27
## Estado del Sistema: CONTROLLED READY (Audit Only)

---

### 1. Resumen Ejecutivo

Esta auditoría evalúa la redundancia funcional, arquitectura de seguridad y consumidores reales del **Jarvis Adapter** (`core/integration/adapters/jarvis_adapter.py`, originado en el recurso externo `Shaan-alpha/jarvis-py`) frente a las **Habilidades Nativas de Windows** de JESSYCA (`skills/apps_skill.py`, `skills/windows_skills.py`, `skills/windows_media_skill.py`, `skills/files_skills.py`, `skills/screenshot_skill.py`).

El objetivo es determinar si Jarvis aporta capacidades exclusivas que justifiquen su mantenimiento en el stack productivo o si constituye una duplicación innecesaria.

---

### 2. Comparación Dimensional de Capacidades

| Dimensión Funcional | Habilidades Nativas JESSYCA | Jarvis Adapter (`jarvis-py`) | Evaluación de Redundancia |
| :--- | :--- | :--- | :--- |
| **Lanzamiento de Aplicaciones** | `apps_skill.py` (`apps.launch`): Resolución de rutas, búsqueda UWP, manejo de argumentos, verificación de PID y ventana activa. | `jarvis.app_control`: Alias estáticos hardcodeados en diccionario (`_APP_ALIASES`), llamada simple a `subprocess.Popen`. | **Duplicada**. La skill nativa es superior y soporta aplicaciones modernas UWP y ejecutables arbitrarios con seguridad de listas blancas. |
| **Cierre de Aplicaciones** | `apps_skill.py` (`apps.close`): Terminación suave (`WM_CLOSE`) con fallback forzado y verificación física de proceso terminado. | `jarvis.app_control`: Búsqueda de nombres de ejecutables en diccionario `_CLOSE_IMAGES` y ejecución de `taskkill /f /im`. | **Duplicada**. La skill nativa es más segura y evita terminaciones abruptas de procesos no deseados. |
| **Control de Volumen / Audio** | `windows_media_skill.py`: Endpoint nativo de Windows Core Audio APIs, lectura de volumen exacto (0-100), silenciamiento y cambio de dispositivo. | `jarvis.volume_control`: Simulación de pulsaciones de teclas multimedia (`VK_VOLUME_UP`, `VK_VOLUME_DOWN`, `VK_VOLUME_MUTE`). | **Duplicada**. La skill nativa interactúa con la API de audio del SO en lugar de depender de emulación de teclado. |
| **Portapapeles (Clipboard)** | `windows_skills.py` (`windows.clipboard`): Lectura y escritura directa en el buffer del portapapeles del SO. | `jarvis.clipboard`: Lectura y escritura utilizando la biblioteca externa `pyperclip`. | **Duplicada**. Introduce una dependencia externa (`pyperclip`) sin aportar valor funcional diferencial. |
| **Telemetría y Procesos** | `windows_skills.py` (`windows.system_info`): Monitoreo de memoria, CPU, procesos activos y recursos del sistema. | `jarvis.system_status`: Extracción de porcentaje de CPU y estado de batería mediante `psutil`. | **Duplicada**. La telemetría nativa del Core cubre la observabilidad del sistema. |
| **Gestión de Archivos** | `files_skills.py`: Búsqueda recursiva, listado, lectura, escritura y organización en cualquier directorio auditado. | `jarvis.workspace_files`: Operaciones básicas de archivos restringidas exclusivamente a `%LOCALAPPDATA%/jarvis/workspace`. | **Duplicada / Subconjunto**. El workspace de Jarvis es un subconjunto artificial que fragmenta el almacenamiento de JESSYCA. |
| **Captura de Pantalla** | `screenshot_skill.py`: Captura multi-monitor, compresión, guardado en sandbox y metadatos de resolución. | NO. Jarvis-py no implementa captura de pantalla en el adaptador auditado. | **Capacidad Única de la Skill Nativa**. |
| **Automatización de Ventanas** | `windows_skills.py`: Minimizar, maximizar, restaurar y enfocar ventanas por título o PID. | NO. Jarvis solo abre o mata ejecutables; no manipula ventanas activas. | **Capacidad Única de la Skill Nativa**. |
| **Navegación Web** | `browser_skills.py` y `browser_youtube_skill.py`: Control de navegación, búsqueda e interacción web nativa. | NO. Solo alias de lanzamiento de ejecutables Chrome/Edge. | **Capacidad Única de la Skill Nativa**. |
| **Frontera de Seguridad** | Integrada de forma nativa con `SecurityPipeline`, `RiskEngine` y políticas JDE. | Requiere mapeo artificial a través del `IntegrationHub` y validación de dependencias externas. | **Nativas son superiores en aislamiento**. |
| **Verificación Física** | `ExecutionVerifier` nativo confirma el estado del SO de forma determinista. | Reporta `verified=False` por defecto requiriendo capas secundarias. | **Nativas se integran sin fricción con el Verifier**. |

---

### 3. Matriz Detallada de Capacidades

| Capacidad | Windows Skill | Jarvis Adapter | ¿Duplicada? | ¿Aporta Capacidad Única? | Consumidor Real |
| :--- | :--- | :--- | :---: | :---: | :--- |
| `apps.launch` | `apps_skill.py` | `jarvis.app_control` (open) | SÍ | NO | `JessycaLocalAgent`, `apps_skill` |
| `apps.close` | `apps_skill.py` | `jarvis.app_control` (close) | SÍ | NO | `JessycaLocalAgent`, `apps_skill` |
| `system.status` | `windows_skills.py` | `jarvis.system_status` | SÍ | NO | `windows_skills` |
| `audio.volume` | `windows_media_skill.py`| `jarvis.volume_control` | SÍ | NO | `windows_media_skill` |
| `clipboard` | `windows_skills.py` | `jarvis.clipboard` | SÍ | NO | `windows_skills` |
| `workspace_files`| `files_skills.py` | `jarvis.workspace_files` | SÍ | NO | Solo tests de Jarvis |
| `screenshot` | `screenshot_skill.py` | NO | NO | N/A (Solo Nativo)| `screenshot_skill` |
| `window.focus` | `windows_skills.py` | NO | NO | N/A (Solo Nativo)| `windows_skills` |

---

### 4. Búsqueda y Clasificación de Consumidores Reales de Jarvis

1. **`core/integration/hub.py`:**
   - **Registro:** Se importa y registra en el `IntegrationRegistry` condicionado por la bandera:
     ```python
     jarvis_enabled = getattr(settings, "JARVIS_ENABLED", False)
     hub.registry.register(jarvis_adapter, enabled=jarvis_enabled)
     ```
   - **Estado:** En configuración estándar, `jarvis_enabled` es `False`.
2. **`core/integration/adapters/__init__.py` y `core/integration/__init__.py`:**
   - **Re-exportación:** Expone `JarvisAdapter` en la API pública de adaptadores del hub.
3. **`tests/test_jarvis_adapter.py`:**
   - **Batería:** 30 pruebas unitarias exhaustivas que evalúan ciclo de vida, dependencias, prevención de path traversal y manejo de errores.
   - **Cobertura:** 100% PASS (30/30).
4. **`core/agent/` / `core/local_agent/`:**
   - **Consumo en Producción:** **CERO (0)**. Ningún flujo del agente principal invoca capacidades con prefijo `jarvis.*`. Todas las operaciones de sistema operativo se canalizan a través de las habilidades nativas (`apps.*`, `windows.*`, `files.*`).

---

### 5. Clasificación Oficial

- **Jarvis Adapter:** `CONTROLLED / DISABLED BY DEFAULT (TEST ONLY)`.
  - No participa en ninguna ruta de producción.
  - Duplica el 100% de sus capacidades con las habilidades nativas.
  - Agrega dependencias innecesarias (`pyperclip`, `psutil`).
  - No aporta ninguna capacidad técnica exclusiva.
- **Native Windows Skills:** `PRODUCTION CERTIFIED / ACTIVE (CONTROLLED)`.
  - Son el estándar arquitectónico de interacción con el sistema operativo Windows para JESSYCA PC.

---

### 6. Recomendación Arquitectónica y Hoja de Ruta

**Dictamen:** `KEEP IN CONTROLLED STATE + DEPRECATION CANDIDATE (NO BORRAR EN ESTA FASE)`.

1. **Acción Inmediata (Fase Actual):**
   - Mantener `core/integration/adapters/jarvis_adapter.py` y `tests/test_jarvis_adapter.py` intactos para garantizar la estabilidad de los 3,581 tests de regresión global.
   - Mantener la bandera `JARVIS_ENABLED=False` por defecto.
2. **Plan de Deprecación Futuro (Post-Certificación):**
   - En una fase de limpieza de dependencias, marcar formalmente el adaptador como deprecado en el catálogo del Integration Hub.
   - Preservar las pruebas unitarias como validación de referencia del marco de adaptadores externos, o refactorizar el adaptador para que sea una fachada que llame internamente a las skills nativas.
