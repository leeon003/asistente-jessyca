# Estado guardado para continuar

Estado histórico del cierre del 18 de octubre de 2026, America/Lima. El usuario retomó el trabajo posteriormente con «hola buenos días continúa». Consultar `ESCUCHA-CONTINUA.md` y sus evidencias para la actualización actual; los detalles siguientes conservan el punto de partida de la reanudación.

## Instalación y entregas

- Repositorio original: `D:\JESSYCA 3.0\asistente-jessyca`. Las correcciones están escritas allí.
- Ejecutable de escritorio: `C:\Users\PC\Desktop\JESSYCA.exe`. Usa la instalación original y `venv`, inicia el backend y abre Aurora con conexión temporal firmada. Icono e identidad usan el JPG del usuario, preservado.
- Interfaz elegida: opción 3, Aurora estudio con paneles. Funciona en `/studio`, puerto 8088.
- Informes y evidencias: esta carpeta y `D:\JESSYCA 3.0\asistente-jessyca\reports\auditoria_codex_20261018`.
- No se hizo un restablecimiento Git ni un commit indiscriminado de los cambios previos de Antigravity. No se sustituyeron las claves/configuración privada ni los almacenes de memoria.

## Último cambio: escucha continua

El usuario señaló que no debe pulsar el micrófono en cada turno. Se implementó en los archivos estáticos originales:

- `interfaces/webui_bridge/studio_static/continuous_voice.js`: segmentación local de audio por energía, inicio de voz, pre-roll aproximado de 300 ms, final tras 900 ms de silencio, duración máxima de 20 s y mínimo de voz 180 ms. No es un modelo acústico OpenWakeWord.
- `studio.js`: una sola apertura del micrófono por sesión de escucha; transcripción automática al terminar la frase; activación textual por «Jessyca» o «Jessica»; continuación sin nombre durante 45 segundos desde cada frase aceptada. Fuera de esa ventana se exige el nombre nuevamente. No se transmiten fragmentos durante silencio continuo.
- La captura no se usa para nuevas órdenes mientras hay procesamiento o TTS; se descartan los fragmentos durante la voz propia y un margen de 650 ms. No se certificó interrupción hablada durante el TTS; el botón Interrumpir sí corta el audio y pausa la escucha.
- Se puede decir «Jessyca, deja de escuchar» para desactivar, o usar Interrumpir. El micrófono vuelve a activarse con su botón. Ajustes permite desmarcar «Mantener a Jessyca atenta» para volver a pulsar para hablar.
- `index.html` carga el nuevo módulo y muestra el ajuste activado por defecto. Al conectar intenta solicitar el micrófono; el navegador puede requerir permiso/activación inicial una sola vez.
- Respaldo anterior: `backups\escucha_continua_20261018`.

## Verificación más reciente

- **9 pruebas JavaScript aprobadas**, cero fallos. Archivo: `tests/voice/test_continuous_studio.cjs`; salida: `escucha-continua-tests.txt`.
- Prueba real en Microsoft Edge/WebAudio con señal de micrófono controlada, transcripciones/chat simulados y TTS real: dos turnos, una sola apertura del micrófono, reanudación automática, frase de fondo sin activación ignorada, voz propia sin nuevas transcripciones, parada/liberación del micrófono, reactivación y modo manual. Cero errores JavaScript. Evidencia: `escucha-continua-prueba.json`, `escucha-continua-interfaz.png`.
- **Pendiente:** probar este nuevo modo de escucha continua con la voz real del usuario y ruido habitual. No presentar la prueba controlada como certificación física de su G435 dentro de Aurora.
- Las ventanas ya abiertas mantienen el JavaScript anterior: al retomar, cerrar la ventana de Jessyca y abrir el ejecutable del escritorio para cargar el nuevo modo. No hizo falta reiniciar el backend para este cambio estático.

## Corrección inmediatamente anterior: YouTube

- La frase «No, te pedí que habrás YouTube y reproduzcas Play Your Face» se desviaba a conversación; el modelo inventó falta de acceso a internet.
- `core/intent/explicit_youtube.py` y su llamada prioritaria en `_resolve_intent` corrigen órdenes explícitas y correcciones orales. Conservan el flujo de políticas y verificación.
- **58 pruebas aprobadas**; prueba real activó `browser.youtube`, encontró `fWov6qL7vyw` y abrió su página. La reproducción automática quedó sin verificar y se informó honestamente. Evidencias: `HOTFIX-YOUTUBE.md`, `youtube-final.xml`, `youtube-hotfix-real.json`.
- Backend reiniciado después de ese arreglo. Lanzador padre observado PID 28640; verificar procesos/parentesco y comando antes de cualquier cambio futuro, porque los PID pueden reutilizarse.

## Resultados previos y límites

- Últimas baterías anteriores a estos hotfixes: voz/interfaz/escritorio **306 aprobadas**; pruebas de los módulos raíz **540 aprobadas**. Matriz anterior de backend: 1013 aprobadas. Son instantáneas diferentes y existen baterías solapadas; no sumar como pruebas únicas.
- «Báilame» reprodujo físicamente tres videos diferentes de `D:\bailes de ia`. Hay 19 videos; evita repetición inmediata.
- G435 probado previamente con voz real, pero mediante diagnóstico anterior, no la nueva captura continua de navegador.
- Voz configurada y probada: Edge TTS, Camila es-PE. No se encontró integración real de voz de Perplexity ni se certificó equivalencia de timbre/naturalidad.
- Ollama qwen3.5:9b y gemma4:e4b generaron y emitieron streaming reales.
- No se certifica todo el repositorio ni paridad con OpenClaw. Permanecen límites de reproducción externa verificada, transporte MCP de ejemplo, modelo acústico de activación en español y pruebas físicas de todas las aplicaciones. Consultar informe principal.
- El informe principal y la guía rápida describen el modo de pulsar para hablar anterior: este archivo es la actualización más reciente sobre escucha continua. Actualizarlos al retomar, después de la prueba con el usuario.

## Próximo paso al retomar

Probar en la aplicación con el usuario: abrir JESSYCA.exe, permitir el micrófono si se pide, decir «Jessyca, hola», esperar la respuesta y dar otra orden sin pulsar; comprobar después «Jessyca, báilame», las pausas, el ruido de fondo y la desactivación. Corregir con evidencia cualquier fallo y actualizar la guía y el informe. No volver a pedir confirmaciones ya autorizadas ni reiniciar la auditoría desde cero.
