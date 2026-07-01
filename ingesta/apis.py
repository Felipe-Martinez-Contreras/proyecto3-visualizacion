"""Clientes de APIs externas (clima y calidad del aire).

- Clima: **Open-Meteo** (global para la ciudad; NO requiere API key).
- Calidad del aire: **OpenAQ v3** (por ubicación/zona; requiere API key en el
  header ``X-API-Key``).

Estas funciones solo consultan la API y devuelven la **respuesta cruda** (JSON ya
parseado a ``dict``). La normalización hacia el esquema de la BD vive en
``ingesta/transformacion.py`` — así el "cómo se consulta" queda separado del
"cómo se transforma", que es más fácil de leer y de testear por separado.

Nota: los tests NO llaman a la red; mockean ``requests`` (ver ``tests/``).
"""

from __future__ import annotations

import os

import requests
from dotenv import load_dotenv

# Carga variables desde un `.env` si existe (no pisa las ya definidas en el entorno).
# Es un no-op silencioso cuando no hay `.env`, así que es seguro en tests y en CI.
load_dotenv()

# Timeout por defecto (segundos) para no colgar la ingesta si una API no responde.
TIMEOUT_S = 10

# Base URLs con valores por defecto alineados a `.env.example`.
OPENMETEO_BASE_URL = os.environ.get(
    "OPENMETEO_BASE_URL", "https://api.open-meteo.com/v1"
)
OPENAQ_BASE_URL = os.environ.get("OPENAQ_BASE_URL", "https://api.openaq.org/v3")

# Variables del clima que pedimos a Open-Meteo (mapean al esquema Condiciones_Clima).
OPENMETEO_CURRENT_VARS = "temperature_2m,relative_humidity_2m,wind_speed_10m"


def obtener_clima(
    latitud: float,
    longitud: float,
    *,
    base_url: str = OPENMETEO_BASE_URL,
    timeout: float = TIMEOUT_S,
) -> dict:
    """Consulta el clima actual en Open-Meteo y devuelve la respuesta cruda (JSON).

    El clima es GLOBAL para la ciudad, por eso se consulta con una sola coordenada.
    """
    respuesta = requests.get(
        f"{base_url}/forecast",
        params={
            "latitude": latitud,
            "longitude": longitud,
            "current": OPENMETEO_CURRENT_VARS,
        },
        timeout=timeout,
    )
    respuesta.raise_for_status()
    return respuesta.json()


def obtener_calidad_aire(
    location_id: int | str,
    *,
    api_key: str | None = None,
    base_url: str = OPENAQ_BASE_URL,
    timeout: float = TIMEOUT_S,
) -> dict:
    """Consulta las últimas mediciones de una ubicación en OpenAQ v3 (respuesta cruda).

    La API key se toma del parámetro `api_key` o, si no se pasa, de la variable de
    entorno `OPENAQ_API_KEY`. Solo se envía el header `X-API-Key` cuando hay clave,
    de modo que la ausencia de clave no rompe la construcción de la petición.
    """
    api_key = api_key if api_key is not None else os.environ.get("OPENAQ_API_KEY")
    headers = {"X-API-Key": api_key} if api_key else {}

    respuesta = requests.get(
        f"{base_url}/locations/{location_id}/latest",
        headers=headers,
        timeout=timeout,
    )
    respuesta.raise_for_status()
    return respuesta.json()
