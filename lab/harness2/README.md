# Harness²: laboratorio separado de JESSYCA Asistente

Estado: preparación experimental, desactivada y sin conexión al runtime. No importa
`core`, no registra herramientas, no toca CRM/RAMY, memoria, voz ni control Windows.
No constituye todavía una integración productiva ni demuestra mejora de JESSYCA.

## Upstream revisado

- https://github.com/google-research/harness2
- Commit: `1cfe254e8d25b15f37048c3730134686abe60335`.
- Apache-2.0; los componentes de terceros conservan sus licencias.
- Python >=3.12,<3.14 y POSIX. JESSYCA declara >=3.11 y Windows: usar procesos
  y entornos separados. No añadir Harness² a las dependencias base.
- El extra `bridge` fija FastAPI 0.139.2 y litellm 1.95.0: evitar compartirlo
  con el servidor JESSYCA. No se habilitan los ejecutores Codex/OpenCode remotos.
- El upstream puede editar prompts, guardrails, scripts, plugins y memoria; estas
  salidas nunca se aplican a JESSYCA desde este laboratorio.

## Comprobación efectuada

Se instaló el commit en un venv separado y se ejecutó el demo determinista oficial,
con entorno sin credenciales y directorio aparte, `--k 1 --mode both`:
2 tareas completadas, 0 fallidas, 14 ejecuciones Python y 16 llamadas al editor
local (sin llamadas a un modelo). No se ejecutaron los benchmarks remotos.
Un venv NO es una barrera de seguridad. El demo revisado usa datos sintéticos;
no utilizar este procedimiento para código generado arbitrariamente.

## Contenedor preparado para aislamiento fuerte

Docker no estaba disponible en el entorno de auditoría; esta receta queda pendiente
 de validación. Construir desde esta carpeta (sin incluir el repositorio JESSYCA):

```sh
docker build -t jessyca-harness2-lab lab/harness2
docker run --name jessyca-h2-demo --network none --read-only \
  --cap-drop ALL --security-opt no-new-privileges --pids-limit 64 \
  --memory 512m --cpus 1 --tmpfs /tmp:rw,nosuid,size=128m \
  jessyca-harness2-lab
```

No montar el proyecto, el directorio personal, el socket Docker, credenciales,
dispositivos ni datos reales. La salida de este contenedor es efímera; el log indica
si las tareas finalizaron. El build necesita red; el run la tiene desactivada.
La imagen base y herramientas de build no están bloqueadas por digest: el commit
fija el código upstream, no garantiza por sí solo un build bit a bit reproducible.

## Interfaz de revisión local

```sh
python -m unittest discover -s lab/harness2 -p 'test_*.py'
python lab/harness2/review.py /ruta/a/demo.json --enable-lab
```

`review.py` acepta hasta 64 KiB y solo devuelve contadores enteros validados.
Descarta textos, scripts y campos desconocidos. No ejecuta nada ni acepta comandos.
El commit de salida identifica la versión compatible; no autentica el archivo.
La salida mantiene `production_ready: false`, incluso si el demo pasa.

Para conectar tareas JESSYCA falta un adaptador de fixtures sintéticos y una
comparación objetiva con su línea base, revisión humana de propuestas y validación
Windows. No reutilizar datos del CRM ni activar aprendizaje automático en producción.
