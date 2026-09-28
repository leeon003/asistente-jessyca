# JESSYCA PC — ORCA + ADE FASE 3 SECURITY REPORT

## ANÁLISIS DE POSTURA DE SEGURIDAD

### 1. Monopolio y Autoridad de Decisión (JDE)
* Todo contrato de tarea `OrcaTaskContract` requiere una decisión previa emitida por el JDE (`ALLOW`).
* Si JDE dictamina `DENY`, la tarea se aborta con cero mutación de disco, cero ejecución de procesos y cero efectos colaterales.
* La firma inmutable (`seal` HMAC/SHA-256) previene la alteración post-decisión de permisos, objetivos o workspaces.

### 2. Contención de Comandos (CommandSecurityGuard)
* **Allowlist Estricta:** Comandos limitados a prefijos autorizados (`git status`, `git diff`, `git branch`, `git log`, `git worktree`, `pytest`, `python -m py_compile`, `python -m unittest`).
* **Bloqueo de Inyecciones y Encadenamiento:** Rechazo automático de separadores y tokens peligrosos (`&&`, `;`, `|`, `` ` ``, `$()`, `>`, `<`, `\n`, `\r`).
* **Bloqueo de Intérpretes del Sistema:** Ejecución de `powershell`, `cmd`, `bash`, `sh`, `sudo`, `curl`, `wget`, `reg`, `net`, `format`, `rm -rf` terminantemente prohibida.

### 3. Política de Red (NetworkSecurityGuard)
* **Aislamiento por Defecto:** `NETWORK = DENY` sin excepción para tráfico saliente externo.
* **Excepción Acotada:** Solo se permite tráfico hacia `localhost` / `127.0.0.1` cuando esté explícitamente ligado a una decisión JDE (`decision_id`).

### 4. Redacción de Secretos y Credenciales
* Motores de redacción regex cubren API keys (`sk-...`), GitHub Personal Access Tokens (`ghp_...`, `gho_...`), contraseñas en configs/env (`password=...`), llaves privadas PEM/RSA (`BEGIN ... PRIVATE KEY`) y connection strings URI.
* Las credenciales nunca son propagadas a logs, contratos de resultado, metadatos ni reportes de auditoría.

### 5. Resistencia a Inyecciones Adversarias de Prompt
* Batería adversarial con 10 vectores de inyección probados contra el orquestador gobernado.
* Todas las solicitudes que intentan desactivar JDE, modificar RiskEngine, consultar secretos o alterar modos operacionales resultan en `DENIED` sin efectos laterales.
