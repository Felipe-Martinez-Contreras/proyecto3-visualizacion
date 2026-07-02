# Monitoreo de Movilidad Urbana y Calidad del Aire

Dashboard interactivo en tiempo real que monitorea **movilidad urbana** y **calidad
del aire** por zona (Centro, Norte, Sur). Proyecto Unidad 3 — Visualización de Datos.

> Estado: **en desarrollo**. Ingesta (APIs + simulador + scheduler) funcionando;
> dashboard con refresco en vivo, las 3 visualizaciones del enunciado (línea
> temporal de tráfico, PM2.5 vs vehículos, temperatura vs tráfico) y los 4
> filtros interactivos (zona, rango de tiempo, métrica y congestión — esta
> última derivada al vuelo, no almacenada).

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
│   ├── sembrar_historico.py #  siembra historial para la demo (real o sintético)
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

# 5. (Opcional) Sembrar historial de 24 h para la demo
#    Por defecto usa datos REALES de Open-Meteo (clima y calidad del aire
#    históricos, resolución horaria, sin API key) + tráfico simulado.
#    (--limpiar borra los datos previos)
uv run python -m db.sembrar_historico --limpiar

# Fallback sin red (o para más resolución): todo sintético, ticks por minuto.
uv run python -m db.sembrar_historico --fuente sintetico --limpiar --semilla 42
```

> La siembra `--fuente real` requiere internet; si Open-Meteo falla, el script
> termina con error y sugiere `--fuente sintetico`. `--paso-minutos` solo aplica
> a la fuente sintética (la real es horaria, ~24 ticks/día).

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

Ambos contenedores fijan `TZ=America/Santiago` (en `docker-compose.yml`), de modo
que los timestamps generados dentro de Docker quedan en hora de Chile, alineados
con las corridas locales. La imagen base `python:3.12-slim` ya incluye `tzdata`,
así que basta con la variable de entorno.

## Modelo de datos

Tres tablas relacionadas por `timestamp` (y `zona` cuando aplica). El clima es global
(sin `zona`). Ver `db/schema.sql`.

| Tabla                | Columnas                                                        |
|----------------------|-----------------------------------------------------------------|
| `Trafico`            | id, timestamp, zona, vehiculos, velocidad_promedio              |
| `Calidad_Aire_Hist`  | id, timestamp, zona, pm25, no2, o3                              |
| `Condiciones_Clima`  | id, timestamp, temperatura, humedad, viento                    |
