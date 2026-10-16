# JESSYCA 4.0 — PROCEDIMIENTO DE ROLLBACK Y RECUPERACIÓN

**Versión:** 4.0.0-PROD  
**Fecha:** Octubre 2026  
**Responsable:** Integración, Calidad, Seguridad y Publicación  

---

## 1. PRINCIPIOS DE REVERSIÓN Y CONTINUIDAD OPERATIVA

El sistema JESSYCA 4.0 ha sido estructurado mediante capas desacopladas y respaldos incrementales. Ante cualquier incidente crítico en producción, fallo imprevisto de dependencias o corrupción de datos locales, este documento define los procedimientos deterministas para revertir el estado del sistema sin pérdida de datos del usuario.

---

## 2. PUNTOS DE CONTROL Y VERSIONES (GIT TAGS & COMMITS)

| Fase | Descripción del Hito | Referencia / Hash | Procedimiento de Reversión |
|---|---|---|---|
| **Fase 0** | Baseline Inicial y Auditoría de Inventario | `v4.0-baseline` | `git checkout tags/v4.0-baseline` |
| **Fase 1** | Consolidación de Seguridad y Limpieza | `v4.0-fase1` | `git checkout tags/v4.0-fase1` |
| **Fase 2** | Integración SAI y Planificación | `v4.0-fase2` | `git checkout tags/v4.0-fase2` |
| **Fase 3** | Motor del Agente Local y Gobernanza | `v4.0-fase3` | `git checkout tags/v4.0-fase3` |
| **Fase 4** | Control de Escritorio Bounded y CUA | `v4.0-fase4` | `git checkout tags/v4.0-fase4` |
| **Fase 5** | Voz y Diálogo Natural con Barge-In | `v4.0-fase5` | `git checkout tags/v4.0-fase5` |
| **Fase 6** | WhatsApp Personal y Wake-on-LAN | `v4.0-fase6` | `git checkout tags/v4.0-fase6` |
| **Fase 7** | Consolidación Final y Certificación 30 Escenarios | `feature/jessyca-4-agent` | Estado actual verificado |

---

## 3. PROCEDIMIENTO DE ROLLBACK COMPLETO (PASO A PASO)

### Paso 1: Detener Todos los Procesos Activos de JESSYCA
Asegurarse de que no existan instancias de Python en ejecución asociadas al proyecto:
```powershell
Get-Process python -ErrorAction SilentlyContinue | Where-Object { $_.Path -like "*asistente-jessyca*" } | Stop-Process -Force
```

### Paso 2: Crear una Rama de Seguridad del Estado Actual
Antes de cualquier reversión, salvaguarda el estado de trabajo:
```powershell
git branch backup/pre-rollback-$(Get-Date -Format "yyyyMMdd-HHmmss")
```

### Paso 3: Reversión del Código Fuente al Estado Deseado
Para volver a una fase anterior estable (por ejemplo, Fase 6):
```powershell
# Revertir árbol de trabajo manteniendo archivos locales sin seguimiento
git restore .

# O cambiar a un commit/tag específico:
git checkout <commit_hash>
```

### Paso 4: Restauración del Entorno Virtual y Dependencias
Si hubo modificaciones en paquetes de Python:
```powershell
# Reinstalar exactamente las dependencias del baseline certificado
pip install -r docs/jessyca4/requirements_freeze_baseline.txt
```

### Paso 5: Restauración de Bases de Datos y Memoria Local
Si la base de datos de memoria persistente (`data/memory.db` o `data/sessions.db`) requiere restauración:
```powershell
# Restaurar desde la copia de seguridad más reciente en backups/:
Copy-Item "backups/memory_backup_latest.db" "data/memory.db" -Force
```

### Paso 6: Verificación de Integridad Post-Rollback
Ejecuta la suite de pruebas básica para comprobar la estabilidad inmediata:
```powershell
pytest tests/desktop/test_real_windows_assistant_capabilities.py -v
pytest tests/remote/test_whatsapp_personal_and_wol.py -v
```

---

## 4. PLAN DE CONTINGENCIA ANTE FALLOS ESPECÍFICOS

### A. Fallo en el Controlador Wake-on-LAN
- **Síntoma**: La PC no responde al Magic Packet tras una actualización del sistema operativo.
- **Acción**:
  1. Ejecutar `python scripts/diagnose_wol.py`.
  2. Verificar si Windows Update deshabilitó *"Permitir que este dispositivo reactive el equipo"* en el Administrador de Dispositivos.
  3. Re-habilitar la casilla en las propiedades avanzadas del adaptador `Realtek PCIe GbE`.

### B. Fallo en el Mutex de CUA (Sesión Bloqueada)
- **Síntoma**: Error `SessionLockBusyError` persistente.
- **Acción**:
  El mutex `SessionExecutionLock` se libera automáticamente al reiniciar el proceso de JESSYCA. En caso de emergencia, reiniciar el agente o invocar `SessionExecutionLock.get_instance().force_release()`.

### C. Bloqueo por Parada de Emergencia Accidental
- **Síntoma**: Todas las órdenes retornan *"Parada de emergencia activa"*.
- **Acción**:
  Invocar `EmergencyStopManager.get_instance().reset("Motivo de reinicio manual")`.

---

## 5. CONCLUSIÓN

El sistema cuenta con trazabilidad total en Git, copias de seguridad de datos locales y scripts de verificación automatizados, garantizando un RTO (Recovery Time Objective) menor a 3 minutos ante cualquier contingencia operativa.
