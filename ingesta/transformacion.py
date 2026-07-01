"""Normalización con Pandas de las respuestas crudas hacia el esquema de la BD.

Convierte el JSON que devuelven los clientes de ``ingesta/apis.py`` en DataFrames
con **exactamente** las columnas de las tablas de ``db/schema.sql``:

- Open-Meteo → ``Condiciones_Clima``: ``timestamp, temperatura, humedad, viento``
  (el clima es GLOBAL, sin ``zona``).
- OpenAQ    → ``Calidad_Aire_Hist``: ``timestamp, zona, pm25, no2, o3``
  (la ``zona`` la etiqueta quien llama, porque OpenAQ se consulta por ubicación).

Se separa de los clientes a propósito: parsear/transformar es lógica pura y sin red,
fácil de leer y de testear con respuestas de ejemplo (ver ``tests/``).
"""

from __future__ import annotations

import pandas as pd

# Columnas destino (orden exacto del esquema).
COLUMNAS_CLIMA = ["timestamp", "temperatura", "humedad", "viento"]
COLUMNAS_AIRE = ["timestamp", "zona", "pm25", "no2", "o3"]

# Contaminantes que persistimos como columnas en Calidad_Aire_Hist.
PARAMETROS_AIRE = ["pm25", "no2", "o3"]

# Mapeo de nombres de contaminantes de Open-Meteo Air Quality → nuestro esquema.
MAPEO_OPENMETEO_AIRE = {
    "pm2_5": "pm25",
    "nitrogen_dioxide": "no2",
    "ozone": "o3",
}


def normalizar_clima(respuesta: dict) -> pd.DataFrame:
    """Respuesta de Open-Meteo → DataFrame con las columnas de ``Condiciones_Clima``.

    Espera el bloque ``current`` del endpoint ``/forecast`` de Open-Meteo, p.ej.::

        {"current": {"time": "2026-07-01T12:00",
                     "temperature_2m": 15.3,
                     "relative_humidity_2m": 60,
                     "wind_speed_10m": 12.4}}
    """
    actual = respuesta.get("current", {})
    fila = {
        "timestamp": actual.get("time"),
        "temperatura": actual.get("temperature_2m"),
        "humedad": actual.get("relative_humidity_2m"),
        "viento": actual.get("wind_speed_10m"),
    }
    df = pd.DataFrame([fila], columns=COLUMNAS_CLIMA)
    return _tipar_clima(df)


def normalizar_calidad_aire(respuesta: dict, zona: str) -> pd.DataFrame:
    """Respuesta de OpenAQ → DataFrame con las columnas de ``Calidad_Aire_Hist``.

    ``zona`` (Centro/Norte/Sur) la aporta quien llama y se usa para etiquetar todas
    las filas: OpenAQ se consulta por ubicación, no "sabe" la zona lógica.

    Espera un bloque ``results`` con mediciones que traen nombre de parámetro, valor
    y datetime UTC (formato OpenAQ v3), p.ej.::

        {"results": [
            {"parameter": {"name": "pm25"}, "value": 12.5,
             "datetime": {"utc": "2026-07-01T12:00:00Z"}},
            ...
        ]}

    Cada timestamp produce una fila con los contaminantes en columnas
    (``pm25``, ``no2``, ``o3``); los que falten quedan como ``NaN``.
    """
    resultados = respuesta.get("results", [])
    registros = [
        {
            "timestamp": _timestamp_utc(item),
            "parametro": _nombre_parametro(item),
            "valor": item.get("value"),
        }
        for item in resultados
    ]

    if not registros:
        # Sin mediciones: DataFrame vacío pero con el esquema correcto.
        return _tipar_aire(pd.DataFrame(columns=COLUMNAS_AIRE), zona)

    largo = pd.DataFrame(registros)
    # Pivot: una fila por timestamp, una columna por contaminante.
    ancho = largo.pivot_table(
        index="timestamp", columns="parametro", values="valor", aggfunc="mean"
    )
    # Garantiza las 3 columnas de contaminantes aunque alguna no venga en la respuesta.
    ancho = ancho.reindex(columns=PARAMETROS_AIRE)
    ancho = ancho.reset_index()
    ancho["zona"] = zona
    return _tipar_aire(ancho[COLUMNAS_AIRE], zona)


def normalizar_calidad_aire_openmeteo(respuesta: dict, zona: str) -> pd.DataFrame:
    """Respuesta de Open-Meteo Air Quality → DataFrame de ``Calidad_Aire_Hist``.

    Mismo esquema destino que OpenAQ (``timestamp, zona, pm25, no2, o3``), para que
    ambas fuentes sean intercambiables aguas abajo. ``zona`` la aporta quien llama,
    porque Open-Meteo se consulta por coordenadas y no "sabe" la zona lógica.

    Espera el bloque ``current`` del endpoint ``/air-quality``, p.ej.::

        {"current": {"time": "2026-07-01T12:00",
                     "pm2_5": 12.5, "nitrogen_dioxide": 30.1, "ozone": 45.0}}

    Los contaminantes ausentes quedan como ``NaN``.
    """
    actual = respuesta.get("current", {})
    fila = {"timestamp": actual.get("time"), "zona": zona}
    for origen, destino in MAPEO_OPENMETEO_AIRE.items():
        fila[destino] = actual.get(origen)
    df = pd.DataFrame([fila], columns=COLUMNAS_AIRE)
    return _tipar_aire(df, zona)


# --- Helpers privados -------------------------------------------------------

def _nombre_parametro(item: dict) -> str | None:
    """Nombre del contaminante, tolerando ``parameter`` como dict o como string."""
    parametro = item.get("parameter")
    if isinstance(parametro, dict):
        return parametro.get("name")
    return parametro


def _timestamp_utc(item: dict) -> str | None:
    """Timestamp UTC de la medición, tolerando ``datetime`` como dict o string."""
    dt = item.get("datetime")
    if isinstance(dt, dict):
        return dt.get("utc")
    return dt


def _tipar_clima(df: pd.DataFrame) -> pd.DataFrame:
    """Fuerza tipos coherentes con el esquema (REAL → float, timestamp → texto)."""
    df = df.copy()
    for col in ("temperatura", "humedad", "viento"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["timestamp"] = df["timestamp"].astype("string")
    return df


def _tipar_aire(df: pd.DataFrame, zona: str) -> pd.DataFrame:
    """Fuerza tipos coherentes con el esquema para Calidad_Aire_Hist."""
    df = df.copy()
    for col in PARAMETROS_AIRE:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["timestamp"] = df["timestamp"].astype("string")
    df["zona"] = zona
    return df
