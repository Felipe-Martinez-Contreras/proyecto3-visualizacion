"""Tests de normalización con Pandas hacia el esquema de la BD.

Usan respuestas de ejemplo (mockeadas) con el formato conocido de Open-Meteo y
OpenAQ v3. No hay red de por medio.
"""

import math

from ingesta.transformacion import (
    COLUMNAS_AIRE,
    COLUMNAS_CLIMA,
    normalizar_calidad_aire,
    normalizar_clima,
)

# --- Open-Meteo → Condiciones_Clima ----------------------------------------

RESPUESTA_OPENMETEO = {
    "latitude": -33.45,
    "longitude": -70.66,
    "current": {
        "time": "2026-07-01T12:00",
        "temperature_2m": 15.3,
        "relative_humidity_2m": 60,
        "wind_speed_10m": 12.4,
    },
}


def test_normalizar_clima_columnas_y_valores():
    df = normalizar_clima(RESPUESTA_OPENMETEO)

    assert list(df.columns) == COLUMNAS_CLIMA
    assert len(df) == 1  # el clima es global: una fila por lectura
    fila = df.iloc[0]
    assert fila["timestamp"] == "2026-07-01T12:00"
    assert fila["temperatura"] == 15.3
    assert fila["humedad"] == 60.0
    assert fila["viento"] == 12.4


def test_normalizar_clima_no_tiene_columna_zona():
    df = normalizar_clima(RESPUESTA_OPENMETEO)
    assert "zona" not in df.columns


# --- OpenAQ → Calidad_Aire_Hist --------------------------------------------

RESPUESTA_OPENAQ = {
    "results": [
        {
            "parameter": {"name": "pm25", "units": "µg/m³"},
            "value": 12.5,
            "datetime": {"utc": "2026-07-01T12:00:00Z"},
        },
        {
            "parameter": {"name": "no2", "units": "µg/m³"},
            "value": 30.1,
            "datetime": {"utc": "2026-07-01T12:00:00Z"},
        },
        {
            "parameter": {"name": "o3", "units": "µg/m³"},
            "value": 45.0,
            "datetime": {"utc": "2026-07-01T12:00:00Z"},
        },
    ]
}


def test_normalizar_aire_columnas_y_zona_etiquetada():
    df = normalizar_calidad_aire(RESPUESTA_OPENAQ, zona="Centro")

    assert list(df.columns) == COLUMNAS_AIRE
    assert len(df) == 1
    fila = df.iloc[0]
    assert fila["timestamp"] == "2026-07-01T12:00:00Z"
    assert fila["zona"] == "Centro"
    assert fila["pm25"] == 12.5
    assert fila["no2"] == 30.1
    assert fila["o3"] == 45.0


def test_normalizar_aire_rellena_contaminantes_faltantes():
    # Solo llega pm25: no2 y o3 deben existir como columnas, con valor NaN.
    respuesta = {
        "results": [
            {
                "parameter": {"name": "pm25"},
                "value": 8.0,
                "datetime": {"utc": "2026-07-01T13:00:00Z"},
            }
        ]
    }
    df = normalizar_calidad_aire(respuesta, zona="Norte")

    assert list(df.columns) == COLUMNAS_AIRE
    fila = df.iloc[0]
    assert fila["pm25"] == 8.0
    assert math.isnan(fila["no2"])
    assert math.isnan(fila["o3"])


def test_normalizar_aire_respuesta_vacia_devuelve_df_con_esquema():
    df = normalizar_calidad_aire({"results": []}, zona="Sur")
    assert list(df.columns) == COLUMNAS_AIRE
    assert len(df) == 0
