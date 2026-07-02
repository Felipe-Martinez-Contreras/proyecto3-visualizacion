"""Selección de fuente de calidad del aire (Open-Meteo AQ por defecto, OpenAQ fallback).

Decisión del equipo: usar **Open-Meteo Air Quality** por defecto (gratis, sin key)
y **OpenAQ** como opción/fallback (gratis, requiere key). Ambas se normalizan al
MISMO esquema (``timestamp, zona, pm25, no2, o3``), así que son intercambiables.

Este módulo es la "capa de orquestación" fina que:
- traduce una ``zona`` lógica (Centro/Norte/Sur) a lo que cada API necesita
  (coordenadas lat/lon para Open-Meteo; ``location_id`` para OpenAQ),
- consulta la fuente configurada y normaliza,
- si la fuente primaria falla (excepción de red), intenta la otra (fallback simple).

Se mantiene separado de ``apis.py`` (clientes puros) y ``transformacion.py`` (parseo
puro) a propósito: aquí vive el "qué fuente y con qué fallback", que es lo que cambia
según configuración.
"""

from __future__ import annotations

import os

import pandas as pd
from dotenv import load_dotenv

from ingesta import apis, transformacion

load_dotenv()

# Fuente por defecto (configurable por entorno). Valores válidos: "open-meteo" | "openaq".
FUENTE_AIRE = os.environ.get("FUENTE_AIRE", "open-meteo")


def _coords_zona(zona: str) -> tuple[float, float]:
    """Coordenadas (lat, lon) de una zona para Open-Meteo AQ, desde entorno con defaults.

    Defaults alrededor de Santiago (Centro/Norte/Sur), separados ≥0.15° en latitud
    para que cada zona caiga en una **celda de grilla distinta** de Open-Meteo AQ
    (grilla de ~0.1°; con zonas muy juntas la API devuelve valores idénticos).
    Se pueden ajustar con ``AIRE_LAT_<ZONA>`` / ``AIRE_LON_<ZONA>`` en el ``.env``.
    """
    defaults = {
        "Centro": (-33.45, -70.66),  # Santiago centro
        "Norte": (-33.20, -70.68),   # Colina / Quilicura
        "Sur": (-33.61, -70.58),     # Puente Alto / Pirque
    }
    lat_def, lon_def = defaults.get(zona, defaults["Centro"])
    clave = zona.upper()
    lat = float(os.environ.get(f"AIRE_LAT_{clave}", lat_def))
    lon = float(os.environ.get(f"AIRE_LON_{clave}", lon_def))
    return lat, lon


def _location_id_zona(zona: str) -> str | None:
    """``location_id`` de OpenAQ para una zona, desde ``OPENAQ_LOC_<ZONA>`` (o None)."""
    valor = os.environ.get(f"OPENAQ_LOC_{zona.upper()}")
    return valor or None


def _obtener_openmeteo(zona: str) -> pd.DataFrame:
    """Consulta Open-Meteo AQ para la zona y normaliza al esquema común."""
    lat, lon = _coords_zona(zona)
    cruda = apis.obtener_calidad_aire_openmeteo(lat, lon)
    return transformacion.normalizar_calidad_aire_openmeteo(cruda, zona)


def _obtener_openaq(zona: str) -> pd.DataFrame:
    """Consulta OpenAQ para la zona y normaliza al esquema común."""
    location_id = _location_id_zona(zona)
    if location_id is None:
        raise ValueError(f"No hay OPENAQ_LOC_{zona.upper()} configurado para la zona '{zona}'.")
    cruda = apis.obtener_calidad_aire(location_id)
    return transformacion.normalizar_calidad_aire(cruda, zona)


# Registro de fuentes disponibles: nombre → (función, nombre-de-fallback).
_FUENTES = {
    "open-meteo": _obtener_openmeteo,
    "openaq": _obtener_openaq,
}


def obtener_calidad_aire_zona(zona: str, fuente: str | None = None) -> pd.DataFrame:
    """Devuelve la calidad del aire de una zona ya normalizada al esquema común.

    - ``fuente``: "open-meteo" (por defecto) u "openaq". Si es ``None`` se toma de
      la variable de entorno ``FUENTE_AIRE``.
    - **Fallback:** si la fuente primaria lanza una excepción (típicamente de red),
      se intenta la otra fuente automáticamente. Un solo try/except: simple y claro.

    Siempre devuelve un DataFrame con columnas ``timestamp, zona, pm25, no2, o3``.
    """
    primaria = (fuente or FUENTE_AIRE).lower()
    secundaria = "openaq" if primaria == "open-meteo" else "open-meteo"

    try:
        return _FUENTES[primaria](zona)
    except Exception as error:
        # La primaria falló (red/config): intentamos la secundaria como fallback.
        print(
            f"[aire] Fuente '{primaria}' falló para zona '{zona}' ({error!r}); "
            f"usando fallback '{secundaria}'."
        )
        return _FUENTES[secundaria](zona)
