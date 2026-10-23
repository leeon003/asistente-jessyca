# Obsidiana · orbe expresivo

Sustituye el renderer aurora_core.js conservando AuroraCore3D y los métodos
usados por Studio y Aurora. Canvas 2D, sin nuevas dependencias. No cambia voz,
conversación, backend, Harness², CRM ni ejecutable de Windows.

Estados: IDLE reposo; LISTENING/WAKEWORD atención; THINKING/TRANSCRIBING/
ROUTING/EXECUTING/SEARCHING procesamiento; SPEAKING/RESPONDING habla;
CLARIFYING/CONFIRMING/AWAITING_CONFIRMATION espera; ERROR/BLOCKED/FAILED atención;
SUCCESS/COMPLETE/COMPLETED sonrisa. No deduce éxito del silencio o de IDLE.
Studio emite principalmente IDLE, LISTENING, THINKING, SPEAKING y ERROR;
los demás gestos requieren señal explícita del cliente.

Audio con amplitud real, caducidad de 250 ms, modo de movimiento reducido,
pausa en pestañas ocultas, densidad máxima 2 y dispose() para limpiar recursos.
Paleta Obsidiana fija: esfera oscura, aro plateado y luz azul tenue.

## Verificación · 23 octubre 2026

Antes: 10 pruebas Python Studio y 11 JavaScript voz aprobadas.
Después: 22 Python y 14 JavaScript aprobadas.

```sh
python -m pytest -o addopts= -q tests/server/test_aurora_studio.py tests/test_brain_harness_merge.py tests/test_audit_regressions.py tests/test_pending_regressions.py
node --test tests/aurora/test_obsidiana.cjs tests/voice/test_continuous_studio.cjs
```

La comprobación visual Chromium no pudo ejecutarse: navegador ausente y descarga
inválida en el entorno. Pendiente Windows: Ctrl+F5, texto, escucha y voz,
detener, movimiento reducido y redimensionado. No certifica toda la aplicación.

## Local

Conservar cambios y stashes antes de actualizar la rama de integración.
No se modifican los archivos Studio personalizados. No reemplazar Jessyca.exe
ni usar reset --hard. Renderer servido en /studio/orb/js/aurora_core.js.

## Actualización de rasgos femeninos

Ojos ovalados verticales, pupilas con reflejos, cejas arqueadas de extremos
finos y pestañas exteriores sutiles. Se conserva la esfera oscura y el aro
plateado. El parpadeo ahora cierra suavemente los párpados y recorta las pupilas
para que no sobresalgan. Los rasgos se aplican a todos los estados del renderer,
incluida la sonrisa de completado, sin cambiar las señales de voz o tareas.

Validación antes y después: 14 pruebas JavaScript y 10 Python de Studio aprobadas.
El acabado es una interpretación Canvas del concepto, no un render idéntico a
la imagen artística. La comprobación visual en Windows sigue pendiente.

## Ajuste kawaii tras revisión en Windows

La captura del usuario mostraba una mirada demasiado abierta. Se redujo la
altura de los ojos y se aumentó la proporción de pupila, con reflejos suaves,
cejas más bajas, pestañas cortas, rubor tenue y sonrisa pequeña. Se conservan
los estados reales y el modo de movimiento reducido. Pruebas antes y después:
14 JavaScript y 10 Python aprobadas. Pendiente valoración visual del usuario.
