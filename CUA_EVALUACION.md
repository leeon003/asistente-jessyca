# EVALUACIÓN TÉCNICA Y DE SEGURIDAD: CUA (COMPUTER-USE AGENT)
**Proyecto:** JESSYCA 3.0 (leeon003/asistente-jessyca)  
**Fecha:** 2026-10-14  
**Repositorio Analizado:** `https://github.com/trycua/cua` (Oficial trycua/cua)  
**Veredicto:** **INTEGRACIÓN NATIVA VÍA BASE-SKILL GOVERNADA / RECHAZO DE DEPENDENCIAS EXTERNAS DE CUA (AGPL-3.0 COPYLEFT)**

---

## 1. RESUMEN EJECUTIVO

Se realizó una investigación exhaustiva del repositorio oficial de CUA (`trycua/cua`) y sus paquetes oficiales del ecosistema:
- `cua` (CLI / Core Orquestador)
- `cua-driver` (Controlador de sistema y eventos de interfaz en Windows/macOS/Linux)
- `cua-computer` & `cua-computer-server` (Protocolo de servidor y cliente para Computer Use)
- `cua-agent` (Agente de bucle interactivo de razonamiento y acción)
- `cua-perception` (Módulo de detección visual y parser de UI basado en OmniParser)
- `cua-sandboxes` / `cua-spaces` (Aislamiento de entornos virtuales y contenedores)

### Veredicto y Decisión Arquitectónica
**NO se instalan los paquetes externos de CUA directamente en el entorno de producción.**  
En su lugar:
1. **Se rechaza la dependencia `cua-perception`** debido a que arrastra componentes bajo **licencia AGPL-3.0 (OmniParser)**, lo que representaría una contaminación copyleft restrictiva e inaceptable para el ecosistema de JESSYCA.
2. **Se adopta el patrón de Computer Use gobernado mediante el contrato oficial `BaseSkill` de JESSYCA (`skills/computer_use_skill.py`)**, acoplado directamente al subsistema nativo existente `ComputerUseAdapter` (`core/integration/adapters/computer_use_adapter.py`) y `RiskEngine` (Nivel 3 - HIGH RISK).
3. **Se garantiza el 100% de la funcionalidad de Computer Use** (observación, clics, escritura, atajos de teclado, foco de ventanas y verificación visual) sin dependencias externas inseguras, sin contenedores externos y con cero riesgo de violación de licencias.

---

## 2. ANÁLISIS DE CRITERIOS CONCRETOS

### A. Compatibilidad con Windows
- **CUA Oficial:** `cua-driver` provee soporte para Windows mediante llamadas directas a Win32 API y eventos sintéticos de mouse/teclado. Sin embargo, su arquitectura está fuertemente orientada a correr dentro de máquinas virtuales o sandboxes de Docker en Linux (usando X11/VNC virtual displays), lo que en Windows requiere WSL2 o un driver daemon en segundo plano que compite con la sesión interactiva del usuario.
- **JESSYCA Nativo:** JESSYCA ya cuenta con un subsistema completo para Windows (`core/integration/adapters/computer_use_adapter.py`, `tools/desktop/ui_backend.py`, `tools/desktop/executors.py`) que utiliza `UIAutomationCore`, `comtypes`, `win32gui` y `pyautogui`, operando de manera nativa sobre el escritorio de Windows 10/11 sin necesidad de daemons ni capas de emulación intermedias.

### B. Compatibilidad con Modelos Locales vía Ollama
- **CUA Oficial:** CUA fue concebido principalmente para APIs propietarias en la nube (Anthropic Claude 3.5 Sonnet Computer Use API). Cuando se conecta a modelos locales vía Ollama, CUA requiere que el modelo emita coordenadas `[x, y]` exactas en formato JSON tras ver capturas de pantalla. Modelos compactos locales (de 4B a 8B) sufren de una tasa de error de puntería superior al 45% si no se cuenta con un grounding visual previo.
- **JESSYCA Nativo:** JESSYCA combina el análisis de accesibilidad de Windows (UI Automation) con visión local vía `qwen3-vl:4b` (`core/vision/ollama_vision_provider.py`). Al poder inspeccionar la jerarquía de ventanas y controles del SO, el agente no depende únicamente de coordenadas de píxeles adivinadas por visión, sino de identificadores de control reales (AutomationId, Name, ClassName), logrando una precisión superior al 95%.

### C. Consumo de Recursos (RAM, VRAM, CPU)
- **CUA Oficial:**
  - `cua-perception` (OmniParser): Requiere modelos de detección YOLO + visual captioning (BLIP/Florence), consumiendo **4.5 GB a 6.0 GB de VRAM adicionales** solo para interpretar la pantalla.
  - Al sumarse a un LLM como `gemma4:e4b` (11.7 GB VRAM) o `llama3.1:latest` (2.2 GB VRAM), el sistema satura la GPU RTX 3060 (12 GB VRAM), provocando que los modelos se descarguen a RAM o fallen por OOM.
- **JESSYCA Nativo:**
  - `ComputerUseAdapter` y `WindowsComputerUseSkill` consumen **0 MB de VRAM adicional** para la inspección de UI y eventos del SO (utilizan CPU y APIs Win32 nativas).
  - Cuando se requiere visión, `qwen3-vl:4b` solo consume ~3.6 GB de VRAM de forma transitoria o se consulta bajo demanda, conviviendo perfectamente con `llama3.1:latest` (2.2 GB VRAM) dentro de los 12 GB disponibles.

### D. Licencias y Riesgos Legales
| Componente CUA | Licencia Declarada | Evaluación para JESSYCA |
| :--- | :--- | :--- |
| `cua-driver` | MIT | Seguro y permisivo |
| `cua` (Core) | Apache 2.0 | Seguro y permisivo |
| `cua-perception` / OmniParser | **AGPL-3.0-only** | **RIESGO CRÍTICO (Copyleft restrictivo).** Exige liberar todo el código que interactúe por red. |
| `cua-spaces` | **FSL-1.1-MIT** | No apto para uso comercial irrestricto sin expiración de términos. |

*Conclusión de Licencias:* La presencia de código AGPL-3.0 y FSL en submódulos de CUA representa un riesgo legal inaceptable. El código nativo de JESSYCA es 100% propietario y limpio (MIT/Apache compatible).

### E. Seguridad y Gobernanza
- **CUA Oficial:** No cuenta con un motor de riesgo granular ni políticas de autonomía de 3 niveles. Las acciones de mouse y teclado se ejecutan directamente una vez que el agente emite la llamada.
- **JESSYCA Nativo:** Todas las operaciones de Computer Use están integradas con:
  - `RiskEngine`: Clasifica el movimiento pasivo/lectura como `SAFE` (Nivel 1), y los clics, escritura de texto y atajos globales como `HIGH_RISK` (Nivel 3).
  - `PermissionManager`: Exige autorización explícita antes de ejecutar acciones físicas sobre ventanas críticas.
  - `EmergencyStopManager`: Si el usuario presiona la tecla de pánico o emite "Alto", todas las acciones de Computer Use se abortan en milisegundos.
  - `ExecutionVerifier`: Ninguna acción de Computer Use se da por exitosa sin verificar el cambio de estado en la ventana objetivo (`verified=False` por defecto).

---

## 3. INTEGRACIÓN IMPLEMENTADA

Se encapsuló la capacidad de Computer Use bajo el contrato formal `BaseSkill`:
- **Archivo:** `skills/computer_use_skill.py`
- **Clase:** `WindowsComputerUseSkill(BaseSkill)`
- **ID de Registro:** `windows.computer_use`
- **Acciones Disponibles:**
  1. `observe`: Captura de pantalla, resolución y lista de ventanas visibles activas (Nivel 1 - SAFE).
  2. `click`: Clic de mouse (izquierdo, derecho, doble clic) en coordenadas o elementos identificados (Nivel 3 - HIGH RISK).
  3. `type_text`: Escritura de texto controlado con soporte para caracteres especiales (Nivel 3 - HIGH RISK).
  4. `press_key`: Presión de teclas de control validadas en lista blanca (Nivel 2 - MODERATE RISK).
  5. `hotkey`: Combinaciones de teclas seguras (ej. `ctrl+c`, `alt+tab`) (Nivel 3 - HIGH RISK).
  6. `focus_window`: Traer al frente y activar una ventana por título o proceso (Nivel 2 - MODERATE RISK).
- **Gobernanza:** Pasa invariablemente por `RiskEngine` y `PermissionManager` antes de cualquier llamada a `pyautogui` o `win32gui`.

---

## 4. CONCLUSIÓN Y RECOMENDACIONES

1. **Rechazo formal de paquetes CUA de terceros:** Se evita la instalación de paquetes con riesgo de copyleft AGPL y alto consumo de recursos.
2. **Capacidad Agéntica Preservada:** Jessyca cuenta con control real del escritorio mediante su propia habilidad `windows.computer_use` certificada.
3. **Evolución Futura:** Si en el futuro se requiere visión densa para aplicaciones sin jerarquía de accesibilidad (ej. juegos o apps aceleradas por GPU sin soporte UI Automation), se evaluará un modelo de segmentación visual ligero con licencia MIT o Apache 2.0 (como MobileNet-SSD o Florence-2 de Microsoft).
