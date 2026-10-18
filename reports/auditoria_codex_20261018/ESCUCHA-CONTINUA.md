# Escucha continua: actualización del 18 de octubre de 2026

## Uso actual

Abrir de nuevo **JESSYCA.exe** en el escritorio para cargar los cambios. Al conectarse, Aurora intenta activar el micrófono. El navegador puede solicitar permiso o una activación inicial; no hace falta repetirla en cada turno.

1. Decir **«Jessyca, hola»** o **«Jessica, hola»**. También se aceptan «Hola, Jessica», «Oye, Jessica» y signos de puntuación habituales de Whisper.
2. Esperar la respuesta y seguir hablando sin pulsar el micrófono. El margen de continuación es de **45 segundos** y se renueva al terminar de responder, para que una respuesta larga no lo consuma.
3. Tras ese margen, Jessyca sigue atenta: volver a decir su nombre inicia otra conversación.
4. Decir **«Jessyca, deja de escuchar»**, o pulsar **Interrumpir**, para desactivar la escucha. Pulsar el micrófono permite reanudarla.

En Ajustes, desmarcar **Mantener a Jessyca atenta** permite usar el modo manual anterior.

## Cambios y verificaciones

- Una apertura de micrófono por sesión de escucha; final automático de frase tras unos 900 ms de silencio y límite de 20 segundos por intervención.
- Se conservan fragmentos previos al inicio de voz, se aceptan confirmaciones breves y el silencio no genera peticiones periódicas.
- Se descartan capturas durante el procesamiento y la voz propia, con un margen posterior de 650 ms. Esto evita que la respuesta se vuelva a enviar como una orden en los casos comprobados.
- La activación se verifica sobre el texto de Whisper; no se presenta como un modelo acústico OpenWakeWord instalado.
- Se corrigieron la puntuación de «Hola, Jessica», la renovación del turno después de respuestas largas y el cambio de modo manual a continuo para no mantener dos micrófonos abiertos.
- La pausa invalida los trabajos de transcripción pendientes, de modo que una respuesta retrasada no pueda ejecutar una orden después de detener la escucha.

## Evidencia automática

**11 pruebas JavaScript aprobadas**, sin fallos. Archivo: `escucha-continua-tests.txt`.

Prueba de navegador con WebAudio controlado y transcripciones/chat simulados, pero TTS real: dos turnos con una apertura de micrófono, voz propia sin nuevas transcripciones, ignorar una frase de fondo fuera de activación, pausar, reanudar y cambiar de modo sin duplicar capturas. Evidencia: `escucha-reanudacion-prueba.json`.

Prueba integrada con español grabado y sintetizado inyectado por WebAudio: **Whisper real, agente HTTP real y TTS real**, sin sustituir sus respuestas. Reconoció:

- «Hola Jessica, ¿cuál es el estado del sistema?», confianza 0,6664.
- «¿Cuánto es dos más dos?», confianza 0,837; respuesta: «Dos más dos son cuatro».

Hubo una sola apertura de micrófono, dos respuestas de voz HTTP 200 y la escucha siguió activa. Evidencia: `escucha-continua-integrada-real.json`.

Estas pruebas usaron **Chrome 155**. Edge 155 se cerró al intentar iniciarlo en modo de pruebas sin ventana con el runtime actual; no se alteró la configuración del navegador del usuario ni el entorno virtual para forzarlo. Las pruebas anteriores con Edge se conservan como históricas, no como verificación de este arranque.

## Pendiente y límites

- El usuario eligió continuar con pruebas automáticas. Falta verificar la nueva escucha con su G435 físico y el ruido habitual de la habitación; las señales inyectadas no prueban ese recorrido.
- Se mantiene el botón Interrumpir. No está certificada la interrupción hablada durante la respuesta TTS: ese tramo se excluye de las nuevas órdenes para evitar realimentación.
- La prueba integrada verificó el transporte de voz, no la corrección semántica de todas las respuestas. La consulta de estado del sistema recibió una respuesta genérica sobre limitaciones; falta conectar o comprobar una herramienta gobernada de diagnóstico para esa consulta. No se afirma que todo el backend esté certificado.
- El transporte de chat de Aurora conserva actualmente su contrato de texto; la confianza STT se filtra en la interfaz. La unificación explícita de la modalidad de voz y sus metadatos en el backend queda como revisión posterior, sin atribuir autoridad de seguridad al audio.

Los cambios están en la instalación original. Respaldos: `backups/escucha_continua_20261018` y `backups/escucha_reanudacion_20261018`.
