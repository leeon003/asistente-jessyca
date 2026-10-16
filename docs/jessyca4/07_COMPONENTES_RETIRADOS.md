# JESSYCA 4.0 — INFORME DE COMPONENTES RETIRADOS Y GOBERNANZA DE CÓDIGO

**Fecha:** Octubre 2026  
**Responsable:** Integración, Calidad, Seguridad y Publicación  
**Principio Rector:** *No borrar por limpieza estética. Toda retirada debe contar con prueba de no-uso en rutas activas, ausencia de dependencias indirectas, preservación funcional y procedimiento de reversión.*

---

## 1. CRITERIOS DE AUDITORÍA Y POLÍTICA DE RETIRADA

Para cada módulo o componente evaluado se verificaron 5 invariantes obligatorias:
1. **No utilizado por ninguna ruta activa**: Ni por el bucle principal (`main.py`), ni por el agente local (`JessycaLocalAgent`), ni por las interfaces de voz o WhatsApp personal.
2. **Sin dependencias indirectas**: Ningún decorador, inyector de dependencias ni adaptador dinámico lo importa en tiempo de ejecución.
3. **Sin pruebas necesarias asociadas**: Ninguna suite de pruebas unitarias o de aceptación depende de su implementación.
4. **Preservación total de funcionalidad**: La capacidad fue absorbida o superada por un componente canónico consolidado.
5. **Respaldo y Reversión garantizados**: El código original se encuentra preservado en el historial Git y documentado con plan de rollback.

---

## 2. COMPONENTES EVALUADOS Y DICTAMEN DE CONSOLIDACIÓN

### 2.1. Adaptadores y Conectores de Tiendas Comerciales / CRM
- **Evaluación**: Durante fases tempranas se propuso la inclusión de conectores a pasarelas de pago, bots de WhatsApp comerciales y CRMs de atención al cliente.
- **Acción**: **Rechazo total y exclusión definitiva**. JESSYCA 4.0 es estricta y exclusivamente un **asistente personal privado**. No contiene librerías comerciales, ni webhooks de terceros, ni telemetría publicitaria.
- **Evidencia**: Se comprobó que `interfaces/whatsapp_personal/gateway.py` se comunica únicamente con el propietario registrado bajo autenticación HMAC y sin dependencias de servicios externos.

### 2.2. Terminal Shell Directa Desgobernada (`cmd` / `powershell` arbitrarios)
- **Evaluación**: Existían funciones legadas de ejecución de comandos de consola mediante `os.system` o `subprocess.Popen(shell=True)`.
- **Riesgo**: Ejecución arbitraria de código sin análisis de riesgo, bypass de sandbox e inyección de comandos maliciosos.
- **Acción**: **Retirada y sustitución**. La ejecución desgobernada fue completamente reemplazada por el catálogo seguro de `UnifiedDesktopController`, `WindowsAppsSkill` y la lista de comandos prohibidos en `RemoteTaskRouter`.
- **Demostración de No-Uso**:
  - `grep_search` confirmó 0 llamadas a `shell=True` en rutas activas de habilidades del usuario.
  - La prueba de aceptación `SC-24` certifica el bloqueo inmediato de `cmd.exe /c format`.

### 2.3. Fallback Sintético de Éxito Falso (Mocking en Rutas de Producción)
- **Evaluación**: Funciones en versiones anteriores que retornaban `"status": "success"` basándose únicamente en que una función no arrojó excepción, sin verificar si el archivo se creó físicamente en disco o si la ventana de la aplicación realmente apareció en pantalla.
- **Riesgo**: Falsos positivos que engañan al usuario haciéndole creer que una tarea se completó cuando en realidad falló silenciosamente.
- **Acción**: **Retirada estricta**. Erradicado en favor de `ExecutionVerifier`, que comprueba el PID real, la existencia física de bytes en disco y las ventanas activas con Win32 API.
- **Demostración**: Escenario de aceptación `SC-23` comprueba que la consulta a un archivo inexistente reporta honestamente el fallo.

### 2.4. Enrutamiento Ambiguo de Audio (Toggle Ciego)
- **Evaluación**: El método `ejecutar` de `windows.audio` conmutaba el estado de mute mediante toggle (`new_mute = not curr_mute`), haciendo imposible asegurar el estado solicitado si la llamada provenía de una orden idempotente ("silencia el audio").
- **Acción**: **Refactorizado y corregido de forma segura**. Se incorporaron las acciones explícitas deterministas `"silenciar"` (`SetMute(True)`) y `"desilenciar"` (`SetMute(False)`), manteniendo `"toggle_mute"` solo para botones de conmutación.
- **Demostración**: Escenarios `SC-07` y `SC-08` verifican la fijación y restauración física del mute con pycaw sin depender de estados previos.

---

## 3. COMPONENTES PRESERVADOS (EVIDENCIA DE UTILIDAD)

Los siguientes componentes fueron sometidos a escrutinio y se determinó su **preservación**:

1. **`core/emergency_stop.py` (`EmergencyStopManager`)**:
   - Vital para la seguridad física del usuario. Proporciona interrupción inmediata del audio, mouse y cancelación de hilos de fondo en <5 ms.
2. **`core/execution/idempotency_guard.py`**:
   - Evita la duplicación de procesos cuando el usuario repite una instrucción o cuando la red retransmite un mensaje.
3. **`skills/skill_sandbox.py` y `core/risk_engine.py`**:
   - Protege activamente el sistema de archivos contra escritura o lectura en `system32`, `windows`, y credenciales `.env`.
4. **`core/remote/wol_controller.py`**:
   - Mantiene la capacidad física de encendido remoto Ethernet probada y documentada para la placa MSI B550M PRO-VDH.

---

## 4. REGISTRO DE ARCHIVOS TEMPORALES Y BASURA DE PRUEBAS ELIMINADA

Durante la ejecución de las fases de prueba se detectaron tres archivos temporales huérfanos creados por scripts de prueba de habilidades en el directorio raíz:
- `nota_asistente.txt` (archivo de prueba de texto)
- `ruta de destino` (artefacto de prueba de rutas con espacios)
- `ruta del archivo` (artefacto de prueba de parámetros)

**Evidencia de Retirada Segura**:
- Se verificó que ningún archivo de configuración (`settings.py`, `apps.yaml`) ni módulo de código fuente hacía referencia a estos tres archivos.
- Fueron eliminados de forma segura mediante PowerShell `Remove-Item` sin impacto en ninguna prueba ni funcionalidad del sistema.

---

## 5. CONCLUSIÓN

No se eliminó ningún módulo por criterios cosméticos. Todas las simplificaciones obedecieron a la política de **seguridad por diseño, determinismo operativo y eliminación de falsos éxitos**.
