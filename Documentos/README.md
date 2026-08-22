# Jessyca Windows MCP 🚀

[![Python Version](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![Architecture](https://img.shields.io/badge/architecture-Clean%20Architecture-green.svg)](docs/architecture.md)
[![License](https://img.shields.io/badge/license-MIT-purple.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/platform-Windows%2010%20%7C%2011-0078D6.svg)](docs/windows_compatibility.md)

**Jessyca Windows MCP** es la arquitectura base extensible de código abierto diseñada para construir un asistente inteligente basado en el **Model Context Protocol (MCP)** en sistemas operativos **Windows 10 y Windows 11**.

El proyecto está diseñado desde cero siguiendo **Clean Architecture**, **principios SOLID**, **tipado estricto** en Python 3.11+, y una separación clara de responsabilidades para garantizar mantenibilidad a largo plazo.

---

## 🏛️ Estructura del Proyecto

```text
asistente-jessyca/
│
├── config/                  # Gestión de configuración tipada (Pydantic BaseSettings)
│   ├── settings.py          # Esquema de configuración y variables de entorno
│   └── manager.py           # ConfigManager Singleton
│
├── core/                    # Núcleo del Dominio (Clean Architecture Core)
│   ├── constants.py         # Constantes globales del sistema
│   ├── exceptions.py        # Jerarquía centralizada de excepciones
│   ├── logger.py            # Sistema de logging centralizado con rotación
│   ├── types.py             # Tipos compartidos, Enums y patrón Result[T]
│   ├── contracts.py         # Interfaces abstractas (Protocols / ABCs)
│   └── error_handler.py     # Manejo global de excepciones no capturadas
│
├── services/                # Servicios de Aplicación y Casos de Uso
│   ├── base_service.py      # Contrato abstracto de servicios con ciclo de vida
│   └── system_service.py    # Servicio de diagnósticos y métricas del SO
│
├── tools/                   # Infraestructura de Herramientas MCP
│   ├── base_tool.py         # Clase abstracta base BaseMCPTool
│   ├── registry.py          # Registro y resolutor dinámico ToolRegistry
│   └── schemas.py           # Esquemas Pydantic y modelos JSON Schema MCP
│
├── utils/                   # Utilidades de Infraestructura y Plataforma
│   ├── platform.py          # Diagnóstico de Windows 10/11 y permisos UAC
│   ├── paths.py             # Resolución centralizada de directorios
│   └── formatting.py        # Sanitización y formateo de datos
│
├── docs/                    # Documentación Técnica
│   ├── architecture.md      # Diseño detallado de la arquitectura
│   ├── windows_compatibility.md # Guía de compatibilidad con Windows
│   └── development.md       # Guía de desarrollo y contribución
│
├── tests/                   # Suite de Pruebas Automatizadas (Pytest)
├── pyproject.toml           # Configuración del proyecto, pytest, ruff y mypy
├── requirements.txt         # Dependencias del proyecto
├── .env.example             # Plantilla de variables de entorno
└── README.md                # Documentación principal
```

---

## ⚡ Inicio Rápido

### Requisitos Previos

- **Python 3.11** o superior instalado.
- Sistema Operativo **Windows 10** (Build >= 19041) o **Windows 11**.

### Instalación

1. Clonar el repositorio:
   ```powershell
   git clone https://github.com/leeon003/asistente-jessyca.git
   cd asistente-jessyca
   ```

2. Crear y activar el entorno virtual:
   ```powershell
   python -m venv venv
   .\venv\Scripts\Activate.ps1
   ```

3. Instalar dependencias:
   ```powershell
   pip install -r requirements.txt
   ```

4. Configurar variables de entorno:
   ```powershell
   Copy-Item .env.example .env
   ```

---

## 🛠️ Herramientas de Calidad y Desarrollo

El proyecto incluye configuración completa para pruebas y análisis estático de código:

### Pruebas Unitarias
```powershell
pytest
```

### Linteado y Formateo (Ruff)
```powershell
ruff check .
```

### Verificación de Tipado Estricto (Mypy)
```powershell
python -m mypy core config services tools utils
```

---

## 📄 Licencia

Este proyecto está bajo la Licencia **MIT**. Consulta el archivo `LICENSE` para más detalles.
