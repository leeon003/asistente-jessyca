# Corrección de la respuesta falsa sobre permisos de internet

18 de octubre de 2026.

La frase de la captura, «No, te pedí que habrás YouTube y reproduzcas Play Your Face», terminó en el manejador de conversación. Sus variantes de apertura y reproducción no coincidían con los patrones anteriores. El modelo emitió una negativa sobre internet sin que una herramienta comprobara una denegación de permisos.

Se agregó reconocimiento determinista de órdenes explícitas de YouTube, incluyendo correcciones orales y variantes como «quiero que abras», «habrás» y «reproduzcas». La petición se envía a `browser.youtube` con el título limpio. Continúa atravesando el flujo existente de ejecución, políticas y verificación. No se deshabilitaron protecciones.

Se mantienen fuera de este reconocimiento las negaciones, preguntas explicativas y rutas de archivos locales. Las pruebas verifican además que el streaming use el resultado de la acción y conserve un error de verificación sin convertirlo en éxito.

Prueba real con la frase de la captura: la herramienta recibió `Play Your Face`, resolvió el video `fWov6qL7vyw` y solicitó abrir su página. No hubo error de permisos. La reproducción quedó **sin verificar** y la respuesta fue: «Intenté reproducir Play Your Face en YouTube, pero no pude confirmar que la reproducción haya comenzado». No se afirma que el audio o la reproducción automática hayan comenzado.

Evidencias: `youtube-hotfix-real.json` y `youtube-final.xml`: **58 aprobadas, cero fallos y cero errores**, en 9,02 segundos. Incluyen regresión de YouTube, archivos locales, puente de herramientas y streaming.

Fuentes corregidas en la instalación original:

- `core/intent/explicit_youtube.py`
- `core/local_agent/local_agent.py`
- `tests/local_agent/test_youtube_spoken_correction.py`

Respaldo inmediato: `backups/hotfix_youtube_20261018/local_agent.py`.

El backend fue reiniciado con la corrección. Las sesiones temporales de conexión anteriores caducan al reiniciarlo: cerrar la ventana de Jessyca y abrir **JESSYCA.exe** desde el escritorio genera una conexión nueva automáticamente. No se modifica la memoria guardada.
