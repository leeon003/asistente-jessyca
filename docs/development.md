# Guía para Desarrolladores - Jessyca Windows MCP

## Requisitos Previos

- Python 3.11+
- Git
- Consola de Windows (PowerShell, Command Prompt o Windows Terminal)

---

## Configuración del Entorno de Desarrollo

1. Clonar el repositorio y navegar a la carpeta:
```powershell
git clone https://github.com/leeon003/asistente-jessyca.git
cd asistente-jessyca
```

2. Crear y activar un entorno virtual de Python:
```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
```

3. Instalar las dependencias de desarrollo:
```powershell
pip install -r requirements.txt
```

---

## Ejecución de Pruebas y Calidad de Código

### 1. Pruebas Unitarias con Pytest
```powershell
pytest
```

### 2. Linter y Formateador con Ruff
```powershell
ruff check .
ruff format .
```

### 3. Verificación de Tipado Estricto con Mypy
```powershell
python -m mypy core config services tools utils
```
