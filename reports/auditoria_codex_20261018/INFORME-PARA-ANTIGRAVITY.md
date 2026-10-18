# JESSYCA: entrega de correcciones, Aurora y acceso de escritorio

Fecha: 18 de octubre de 2026. Instalación: `D:\JESSYCA 3.0\asistente-jessyca`.

**Actualización posterior:** Aurora incorpora escucha continua. Consultar `ESCUCHA-CONTINUA.md` para el comportamiento y las pruebas más recientes; la descripción de pulsar para hablar de esta entrega inicial se conserva como historial.

## Estado de entrega

Las correcciones se aplicaron en la carpeta original. Las pruebas generales se ejecutaron en copias de trabajo sin copiar la configuración privada ni la memoria de producción. También se hicieron comprobaciones reales contra el backend de la instalación original, Ollama, el micrófono G435, el sintetizador y los videos del disco D:.

Existe un ejecutable en `C:\Users\PC\Desktop\JESSYCA.exe`. Al abrirlo inicia el backend si hace falta y abre Aurora en una ventana de aplicación. No requiere Antigravity ni escribir comandos. Es un lanzador de la instalación existente: necesita conservar el repositorio y su entorno `venv` en la ubicación indicada; no es una distribución portátil de todos los modelos y dependencias.

Se usó la imagen proporcionada por el usuario para el icono del ejecutable, el icono de la ventana y la identidad de la interfaz. El JPG original no se modificó.

No se certifica que todo el repositorio esté libre de errores, que todas sus funciones externas estén operativas ni que tenga paridad con OpenClaw. Las pruebas simuladas se distinguen de las comprobaciones físicas.

## Fase 1: ejecución y reproducción local

- «Jessyca, báilame», «bailame» y «báilame» usan `D:\bailes de ia` y el reproductor local. La carpeta contiene 19 videos.
- Se evita repetir el video inmediatamente anterior, también usando el estado persistido del reproductor.
- Una ruta local explícita tiene prioridad sobre heurísticas de búsqueda web. Una ruta inexistente produce un error o una aclaración; no se sustituye silenciosamente por otra búsqueda.
- La verificación del reproductor comprueba proceso, archivo y avance del reloj de decodificación. Lanzar un proceso por sí solo no se considera prueba de reproducción.
- Se comprobó la reproducción real de tres videos diferentes mediante el agente: `jessyca10.mp4`, `jessyca14.mp4`, `jessyca8.mp4`. Se cerraron únicamente los reproductores creados por esas pruebas.

Evidencia: `reproduccion-real.json`. La confirmación verifica reproducción/decodificación, no una evaluación humana de cada cuadro o del sonido.

## Fase 2: intención, contexto, herramientas y seguridad

- Se conservan los manejadores especializados para archivos, aplicaciones, navegador, memoria, documentos, audio, portapapeles y cálculos.
- Se corrige la delegación que omitía las aclaraciones, las listas y las respuestas contextuales. Las decisiones deterministas de aclaración no se reemplazan con una conversación genérica del modelo.
- Se resuelve la intención una sola vez por turno, evitando consumir dos veces una pregunta pendiente.
- Se separan errores, resultados sin verificar y éxitos comprobados. Una herramienta no verificada no genera una confirmación de éxito.
- Las políticas JDE de denegación o revisión detienen la ejecución antes de llamar la herramienta. Los fallos de política cierran el paso.
- Se conserva la confirmación de acciones sensibles. La memoria no concede permisos para futuras acciones.
- Se limita la repetición de acciones mediante identificación de solicitud y parámetros; un fallo interno de tipo no provoca un segundo intento automático con posibles efectos duplicados.
- La confirmación de guardado exige un archivo real no vacío y una ruta explícita; no se confunde una combinación de teclas con un guardado comprobado.
- Se comprueba persistencia antes de afirmar que se recordó un dato y se filtran instrucciones o secretos indebidos de la memoria semántica.

Evidencia: `handoff-regression.xml`, `studio-repair-final.xml`, pruebas del puente de herramientas y contratos del cerebro. Los tests que sustituyen herramientas del escritorio por dobles no certifican interacción física con todas las aplicaciones de Windows.

## Fase 3: voz, modelos y streaming

- El reconocimiento consume los segmentos diferidos de Whisper dentro del trabajo con tiempo límite. Se impide acumular otra inferencia mientras la anterior sigue en ejecución.
- El calentamiento también tiene límite y realiza una inferencia auténtica: el filtro de silencio no debe omitir el modelo y esconder dependencias CUDA ausentes.
- Pedir CPU explícitamente no reutiliza una instancia creada con otra configuración. Se conserva el modelo entre solicitudes equivalentes.
- Se corrigen los eventos de fin de voz y la medición de duración del VAD.
- Se alcanza la cancelación del sintetizador antes de esperar el bloqueo de reproducción.
- El streaming HTTP usa una cola acotada, cancela cooperativamente al desconectar y transmite errores sin emitir una finalización de éxito ficticia. No se repite una acción porque un adaptador lance `TypeError`.
- El proveedor local comunica fallos y cierra el flujo correctamente; se filtran respuestas de razonamiento interno y se admiten salidas de los modelos configurados.

### Voz con naturalidad similar a la referencia indicada

No se encontró un cliente de voz de Perplexity conectado al modo de voz en el código inspeccionado. Existían Edge TTS, Pocket TTS y respaldo SAPI. La configuración real selecciona **Edge TTS, `es-PE-CamilaNeural`, velocidad +0%, tono +0Hz**.

Se implementó una preparación de texto hablado que omite marcas de formato, enlaces crudos, referencias numéricas, bloques de código y razonamiento interno, conservando el texto completo en la conversación. Se mantienen frases orales y se evita fragmentar innecesariamente respuestas cortas. Esto mejora la salida hablada, pero no demuestra que la voz sea idéntica a Perplexity ni activa un servicio propietario inexistente.

Se generó audio real mediante el gestor configurado, sin respaldo: `voz-natural-jessyca.mp3` y `voz-natural-real.json`. Se verificó además su reproducción en el navegador mediante inicio y fin reales del elemento de audio. La valoración de naturalidad y timbre requiere escuchar la muestra.

### Comprobaciones físicas

| Función | Resultado observado | Evidencia |
|---|---|---|
| G435: primera captura | Silencio; no se ejecutó una acción | `microfono-intento1.json` |
| G435: segunda captura | «Jessica, báilame.», confianza 0,8908; transcripción 656 ms; reproducción verificada | `microfono-real.json` |
| Ollama qwen3.5:9b | Generación y streaming reales | `ollama-real.json` |
| Ollama gemma4:e4b | Generación y streaming reales | `ollama-real.json` |
| TTS neuronal | Audio no vacío y reproducción web iniciada/finalizada | `voz-natural-real.json`, `interfaz-prueba-real.json` |
| Backend HTTP | Salud correcta, respuesta normal, streaming completo y rechazo 401 sin clave | `backend-real.json` |

La prueba del G435 fue diagnóstica: capturó voz real y verificó la acción, pero normalizó la frase reconocida antes de enviarla al agente. No se presenta como certificación completa de todo el bucle de escucha continua. No se conservaron grabaciones crudas del micrófono.

## Fase 4: interfaz Aurora elegida por el usuario

Se generaron tres referencias mediante la herramienta integrada imagegen. El usuario eligió **3: Aurora estudio con paneles**. Sus prompts e imágenes están en la carpeta hermana `referencias-interfaz`.

La implementación usa el orbe Three.js existente y mantiene el prototipo anterior. Se sirve en `http://127.0.0.1:8088/studio` con:

- Conversación con el agente real y streaming de respuestas.
- Captura de micrófono al pulsar Hablar; volver a pulsar termina la grabación. El límite de captura es 20 segundos por intervención. No escucha permanentemente en segundo plano.
- Transcripción local del WAV y revisión antes de enviar si la confianza es baja.
- Síntesis neuronal y reproducción en el navegador; el orbe recibe amplitud de la captura o del audio reproducido, no métricas de demostración.
- Interrupción del audio y cancelación cooperativa de la solicitud. Interrumpir no deshace una acción física ya completada.
- Listado real de la carpeta de bailes y accesos para abrirla o pedir un video aleatorio.
- Conversación nueva, consulta de memoria y ajustes de lectura en voz alta/movimiento reducido.
- Errores visibles, sin mensajes de éxito al fallar el servicio.

Prueba en Microsoft Edge real con motor WebGL: conexión, 19 archivos, chat, TTS HTTP 200, inicio/fin de reproducción, fallo controlado, recuperación del botón Enviar y pantalla pequeña sin desbordamiento horizontal. No hubo errores JavaScript. Evidencia: `interfaz-prueba-real.json`, `interfaz-aurora-escritorio.png`, `interfaz-aurora-movil.png`.

## Fase 5: ejecutable y conexión automática

`JESSYCA.exe` es un ejecutable Windows gráfico compilado desde `desktop/JessycaLauncher.cs`, con el icono incrustado. Inicia `jessyca_escritorio.pyw` mediante el entorno instalado, sin consola. El lanzador también intenta iniciar Ollama si no responde y encuentra su ejecutable.

Se comprobó el arranque con el backend detenido: se inició el servicio, apareció la ventana **Jessyca · Aurora**, y las solicitudes de vinculación, estado y archivos devolvieron 200.

El escritorio utiliza un enlace firmado de un solo uso, válido durante 60 segundos, para obtener una sesión temporal de cuatro horas. La clave principal no se coloca en la URL ni se entrega al navegador por ese flujo. El fragmento de vinculación se retira de la dirección y la sesión queda solo en memoria. En una apertura manual de `/studio`, Ajustes conserva la posibilidad de introducir la clave existente.

Se probaron la exigencia de autenticación, los enlaces modificados, vencidos y repetidos, el rechazo de audio inválido/excesivo y los fallos de síntesis sin devolver audio falso. Evidencia: `desktop-studio-auth.xml`, `ejecutable-escritorio.json`.

## Pruebas y alcance

Los archivos JUnit y `matriz-pruebas.json` conservan las cantidades exactas y los fallos de cada ejecución. Las baterías se solapan: **no deben sumarse como si fueran pruebas únicas**. Los resultados antiguos con fallos se conservan para no ocultar la evolución.

- Matriz de backend: 1013 aprobadas en la instantánea de esa ejecución.
- Repetición final de todos los módulos de pruebas situados directamente en `tests/`: **540 aprobadas, cero fallos y cero errores**, en 89,88 segundos. Evidencia: `root-final.xml`. No incluye las subcarpetas de pruebas.
- Regresión de entrega: 85 aprobadas.
- Reparación de voz/contexto e interfaz: 58 aprobadas.
- Autenticación del escritorio e interfaz: 14 aprobadas.
- Batería final de voz, reproducción, interfaz y escritorio: **306 aprobadas, cero fallos y cero errores**, en 226,94 segundos. Evidencia: `voice-desktop-certification.xml`.
- Análisis sintáctico: consultar `sintaxis.json`; revisión de nombres indefinidos y comprobación de dependencias sin errores en el cierre de esta fase.

También se ejecutaron matrices amplias de catálogo, pruebas raíz y módulos adicionales que detectaron fallos; sus resultados originales están adjuntos, aunque varios casos se corrigieron y se volvieron a comprobar en regresiones específicas. Una ejecución anterior interrumpida por un bloqueo de calentamiento y otra afectada por cambios de módulos durante la ejecución no se cuentan como baterías aprobadas.

## Límites y trabajo que no debe darse por certificado

1. No se ha aprobado la suite completa de más de cuatro mil pruebas en una única ejecución final del mismo estado del código.
2. La palabra de activación acústica en español requiere un modelo configurado de OpenWakeWord; sus pruebas con dobles no prueban un modelo acústico instalado.
3. No se certifica cada programa Windows, cada archivo de disco D:, cada operación externa o cada situación de red. Las comprobaciones de YouTube con bloqueo o reproducción no verificable deben seguir reportando error honesto.
4. La integración MCP externa conserva componentes de frontera de ejecución de ejemplo; inicializar el SDK no certifica todo el transporte ni todas las herramientas remotas.
5. No se enviaron correos ni mensajes, ni se probaron operaciones comerciales/CRM sobre datos reales. Se preservó esa separación.
6. No se midieron percentiles de latencia bajo carga sostenida ni calidad perceptual humana del audio. Las medidas de ejemplos reales no son un benchmark general.
7. Una operación nativa bloqueada no se puede matar de forma segura desde un hilo Python. El tiempo límite devuelve control y rechaza solapar otra inferencia; no afirma que el trabajo nativo haya desaparecido.
8. El reproductor limita la lectura de su registro, pero no rota todavía el archivo de registro durante una reproducción muy larga.

## Preservación y revisión en Antigravity

No se sustituyeron `.env`, los almacenes de memoria originales ni la configuración del usuario. Se conservaron los cambios previos de Antigravity; no se hizo un restablecimiento Git ni una sustitución total del repositorio. Las pruebas que necesitan escribir se aislaron en copias de trabajo o rutas temporales. Dos registros semánticos creados por una prueba se retiraron individualmente a un respaldo identificado, sin borrar la memoria previa.

Respaldos de código en la instalación original:

- `backups\auditoria_codex_20261017_234804_265842`
- `backups\auditoria_fase4_pre`
- `backups\auditoria_voz_natural_20261018`
- `backups\auditoria_pruebas_pre_desde_copia` (fuentes de pruebas anteriores conservadas desde la primera copia aislada).

`cambios-respaldados.json` relaciona archivos y hashes. El paquete de correcciones contiene solo fuentes/activos identificados, sin claves, memoria, modelos ni el entorno virtual.

Para revisar, abrir en Antigravity **la carpeta original**, leer este informe y las evidencias, y comparar archivos con sus respaldos. Para usar Jessyca, abrir **JESSYCA.exe en el escritorio**. El navegador solicitará permiso de micrófono la primera vez que se pulse Hablar.
