# Monitoreo de Movilidad Urbana y Calidad del Aire

Dashboard interactivo en tiempo real que monitorea **movilidad urbana** y **calidad
del aire** por zona (Centro, Norte, Sur). Proyecto Unidad 3 — Visualización de Datos.

> Estado: **en desarrollo**. Ingesta (APIs + simulador + scheduler) funcionando;
> dashboard con la línea temporal de tráfico y refresco en vivo. Faltan los filtros
> y las otras dos visualizaciones.

## Stack

- **Python 3.12** — ingesta (scheduler) + dashboard. Entorno gestionado con **`uv`** en un `.venv`.
- **SQLite** — un único archivo `db/monitoreo.sqlite`, versionado en el repo y
  compartido por el equipo.
- **Dash + Plotly** — visualización · **Pandas** — transformación.
- **APScheduler** — ingesta continua · **requests** — clientes de API.
- **Docker + docker-compose** — orquestación.

## Estructura del proyecto

```
.
├── db/                 # Base de datos SQLite
│   ├── schema.sql      #   esquema (3 tablas) — fuente de verdad
│   ├── init_db.py      #   crea/recrea db/monitoreo.sqlite
│   └── monitoreo.sqlite#   archivo de BD (versionado)
├── ingesta/            # Consumo de APIs, simulador de tráfico y scheduler
├── datos/              # Acceso a datos: conexión + repositorio de las 3 tablas
├── dashboard/          # App Dash + Plotly (layout, callbacks, vistas)
├── tests/              # Tests con pytest
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
└── .env.example
```

Se eligió una estructura de **paquetes por capa a nivel raíz** (`ingesta`, `datos`,
`dashboard`) en lugar de un layout `src/`: para un proyecto educacional y de vida corta
es más plano y fácil de navegar, sin dejar de separar responsabilidades con claridad.

## Puesta en marcha (local)

Requiere **Python 3.12** y **[`uv`](https://docs.astral.sh/uv/)** (`brew install uv`).
El entorno se gestiona siempre con `uv` dentro de un `.venv`.

```bash
# 1. Entorno virtual (Python 3.12) e instalación de dependencias
uv venv --python 3.12
uv pip install -r requirements.txt

# 2. Variables de entorno (opcional; hay valores por defecto)
cp .env.example .env

# 3. Crear la base de datos (idempotente)
uv run python db/init_db.py

# 4. Correr los tests
uv run pytest
```

> `uv run <cmd>` ejecuta dentro del `.venv` sin necesidad de activarlo. Si prefieres
> activarlo: `source .venv/bin/activate` (Windows: `.venv\Scripts\activate`).

## Puesta en marcha (Docker)

```bash
docker compose up --build
```

Levanta dos servicios que comparten el archivo SQLite vía volumen del repo:

- **simulador** — ingesta continua (`ingesta.scheduler`).
- **dashboard** — app Dash en http://localhost:8050 (`dashboard.app`).

En local, el dashboard también puede arrancarse directo con
`uv run python -m dashboard.app`.

## Modelo de datos

Tres tablas relacionadas por `timestamp` (y `zona` cuando aplica). El clima es global
(sin `zona`). Ver `db/schema.sql`.

| Tabla                | Columnas                                                        |
|----------------------|-----------------------------------------------------------------|
| `Trafico`            | id, timestamp, zona, vehiculos, velocidad_promedio              |
| `Calidad_Aire_Hist`  | id, timestamp, zona, pm25, no2, o3                              |
| `Condiciones_Clima`  | id, timestamp, temperatura, humedad, viento                    |
